"""Export an explicit evidence allowlist, never the private working directory."""
import argparse,hashlib,json,pathlib,shutil,zipfile

def scrub(value):
    if isinstance(value,dict):return {k:scrub(v) for k,v in value.items() if k not in ('encrypted_content','response_id')}
    if isinstance(value,list):return [scrub(v) for v in value]
    return value

def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);args=p.parse_args()
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    for name in ['plan.json','plan.sha256','results.json','scored-start.json','executor-preflight.json','source-receipts.json','classification-correction.json']:
        if (args.work/name).exists():shutil.copy2(args.work/name,out/name)
    archive=out/'traces.zip'
    receipts=[]
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for folder in sorted((args.work/'trials').iterdir()):
            if not folder.is_dir():continue
            for f in sorted(folder.iterdir()):
                if f.name not in ('trace.json','held-out.json','result.json') and not (f.name.startswith(('candidate-','execution-')) and f.suffix in ('.py','.json')):continue
                raw=f.read_bytes()
                if f.suffix=='.json':raw=(json.dumps(scrub(json.loads(raw)),indent=2)+'\n').encode()
                name=folder.name+'/'+f.name;z.writestr(name,raw)
                receipts.append({'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
        for source in (args.work/'executor/sources').iterdir():
            for license_name in ['LICENSE','LICENSE.txt']:
                f=source/license_name
                if f.exists():z.writestr('UPSTREAM_LICENSES/'+source.name+'/'+license_name,f.read_bytes())
    (out/'trace-manifest.json').write_bytes((json.dumps({'files':receipts,'redactions':['Opaque encrypted reasoning payloads and provider response IDs omitted; usage, prompts, tool requests, candidates and execution evidence retained.'],'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2)+'\n').encode())
    print(json.dumps({'exported_files':len(receipts),'trace_zip_bytes':archive.stat().st_size}))
if __name__=='__main__':main()
