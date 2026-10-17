"""Build a source-only index from reviewed, immutable official example files.

Fetches source text for hashing and static inspection. It never imports upstream
modules, installs packages, downloads model assets, or executes an example.
"""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import urllib.request

from reference_index import write_source_index

ROOT = Path(__file__).resolve().parents[1]
CHECKED = "2026-10-17"
PROJECTS = {
    "pybullet": {"repository": "https://github.com/bulletphysics/bullet3",
                 "commit": "2c204c49e56ed15ec5fcfa71d199ab6d6570b3f5", "tag": "3.25", "stars": 14800,
                 "license_path": "LICENSE.txt", "spdx": "Zlib", "license_marker": "This software is provided 'as-is'",
                 "license_sha256": "885cd516a8420acb7c3e0b1a7119913b686495001ae564e3229740460e8cff59",
                 "python": "upstream-defined", "packages": ["pybullet (build matching the pinned upstream source)"],
                 "setup_url": "https://github.com/bulletphysics/bullet3/blob/2c204c49e56ed15ec5fcfa71d199ab6d6570b3f5/README.md"},
    "robosuite": {"repository": "https://github.com/ARISE-Initiative/robosuite",
                  "commit": "a071383d53568ab798eb315c0e95357911be922d", "tag": "v1.5.1", "stars": 2666,
                  "license_path": "LICENSE", "spdx": "MIT", "license_marker": "Permission is hereby granted, free of charge",
                  "license_sha256": "177978cbece0a4c454c2aaec5b3f145b39270814874c43109da9e829c39d9cba",
                  "python": "upstream-defined; setup.py declares >=3, dependencies impose additional constraints", "packages": ["robosuite==1.5.1"],
                  "setup_url": "https://github.com/ARISE-Initiative/robosuite/blob/a071383d53568ab798eb315c0e95357911be922d/README.md"},
    "mujoco": {"repository": "https://github.com/google-deepmind/mujoco",
               "commit": "f1d45bd5422c74beddfb0d1deb590a02583d21de", "tag": "3.3.7", "stars": 15726,
               "license_path": "LICENSE", "spdx": "Apache-2.0", "license_marker": "Apache License",
               "license_sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
               "python": "Python examples follow upstream package constraints; native samples use C++",
               "packages": ["mujoco==3.3.7 (Python)", "MuJoCo 3.3.7 and CMake toolchain (native samples)"],
               "setup_url": "https://mujoco.readthedocs.io/en/3.3.7/programming/samples.html"},
}

# framework, path, title, original summary, tags. No upstream code is republished.
EXAMPLES = [
    ("pybullet", "examples/pybullet/examples/hello_pybullet.py", "PyBullet simulation quickstart", "Load a plane and R2D2 model, step simulation, and inspect the base pose.", ["simulation", "urdf", "quickstart"]),
    ("pybullet", "examples/pybullet/examples/inverse_kinematics.py", "PyBullet KUKA inverse kinematics", "Move a KUKA end effector along target positions using inverse kinematics and joint motors.", ["inverse-kinematics", "kuka", "arm-control"]),
    ("pybullet", "examples/pybullet/examples/ik_end_effector_orientation.py", "PyBullet end-effector orientation IK", "Control KUKA end-effector position and orientation toward a fixed pose.", ["inverse-kinematics", "orientation", "kuka"]),
    ("pybullet", "examples/pybullet/examples/inverse_dynamics.py", "PyBullet inverse dynamics", "Compute inverse dynamics and use torque control in a simulated articulated model.", ["inverse-dynamics", "torque-control"]),
    ("pybullet", "examples/pybullet/examples/jacobian.py", "PyBullet Jacobian computation", "Compute a robot Jacobian and compare Cartesian velocity calculations.", ["jacobian", "kinematics"]),
    ("pybullet", "examples/pybullet/examples/kuka_with_cube.py", "PyBullet KUKA and cube interaction", "Run a KUKA arm along an IK trajectory in a cube scene and record state/contact logs.", ["kuka", "manipulation", "joint-control"]),
    ("pybullet", "examples/pybullet/examples/kuka_grasp_block_playback.py", "PyBullet KUKA grasp log playback", "Replay a recorded KUKA grasp trajectory from the upstream state log.", ["grasping", "trajectory-playback", "kuka"]),
    ("pybullet", "examples/pybullet/examples/racecar.py", "PyBullet racecar control", "Drive the simulated racecar using upstream motor and steering controls.", ["mobile-robot", "steering", "vehicle-control"]),
    ("pybullet", "examples/pybullet/examples/racecar_differential.py", "PyBullet differential racecar", "Control a racecar model with differential drivetrain constraints.", ["mobile-robot", "differential-drive", "constraints"]),
    ("pybullet", "examples/pybullet/examples/humanoid_knee_position_control.py", "PyBullet humanoid knee control", "Explore position control on the knees of a simulated humanoid.", ["humanoid", "position-control", "motor-control"]),
    ("pybullet", "examples/pybullet/examples/quadruped.py", "PyBullet quadruped simulation", "Load and control a quadruped model using the upstream interactive example.", ["quadruped", "joint-control"]),
    ("pybullet", "examples/pybullet/examples/pdControl.py", "PyBullet PD control comparison", "Compare proportional-derivative controllers on an articulated robot.", ["pd-control", "joint-control"]),
    ("pybullet", "examples/pybullet/examples/pointCloudFromCameraImage.py", "PyBullet depth to point cloud", "Convert rendered camera depth samples into a world-space point cloud.", ["point-cloud", "camera", "depth"]),
    ("pybullet", "examples/pybullet/examples/batchRayCast.py", "PyBullet batch ray casting", "Cast batches of rays around a simulated scene and visualize intersections.", ["ray-casting", "sensing", "collision"]),
    ("pybullet", "examples/pybullet/examples/forcetorquesensor.py", "PyBullet force torque sensing", "Enable joint force torque sensing and inspect the sensor readings.", ["force-torque", "sensing"]),
    ("pybullet", "examples/pybullet/examples/contactFriction.py", "PyBullet contact friction", "Inspect contact behavior under different friction settings.", ["contact", "friction", "physics"]),
    ("pybullet", "examples/pybullet/examples/collisionFilter.py", "PyBullet collision filtering", "Configure collision groups and masks between simulated bodies.", ["collision", "filtering"]),
    ("pybullet", "examples/pybullet/examples/constraint.py", "PyBullet articulated constraints", "Create and change constraints between robot links and other bodies.", ["constraints", "articulation"]),
    ("pybullet", "examples/pybullet/examples/saveRestoreState.py", "PyBullet save and restore state", "Save and restore simulation states for repeatable experiments.", ["state", "replay", "simulation"]),
    ("pybullet", "examples/pybullet/examples/robotcontrol.py", "PyBullet interactive robot joint control", "Inspect a robot's joints and drive them with GUI control parameters.", ["joint-control", "robot-model"]),
    ("robosuite", "robosuite/demos/demo_random_action.py", "robosuite random action environment", "Create an upstream robot manipulation environment and step random actions.", ["environment", "manipulation", "quickstart"]),
    ("robosuite", "robosuite/demos/demo_control.py", "robosuite controller demonstration", "Compare controller behavior with prescribed action sequences.", ["controllers", "manipulation"]),
    ("robosuite", "robosuite/demos/demo_device_control.py", "robosuite device teleoperation", "Teleoperate a simulated robot with an upstream supported input device.", ["teleoperation", "device-control"]),
    ("robosuite", "robosuite/demos/demo_composite_robot.py", "robosuite composite robot", "Instantiate a composed robot and exercise its action space in a manipulation task.", ["robot-composition", "controllers"]),
    ("robosuite", "robosuite/demos/demo_domain_randomization.py", "robosuite domain randomization", "Apply upstream domain randomization to visual and physical environment properties.", ["domain-randomization", "simulation"]),
    ("robosuite", "robosuite/demos/demo_gripper_interaction.py", "robosuite gripper interaction", "Run an upstream gripper interaction test scene.", ["gripper", "contact"]),
    ("robosuite", "robosuite/demos/demo_gripper_selection.py", "robosuite gripper selection", "Select robot and gripper models and simulate an upstream manipulation environment.", ["gripper", "robot-model", "manipulation"]),
    ("robosuite", "robosuite/demos/demo_gym_functionality.py", "robosuite Gym wrapper", "Use the upstream GymWrapper interface around a manipulation environment.", ["gym", "environment", "reinforcement-learning"]),
    ("robosuite", "robosuite/demos/demo_segmentation.py", "robosuite segmentation observations", "Render and inspect instance, class, or element segmentation observations.", ["segmentation", "camera", "perception"]),
    ("robosuite", "robosuite/demos/demo_sensor_corruption.py", "robosuite sensor corruption", "Add upstream sensor noise, delay, and corruption to observations.", ["sensing", "domain-randomization", "robustness"]),
    ("robosuite", "robosuite/demos/demo_video_recording.py", "robosuite video recording", "Record a manipulation environment's camera frames to video.", ["video", "camera", "simulation"]),
    ("robosuite", "robosuite/demos/demo_collect_and_playback_data.py", "robosuite collect and replay data", "Collect state and action data, then replay it in the upstream demonstration workflow.", ["demonstrations", "data-collection", "trajectory-playback"]),
    ("mujoco", "python/tutorial.ipynb", "MuJoCo Python tutorial", "Work through official model loading, simulation, rendering, and control examples.", ["simulation", "python", "control", "quickstart"]),
    ("mujoco", "mjx/tutorial.ipynb", "MuJoCo MJX tutorial", "Use the official notebook to explore JAX-based accelerated MuJoCo simulation.", ["jax", "accelerated-simulation", "reinforcement-learning"]),
    ("mujoco", "python/mujoco/viewer.py", "MuJoCo Python interactive viewer", "Launch the official Python viewer and inspect its passive and managed simulation interfaces.", ["viewer", "simulation", "python"]),
    ("mujoco", "sample/basic.cc", "MuJoCo minimal interactive simulator", "Build the official minimal C++ simulator with GLFW camera interaction.", ["simulation", "cpp", "viewer"]),
    ("mujoco", "sample/compile.cc", "MuJoCo model format conversion", "Convert MJCF, URDF, and binary model formats with the official compiler sample.", ["model-conversion", "mjcf", "urdf"]),
    ("mujoco", "sample/record.cc", "MuJoCo offscreen trajectory recording", "Render passive model dynamics offscreen and write raw frame data.", ["offscreen-rendering", "video", "simulation"]),
    ("mujoco", "sample/testspeed.cc", "MuJoCo simulation benchmark sample", "Time model rollouts and inspect contact, constraint, and CPU statistics.", ["benchmark", "simulation", "rollout"]),
    ("mujoco", "simulate/main.cc", "MuJoCo full interactive simulator", "Build and run the official simulator with model inspection, profiling, and sensor plots.", ["simulation", "viewer", "profiling"]),
]


def fetch_source(project, path, cache):
    relative = Path(project["repository"].rsplit("/", 1)[-1]) / project["commit"] / path
    destination = cache / relative
    raw = project["repository"].replace("https://github.com/", "https://raw.githubusercontent.com/")
    request = urllib.request.Request(f"{raw}/{project['commit']}/{path}", headers={"User-Agent": "robot-skill-hub/1"})
    data = urllib.request.urlopen(request, timeout=40).read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data


def read_source(project, path, cache):
    return (cache / project["repository"].rsplit("/", 1)[-1] / project["commit"] / path).read_bytes()


def source_imports(path, text):
    if path.endswith(".ipynb"):
        notebook = json.loads(text)
        code = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
        # Notebook magics are not Python syntax. Extract imports without running cells.
        return sorted(set(re.findall(r"^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)", code, re.MULTILINE)))
    if path.endswith(".py"):
        tree = ast.parse(text)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return sorted(set(imports))
    if "int main(" not in text and "int main (" not in text:
        raise ValueError(f"Native source has no main entrypoint: {path}")
    return sorted(set(re.findall(r"^#include\s+[<\"]([^>\"]+)", text, re.MULTILINE)))


def merge_reference_records(existing, generated):
    """Refreshing the original three projects must not erase other importers."""
    project_repositories = {project["repository"] for project in PROJECTS.values()}
    preserved = [record for record in existing if record.get("source", {}).get("repository") not in project_repositories
                 or record.get("source_registry")]
    records = preserved + generated
    if len({record["id"] for record in records}) != len(records):
        raise ValueError("Duplicate source reference id across import registries")
    return sorted(records, key=lambda record: (record["framework"], record["id"]))


def build(cache, fetch=False):
    sources = [(PROJECTS[framework], path) for framework, path, *_ in EXAMPLES]
    sources += [(project, project["license_path"]) for project in PROJECTS.values()]
    if fetch:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda item: fetch_source(*item, cache), sources))
    for project in PROJECTS.values():
        data = read_source(project, project["license_path"], cache)
        text = data.decode("utf-8")
        if project["license_marker"] not in text or hashlib.sha256(data).hexdigest() != project["license_sha256"]:
            raise ValueError(f"Unexpected license text: {project['repository']}")
    records = []
    for framework, path, title, summary, capabilities in EXAMPLES:
        project = PROJECTS[framework]
        data = read_source(project, path, cache)
        text = data.decode("utf-8")
        imports = source_imports(path, text)
        ident = framework + "-" + re.sub(r"[^a-z0-9]+", "-", Path(path).stem.lower()).strip("-")
        if path == "mjx/tutorial.ipynb":
            ident = "mujoco-mjx-tutorial"
        if path == "simulate/main.cc":
            ident = "mujoco-simulate"
        if path.endswith(".py"):
            entrypoint = f"python {path}"
        elif path.endswith(".ipynb"):
            entrypoint = f"Notebook: {path}"
        else:
            entrypoint = f"C++ main: {path} (build with upstream CMake)"
        if path == "python/mujoco/viewer.py":
            entrypoint = "python -m mujoco.viewer --mjcf=/path/to/model.xml"
        display = "Upstream example controls rendering; inspect source before use. GUI, device, model or dataset setup may be required."
        if framework == "pybullet":
            display = "Most examples connect to a PyBullet GUI or shared-memory server. Upstream pybullet_data models and adjacent helper files may be required."
        elif framework == "robosuite":
            display = "OpenGL/MuJoCo rendering and upstream robot assets are required; teleoperation demos also need an input device."
        packages = list(project["packages"])
        if path == "mjx/tutorial.ipynb":
            display = "The upstream notebook requires a GPU-accelerated Colab runtime and JAX/MJX setup. Inspect notebook install cells before running."
            packages = ["mujoco-mjx (follow pinned tutorial install cells)", "jax and accelerator-compatible jaxlib", "notebook dependencies listed in source_imports"]
        records.append({
            "id": ident, "name": title, "summary": summary, "framework": framework, "kind": "official_example",
            "capabilities": capabilities,
            "source": {"repository": project["repository"], "commit": project["commit"], "tag": project["tag"],
                       "path": path, "url": f"{project['repository']}/blob/{project['commit']}/{path}",
                       "raw_url": f"{project['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/')}/{project['commit']}/{path}",
                       "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
            "license": {"spdx": project["spdx"], "url": f"{project['repository']}/blob/{project['commit']}/{project['license_path']}",
                        "sha256": project["license_sha256"],
                        "scope": "Example source code. Robot models, textures, logs, and third-party assets retain their own upstream licenses."},
            "access": {"mode": "source_reference", "hub_prepare": False,
                       "instructions": "Open the pinned source and follow upstream setup and invocation. This entry has no Hub runtime adapter.",
                       "setup_url": project["setup_url"]},
            "requirements": {"python": project["python"], "packages": packages, "display": display,
                             "source_imports": imports},
            "invocation": {"entrypoint": entrypoint,
                           "notes": "Inspect source arguments and local paths first. Run from the pinned upstream checkout as documented; examples may open a window, run continuously, or expect existing data. No success-rate or task-completion guarantee is attached."},
            "popularity": {"metric": "github_stars", "repository_stars": project["stars"], "checked_at": CHECKED,
                           "meaning": "Repository interest proxy, not example usage or install count."},
            "evidence": {"level": "source_reviewed", "runtime_verification": "not_run", "checked_at": CHECKED,
                         "inspection": "Fetched the exact source file, parsed Python/imports or located its native main/notebook cells, and inspected the repository license."},
        })
    destination = ROOT / "catalog/references.json"
    existing = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else {"records": []}
    records = merge_reference_records(existing["records"], records)
    output = {**existing, "schema_version": "1", "checked_at": max(CHECKED, existing.get("checked_at", CHECKED)),
              "description": "Pinned official examples for source discovery. These entries are separate from Hub preparation recipes.",
              "selection": "Official examples from widely followed simulator repositories. GitHub stars are a dated repository interest proxy, not a ranking of actual usage.",
              "records": records}
    if len(records) > len(EXAMPLES):
        output["description"] = existing.get("description", output["description"])
        output["selection"] = existing.get("selection", output["selection"])
    destination.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8", newline="\n")
    write_source_index(records, destination.parent / "source-index.json")
    print(f"Indexed {len(records)} immutable official examples, preserving other registries; no upstream code executed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/reference-review")
    parser.add_argument("--fetch", action="store_true", help="Fetch the exact source files into the local inspection cache")
    args = parser.parse_args()
    build(args.cache, args.fetch)
