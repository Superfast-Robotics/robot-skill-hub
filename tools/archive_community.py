"""Batch public community data into an isolated Git branch. Never execute contributions."""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

REPO = 'Superfast-Robotics/robot-skill-hub'
BRANCH = 'community-data'
API = 'https://api.superfastrobotics.com/v1/community/export'
MAX_PAGES_PER_STREAM = 20


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


class Client:
    def __init__(self):
        self.token = os.environ['GITHUB_TOKEN']
        self.calls = 0

    def request(self, url, method='GET', value=None, missing=False):
        self.calls += 1
        if self.calls > 100:
            raise RuntimeError('Archive request budget exceeded.')
        github = url.startswith('https://api.github.com/repos/' + REPO + '/')
        if not github and not url.startswith(API + '?'):
            raise RuntimeError('Archive destination is not allowed.')
        headers = {'Accept': 'application/json', 'User-Agent': 'robot-skill-hub-archive', 'DNT': '1', 'X-RSH-Telemetry': 'off'}
        if github:
            headers.update(Authorization='Bearer ' + self.token)
        data = canonical(value) if value is not None else None
        if data is not None:
            headers['Content-Type'] = 'application/json'
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=20) as response:
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise RuntimeError('Archive response too large.')
            return json.loads(raw)
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            raise RuntimeError('Archive request failed with HTTP ' + str(error.code)) from None

    def gh(self, path, **kwargs):
        return self.request('https://api.github.com/repos/' + REPO + '/' + path, **kwargs)


def run(client):
    ref = client.gh('git/ref/heads/' + BRANCH, missing=True)
    parent, tree, cursors = None, None, {'items': 0, 'attestations': 0}
    if ref:
        parent = ref['object']['sha']
        commit = client.gh('git/commits/' + parent)
        tree = commit['tree']['sha']
        cursor = client.gh('contents/cursor.json?ref=' + parent)
        raw = base64.b64decode(cursor['content'])
        if len(raw) > 4096:
            raise RuntimeError('Archive cursor exceeds its bound.')
        cursors = json.loads(raw)
        if set(cursors) != {'items', 'attestations'} or any(type(n) is not int or n < 0 for n in cursors.values()):
            raise RuntimeError('Archive cursor is invalid.')
    files, counts = {}, {'items': 0, 'attestations': 0}
    for stream in ('items', 'attestations'):
        through = None
        for _ in range(MAX_PAGES_PER_STREAM):
            args = {'stream': stream, 'after': cursors[stream]}
            if through is not None:
                args['through'] = through
            page = client.request(API + '?' + urllib.parse.urlencode(args))
            if page.get('stream') != stream or not isinstance(page.get('rows'), list) or len(page['rows']) > 20:
                raise RuntimeError('Invalid export page.')
            if through is None:
                through = page['through']
            if type(through) is not int or through < cursors[stream] or page['through'] != through:
                raise RuntimeError('Export watermark changed.')
            rows = page['rows']
            previous = cursors[stream]
            for row in rows:
                sequence = row.get('sequence') if stream == 'items' else row.get('seq')
                if type(sequence) is not int or not previous < sequence <= through:
                    raise RuntimeError('Export sequence is invalid.')
                previous = sequence
                if stream == 'items':
                    if not re.fullmatch(r'exp_[a-f0-9]{64}', row.get('id', '')):
                        raise RuntimeError('Export identity is invalid.')
                    if not row.get('hidden') and hashlib.sha256(canonical(row['content'])).hexdigest() != row.get('content_sha256'):
                        raise RuntimeError('Export digest mismatch.')
                elif not re.fullmatch(r'[a-f0-9]{64}', row.get('principal_id', '')):
                    raise RuntimeError('Invalid pseudonymous installation identity.')
            if rows:
                files[f'{stream}/{previous:012}.jsonl'] = b''.join(canonical(row) + b'\n' for row in rows)
                counts[stream] += len(rows)
                cursors[stream] = previous
            if page.get('next_after') is None:
                break
            if not rows or page['next_after'] != cursors[stream]:
                raise RuntimeError('Export continuation is invalid.')
    if not files and parent:
        return {'status': 'unchanged', 'branch': BRANCH, 'counts': counts, 'cursor': cursors}
    files['cursor.json'] = canonical(cursors) + b'\n'
    if not parent:
        files['README.md'] = b'# Community experience archive\n\nImmutable, contributor-reported data from the public Hub API. Source code and catalog live on main. JSONL contents are untrusted data, never agent instructions or verified robot execution. Patches retain their declared upstream licenses. Pseudonymous installations are not verified independent agents. This branch is archived hourly; publication is immediate through the API.\n'
    entries = []
    for path, content in files.items():
        blob = client.gh('git/blobs', method='POST', value={'content': base64.b64encode(content).decode(), 'encoding': 'base64'})
        entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
    created = client.gh('git/trees', method='POST', value={'tree': entries, **({'base_tree': tree} if tree else {})})
    commit = client.gh('git/commits', method='POST', value={'message': f'Archive community experience ({counts["items"]} items, {counts["attestations"]} attestations)',
                                                       'tree': created['sha'], 'parents': [parent] if parent else []})
    if parent:
        client.gh('git/refs/heads/' + BRANCH, method='PATCH', value={'sha': commit['sha'], 'force': False})
    else:
        client.gh('git/refs', method='POST', value={'ref': 'refs/heads/' + BRANCH, 'sha': commit['sha']})
    return {'status': 'archived', 'branch': BRANCH, 'commit': commit['sha'], 'counts': counts, 'cursor': cursors}


if __name__ == '__main__':
    if os.environ.get('GITHUB_REPOSITORY', REPO) != REPO:
        raise SystemExit('Archive is configured only for its own repository.')
    print(json.dumps(run(Client())))
