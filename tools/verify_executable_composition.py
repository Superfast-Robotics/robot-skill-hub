"""Explicit CPU regression: actual pinned A* output handed to the smoother."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/find-robot-skills/scripts'))
from rshlib.interfaces import validate_handoff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--publish-evidence', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    plan = json.loads((ROOT / 'catalog/executable-conversions.json').read_text())
    recipes = {r['id']: r for r in plan['recipes']}
    source = recipes['pythonrobotics-astar-planner']
    target = recipes['pythonrobotics-path-smoothing']
    environment = {k: v for k, v in os.environ.items() if k.upper() in
                   ['PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATHEXT']}
    environment.update(MPLBACKEND='Agg', MPLCONFIGDIR=str((args.output / 'matplotlib-cache').resolve()),
                       RSH_TELEMETRY='off', PYTHONNOUSERSITE='1', OPENBLAS_NUM_THREADS='1')

    def execute(recipe, data, label):
        adapter = ROOT / 'recipes' / recipe['id'] / 'run.py'
        result = subprocess.run([sys.executable, str(adapter), '--source-dir',
            str(args.source_cache.resolve() / 'pythonrobotics'), '--input-json', json.dumps(data)],
            capture_output=True, env=environment, timeout=30)
        (args.output / (label + '.stdout')).write_bytes(result.stdout)
        (args.output / (label + '.stderr')).write_bytes(result.stderr)
        return result, json.loads(result.stdout)

    results = []
    for index, case in enumerate(source['cases']):
        initial, a = execute(source, case, str(index) + '-astar')
        if initial.returncode or a.get('success') is not True:
            raise RuntimeError('A* failed; inspect retained output')
        path = validate_handoff(a['outputs']['path_xy'], source['interface'], 'path_xy', target['interface'], 'path_xy')
        data = {'path_xy': path, 'obstacles': [p + [0.] for p in case['obstacles']],
                'robot_radius': case['robot_radius'], 'seed': [0, 7, 42][index]}
        final, b = execute(target, data, str(index) + '-smoothing')
        lo, hi = case['bounds']; radius = case['robot_radius']
        output_path = b.get('outputs', {}).get('path_xy', [])
        contained = bool(output_path) and all(lo + radius <= v <= hi - radius for p in output_path for v in p)
        passed = final.returncode == 0 and b.get('success') is True and contained
        results.append({'case': index, 'handoff_validated': True, 'passed': passed,
                        'convex_map_bounds_preserved': contained,
                        'source_length_m': a['outputs']['length_m'],
                        'target_length_m': b.get('outputs', {}).get('length_m'),
                        'checks': b.get('checks', {}), 'target_exit_code': final.returncode})
    # The caller cannot submit an already colliding path and get a success.
    invalid = {'path_xy': [[0., 0.], [2., 0.]], 'obstacles': [[1., 0., .1]], 'robot_radius': .2, 'seed': 0}
    run, body = execute(target, invalid, 'colliding-input')
    rejected = run.returncode == 2 and body.get('reason_code') == 'invalid_input_or_environment'
    receipt = {'schema_version': '1', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'platform': platform.system().lower(), 'python': platform.python_version(),
        'scope': 'Three authored A* maps followed by smoothing; not an autonomous LLM or hardware task.',
        'mapping': 'Same map frame and meters; point obstacles become zero-radius circles. Convex map bounds checked separately on all endpoints.',
        'source_commit': source['source_commit'],
        'adapters': {r['id']: hashlib.sha256((ROOT / 'recipes' / r['id'] / 'run.py').read_bytes()).hexdigest() for r in [source, target]},
        'cases': results, 'passed': sum(r['passed'] for r in results), 'total': len(results),
        'colliding_input_rejected': rejected, 'gpu': False, 'physical_robot': False}
    (args.output / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
    good = receipt['passed'] == receipt['total'] and rejected
    if args.publish_evidence:
        if not good: raise RuntimeError('Do not publish failed composition evidence')
        destination = ROOT / 'evidence/integration/executable-composition-v1.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
    print(json.dumps(receipt))
    return 0 if good else 1


if __name__ == '__main__': raise SystemExit(main())
