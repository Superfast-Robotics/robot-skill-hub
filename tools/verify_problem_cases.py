"""Run frozen failure/valid-input reproductions; public reads never invoke this."""
import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/find-robot-skills/scripts'))
from rshlib.interfaces import validate_handoff
from generate_problem_cases import case_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-cache', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--publish-evidence', action='store_true')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    plan = json.loads((ROOT / 'catalog/problem-cases.json').read_text())
    recipes = {r['id']: r for r in json.loads((ROOT / 'catalog/executable-conversions.json').read_text())['recipes']}
    environment = {k: v for k, v in os.environ.items() if k.upper() in ['PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATHEXT']}
    environment.update(MPLBACKEND='Agg', MPLCONFIGDIR=str((args.output / 'matplotlib').resolve()), RSH_TELEMETRY='off', OPENBLAS_NUM_THREADS='1', PYTHONNOUSERSITE='1')

    def execute(ident, data, label):
        recipe = recipes[ident]
        command = [sys.executable, str(ROOT / 'recipes' / ident / 'run.py'), '--source-dir',
                   str(args.source_cache.resolve() / recipe['backend']), '--input-json', json.dumps(data)]
        run = subprocess.run(command, capture_output=True, timeout=30, env=environment)
        (args.output / (label + '.stdout')).write_bytes(run.stdout); (args.output / (label + '.stderr')).write_bytes(run.stderr)
        return run.returncode, json.loads(run.stdout)

    reports = []
    for case in plan['cases']:
        mode = case['mode']; observed = {}
        if mode == 'upstream_interpolation':
            recipe = recipes[case['skill_id']]
            path = args.source_cache / 'pythonrobotics' / recipe['source_path']; raw = path.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == recipe['source_hashes'][recipe['source_path']]
            node = next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'get_target_point')
            scope = {'math': math}; exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
            value = scope['get_target_point'](case['bad_input']['path'], case['bad_input']['distance'])
            problem = value != case['bad_input']['expected']; observed = {'original_result': value, 'expected': case['bad_input']['expected']}
        elif mode == 'handoff':
            source = recipes[case['skill_id']]['interface']; target = copy.deepcopy(recipes['pythonrobotics-path-smoothing']['interface'])
            target['conventions']['coordinate_frame'] = case['bad_input']['target_frame']
            try: validate_handoff(case['bad_input']['path_xy'], source, 'path_xy', target, 'path_xy'); problem = False
            except ValueError: problem = True
            validate_handoff(case['bad_input']['path_xy'], source, 'path_xy', recipes['pythonrobotics-path-smoothing']['interface'], 'path_xy')
        else:
            code, bad = execute(case['bad_skill_id'], case['bad_input'], case['id'] + '-bad')
            problem = code != 0 and bad.get('success') is False
            observed = {'exit_code': code, 'reason_code': bad.get('reason_code')}
        if mode == 'handoff': good, checks = True, {'compatible_field_handoff': True}
        else:
            code, body = execute(case['skill_id'], case['good_input'], case['id'] + '-valid')
            checks = body.get('checks', {}); good = code == 0 and body.get('success') is True and bool(checks) and all(checks.values())
        report = {'id': case['id'], 'case_sha256': case_hash(case), 'problem_reproduced': problem,
                  'valid_case_passed': good, 'observed_problem': observed, 'checks': checks,
                  'adapter_sha256': hashlib.sha256((ROOT / 'recipes' / case['skill_id'] / 'run.py').read_bytes()).hexdigest(),
                  'bad_adapter_sha256': hashlib.sha256((ROOT / 'recipes' / case['bad_skill_id'] / 'run.py').read_bytes()).hexdigest(),
                  'source_commit': case['source_commit'], 'mode': mode}
        reports.append(report); print(json.dumps(report), flush=True)
    receipt = {'schema_version': '1', 'observed_at': datetime.now(timezone.utc).isoformat(), 'cases': reports,
               'passed': sum(r['problem_reproduced'] and r['valid_case_passed'] for r in reports), 'total': len(reports),
               'scope': 'Authored failure/valid-input CPU regressions and one field handoff; not autonomous LLM discovery or hardware.', 'physical_robot': False, 'gpu': False}
    (args.output / 'summary.json').write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
    good = receipt['passed'] == receipt['total']
    if args.publish_evidence:
        if not good: raise RuntimeError('Do not publish unsuccessful reproduction evidence')
        dest = ROOT / 'evidence/integration/agent-discovery-v1/problem-cases.json'
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
    return 0 if good else 1


if __name__ == '__main__': raise SystemExit(main())
