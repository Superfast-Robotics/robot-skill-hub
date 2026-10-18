"""Local memory is useful immediately; public delivery is scoped and idempotent."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import io
import runpy
from contextlib import redirect_stdout
from unittest import mock

from test_rsh import fixture_catalog, SKILL
from test_memory_cli import finding
from rshlib import community, contributions, memories, setup
from rshlib.core import RshError


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.input = self.project / 'finding.json'
        self.input.write_text(json.dumps(finding()), encoding='utf-8')
        self.catalog = fixture_catalog()

    def tearDown(self):
        self.tmp.cleanup()

    def enable(self):
        setup.configure(self.project, allow_public_memory=True, skill_ids=['fixture-pick'], kinds=['missing_requirement'])
        path = setup.policy_path(self.project)
        value = setup.read_policy(path)
        value['community'] = {'enabled': True, 'sync_before_recall': True}
        setup.write_policy(path, value)

    def test_local_save_recall_and_environment_isolation_without_permission_or_network(self):
        with mock.patch.object(community, 'request', side_effect=AssertionError('no network')):
            saved = community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True)
            replay = community.save(self.catalog, 'fixture-pick', self.project, self.input)
            self.assertEqual(saved['id'], replay['id'])
            self.assertEqual(replay['reason_code'], 'public_scope_not_allowed')
            recalled = community.recall(self.catalog, 'fixture-pick', {'robot': 'PANDA'}, project=self.project, offline=True)
            self.assertEqual(recalled['results'][0]['id'], saved['id'])
            self.assertEqual(community.recall(self.catalog, 'fixture-pick', {'robot': 'ur5'}, project=self.project, offline=True)['results'], [])
            changed = fixture_catalog()
            changed['records'][0]['source']['commit'] = 'f' * 40
            self.assertEqual(community.recall(changed, 'fixture-pick', {}, project=self.project, offline=True)['results'], [])

    def test_real_cli_entrypoint_saves_then_inspects_local_experience_without_public_queries(self):
        self.enable()
        catalog = self.project / 'catalog.json'
        catalog.write_text(json.dumps(self.catalog), encoding='utf-8')
        cli = runpy.run_path(str(SKILL / 'scripts/rsh.py'), run_name='community_cli_test')
        def call(args):
            output = io.StringIO()
            with redirect_stdout(output):
                status = cli['main']([*args, '--catalog', str(catalog), '--offline', '--json'])
            self.assertEqual(status, 0, output.getvalue())
            return json.loads(output.getvalue())
        with mock.patch.object(community, 'request', side_effect=AssertionError('no implicit public lookup')):
            saved = call(['save', 'fixture-pick', '--project', str(self.project), '--finding', str(self.input)])
            inspected = call(['inspect', 'fixture-pick', '--project', str(self.project), '--robot', 'panda'])
            self.assertEqual(inspected['community']['results'][0]['id'], saved['id'])
            self.assertEqual(inspected['community']['remote_status'], 'offline')
            self.assertFalse(inspected['community']['execution_performed'])

    def test_old_local_outbox_is_recalled_and_duplicate_does_not_fill_results(self):
        memories.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True)
        saved = community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True)
        recalled = community.recall(self.catalog, 'fixture-pick', {}, project=self.project, offline=True)
        self.assertEqual([row['id'] for row in recalled['results']], [saved['id']])

    def test_delivery_receipt_failure_and_retry_never_lose_local_experience(self):
        self.enable()
        with mock.patch.object(community, 'credential', return_value={'token': 'csh_' + 'x'*43}), mock.patch.object(community, 'request', side_effect=RshError('offline', 'offline')) as request:
            saved = community.save(self.catalog, 'fixture-pick', self.project, self.input)
            self.assertEqual(saved['status'], 'local_saved')
            community.sync(self.project)
            self.assertEqual(request.call_count, 1, 'automatic retry respects backoff')
        path = Path(saved['finding_path'])
        entry = json.loads(path.read_text())
        entry['delivery']['retry_after'] = 0
        path.write_text(json.dumps(entry))
        def posted(method, route, *, value, token):
            self.assertEqual(route, '/items')
            self.assertTrue(value['finding']['publication']['public_submission_allowed'])
            return {'status': 'stored', 'id': community.identity(value), 'content': value,
                    'content_sha256': hashlib.sha256(contributions.canonical_bytes(value)).hexdigest()}
        with mock.patch.object(community, 'credential', return_value={'token': 'csh_'+'x'*43}), mock.patch.object(community, 'request', side_effect=posted) as request:
            self.assertEqual(community.sync(self.project)['deliveries'][0]['status'], 'stored')
            self.assertEqual(community.sync(self.project)['deliveries'], [])
            self.assertEqual(request.call_count, 1)
        self.assertEqual(community.recall(self.catalog, 'fixture-pick', {}, project=self.project, offline=True)['results'][0]['id'], saved['id'])

    def test_revoked_policy_prevents_pending_delivery_and_secret_is_rejected(self):
        self.enable()
        community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True)
        setup.configure(self.project, local_only=True)
        with mock.patch.object(community, 'request', side_effect=AssertionError('revoked')):
            self.assertEqual(community.sync(self.project)['deliveries'][0]['reason_code'], 'public_scope_not_allowed')
        self.input.write_text(json.dumps(finding(observation='A credential csh_' + 'x'*43)), encoding='utf-8')
        with self.assertRaises(RshError):
            community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True)

    def test_variants_and_reports_keep_parent_identity_and_do_not_apply_patch(self):
        patch = self.project / 'change.diff'
        patch.write_text('--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-old\n+new\n')
        saved = community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True, patch=patch, license_spdx='MIT')
        report = community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True, parent_id=saved['id'], outcome='failed')
        self.assertNotEqual(saved['id'], report['id'])
        self.assertFalse((self.project / 'demo.py').exists())
        content = json.loads(Path(report['finding_path']).read_text())['content']
        self.assertEqual(content['parent_id'], saved['id'])
        self.assertEqual(content['outcome'], 'failed')
        with self.assertRaises(RshError):
            community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True, outcome='succeeded')

    def test_enrollment_does_not_expand_scope_without_explicit_flag(self):
        with mock.patch.object(community, 'request', side_effect=AssertionError('no network')):
            with self.assertRaises(RshError):
                community.join(self.project, skill_ids=['fixture-pick'], kinds=['missing_requirement'])
        self.assertFalse(setup.policy_path(self.project).exists())

    def test_private_environment_keys_are_rejected_before_any_read_request(self):
        with mock.patch.object(community, 'request', side_effect=AssertionError('no network')):
            with self.assertRaises(RshError):
                community.recall(self.catalog, 'fixture-pick', {'private_task': 'not for upload'}, project=self.project)

    def test_enrollment_solves_real_hash_puzzle_and_does_not_return_credential(self):
        challenge = '9999999999.' + 'a'*64 + '.' + 'b'*64
        def service(method, path, **kwargs):
            if path == '/challenge':
                return {'difficulty_hex_zeros': 4, 'challenge': challenge}
            value = kwargs['value']
            token_hash = hashlib.sha256(value['token'].encode()).hexdigest()
            self.assertTrue(hashlib.sha256((challenge + '.' + token_hash + '.' + value['nonce']).encode()).hexdigest().startswith('0000'))
            return {'status': 'ready', 'principal_id': token_hash}
        credentials = self.project / 'private-home/key.json'
        with mock.patch.object(community, 'key_path', return_value=credentials), mock.patch.object(community, 'request', side_effect=service) as request:
            result = community.join(self.project, skill_ids=['fixture-pick'], kinds=['missing_requirement'], allow_public_memory=True)
            self.assertEqual(request.call_count, 2)
            self.assertNotIn(json.loads(credentials.read_text())['token'], json.dumps(result))
            self.assertTrue(community.enabled(self.project))
            community.join(self.project, skill_ids=['fixture-pick'], kinds=['missing_requirement'], allow_public_memory=True)
            self.assertEqual(request.call_count, 2, 'a joined installation does not enroll again')

    def test_content_identity_ignores_attribution_and_hub_generation_but_preserves_environment(self):
        saved = community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True)
        value = json.loads(Path(saved['finding_path']).read_text())['content']
        value['finding']['attribution']['contributor_label'] = 'another installation'
        value['finding']['base']['hub_commit'] = 'c' * 40
        self.assertEqual(community.identity(value), saved['id'])
        value['finding']['environment']['robot'] = 'other'
        self.assertNotEqual(community.identity(value), saved['id'])

    def test_large_delivered_history_does_not_starve_a_later_pending_entry(self):
        self.enable()
        saved = community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True)
        directory = community.root(self.project)
        for number in range(1000):
            (directory / ('exp_' + format(number, '064x') + '.json')).write_text('{"delivery":{"status":"stored"}}')
        with mock.patch.object(community, 'request', side_effect=AssertionError('first page is already delivered')):
            first = community.sync(self.project)
        self.assertEqual(first['scanned'], 1000)
        self.assertEqual(first['deliveries'], [])
        def posted(method, route, *, value, token):
            return {'status':'stored','id':community.identity(value),'content':value,'content_sha256':hashlib.sha256(contributions.canonical_bytes(value)).hexdigest()}
        with mock.patch.object(community, 'credential', return_value={'token':'csh_'+'x'*43}), mock.patch.object(community, 'request', side_effect=posted):
            second = community.sync(self.project)
        self.assertEqual(second['deliveries'][0]['id'], saved['id'])
        self.assertEqual(second['deliveries'][0]['status'], 'stored')

    def test_permanent_rejection_pauses_until_explicit_retry(self):
        self.enable()
        with mock.patch.object(community, 'credential', return_value={'token':'csh_'+'x'*43}), mock.patch.object(community, 'request', side_effect=RshError('license_mismatch','Rejected.',retryable=False,http_status=422)) as request:
            saved = community.save(self.catalog, 'fixture-pick', self.project, self.input)
            self.assertFalse(saved['automatic_retry'])
            self.assertEqual(community.sync(self.project)['deliveries'], [])
            self.assertEqual(request.call_count,1)
            community.sync(self.project,retry_blocked=True)
            self.assertEqual(request.call_count,2)

    def test_public_outcome_updates_local_entry_and_new_shared_variants_are_visible(self):
        saved = community.save(self.catalog, 'fixture-pick', self.project, self.input, offline=True)
        base, _ = memories.base_for(self.catalog, 'fixture-pick')
        rows = [{'id':saved['id'],'base':base,'reuse_reports':{'failed':1}},
                {'id':'exp_'+'f'*64,'base':base,'kind':'variant','summary':'A later shared fix'}]
        with mock.patch.object(community,'request',return_value={'status':'ready','results':rows,'complete':True}):
            result = community.recall(self.catalog,'fixture-pick',{},project=self.project)
        self.assertEqual(result['results'][0]['location'],'local')
        self.assertEqual(result['results'][0]['reuse_reports']['failed'],1)
        self.assertTrue(result['results'][0]['also_published'])
        self.assertEqual(result['results'][1]['location'],'community')


if __name__ == '__main__':
    unittest.main()
