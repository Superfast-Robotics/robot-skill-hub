"""Deterministic current-version coverage; no network, execution or inferred robots."""
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path

STATES = ('completed', 'failed', 'not_executed', 'evidence_unbound')
ENV_FIELDS = ('runtime', 'runtime_version', 'robot', 'controller', 'observation', 'os', 'architecture', 'python')
# These finite-cohort receipts verify only the declared numerical/synthetic
# models. Adding a different robot label cannot inherit their environment proof.
COHORT_MODELS = {'pythonrobotics': 'mathematical-model', 'ruckig': 'independent-axes',
                 'pybullet': 'synthetic-seven-axis-or-procedural-scene'}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def groups(rows, field):
    counts = Counter()
    for row in rows:
        values = row.get(field, [])
        if isinstance(values, str): values = [values]
        for value in set(values):
            if isinstance(value, str) and value: counts[value] += 1
    return [{'label': label, 'references': count} for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def build_coverage(records, references, root, hub_commit, base):
    root = Path(root)
    manifest_path = root / 'catalog/executable-conversions.json'
    plan = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'recipes': []}
    cohort = {r['id']: r for r in plan['recipes']}
    reports = defaultdict(list)
    for path in sorted((root / 'evidence/runtime').rglob('report.json')):
        report = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(report, dict) and isinstance(report.get('skill_id'), str):
            reports[report['skill_id']].append((path, report))
    items = []
    for record in records:
        ident = record['id']; domain = record.get('interface', {}).get('execution_domain', 'unspecified')
        adapter = root / 'recipes' / ident / 'run.py'
        adapter_hash = digest(adapter.read_bytes())
        state = 'not_executed'; case_runs = Counter(); proof_paths = []; tested_os = set(); task_name = record['name']
        runtime = record['compatibility'][0]['runtime']
        verification = record['evidence'].get('hub_verification') or {}
        completed = record['evidence']['runtime_verification'] == 'task_complete'
        if completed and ident in cohort:
            recipe = cohort[ident]
            path = root / 'evidence/runtime/executable-conversions-v1' / (ident + '.json')
            proof = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
            runs = [proof] + proof.get('additional_runs', []) if proof else []
            valid = bool(runs)
            valid = valid and all(record.get('interface', {}).get(k) == v for k, v in recipe['interface'].items())
            expected_version = recipe['source_commit'][:12] if runtime == 'pythonrobotics' else '0.19.4' if runtime == 'ruckig' else '3.2.7'
            valid = valid and all(c.get('runtime') == recipe['backend'] and c.get('robot') == COHORT_MODELS.get(recipe['backend'])
                                  and c.get('runtime_version') == expected_version and c.get('controller') == 'json-contract-v1'
                                  and c.get('observation') == 'explicit-json-input' and c.get('architecture') == 'x86_64'
                                  and c.get('python') == '3.10' for c in record['compatibility'])
            for run in runs:
                valid = valid and run.get('adapter_sha256') == adapter_hash and run.get('source_commit') == record['source']['commit'] == recipe['source_commit']
                valid = valid and run.get('case_plan_sha256') == digest(encoded(recipe['cases'])) and run.get('source_guards_sha256') == digest(encoded(recipe['source_hashes']))
                valid = valid and run.get('passed') == len(recipe['cases']) and run.get('failed') == 0 and run.get('negative_unknown_field_rejected') is True
                valid = valid and [c.get('input') for c in run.get('cases', [])] == recipe['cases']
                valid = valid and all(c.get('passed') is True and c.get('exit_code') == 0 and c.get('checks') and all(c['checks'].values()) for c in run.get('cases', []))
                valid = valid and set(record['requirements']['packages']) <= set(run.get('packages', []))
                valid = valid and run.get('execution_domain') == domain and run.get('physical_robot') is False
                platforms = run.get('platforms', [])
                valid = valid and len(platforms) == 1 and platforms[0] in ('linux', 'windows')
            if valid:
                state = 'completed'; proof_paths = [path.relative_to(root).as_posix()]
                for run in runs:
                    tested_os.update(run['platforms']); case_runs[run['platforms'][0]] += run['passed']
            else: state = 'evidence_unbound'
        elif completed:
            valid = domain == 'simulation' and verification.get('runtime') == 'task_complete' and verification.get('adapter_sha256') == adapter_hash
            valid = valid and verification.get('source_commit') == record['source']['commit'] and verification.get('record_version') == record['maintenance']['record_version']
            candidates = [(p, r) for p, r in reports[ident] if r.get('adapter_sha256') == adapter_hash
                          and r.get('source_commit') == record['source']['commit'] and r.get('record_version') == record['maintenance']['record_version']
                          and str(verification.get('workflow_run_id', 'missing')) in str(p)
                          and r.get('execution_performed') is True and r.get('success') is True and r.get('contract_matches') is True
                          and r.get('status') == 'task_complete' and r.get('execution', {}).get('exit_code') == 0]
            valid = valid and bool(candidates) and all(c.get('runtime') == 'maniskill' and c.get('robot') == candidates[0][1].get('result', {}).get('robot')
                and c.get('runtime_version') == candidates[0][1].get('result', {}).get('runtime')
                and c.get('controller') == candidates[0][1].get('result', {}).get('controller')
                and c.get('observation') == candidates[0][1].get('result', {}).get('observation')
                and c.get('os') == 'linux' for c in record['compatibility'])
            if valid:
                path, proof = candidates[0]; state = 'completed'; case_runs['linux'] = 1; tested_os.add('linux')
                task_name = proof.get('result', {}).get('task', task_name); proof_paths = [path.relative_to(root).as_posix()]
            else: state = 'evidence_unbound'
        else:
            attempt = verification.get('last_task_attempt') or {}
            if attempt.get('execution_performed') is True:
                candidates = [(p, r) for p, r in reports[ident] if r.get('adapter_sha256') == adapter_hash
                              and r.get('source_commit') == record['source']['commit'] and r.get('record_version') == record['maintenance']['record_version']
                              and str(attempt.get('workflow_run_id', 'missing')) in str(p)
                              and r.get('execution_performed') is True and r.get('success') is False
                              and r.get('execution', {}).get('started') is True]
                if domain == 'simulation' and attempt.get('status') == 'failed' and candidates:
                    path, proof = candidates[0]; state = 'failed'
                    platform = attempt.get('environment', {}).get('os', 'unspecified')
                    tested_os.add(platform); case_runs[platform] = 1
                    task_name = proof.get('result', {}).get('task', task_name); proof_paths = [path.relative_to(root).as_posix()]
                else: state = 'evidence_unbound'
        declared_envs = [{k: c.get(k, 'unspecified') for k in ENV_FIELDS} for c in record['compatibility']]
        tested_envs = [c for c in declared_envs if c['os'] in tested_os]
        items.append({'id': ident, 'name': record['name'], 'task_or_operation': task_name, 'runtime': runtime,
                      'domain': domain, 'abstraction_level': record.get('interface', {}).get('abstraction_level'),
                      'robot_model_labels': sorted({c['robot'] for c in declared_envs}), 'state': state,
                      'tested_os': sorted(tested_os), 'declared_environments': declared_envs, 'tested_environments': tested_envs,
                      'case_runs_by_os': dict(case_runs), 'record_url': base + '/skills/' + ident + '/skill.json',
                      'evidence_urls': ['https://raw.githubusercontent.com/Superfast-Robotics/robot-skill-hub/' + hub_commit + '/' + p for p in proof_paths]})
    counts = Counter(item['state'] for item in items)
    execution_rows = {}
    level_rows = {}
    for item in items:
        key = (item['runtime'], ', '.join(item['robot_model_labels']), item['domain'])
        row = execution_rows.setdefault(key, {'runtime': key[0], 'robot_model': key[1], 'domain': key[2], 'prepared': 0,
                                             **{s: 0 for s in STATES}, 'tested_os': set(), 'case_runs_by_os': Counter()})
        row['prepared'] += 1; row[item['state']] += 1; row['tested_os'].update(item['tested_os']); row['case_runs_by_os'].update(item['case_runs_by_os'])
        level = level_rows.setdefault(item['abstraction_level'], {'level': item['abstraction_level'], 'prepared': 0, **{s: 0 for s in STATES}})
        level['prepared'] += 1; level[item['state']] += 1
    rows = []
    for key, row in sorted(execution_rows.items()):
        row['tested_os'] = sorted(row['tested_os']); row['case_runs_by_os'] = dict(row['case_runs_by_os']); rows.append(row)
    refs = references['records']
    ref_environments = [{**r, 'runtime_labels': sorted({c['runtime'] for c in r.get('compatibility', [])}),
                         'robot_labels': sorted(set(r.get('robots', [])) | {c['robot'] for c in r.get('compatibility', [])})} for r in refs]
    case_runs = Counter(); environments = set()
    for item in items:
        case_runs.update(item['case_runs_by_os'])
        environments.update(encoded(e) for e in item['tested_environments'])
    return {'schema_version': '1', 'interpretation': 'data_only', 'hub_commit': hub_commit,
            'scope': 'Current pinned recipes and retained exact-adapter evidence. Historical attempts do not promote a changed version. Authored cases are not general accuracy estimates.',
            'totals': {'preparation_recipes': len(records), 'source_references': len(refs), **{s: counts[s] for s in STATES},
                       'completed_computations': sum(i['state'] == 'completed' and i['domain'] == 'computation' for i in items),
                       'completed_simulations': sum(i['state'] == 'completed' and i['domain'] == 'simulation' for i in items),
                       'completed_hardware': sum(i['state'] == 'completed' and i['domain'] == 'hardware' for i in items),
                       'tested_environment_combinations': len(environments),
                       'reference_frameworks': len({r['framework'] for r in refs})},
            'execution_by_runtime_model': rows, 'execution_by_abstraction': [r for _, r in sorted(level_rows.items(), key=lambda pair: str(pair[0]))],
            'case_runs_by_os': dict(case_runs), 'recipes': items,
            'references': {'counting_rule': 'Framework totals count each reference once. Robot, environment and capability tags may overlap and do not establish execution or hardware support.',
                           'by_framework': groups(refs, 'framework'), 'by_robot_type': groups(refs, 'robot_types'),
                           'by_robot_label': groups(ref_environments, 'robot_labels'), 'by_runtime_label': groups(ref_environments, 'runtime_labels'),
                           'by_capability': groups(refs, 'capabilities'),
                           'by_runtime_evidence': groups([{**r, 'runtime_evidence': r['evidence']['runtime_verification']} for r in refs], 'runtime_evidence')}}


def table(caption, headers, rows):
    esc = lambda v: html.escape(str(v), quote=True)
    def cell(value):
        if isinstance(value, tuple) and len(value) == 2:
            label, url = value
            return '<a href="' + esc(url) + '">' + esc(label) + '</a>' if str(url).startswith(('https://', 'http://')) else esc(label)
        return esc(value)
    return '<table><caption>' + esc(caption) + '</caption><thead><tr>' + ''.join('<th scope="col">' + esc(h) + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + cell(c) + '</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table>'


def coverage_tables(report, base, *, full=False):
    counts = report['totals']
    execution = [[r['runtime'], r['robot_model'], r['domain'], ', '.join(r['tested_os']) or 'no task run', r['prepared'], r['completed'], r['failed'], r['not_executed'], r['evidence_unbound']] for r in report['execution_by_runtime_model']]
    text = '<h2>Execution coverage</h2><p>' + str(counts['completed']) + ' recipes have exact-version completion evidence: ' + str(counts['completed_computations']) + ' computations and ' + str(counts['completed_simulations']) + ' simulations. Physical robot completions: ' + str(counts['completed_hardware']) + '.</p>'
    text += table('Current recipes by runtime and declared model', ['Runtime', 'Robot / model', 'Domain', 'Tested OS', 'Prepared', 'Passed', 'Failed', 'No task run', 'Unbound evidence'], execution)
    text += '<p>Passed means this operation and its recorded checks, not arbitrary task success. Failed is an executed current-version task failure. Other declared robot variants have no current task run. Counts are recipe counts, not unique physical robots or a benchmark success rate.</p>'
    text += '<p>Retained case runs for current recipes: ' + ', '.join(str(count) + ' on ' + platform for platform, count in sorted(report['case_runs_by_os'].items())) + '. These include the recorded failure; historical repeats and obsolete adapters are not added.</p>'
    names = {0: '0: algorithm / sensing', 1: '1: motion / control', 2: '2: task', 3: '3: workflow'}
    text += table('Task abstraction', ['Level', 'Prepared', 'Passed', 'Failed', 'No task run', 'Unbound evidence'], [[names.get(r['level'], 'unspecified'), r['prepared'], r['completed'], r['failed'], r['not_executed'], r['evidence_unbound']] for r in report['execution_by_abstraction']])
    text += '<h2>Source-reference coverage</h2><p>' + str(counts['source_references']) + ' references across ' + str(counts['reference_frameworks']) + ' frameworks. These are declared source environments, robot labels and capabilities; catalog presence is not execution evidence. Tags overlap.</p>'
    sections = [('by_framework', 'Reference frameworks', 'Framework'), ('by_robot_type', 'Reference robot categories', 'Robot category'), ('by_capability', 'Reference task / capability tags', 'Capability')]
    if full: sections += [('by_robot_label', 'Declared reference robot labels', 'Robot label'), ('by_runtime_label', 'Declared reference runtime labels', 'Runtime'), ('by_runtime_evidence', 'Reference execution evidence', 'Evidence')]
    for key, caption, label in sections:
        rows = report['references'][key]; visible = rows if full or key in ('by_framework', 'by_robot_type') else rows[:6]
        data = [[r['label'], r['references']] for r in visible]
        if not full and key == 'by_framework' and len(rows) > len(visible): data.append(['Other frameworks (' + str(len(rows) - len(visible)) + ')', sum(r['references'] for r in rows[len(visible):])])
        text += table(caption + (' (leading groups)' if len(visible) < len(rows) else ''), [label, 'References'], data)
    text += '<p><a href="' + html.escape(base, quote=True) + '/coverage.html">Full robot, environment and task tables</a> | <a href="' + html.escape(base, quote=True) + '/catalog/v1/coverage.json">Coverage JSON</a>. Source pins and retained evidence are available per recipe.</p>'
    if full:
        text += table('Every current preparation recipe', ['ID', 'Task / operation', 'State', 'Tested OS', 'Evidence'],
                      [[(i['id'], i['record_url']), i['task_or_operation'], i['state'], ', '.join(i['tested_os']) or 'none',
                        ('receipt', i['evidence_urls'][0]) if i['evidence_urls'] else 'none'] for i in report['recipes']])
    return text
