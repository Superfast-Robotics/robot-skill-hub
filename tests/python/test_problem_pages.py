"""Verify problem entrypoints bind public claims to current reproducible evidence."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from problem_pages import publish


class ProblemPagesTests(unittest.TestCase):
    def test_same_case_and_receipt_are_readable_without_javascript(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            urls = publish(ROOT, out, 'https://example.test', 'a' * 40)
            self.assertEqual(len(urls), 11)
            for case in json.loads((ROOT / 'catalog/problem-cases.json').read_text())['cases']:
                page = out / 'problems' / case['id']
                body = json.loads((page / 'index.json').read_text())
                self.assertEqual(body['case'], case)
                self.assertTrue(body['evidence']['problem_reproduced'])
                self.assertTrue(body['evidence']['valid_case_passed'])
                self.assertEqual((page / 'index.md').read_text(), (ROOT / 'docs/problems' / (case['id'] + '.md')).read_text())
                self.assertNotIn('<script', (page / 'index.html').read_text())

    def test_changed_adapter_cannot_republish_old_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['catalog/problem-cases.json', 'catalog/executable-conversions.json', 'evidence/integration/agent-discovery-v1/problem-cases.json']:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, root / name)
            for case in json.loads((root / 'catalog/problem-cases.json').read_text())['cases']:
                path = root / 'recipes' / case['skill_id'] / 'run.py'
                path.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / path.relative_to(root), path)
            first = json.loads((root / 'catalog/problem-cases.json').read_text())['cases'][0]
            path = root / 'recipes' / first['skill_id'] / 'run.py'
            path.write_bytes(path.read_bytes() + b'\n# changed\n')
            with self.assertRaisesRegex(ValueError, 'Stale or unsuccessful'):
                publish(root, root / 'output', 'https://example.test', 'b' * 40)
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__': unittest.main()
