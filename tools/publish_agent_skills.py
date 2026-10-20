"""Publish bounded, checksum-addressed task skill archives over ordinary HTTPS."""
import hashlib
import io
import json
from pathlib import Path
import zipfile

if __package__:
    from .generate_task_skills import SKILLS
else:
    from generate_task_skills import SKILLS

SCHEMA = 'https://schemas.agentskills.io/discovery/0.2.0/schema.json'
FILES = ('SKILL.md', 'scripts/lookup.py', 'references/prepare.md', 'LICENSE')
MAX_ARCHIVE = 64 * 1024


def publish(root: Path, output: Path, base: str, commit: str):
    """Ship only explicit standalone packages; never include local files/caches."""
    if not any((root / 'skills' / item[0]).exists() for item in SKILLS):
        return None  # Catalog-only test roots can omit installable packages.
    built = []
    for name, _, description, *_ in SKILLS:
        folder = root / 'skills' / name
        buffer = io.BytesIO(); hashes = {}
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
            for relative in FILES:
                path = folder / relative
                if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
                    raise ValueError('Task package escapes its source directory')
                raw = path.read_bytes()
                if len(raw) > MAX_ARCHIVE:
                    raise ValueError('Task skill file exceeds its publication budget')
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3; info.external_attr = 0o100644 << 16
                archive.writestr(info, raw)
                hashes[relative] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        raw = buffer.getvalue()
        if len(raw) > MAX_ARCHIVE:
            raise ValueError('Task skill archive exceeds its publication budget')
        digest = hashlib.sha256(raw).hexdigest()
        relative = '.well-known/agent-skills/artifacts/' + digest + '.zip'
        built.append((relative, raw, {'name': name, 'type': 'archive', 'description': description,
                                     'url': base + '/' + relative, 'digest': 'sha256:' + digest}, hashes))
    # Validate every package before replacing any public entrypoint.
    index = {'$schema': SCHEMA, 'skills': [entry for _, _, entry, _ in built]}
    index_raw = (json.dumps(index, indent=2) + '\n').encode()
    for relative, raw, _, _ in built:
        path = output / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    directory = output / '.well-known/agent-skills'
    (directory / 'index.json').write_bytes(index_raw)
    manifest = {'schema_version': '1', 'hub_commit': commit, 'index_sha256': hashlib.sha256(index_raw).hexdigest(),
                'license': 'Apache-2.0', 'files': {entry['name']: hashes for _, _, entry, hashes in built},
                'scope': 'Three agent lookup packages; not robot runtime code or a community finding upload.',
                'maximum_archive_bytes': MAX_ARCHIVE}
    (directory / 'publication.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return base + '/.well-known/agent-skills/index.json'
