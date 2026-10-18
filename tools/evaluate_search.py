"""Finite offline relevance evaluation of the actual first-party Python matcher.

No robot source, native index, API, CLI subprocess or model is executed. Input
records come from a complete checksummed local publisher fixture, not snapshots.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def read(path, maximum=8 * 1024 * 1024):
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum
    raw = path.read_bytes()
    return json.loads(raw), raw


def safe(path):
    return isinstance(path, str) and path and ':' not in path and '\\' not in path and all(p not in ('', '.', '..') for p in path.split('/'))


def canonical(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def summary(rows):
    count = len(rows)
    return {'queries': count, **{key: sum(row[key] for row in rows) / count for key in
            ('hit_at_1', 'hit_at_3', 'hit_at_10', 'labeled_recall_at_3', 'labeled_recall_at_10', 'reciprocal_rank_at_10')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--build-receipt', type=Path, required=True)
    parser.add_argument('--cases', type=Path, default=ROOT / 'benchmarks/search/tasks.h15.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    assert ROOT in output.parents and not output.exists(), 'Use a fresh output below this checkout'
    output.mkdir(parents=True, exist_ok=False)
    calls, blocked = 0, []
    try:
        suite, cases_raw = read(args.cases.resolve(), 512 * 1024)
        built, built_raw = read(args.build_receipt.resolve(), 128 * 1024)
        assert sha(built_raw) == suite['publisher_receipt_sha256'] and built['head'] == suite['fixture_generation'] and built['tree'] == suite['fixture_tree'] and built['counts'] == suite['counts'] and built['builder_exit_code'] == 0
        cases = suite['cases']
        assert len(cases) == 60 and len({c['id'] for c in cases}) == 60
        task_cases = [c for c in cases if c['group'] == 'task']
        assert len(task_cases) == suite['task_queries'] == 40 and len({c['task_id'] for c in task_cases}) == suite['tasks'] == 20
        assert all({c['variant'] for c in task_cases if c['task_id'] == name} == {'short', 'natural'} for name in {c['task_id'] for c in task_cases})
        version, version_raw = read(args.site / 'catalog/v1/version.json', 32768)
        assert version['hub_commit'] == suite['fixture_generation'] and version['counts'] == suite['counts']
        resources = {'catalog/v1/version.json': {'bytes': len(version_raw), 'sha256': sha(version_raw)}}

        def resource(name, relative):
            value, raw = read(args.site / relative)
            assert sha(raw) == version['resources'][name]['sha256']
            resources[relative] = {'bytes': len(raw), 'sha256': sha(raw)}
            assert value['hub_commit'] == suite['fixture_generation']
            return value

        catalog = resource('index', 'catalog/v1/index.json')
        references = resource('references', 'catalog/v1/references.json')
        manifest = resource('search-manifest', 'catalog/v2/search-manifest.json')
        assert len(catalog['records']) == 17 and len(references['records']) == 1286
        assert manifest['counts'] == suite['counts'] and manifest['records'] == 1303 and len(manifest['pages']) == 16
        indexed_ids = set()
        for page in manifest['pages']:
            assert safe(page['path']) and 0 < page['bytes'] <= 256 * 1024
            value, raw = read(args.site / page['path'], 256 * 1024)
            assert len(raw) == page['bytes'] and sha(raw) == page['sha256'] and len(value['records']) == page['records'] and value['hub_commit'] == suite['fixture_generation']
            for row in value['records']:
                assert row['id'] not in indexed_ids
                indexed_ids.add(row['id'])
            resources[page['path']] = {'bytes': len(raw), 'sha256': sha(raw)}
        records = {r['id']: (r, False) for r in catalog['records']}
        assert len(records) == 17
        for record in references['records']:
            assert record['id'] not in records
            records[record['id']] = (record, True)
        assert set(records) == indexed_ids and len(indexed_ids) == 1303
        for identifier, target in suite['targets'].items():
            record, reference = records[identifier]
            assert sha(canonical(record)) == target['record_json_sha256']
            source = record['source']
            assert (source.get('commit') or source.get('revision')) == target['source_commit']
            assert record['license'] == target['license']
            assert ('source-' + source['sha256'] if reference else record['maintenance']['record_version']) == target['record_version']
        # Keep source references under references.records. Both real generation
        # fields remain the publisher candidate; never relabel it as live main.
        catalog['references'] = references
        catalog.update(catalog_origin='complete_local_publisher_fixture', references_origin='complete_local_publisher_fixture', discovery_scope='complete_offline_inventory')
        catalog['coverage'] = {'complete': True, 'scope': 'all_local_publisher_recipes_and_references'}
        references['coverage'] = dict(catalog['coverage'])

        def audit(event, _arguments):
            if event in {'socket.connect', 'socket.connect_ex', 'socket.bind', 'socket.getaddrinfo', 'socket.gethostbyname', 'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec'}:
                blocked.append(event)
                raise RuntimeError('Offline matcher evaluation denied: ' + event)

        sys.addaudithook(audit)
        sys.path.insert(0, str(ROOT / 'skills/find-robot-skills/scripts'))
        from rshlib import core
        core_path = ROOT / 'skills/find-robot-skills/scripts/rshlib/core.py'
        assert Path(core.__file__).resolve() == core_path
        core.validate_catalog(catalog)
        save(output / 'request.json', {'at': datetime.now(timezone.utc).isoformat(), 'cases_sha256': sha(cases_raw), 'runner_sha256': sha(Path(__file__).read_bytes()), 'matcher_path': 'skills/find-robot-skills/scripts/rshlib/core.py', 'matcher_sha256': sha(core_path.read_bytes()), 'matcher_function': 'rshlib.core.find', 'planned_matcher_calls': 60, 'limit': 10, 'requested_scope': 'one offline batch; no ranking changes', 'catalog_generation': suite['fixture_generation'], 'published_H15_commit_context': suite['hub_commit'], 'same_Git_tree_context': suite['fixture_tree'], 'publisher_receipt_sha256': sha(built_raw), 'resources': resources})
        results, raw_results = [], []
        for case in cases:
            assert calls < 60
            calls += 1
            terms = core.query_terms(case['query'])
            try:
                result = core.find(catalog, case['query'], case['environment'], limit=10, hub_commit=case.get('hub_commit', suite['fixture_generation']))
            except core.RshError as error:
                raw_results.append({'id': case['id'], 'error': error.result})
                results.append({'id': case['id'], 'group': case['group'], 'query_terms': terms, 'actual_error': error.result['reason_code'], 'control_pass': case.get('expected_error') == error.result['reason_code']})
                continue
            raw_results.append({'id': case['id'], 'response': result})
            assert result['search_semantics'] == 'all_terms_word_prefix' and result['execution_performed'] is False
            assert result['catalog_hub_commit'] == result['references_hub_commit'] == suite['fixture_generation']
            ids = [row['id'] for row in result['results']]
            for row in result['results']:
                record, reference = records[row['id']]
                version_id = 'source-' + record['source']['sha256'] if reference else record['maintenance']['record_version']
                assert row['source_commit'] == (record['source'].get('commit') or record['source'].get('revision'))
                assert row['memory_base']['record_version'] == version_id
                assert row['memory_base']['hub_commit'] == suite['fixture_generation']
                assert row['hub_prepare'] is (not reference)
                if reference:
                    assert row['compatibility_status'] == 'unknown'
            item = {'id': case['id'], 'group': case['group'], 'query': case['query'], 'query_terms': terms, 'environment': case['environment'], 'total_matches': result['total'], 'returned_ids': ids, 'source_version_identity_preserved': True}
            if case['group'] == 'task':
                expected = set(case['expected_ids'])
                ranks = [ids.index(identifier) + 1 for identifier in expected if identifier in ids]
                item.update(task_id=case['task_id'], variant=case['variant'], expected_ids=case['expected_ids'], first_labeled_rank_at_10=min(ranks) if ranks else None,
                            hit_at_1=int(bool(expected.intersection(ids[:1]))), hit_at_3=int(bool(expected.intersection(ids[:3]))), hit_at_10=int(bool(ranks)),
                            labeled_recall_at_3=len(expected.intersection(ids[:3])) / len(expected), labeled_recall_at_10=len(expected.intersection(ids)) / len(expected), reciprocal_rank_at_10=1 / min(ranks) if ranks else 0)
            else:
                checks = []
                if 'expected_first' in case: checks.append(bool(ids) and ids[0] == case['expected_first'])
                if 'expected_total' in case: checks.append(result['total'] == case['expected_total'])
                if 'expected_ids_exact' in case: checks.append(set(ids) == set(case['expected_ids_exact']) and result['total'] == len(case['expected_ids_exact']))
                if 'required_ids' in case: checks.append(set(case['required_ids']).issubset(ids))
                if 'expected_terms' in case: checks.append(terms == case['expected_terms'])
                if 'compatibility_status' in case: checks.append(bool(ids) and all(row['compatibility_status'] == case['compatibility_status'] for row in result['results']))
                if 'expected_error' in case: checks.append(False)
                assert checks
                item['control_pass'] = all(checks)
                item['normalizer_contract_only'] = case.get('normalizer_contract_only', False)
            results.append(item)
        assert calls == len(cases) == 60 and not blocked
        tasks = [row for row in results if row['group'] == 'task']
        controls = [row for row in results if row['group'] == 'control']
        assert len(tasks) == 40 and len(controls) == 20
        with (output / 'raw-matcher-results.jsonl').open('x', encoding='utf-8') as stream:
            for item in raw_results: stream.write(json.dumps(item, ensure_ascii=False) + '\n')
        save(output / 'case-results.json', results)
        save(output / 'result.json', {'status': 'OFFLINE_BASELINE_MEASURED_NO_SEARCH_CHANGE', 'at': datetime.now(timezone.utc).isoformat(), 'cases_sha256': sha(cases_raw), 'runner_sha256': sha(Path(__file__).read_bytes()), 'matcher_sha256': sha(core_path.read_bytes()), 'case_results_sha256': sha((output / 'case-results.json').read_bytes()), 'raw_results_sha256': sha((output / 'raw-matcher-results.jsonl').read_bytes()), 'matcher_calls': calls, 'counts': suite['counts'], 'searchable_records': 1303, 'coverage_complete_for_local_inventory': True, 'fixture_generation': suite['fixture_generation'], 'published_H15_context': suite['hub_commit'], 'same_Git_tree_context': suite['fixture_tree'], 'metrics': {'all_task_queries': summary(tasks), 'short': summary([r for r in tasks if r['variant'] == 'short']), 'natural': summary([r for r in tasks if r['variant'] == 'natural'])}, 'controls': {'total': len(controls), 'passed': sum(row['control_pass'] for row in controls), 'failed_ids': [r['id'] for r in controls if not r['control_pass']]}, 'bounds': {'network_and_subprocess_attempts_denied': blocked, 'first_party_Python_matcher_executed': True, 'robot_or_upstream_source_execution': False, 'CLI_processes': 0, 'API_requests': 0, 'native_index_runs': 0, 'LLM_or_embedding_calls': 0, 'search_or_catalog_changes': False}, 'caveats': ['Maintainer-authored engineering cases, not observed external-user or agent requests/adoption.', 'Selected relevant labels are incomplete; precision and exhaustive recall are not claimed.', 'MRR is truncated at10; hit@3 corresponds to the default result-window ordering.', 'Short keywords intentionally contrast with natural task paraphrases; this is a diagnostic pair set, not an unbiased language distribution.', 'Only actual Python core.find was evaluated; no new CLI/static-server/native/MCP agreement measurement.', 'Source discovery labels and unknown compatibility are not robot support or runtime qualification.', 'Complete retained publisher candidate fixture has the actual H15 tree; its generation is not relabeled as the live merge.']})
        print(json.dumps({'status': 'OFFLINE_BASELINE_MEASURED_NO_SEARCH_CHANGE', 'metrics': json.loads((output / 'result.json').read_bytes())['metrics'], 'control_failures': [r['id'] for r in controls if not r['control_pass']]}))
    except BaseException as error:
        save(output / 'failure.json', {'status': 'FAILED_STOP_NO_RETRY', 'error_type': type(error).__name__, 'message': str(error)[:500], 'matcher_calls_completed_or_attempted': calls, 'blocked_events': blocked, 'traceback': traceback.format_exc()})
        raise


if __name__ == '__main__':
    main()
