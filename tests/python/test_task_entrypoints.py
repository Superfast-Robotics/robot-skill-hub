"""Observable task entrypoint behavior, version pins and inert catalog export."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('task_client', ROOT / 'tools/task_skill_client.py')
client = importlib.util.module_from_spec(spec); spec.loader.exec_module(client)
URL = client.API + '/v1/skills/example?hub_commit=' + 'a' * 40 + '&record_version=1.0.0&include=experience'


class TaskEntryTests(unittest.TestCase):
    def test_start_preserves_unknown_environment_and_never_executes_handoff(self):
        calls = []
        response = {'results': [], 'selected': None, 'execution_performed': False}
        def fetch(url, channel):
            calls.append((url, channel))
            return response
        self.assertEqual(response, client.start('inverse kinematics', 'task-kinematics', task=True, fetch=fetch))
        self.assertIn('/v1/start?', calls[0][0])
        self.assertNotIn('runtime=', calls[0][0])
        self.assertEqual('task-kinematics', calls[0][1])
        with self.assertRaises(ValueError):
            client.start('   ', 'task-kinematics', fetch=fetch)
        with self.assertRaises(ValueError):
            client.start('IK', 'task-kinematics', fetch=lambda *_: {'results': [{}] * 4, 'selected': {}})

    def record(self):
        return {'hub_commit': 'a' * 40, 'record': {'id': 'example', 'interface': {'abstraction_level': 0},
            'maintenance': {'record_version': '1.0.0'}, 'preparation': {'files': {'run.py': 'print(1)\n'}}},
            'findings': {'status': 'unknown'}, 'community': {'status': 'unknown'}}

    def test_search_is_bounded_without_inventing_environment(self):
        seen = []
        def fetch(url, channel):
            seen.append((url, channel)); return {'results': []}
        result = client.find('inverse kinematics', 'task-kinematics', fetch=fetch)
        self.assertNotIn('runtime=', seen[0][0]); self.assertIn('limit=3', seen[0][0])
        self.assertIn('kind=preparation_recipe', seen[0][0]); self.assertFalse(result['execution_performed'])
        with self.assertRaises(ValueError): client.find('x' * 161, 'task-kinematics', fetch=fetch)

    def test_inspection_preserves_recall_and_omits_code_by_default(self):
        result = client.inspect_url(URL, 'task-planning', fetch=lambda *_: self.record())
        self.assertNotIn('files', result['record']['preparation'])
        self.assertEqual('unknown', result['findings']['status'])
        for change in ['hub_commit', 'record_version']:
            body = self.record()
            if change == 'hub_commit': body['hub_commit'] = 'b' * 40
            else: body['record']['maintenance']['record_version'] = '2.0.0'
            with self.assertRaises(ValueError): client.inspect_url(URL, 'task-planning', fetch=lambda *_: body)
        with self.assertRaises(ValueError): client.inspect_url(client.API + '/v1/skills/example', 'task-planning')

    def test_catalog_export_is_inert_complete_and_does_not_overwrite_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'catalog.json'
            result = client.export_catalog(URL, 'task-planning', output, fetch=lambda *_: self.record())
            catalog = json.loads(output.read_bytes())
            self.assertEqual('a' * 40, catalog['hub_commit'])
            self.assertEqual('print(1)\n', catalog['records'][0]['preparation']['files']['run.py'])
            self.assertFalse(result['execution_performed'])
            with self.assertRaises(FileExistsError): client.export_catalog(URL, 'task-planning', output, fetch=lambda *_: self.record())

    def test_arbitrary_hosts_and_non_api_routes_are_rejected_before_network(self):
        for url in ['https://attacker.invalid/v1/search', 'https://api.superfastrobotics.com@attacker.invalid/v1/search',
                    'http://api.superfastrobotics.com/v1/search', client.API + '/v1/skills/example#fragment', client.API + '/admin']:
            with self.assertRaises(ValueError): client.read_json(url, 'task-planning')


if __name__ == '__main__': unittest.main()
