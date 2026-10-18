"""Rebuild explicitly reviewed platform references from immutable text; never execute it."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

from import_ecosystem_examples import safe_relative
from reference_index import check_source_index, write_source_index

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = 'curated-platform-sources-v1'
MAX_BYTES = 256 * 1024


def checked(project, pin, cache, fetch=False):
    safe_relative(pin['path'])
    if (not re.fullmatch('[a-f0-9]{64}', pin['sha256']) or not re.fullmatch('[a-f0-9]{40}', pin['git_blob'])
            or type(pin['bytes']) is not int or not 0 < pin['bytes'] <= MAX_BYTES):
        raise ValueError('A bounded source SHA-256, Git blob and byte count are required')
    path = Path(cache) / (pin['sha256'] + '.txt')
    if path.is_symlink() or not path.resolve().is_relative_to(Path(cache).resolve()):
        raise ValueError('Source cache escapes its directory')
    if fetch:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        url = project['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/') + '/' + project['commit'] + '/' + urllib.parse.quote(pin['path'], safe='/')
        request = urllib.request.Request(url, headers={'User-Agent':'robot-skill-hub-source-review', 'DNT':'1', 'X-RSH-Telemetry':'off'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            data = response.read(MAX_BYTES + 1)
    else:
        with path.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
    if (len(data) != pin['bytes'] or hashlib.sha256(data).hexdigest() != pin['sha256']
            or hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != pin['git_blob'] or b'\0' in data):
        raise ValueError('Source identity mismatch: ' + pin['path'])
    text = data.decode('utf-8-sig')
    if any(anchor not in text for anchor in pin.get('contains', [])):
        raise ValueError('Reviewed source evidence changed: ' + pin['path'])
    if fetch:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return text


def build(manifest, existing, cache, fetch=False):
    if manifest.get('schema_version') != '1' or not manifest.get('projects'):
        raise ValueError('A nonempty reviewed manifest is required')
    generated = []
    for p in manifest['projects']:
        if (not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', p['repository'])
                or not re.fullmatch('[a-f0-9]{40}', p['commit']) or not p['authors'] or not p['artifacts']):
            raise ValueError('Public repository, immutable commit, authors and artifacts are required')
        texts = {pin['path']: checked(p,pin,cache,fetch) for pin in [p['license'],*p['evidence_files'],*p['artifacts']]}
        if p['license']['spdx'] != 'Apache-2.0' or 'Apache License' not in texts[p['license']['path']] or not p['license']['scope']:
            raise ValueError('This selection requires its reviewed Apache-2.0 source terms')
        url = lambda path: p['repository'] + '/blob/' + p['commit'] + '/' + urllib.parse.quote(path,safe='/')
        for a in p['artifacts']:
            text = texts[a['path']]
            if a['format'] == 'python':
                tree = ast.parse(text, filename=a['path'])
                if not any(isinstance(n,ast.Call) for n in ast.walk(tree)):
                    raise ValueError('Python program must contain its reviewed operation')
            elif a['format'] == 'cpp':
                code = re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
                if not re.search(r'\bint\s+main\s*\(',code):
                    raise ValueError('Native example requires a main entrypoint')
            elif a['format'] == 'agent-skill-markdown':
                if not text.startswith('---\n') or not re.search(r'^name:\s*\S+',text,re.M) or not re.search(r'^description:\s*\S+',text,re.M):
                    raise ValueError('Agent instruction source requires declared name and description')
            else:
                raise ValueError('Unsupported curated artifact format')
            declarations = re.findall(r'SPDX-License-Identifier:\s*([^\r\n]+)',text[:6000])
            if any(d.strip().rstrip('*/ ') != p['license']['spdx'] for d in declarations):
                raise ValueError('Conflicting file license requires separate review')
            if not re.fullmatch('[a-z0-9][a-z0-9-]{0,79}',a['id']) or not a['contains']:
                raise ValueError('Stable ID and reviewed source anchors are required')
            generated.append({
                'id':a['id'],'name':a['name'],'summary':a['summary'],'framework':p['id'],'kind':'official_example','source_registry':REGISTRY,
                'capabilities':a['capabilities'],'aliases':a.get('aliases',[]),'robot_types':p['robot_types'],
                'robot_scope':p['robot_scope'],
                'source':{'repository':p['repository'],'commit':p['commit'],'path':a['path'],'url':url(a['path']),
                    'sha256':a['sha256'],'bytes':a['bytes'],'authors':p['authors']},
                'license':{'spdx':p['license']['spdx'],'url':url(p['license']['path']),'sha256':p['license']['sha256'],'bytes':p['license']['bytes'],'verified':True,'scope':p['license']['scope']},
                'artifact':{'kind':'workflow' if a['format']=='agent-skill-markdown' else 'source_code','format':a['format'],'role':a['role']},
                'access':{'mode':'source_reference','hub_prepare':False,'setup_url':url(a.get('setup_path',p['setup_path'])),
                    'instructions':'Read the exact source with its upstream setup and adjacent dependencies. This reference neither installs an agent instruction bundle nor authorizes code or physical motion.'},
                'requirements':{**p['requirements'],'execution_domain':a['execution_domain']},
                'invocation':{'entrypoint':a['entrypoint'],'notes':a['invocation_notes']},
                'evidence':{'level':'source_reviewed','runtime_verification':'not_run','checked_at':p['checked_at'],'inspection_method':'static_text_and_source_identity',
                    'inspection':'Verified SHA-256, byte count, Git blob, reviewed operation anchors and source license. Parsed Python as AST or inspected native/instruction entry documents; no upstream instructions or code executed.',
                    'source_anchors':a['contains'],'provenance_files':[{'path':pin['path'],'url':url(pin['path']),'sha256':pin['sha256'],'bytes':pin['bytes']} for pin in p['evidence_files']]}
            })
    records = [r for r in existing['records'] if r.get('source_registry') != REGISTRY] + generated
    if (len({r['id'] for r in records}) != len(records)
            or len({(r['source']['repository'],r['source'].get('commit',r['source'].get('revision')),r['source']['path']) for r in records}) != len(records)):
        raise ValueError('Duplicate record or source identity')
    return {**existing,'curated_source_manifest':'curated-source-projects.json','records':sorted(records,key=lambda r:(r['framework'],r['id']))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'catalog/curated-source-projects.json')
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--fetch',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    path=ROOT/'catalog/references.json'
    existing=json.loads(path.read_text(encoding='utf-8'))
    result=build(json.loads(args.manifest.read_text(encoding='utf-8')),existing,args.cache,args.fetch)
    if args.check:
        if result != existing: raise ValueError('Curated source catalog drift')
        check_source_index(result['records'],ROOT/'catalog/source-index.json')
    else:
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        write_source_index(result['records'],ROOT/'catalog/source-index.json')
    print(json.dumps({'curated_references':sum(r.get('source_registry')==REGISTRY for r in result['records']),'total_official_references':len(result['records']),'execution_performed':False}))


if __name__=='__main__': main()
