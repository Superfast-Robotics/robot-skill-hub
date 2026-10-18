"""Archive verifies public bytes before committing and advances cursors atomically."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

from test_rsh import ROOT

spec = importlib.util.spec_from_file_location('archive_community', ROOT / 'tools/archive_community.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class Fake:
    def __init__(self, corrupt=False, empty=False):
        self.calls = []
        self.corrupt, self.empty = corrupt, empty

    def gh(self, path, **kwargs):
        self.calls.append((path, kwargs))
        if path.startswith('git/ref/'):
            return None
        return {'sha': 'a'*40}

    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if 'stream=attestations' in url:
            return {'stream': 'attestations', 'through': 0, 'rows': [], 'next_after': None}
        content = {'schema_version': '1', 'finding': {'summary': 'Already public fixture'}}
        rows = [] if self.empty else [{'sequence': 1, 'id': 'exp_'+'b'*64, 'content': content,
                 'content_sha256': 'f'*64 if self.corrupt else hashlib.sha256(archive.canonical(content)).hexdigest()}]
        return {'stream': 'items', 'through': len(rows), 'rows': rows, 'next_after': None}


class ArchiveTests(unittest.TestCase):
    def test_first_archive_is_data_only_orphan_branch_with_exact_cursor(self):
        fake = Fake()
        result = archive.run(fake)
        self.assertEqual(result['cursor'], {'items': 1, 'attestations': 0})
        commit = next(kwargs['value'] for path, kwargs in fake.calls if path == 'git/commits')
        self.assertEqual(commit['parents'], [])
        tree = next(kwargs['value'] for path, kwargs in fake.calls if path == 'git/trees')
        self.assertEqual({r['path'] for r in tree['tree']}, {'items/000000000001.jsonl', 'README.md', 'cursor.json'})
        self.assertNotIn('base_tree', tree)
        self.assertEqual(fake.calls[-1][1]['value']['ref'], 'refs/heads/community-data')

    def test_corrupt_export_never_writes_github_or_advances_cursor(self):
        fake = Fake(corrupt=True)
        with self.assertRaisesRegex(RuntimeError, 'digest mismatch'):
            archive.run(fake)
        self.assertFalse(any(kwargs.get('method') in ('POST', 'PATCH') for _, kwargs in fake.calls))

    def test_existing_archive_without_new_items_does_not_create_commit(self):
        fake = Fake(empty=True)
        def gh(path, **kwargs):
            fake.calls.append((path, kwargs))
            if path.startswith('git/ref/'):
                return {'object': {'sha': 'a'*40}}
            if path.startswith('git/commits/'):
                return {'tree': {'sha': 'b'*40}}
            if path.startswith('contents/'):
                return {'content': base64.b64encode(b'{"items":0,"attestations":0}').decode()}
            self.fail('Unexpected mutation')
        fake.gh = gh
        self.assertEqual(archive.run(fake)['status'], 'unchanged')


if __name__ == '__main__':
    unittest.main()
