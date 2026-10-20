"""Check complete HTTP artifacts, digest changes and publication failure bounds."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from publish_agent_skills import publish, FILES, MAX_ARCHIVE, SKILLS


class AgentSkillDistributionTests(unittest.TestCase):
    def test_archives_are_reproducible_complete_and_exclude_local_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for item in SKILLS:
                shutil.copytree(ROOT / 'skills' / item[0], root / 'skills' / item[0])
                (root / 'skills' / item[0] / 'do-not-publish.secret').write_text('fixture')
            for name in ['first', 'second']:
                publish(root, root / name, 'https://example.test', 'a' * 40)
            for path in (root / 'first').rglob('*'):
                if path.is_file():
                    self.assertEqual(path.read_bytes(), (root / 'second' / path.relative_to(root / 'first')).read_bytes())
            index = json.loads((root / 'first/.well-known/agent-skills/index.json').read_text())
            self.assertEqual(len(index['skills']), 3)
            for entry in index['skills']:
                raw = (root / 'first' / entry['url'].removeprefix('https://example.test/')).read_bytes()
                self.assertEqual('sha256:' + hashlib.sha256(raw).hexdigest(), entry['digest'])
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertEqual(sorted(archive.namelist()), sorted(FILES))
                    for name in FILES:
                        self.assertEqual(archive.read(name), (root / 'skills' / entry['name'] / name).read_bytes())

    def test_oversized_package_preserves_previous_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for item in SKILLS:
                shutil.copytree(ROOT / 'skills' / item[0], root / 'skills' / item[0])
            out = root / 'site'; publish(root, out, 'https://example.test', 'a' * 40)
            before = (out / '.well-known/agent-skills/index.json').read_bytes()
            (root / 'skills' / SKILLS[-1][0] / 'scripts/lookup.py').write_bytes(b'x' * (MAX_ARCHIVE + 1))
            with self.assertRaisesRegex(ValueError, 'budget'):
                publish(root, out, 'https://example.test', 'b' * 40)
            self.assertEqual(before, (out / '.well-known/agent-skills/index.json').read_bytes())


if __name__ == '__main__': unittest.main()
