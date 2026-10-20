"""Maintainer-only live HTTP, LangChain and pinned-catalog preparation probes."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ['RSH_TELEMETRY'] = 'off'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    reports = []
    for skill, query, runtime in [('robot-motion-planning', 'astar', 'pythonrobotics'),
                                  ('robot-kinematics', 'inverse kinematics', 'pybullet'),
                                  ('robot-trajectory', 'trajectory', 'ruckig')]:
        client = load(ROOT / 'skills' / skill / 'scripts/lookup.py', skill)
        found = client.find(query, 'agent-pilot', runtime)
        assert found['results'], skill
        selected = found['results'][0]; url = selected['inspect_url']
        inspected = client.inspect_url(url, 'agent-pilot')
        assert inspected['embedded_recipe_files_omitted'] and 'files' not in inspected['record']['preparation']
        catalog = args.output / (skill + '.json')
        client.export_catalog(url, 'agent-pilot', catalog)
        command = [sys.executable, str(ROOT / 'skills/find-robot-skills/scripts/rsh.py'),
                   '--catalog', str(catalog.resolve()), '--offline', 'prepare', selected['id'],
                   '--project', str((args.output / skill).resolve()), '--plan', '--json']
        result = subprocess.run(command, capture_output=True, timeout=30)
        (args.output / (skill + '-plan.stdout')).write_bytes(result.stdout)
        (args.output / (skill + '-plan.stderr')).write_bytes(result.stderr)
        plan = json.loads(result.stdout)
        host_rejected = plan.get('reason_code') == 'unsupported_environment'
        assert result.returncode in (0, 2) and plan.get('reason_code') in ('preparation_plan', 'unsupported_environment'), plan
        assert plan['source_commit'] == inspected['record']['source']['commit']
        if host_rejected:
            assert runtime == 'pybullet' and sys.platform == 'win32' and plan['status'] == 'unsupported'
        else:
            assert plan['preparation_performed'] is False
        reports.append({'skill': skill, 'selected_id': selected['id'], 'hub_commit': inspected['hub_commit'],
                        'record_version': selected['record_version'], 'source_commit': inspected['record']['source']['commit'],
                        'search': True, 'pinned_inspection': True, 'inert_catalog_export': True,
                        'offline_prepare_plan': not host_rejected, 'plan_status': plan['status'],
                        'host_rejected_as_unsupported': host_rejected, 'runtime_execution': False})
    sys.path.insert(0, str(ROOT / 'examples/rai'))
    tools = load(ROOT / 'examples/rai/hub_lookup.py', 'rai_lookup').ROBOT_CODE_TOOLS
    found = json.loads(tools[0].invoke({'query': 'astar', 'runtime': 'pythonrobotics'}))
    inspected = json.loads(tools[1].invoke({'inspection_url': found['results'][0]['inspect_url']}))
    assert inspected['record']['id'] == found['results'][0]['id']
    from importlib.metadata import version
    receipt = {'schema_version': '1', 'observed_at': datetime.now(timezone.utc).isoformat(),
               'task_skills': reports, 'rai': {'langchain_core': version('langchain-core'),
               'structured_tool_invoke': True, 'real_hub_http': True, 'full_rai': False, 'ros': False},
               'maintainer_probe': True, 'telemetry_opt_out': True, 'physical_robot': False,
               'scope': 'Maintainer HTTP/preparation-plan and LangChain invocation checks; not autonomous agent selection or adoption.'}
    (args.output / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__': main()
