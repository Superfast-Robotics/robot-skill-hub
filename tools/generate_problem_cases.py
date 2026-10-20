"""Publish ten finite, reproducible robotics input/compatibility cases."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cases():
    manifest = json.loads((ROOT / 'catalog/executable-conversions.json').read_text())
    recipes = {r['id']: r for r in manifest['recipes']}
    profiles = [
        ('path-smoothing-arclength', 'Path smoothing selects the wrong arclength point', 'pythonrobotics-path-smoothing', 'Upstream segment indexing and interpolation can select a point off the requested path segment. The Hub wrapper corrects interpolation; original source remains pinned and unchanged.', 'upstream_interpolation', None),
        ('path-smoothing-collision', 'Reject a path that already crosses an inflated obstacle', 'pythonrobotics-path-smoothing', 'A shortcut algorithm cannot establish safety for an already colliding input path. Supply a valid detour and retain exact segment/circle checks.', 'input', {'path_xy': [[0, 0], [2, 0]], 'obstacles': [[1, 0, .1]], 'robot_radius': .2, 'seed': 0}),
        ('ekf-state-dimension', 'Choose a five-state EKF for velocity-scale correction', 'pythonrobotics-ekf-velocity-update', 'The velocity-correction model adds a fifth velocity-scale state. Use its matching state and covariance instead of supplying five components to the four-state model.', 'input', None),
        ('ekf-covariance', 'EKF covariance must be symmetric positive definite', 'pythonrobotics-ekf-update', 'A zero/negative initial covariance eigenvalue violates this adapter precondition. The valid example uses a positive diagonal covariance; choose values justified by the actual model.', 'input', None),
        ('planar-ik-reachability', 'Check planar IK target reachability before solving', 'pythonrobotics-planar-ik', 'A target outside the sum of link lengths is unreachable for this planar model. Check units, model and target; the corrected example selects a reachable target.', 'input', None),
        ('forward-kinematics-joint-order', 'Forward kinematics needs one angle per link', 'pythonrobotics-planar-fk', 'The ordered angle vector must match the ordered link-length vector. Preserve joint order rather than truncating or silently broadcasting a vector.', 'input', None),
        ('pendulum-lqr-state-cost', 'Use positive state costs for this bounded LQR example', 'pythonrobotics-pendulum-lqr', 'This adapter requires positive state costs and checks the discrete linear closed-loop eigenvalues. This is a linear model check, not nonlinear or hardware stabilization.', 'input', None),
        ('ruckig-motion-limits', 'Ruckig requires positive per-axis motion limits', 'ruckig-online-trajectory', 'Use physically justified positive velocity, acceleration and jerk bounds. These input checks and sampled trajectory checks are separate from actuator safety.', 'input', None),
        ('ruckig-axis-count', 'Ruckig state and limit vectors must share an axis count', 'ruckig-online-trajectory', 'Position, velocity, acceleration and all limits must describe the same ordered axes. Match vector lengths and coordinate_type explicitly.', 'input', None),
        ('path-coordinate-frame', 'Reject a path handoff between different coordinate frames', 'pythonrobotics-astar-planner', 'The field handoff validator rejects a map path labeled as a robot-base path. Supply an explicit transform when needed; merely relabeling coordinates is not a transform.', 'handoff', None),
    ]
    output = []
    for slug, title, ident, resolution, mode, bad in profiles:
        recipe = recipes[ident]; good = copy.deepcopy(recipe['example'])
        if slug == 'path-smoothing-collision': good = {**bad, 'path_xy': [[0, 0], [0, 1], [2, 1], [2, 0]]}
        if bad is None: bad = copy.deepcopy(good)
        bad_id = ident
        if slug == 'ekf-state-dimension': bad_id = 'pythonrobotics-ekf-update'
        if slug == 'ekf-covariance': bad['covariance'][0][0] = -0.1
        if slug == 'planar-ik-reachability': bad['target_xy'] = [3., 0.]
        if slug == 'forward-kinematics-joint-order': bad['joint_angles'] = [0.1, 0.3]
        if slug == 'pendulum-lqr-state-cost': bad['state_cost_diagonal'][0] = 0.
        if slug == 'ruckig-motion-limits': bad['max_velocity'][0] = 0.
        if slug == 'ruckig-axis-count': bad['current_velocity'] = [0., 0.]
        if mode == 'upstream_interpolation': bad = {'path': [[0., 0.], [10., 0.], [10., 10.]], 'distance': 5., 'expected': [5., 0., 0]}
        if mode == 'handoff': bad = {'path_xy': [[2., 2.], [3., 3.], [4., 4.]], 'target_frame': 'robot_base'}
        output.append({'id': slug, 'title': title, 'resolution': resolution, 'mode': mode,
                       'skill_id': ident, 'bad_skill_id': bad_id, 'runtime': recipe['backend'],
                       'source_commit': recipe['source_commit'], 'bad_input': bad, 'good_input': good,
                       'contracts_sha256': hashlib.sha256(json.dumps([recipe['interface'], recipes[bad_id]['interface'], recipes['pythonrobotics-path-smoothing']['interface'] if mode == 'handoff' else None], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                       'scope': 'Authored reproduction; not autonomous agent discovery, general accuracy or hardware verification.'})
    return output


def case_hash(case):
    return hashlib.sha256(json.dumps(case, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verified_cases(root=ROOT):
    """Reject stale published claims after input, contract or adapter changes."""
    plan = root / 'catalog/problem-cases.json'
    if not plan.exists(): return []
    entries = json.loads(plan.read_text())['cases']
    recipes = {r['id']: r for r in json.loads((root / 'catalog/executable-conversions.json').read_text())['recipes']}
    receipt = json.loads((root / 'evidence/integration/agent-discovery-v1/problem-cases.json').read_text())
    reports = {r['id']: r for r in receipt['cases']}
    if len(reports) != len(entries): raise ValueError('Problem evidence coverage mismatch')
    for case in entries:
        row = reports[case['id']]
        current = hashlib.sha256((root / 'recipes' / case['skill_id'] / 'run.py').read_bytes()).hexdigest()
        bad_adapter = hashlib.sha256((root / 'recipes' / case['bad_skill_id'] / 'run.py').read_bytes()).hexdigest()
        contracts = [recipes[case['skill_id']]['interface'], recipes[case['bad_skill_id']]['interface'], recipes['pythonrobotics-path-smoothing']['interface'] if case['mode'] == 'handoff' else None]
        contract_hash = hashlib.sha256(json.dumps(contracts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if not (row['case_sha256'] == case_hash(case) and row['adapter_sha256'] == current
                and row['bad_adapter_sha256'] == bad_adapter and case['contracts_sha256'] == contract_hash
                and row['source_commit'] == case['source_commit'] and row['mode'] == case['mode']
                and row['problem_reproduced'] is True and row['valid_case_passed'] is True):
            raise ValueError('Stale or unsuccessful problem evidence: ' + case['id'])
    return entries


def generate(check=False):
    entries = cases()
    files = {ROOT / 'catalog/problem-cases.json': json.dumps({'schema_version': '1', 'cases': entries}, indent=2) + '\n'}
    for case in entries:
        query = 'smoothing' if 'smoothing' in case['id'] else 'ekf' if case['id'].startswith('ekf') else 'trajectory' if case['runtime'] == 'ruckig' else case['skill_id'].removeprefix('pythonrobotics-').replace('-', ' ')
        from urllib.parse import urlencode
        search = 'https://api.superfastrobotics.com/v1/search?' + urlencode({'q': query, 'runtime': case['runtime'], 'kind': 'preparation_recipe', 'limit': 3})
        files[ROOT / 'docs/problems' / (case['id'] + '.md')] = f'''# {case['title']}

{case['resolution']}

Runtime: `{case['runtime']}`. Recipe: `{case['skill_id']}`. Source revision: `{case['source_commit']}`.

[Find applicable prepared recipes]({search}). Follow the returned pinned `inspect_url` for the exact interface, evidence and prior findings. [Preparation and execution](https://hub.superfastrobotics.com/executable-skills.md) remain separate local operations. Source files retain their original license and authors.

## Reproduction input

Mode: `{case['mode']}`. Reproduction recipe: `{case['bad_skill_id']}`.

```json
{json.dumps(case['bad_input'], indent=2)}
```

## Valid adapter input

```json
{json.dumps(case['good_input'], indent=2)}
```

Use the `tools/verify_problem_cases.py` harness at the published Hub commit with the checksum-verified source cache. `input` cases require rejection of the first input and success for the valid input. `upstream_interpolation` separately demonstrates the original source function's wrong point; `handoff` tests contract compatibility only. Neither mode claims physical execution.

The [source and receipts](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/evidence/integration/agent-discovery-v1) distinguish reproduced failures from successful bounded checks. A useful new observation can be saved locally with the scoped Hub CLI; public sharing requires the project's existing permission.

{case['scope']}
'''
    index = '# Robotics problem reproductions\n\nTen authored cases with exact source pins, invalid inputs, valid inputs and explicit verification scope.\n\n'
    index += '\n'.join(f"- [{c['title']}](https://hub.superfastrobotics.com/problems/{c['id']}/)" for c in entries) + '\n'
    files[ROOT / 'docs/problems.md'] = index
    for path, body in files.items():
        raw = body.encode()
        if check:
            if not path.exists() or path.read_bytes() != raw: raise ValueError('Regenerate ' + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    print(('Checked' if check else 'Generated') + ' 10 problem cases')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--check', action='store_true')
    generate(p.parse_args().check)
