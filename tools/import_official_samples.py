"""Rebuild the additional pinned ManiSkill recipes without editing published records.

Run with --archive to inspect the upstream archive and verify solver contracts.
The source archive is downloaded by rsh prepare, not vendored into this repository.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
PIN = "33967b9e3ead1f841eec57cc9f31d0d8b8cf0907"
ARCHIVE_SHA256 = "d194e39e4f86063f7ea49f25c918ca7474d088ad8d5abdc37573daf4672f86d4"
CHECKED = "2026-10-17"

# slug, upstream solver namespace, task ID, exact robot UID, task source,
# summary, capabilities. These are actual upstream solvers, not arbitrary tasks.
SAMPLES = [
    ("panda-push-cube", "panda", "PushCube-v1", "panda", "tabletop/push_cube.py", "Push a cube to a goal region with the official Panda motion planner.", ["pushing", "object-manipulation"]),
    ("panda-pull-cube", "panda", "PullCube-v1", "panda", "tabletop/pull_cube.py", "Pull a cube to its goal with the official Panda motion planner.", ["pulling", "object-manipulation"]),
    ("panda-pull-cube-tool", "panda", "PullCubeTool-v1", "panda", "tabletop/pull_cube_tool.py", "Use an L-shaped tool to pull a cube toward a goal.", ["tool-use", "pulling", "grasping"]),
    ("panda-lift-peg-upright", "panda", "LiftPegUpright-v1", "panda", "tabletop/lift_peg_upright.py", "Grasp a peg and lift it upright with the official Panda planner.", ["grasping", "lifting", "reorientation"]),
    ("panda-peg-insertion-side", "panda", "PegInsertionSide-v1", "panda_wristcam", "tabletop/peg_insertion_side.py", "Align a peg with a side-facing hole and insert it using Panda WristCam.", ["peg-in-hole", "insertion", "assembly"]),
    ("panda-plug-charger", "panda", "PlugCharger-v1", "panda_wristcam", "tabletop/plug_charger.py", "Grasp a charger, align its pins, and plug it into a receptacle.", ["insertion", "assembly", "grasping"]),
    ("panda-place-sphere", "panda", "PlaceSphere-v1", "panda", "tabletop/place_sphere.py", "Pick up a sphere and place it into a bin with the official Panda planner.", ["pick-and-place", "grasping", "placing"]),
    ("panda-stack-pyramid", "panda", "StackPyramid-v1", "panda", "tabletop/stack_pyramid.py", "Arrange three cubes into a pyramid using the official Panda planner.", ["stacking", "pick-and-place", "multi-object"]),
    ("panda-stick-draw-triangle", "panda", "DrawTriangle-v1", "panda_stick", "drawing/draw_triangle.py", "Trace a triangle with the Panda Stick motion planner.", ["drawing", "trajectory-following"]),
    ("panda-stick-draw-svg", "panda", "DrawSVG-v1", "panda_stick", "drawing/draw_svg.py", "Trace the environment's default SVG outline with the Panda Stick planner.", ["drawing", "trajectory-following", "svg"]),
    ("xarm6-pick-cube", "xarm6", "PickCube-v1", "xarm6_robotiq", "tabletop/pick_cube.py", "Grasp a cube and move it to a goal with the official xArm6 Robotiq solver.", ["grasping", "pick-and-place"]),
    ("xarm6-push-cube", "xarm6", "PushCube-v1", "xarm6_robotiq", "tabletop/push_cube.py", "Push a cube to a goal with the official xArm6 Robotiq solver.", ["pushing", "object-manipulation"]),
    ("xarm6-stack-cube", "xarm6", "StackCube-v1", "xarm6_robotiq", "tabletop/stack_cube.py", "Stack one cube on another with the official xArm6 Robotiq solver.", ["stacking", "pick-and-place"]),
    ("xarm6-plug-charger", "xarm6", "PlugCharger-v1", "xarm6_robotiq", "tabletop/plug_charger.py", "Insert a charger using the official xArm6 Robotiq motion planner.", ["insertion", "assembly", "grasping"]),
    ("so100-pick-cube", "so100", "PickCubeSO100-v1", "so100", "tabletop/pick_cube.py", "Pick up a cube and move it to a goal with the official SO100 planner.", ["grasping", "pick-and-place"]),
]


def solver_module(sample):
    slug, namespace, task, robot, task_path, *_ = sample
    solver = slug.split("-", 1)[1]
    if namespace == "panda" and robot == "panda_stick":
        solver = solver.removeprefix("stick-")
    return f"mani_skill.examples.motionplanning.{namespace}.solutions.{solver.replace('-', '_')}"


def inspect_archive(archive):
    digest = hashlib.sha256()
    with open(archive, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise ValueError("ManiSkill source archive SHA256 differs from the reviewed release")
    with tarfile.open(archive, "r:gz") as bundle:
        prefix = bundle.getmembers()[0].name.split("/")[0] + "/"
        if not prefix.rstrip("/").endswith(PIN):
            raise ValueError("Archive root differs from the pinned commit")
        license_text = bundle.extractfile(prefix + "LICENSE").read().decode()
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            raise ValueError("Expected upstream Apache-2.0 license")
        for sample in SAMPLES:
            module = solver_module(sample)
            source = bundle.extractfile(prefix + module.replace(".", "/") + ".py").read().decode()
            tree = ast.parse(source)
            solve = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "solve")
            if [arg.arg for arg in solve.args.args] != ["env", "seed", "debug", "vis"]:
                raise ValueError(f"Unexpected solver signature: {module}")
            task_path = "mani_skill/envs/tasks/" + sample[4]
            if sample[2] not in bundle.extractfile(prefix + task_path).read().decode():
                raise ValueError(f"Task registration missing: {sample[2]}")
    print(f"Verified archive hash, Apache-2.0 license, and {len(SAMPLES)} solver/task contracts")


def wrapper(sample):
    _, _, task, robot, *_ = sample
    # PickCubeSO100Env already supplies robot_uids and rejects a duplicate keyword.
    robot_arg = "" if robot == "so100" else f'robot_uids="{robot}", '
    return f'''"""Hub adapter for the pinned official {task} / {robot} motion planner.

Upstream solver: ManiSkill contributors, Apache-2.0. This wrapper contains no
upstream solver implementation. Simulation execution is a separate explicit step.
"""
import argparse
import importlib.metadata
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    actual = importlib.metadata.version("mani_skill")
    if actual != "3.0.0b22":
        raise RuntimeError(f"Expected mani_skill 3.0.0b22, found {{actual}}")
    import gymnasium as gym
    import mani_skill.envs
    from {solver_module(sample)} import solve

    # Sparse reward avoids robot-specific dense reward helpers in upstream variants.
    env = gym.make("{task}", {robot_arg}obs_mode="state",
                   control_mode="pd_joint_pos", sim_backend="cpu",
                   render_backend="none", render_mode=None, reward_mode="sparse")
    try:
        result = solve(env, seed=args.seed, debug=False, vis=False)
        if isinstance(result, int) and result == -1:
            report = {{"status": "failed", "reason_code": "motion_plan_failed"}}
        else:
            info = result[-1]
            success = bool(info["success"].item())
            report = {{"status": "task_complete" if success else "failed",
                      "success": success, "elapsed_steps": int(info["elapsed_steps"].item())}}
        report.update(task="{task}", seed=args.seed, runtime="3.0.0b22",
                      robot="{robot}", controller="pd_joint_pos", observation="state",
                      sim_backend="cpu", render_backend="none")
        print(json.dumps(report))
        return 0 if report.get("success") else 1
    finally:
        env.close()


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as error:
        print(json.dumps({{"status": "failed", "reason_code": "runtime_error",
                          "error_type": type(error).__name__, "message": str(error)}}))
        exit_code = 1
    raise SystemExit(exit_code)
'''


def generate():
    base = json.loads((ROOT / "catalog/records/maniskill-panda-pick-cube.json").read_text(encoding="utf-8"))
    requirements = (ROOT / "recipes/maniskill-panda-pick-cube/requirements.txt").read_text(encoding="utf-8")
    for sample in SAMPLES:
        slug, namespace, task, robot, task_path, summary, capabilities = sample
        ident = "maniskill-" + slug
        record = copy.deepcopy(base)
        record.update(id=ident, name=f"ManiSkill {robot} {task} motion planner", summary=summary,
                      capabilities=[*capabilities, "motion-planning"],
                      aliases=[task, robot, namespace, slug.replace("-", "_"), "robot manipulation", "reusable Python code"])
        # Identical aliases are not valid in the canonical contract.
        record["aliases"] = list(dict.fromkeys(record["aliases"]))
        record["source"]["paths"] = [f"mani_skill/examples/motionplanning/{namespace}/run.py",
                                          solver_module(sample).replace(".", "/") + ".py",
                                          "mani_skill/envs/tasks/" + task_path, "setup.py", "LICENSE"]
        record["compatibility"][0].update(robot=robot, status="source_reviewed")
        record["invocation"].update(entrypoint=solver_module(sample) + ":solve",
                                    example=f"python skills/find-robot-skills/scripts/rsh.py prepare {ident} --project ./experiment --json")
        record["invocation"]["inputs"].update(task=task, robot=robot, reward_mode="sparse")
        record["completion"].update(success_condition=f"{task} env info.success is true after the upstream solver finishes; exit 0 requires success.",
                                     timeout_seconds=300, stop_condition="Stop after one seed; no automatic retries. Use an external 300-second process timeout.")
        record["preparation"].update(recipe_path=f"recipes/{ident}", requirements_file=f"recipes/{ident}/requirements.txt")
        record["evidence"] = {"level": "source_reviewed", "verified_by": "Robot Skill Hub source review", "date": CHECKED,
                              "environment": {"source": "pinned upstream release", "host": "Windows source inspection"},
                              "commands": ["python tools/import_official_samples.py --archive .local/upstream/maniskill-33967b9.tar.gz --check",
                                           "python -m unittest discover -s tests/python -p test_bulk_catalog.py"],
                              "result": "Inspected the pinned solver signature, task registration, source license and wrapper contract. No simulator invocation evidence is attached.",
                              "artifacts": [], "runtime_verification": "not_run", "contributor_reported": None,
                              "hub_verification": {"level": "source_reviewed", "runtime": "not_run"}}
        record["maintenance"].update(record_version="1.0.0", last_checked=CHECKED)
        record["contribution"]["allowed_paths"] = [f"catalog/records/{ident}.json", f"docs/recipes/{ident}.md",
                                                      f"recipes/{ident}/requirements.txt", f"recipes/{ident}/run.py"]
        deps = requirements
        if task == "DrawSVG-v1":
            deps += "# Optional drawing task parser required by DrawSVGEnv.\nsvgpathtools==1.6.1\n"
            record["requirements"]["packages"].append("svgpathtools==1.6.1")
        recipe = ROOT / "recipes" / ident
        recipe.mkdir(parents=True, exist_ok=True)
        (recipe / "run.py").write_text(wrapper(sample), encoding="utf-8", newline="\n")
        (recipe / "requirements.txt").write_text(deps, encoding="utf-8", newline="\n")
        (ROOT / "catalog/records" / f"{ident}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
        doc = f'''# {record['name']}

{summary}

## Source

- Repository: {record['source']['repository']}
- Release: v3.0.0b22; commit `{PIN}`
- Solver: [{solver_module(sample)}:solve]({record['source']['repository']}/blob/{PIN}/{solver_module(sample).replace('.', '/')}.py)
- License: [Apache-2.0]({record['license']['url']}); robot/mesh assets retain upstream notices.
- Recipe ID: `{ident}`
- Canonical JSON: https://hub.superfastrobotics.com/skills/{ident}/skill.json

## Agent preparation

```sh
python skills/find-robot-skills/scripts/rsh.py inspect {ident} --json
python skills/find-robot-skills/scripts/rsh.py prepare {ident} --project ./experiment --plan --json
python skills/find-robot-skills/scripts/rsh.py prepare {ident} --project ./experiment --download-only --json
```

Run preparation on Linux x86_64 with Python 3.10 for the simulator environment.
Add `--install-deps` explicitly to install dependencies. The returned task command
is a separate execution step. Input is one seed (`--seed 0` by default); output is
a final JSON line with task status and success. Use a 300-second process timeout.

## Environment contract

`maniskill==3.0.0b22`, robot `{robot}`, `pd_joint_pos`, `state` observations,
`cpu` simulation, `render_backend=none`, no video/display, sparse rewards.
The planner reads privileged simulator poses and collision geometry. It is a
simulation example, not a perception policy or a physical robot controller.

The source archive and direct dependency versions are pinned. Transitive Python
dependencies resolve during installation and are captured by the project lock.
The exact source and wrapper contracts were inspected; runtime status is recorded
in the JSON evidence fields. A nonzero exit and JSON error preserve failures.
'''
        if namespace == "xarm6":
            doc += "\nThis robot variant comes from the official xArm6 runner. Some upstream task declarations list Panda/Fetch only and log a warning for xArm6. Sparse rewards avoid Panda-specific dense reward code; confirm the variant in your simulator environment.\n"
        (ROOT / "docs/recipes" / f"{ident}.md").write_text(doc, encoding="utf-8", newline="\n")
    print(f"Generated {len(SAMPLES)} additional recipes; two existing published records were preserved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Existing SHA256-pinned upstream tar.gz to inspect")
    parser.add_argument("--check", action="store_true", help="Inspect archive without generating files")
    args = parser.parse_args()
    if args.archive:
        inspect_archive(args.archive)
    if not args.check:
        generate()
