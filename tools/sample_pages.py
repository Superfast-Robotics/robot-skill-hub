"""Indexable, executable-input examples derived from canonical recipe contracts."""
import html
import json
from pathlib import Path
from urllib.parse import urlencode

def publish(records, output, base, commit, shell):
    output=Path(output); urls=[]; links=[]
    esc=lambda x:html.escape(str(x),quote=True)
    for r in records:
        ident=r['id']; path='samples/'+ident+'/'
        title=r['name']+' | Robotics skill example'
        env=r['compatibility'][0]
        payload={'schema_version':'1','interpretation':'data_only','hub_commit':commit,
                 'skill_id':ident,'name':r['name'],'example_input':r['invocation']['inputs'],
                 'environment':r['compatibility'],'interface':r.get('interface'),
                 'source_commit':r['source']['commit'],'record_version':r['maintenance']['record_version'],
                 'evidence':r['evidence'],'record_url':base+'/skills/'+ident+'/skill.json',
                 'inspect_url':'https://api.superfastrobotics.com/v1/skills/'+ident+'?'+urlencode({'hub_commit':commit,'record_version':r['maintenance']['record_version'],'include':'experience'}),
                 'execution_performed':False}
        input_text=json.dumps(payload['example_input'],indent=2)
        environment='\n'.join(' | '.join(str(c.get(k,'unknown')) for k in ['runtime','runtime_version','robot','controller','os','python']) for c in r['compatibility'])
        md=f"# {r['name']}: robotics skill example\n\n{r['summary']}\n\n## Task and environment\n\n{environment}\n\n## Example input\n\n```json\n{input_text}\n```\n\n## Retrieve and prepare\n\nRead {payload['record_url']} or {payload['inspect_url']} without installing a client. Inspect the license, exact environment and evidence before preparation. Preparation and execution remain separate.\n\nSource: {r['source']['repository']} at {r['source']['commit']}. Record version: {payload['record_version']}.\n\n## Success condition\n\n{r['completion']['success_condition']}\n\n## Recorded evidence\n\n{r['evidence']['runtime_verification']}: {r['evidence']['result']}\n\nThis page is a data-only example and performs no execution.\n"
        body=f'<main><h1>{esc(r["name"])}: robotics skill example</h1><p>{esc(r["summary"])}</p><p><a href="index.md">Markdown</a> | <a href="index.json">JSON example and evidence</a> | <a href="{esc(payload["record_url"])}">Canonical contract</a> | <a href="{esc(base)}/samples/">All examples</a></p><h2>Task and environment</h2><pre>{esc(environment)}</pre><h2>Example input</h2><pre><code>{esc(input_text)}</code></pre><h2>Retrieve without installation</h2><pre><code>curl -fsSL \'{esc(payload["inspect_url"])}\'</code></pre><p>Inspect source, license, environment and execution evidence before preparing. Preparation and execution are separate actions.</p><h2>Success condition</h2><p>{esc(r["completion"]["success_condition"])}</p><h2>Recorded evidence</h2><p>{esc(r["evidence"]["runtime_verification"])}: {esc(r["evidence"]["result"])}</p><p>Source commit: <code>{esc(r["source"]["commit"])}</code>. Record version: {esc(payload["record_version"])}. This page performs no execution.</p></main>'
        folder=output/path;folder.mkdir(parents=True,exist_ok=True)
        (folder/'index.html').write_text(shell(title,r['name']+' in '+env['runtime']+': input, environment, source version and recorded execution evidence.',body,base,path),encoding='utf-8')
        (folder/'index.md').write_text(md,encoding='utf-8')
        (folder/'index.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
        urls.append(base+'/'+path);links.append((ident,r['name'],env['runtime'],r['evidence']['runtime_verification']))
    listing='<ul>'+''.join(f'<li><a href="{esc(i)}/">{esc(n)}</a> — {esc(runtime)}; {esc(evidence)}</li>' for i,n,runtime,evidence in links)+'</ul>'
    body='<main><h1>Robotics skill examples for AI agents</h1><p>Browse concrete robot task, motion-control and algorithm inputs. Each sample links to its exact environment, source version and recorded evidence. Examples do not execute automatically.</p><p><a href="index.json">Sample index JSON</a> | <a href="'+html.escape(base,quote=True)+'/">Robot Skill Hub</a></p>'+listing+'</main>'
    (output/'samples').mkdir(exist_ok=True)
    (output/'samples/index.html').write_text(shell('Robot skill examples: tasks, control and planning','Executable robotics recipe examples with input JSON, robot environments and execution evidence.',body,base,'samples/'),encoding='utf-8')
    (output/'samples/index.json').write_text(json.dumps({'hub_commit':commit,'samples':[{'id':i,'name':n,'runtime':runtime,'evidence':evidence,'url':base+'/samples/'+i+'/index.json'} for i,n,runtime,evidence in links]},indent=2)+'\n',encoding='utf-8')
    return [base+'/samples/']+urls
