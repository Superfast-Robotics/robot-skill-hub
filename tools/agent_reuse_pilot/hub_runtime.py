"""Experiment-only warm wrapper around exact published CLI adapters."""
import json,subprocess,sys
SOURCES={'pythonrobotics-astar-planner':'pythonrobotics','ruckig-offline-trajectory':'ruckig','pybullet-ik-skill':'pybullet'}
def run_recipe(skill_id,task):
    if skill_id not in SOURCES:raise ValueError('Recipe outside this pilot')
    proc=subprocess.run([sys.executable,'/hub/'+skill_id+'/run.py','--source-dir','/sources/'+SOURCES[skill_id],
        '--input-json',json.dumps(task)],capture_output=True,text=True,timeout=25)
    result=json.loads(proc.stdout)
    if proc.returncode or not result.get('success'):raise RuntimeError(json.dumps(result))
    return result['outputs']
