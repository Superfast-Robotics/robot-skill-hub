"""Apache-2.0. Credential-free, bounded robotics discovery for task skills."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.superfastrobotics.com'
MAX_BYTES = 512 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def read_json(url, channel):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'api.superfastrobotics.com' or parsed.fragment:
        raise ValueError('Use the exact HTTPS API inspect_url returned by search')
    if not (parsed.path in ('/v1/search', '/v1/start') or re.fullmatch(r'/v1/skills/[a-z0-9-]{1,80}', parsed.path)):
        raise ValueError('Only public search and skill inspection are supported')
    headers = {'Accept': 'application/json', 'User-Agent': 'robot-skill-hub/task-skill-v1',
               'X-RSH-Channel': channel}
    if os.environ.get('RSH_TELEMETRY', '').lower() == 'off':
        headers.update({'DNT': '1', 'X-RSH-Telemetry': 'off'})
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('API response exceeds the bounded read budget')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Expected an API JSON object')
    return result


def find(query, channel, runtime=None, task=False, fetch=read_json):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 160:
        raise ValueError('Use 1 to 160 characters describing the current robotics task')
    params = {'q': query, 'kind': 'preparation_recipe', 'limit': 3}
    if runtime:
        params['runtime'] = runtime
    if task:
        params['query_mode'] = 'task'
    result = fetch(API + '/v1/search?' + urllib.parse.urlencode(params), channel)
    rows = result.get('results')
    if not isinstance(rows, list) or len(rows) > 3:
        raise ValueError('Invalid bounded search response')
    return {**result, 'execution_performed': False}


def start(query, channel, runtime=None, task=False, fetch=read_json):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 160:
        raise ValueError('Use 1 to 160 characters describing the current robotics task')
    params = {'q': query, 'limit': 1, 'query_mode': 'task' if task else 'all_terms'}
    if runtime:
        params['runtime'] = runtime
    result = fetch(API + '/v1/start?' + urllib.parse.urlencode(params), channel)
    if not isinstance(result.get('results'), list) or len(result['results']) > 3 or 'selected' not in result:
        raise ValueError('Invalid bounded task-start response')
    return result


def inspect_url(url, channel, fetch=read_json, include_files=False):
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
    if not re.fullmatch(r'/v1/skills/[a-z0-9-]{1,80}', parsed.path):
        raise ValueError('Use a skill inspect_url, not a search or arbitrary URL')
    if not re.fullmatch('[a-f0-9]{40}', query.get('hub_commit', [''])[0]) or not query.get('record_version'):
        raise ValueError('Keep the search result hub_commit and record_version pins')
    if query.get('include') != ['experience']:
        raise ValueError('Use the returned include=experience inspect_url')
    result = fetch(url, channel)
    record = result.get('record')
    if not isinstance(record, dict) or not record.get('interface'):
        raise ValueError('Selected result does not expose an execution interface')
    if result.get('hub_commit') != query['hub_commit'][0]:
        raise ValueError('The catalog generation changed; refresh search')
    if record.get('maintenance', {}).get('record_version') != query['record_version'][0]:
        raise ValueError('The selected record version changed; refresh search')
    # Keep source pins, contracts, evidence and recall; code is obtained only
    # through the separate pinned preparation CLI, not dumped into context.
    record = dict(record)
    if not include_files:
        record['preparation'] = {k: v for k, v in record.get('preparation', {}).items() if k != 'files'}
    return {**result, 'record': record, 'inspection_url': url, 'execution_performed': False,
            'embedded_recipe_files_omitted': not include_files}


def export_catalog(url, channel, output, fetch=read_json):
    value = inspect_url(url, channel, fetch, include_files=True)
    record = value['record']
    if not record.get('preparation', {}).get('files'):
        raise ValueError('The selected recipe does not expose preparation files')
    catalog = {'schema_version': '1', 'hub_commit': value['hub_commit'], 'records': [record]}
    with Path(output).open('xb') as stream:
        stream.write((json.dumps(catalog, ensure_ascii=True) + '\n').encode())
    return {'status': 'ready', 'catalog_path': str(Path(output).resolve()),
            'hub_commit': value['hub_commit'], 'skill_id': record['id'],
            'execution_performed': False}


def main(channel):
    parser = argparse.ArgumentParser(description='Find and inspect pinned executable robotics recipes; never execute them.')
    sub = parser.add_subparsers(dest='operation', required=True)
    search = sub.add_parser('find')
    search.add_argument('query')
    search.add_argument('--runtime', help='Only a known runtime; omit unknown environment labels')
    search.add_argument('--task', action='store_true', help='Rank an English task sentence')
    starter = sub.add_parser('start', help='Get candidates, the first contract, prior fixes and pinned preparation argv')
    starter.add_argument('query')
    starter.add_argument('--runtime')
    starter.add_argument('--task', action='store_true')
    inspect = sub.add_parser('inspect')
    inspect.add_argument('url', help='Exact inspect_url from a search result')
    catalog = sub.add_parser('catalog', help='Export the selected full record as inert pinned CLI data')
    catalog.add_argument('url')
    catalog.add_argument('--output', required=True, type=Path, help='Fresh file; existing files are preserved')
    args = parser.parse_args()
    try:
        if args.operation == 'start':
            result = start(args.query, channel, args.runtime, args.task)
        elif args.operation == 'find':
            result = find(args.query, channel, args.runtime, args.task)
        elif args.operation == 'catalog':
            result = export_catalog(args.url, channel, args.output)
        else:
            result = inspect_url(args.url, channel)
        print(json.dumps(result, ensure_ascii=True, separators=(',', ':'), allow_nan=False))
        return 0
    except (ValueError, OSError, urllib.error.URLError) as error:
        print(json.dumps({'status': 'failed', 'reason_code': 'discovery_unavailable',
                          'message': str(error), 'execution_performed': False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main('task-kinematics'))
