#!/usr/bin/env python3
"""Run two reviewed CPU/state recipes on Linux; never publish or submit evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/find-robot-skills/scripts/rsh.py"
SKILLS = ("maniskill-panda-pick-cube", "maniskill-panda-stack-cube")
TASK_TIMEOUT = 180


def load_runtime_records():
    # Use the publisher's validated, self-contained records, including the
    # reviewed recipe files that the installed preparation CLI consumes.
    sys.path.insert(0, str(ROOT / "tools"))
    from build_catalog import load_records
    records = {record["id"]: record for record in load_records()}
    return [records[skill_id] for skill_id in SKILLS]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(argv, prefix, *, cwd=ROOT, timeout=1200):
    """Keep logs and kill the complete POSIX process group on timeout."""
    start = time.monotonic()
    stdout_path, stderr_path = prefix.with_suffix(".stdout.txt"), prefix.with_suffix(".stderr.txt")
    outcome = {"argv": [str(value) for value in argv], "timeout_seconds": timeout,
               "started": False, "timed_out": False, "exit_code": None}
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(outcome["argv"], cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=os.name == "posix")
            outcome["started"] = True
            try:
                outcome["exit_code"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                outcome["timed_out"] = True
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                outcome["exit_code"] = process.wait()
    except OSError as error:
        outcome["error_type"] = type(error).__name__
    outcome["duration_seconds"] = round(time.monotonic() - start, 3)
    outcome["stdout_file"], outcome["stderr_file"] = stdout_path.name, stderr_path.name
    write_json(prefix.with_suffix(".command.json"), outcome)
    return outcome, stdout_path.read_text(encoding="utf-8", errors="replace")


def require_json_command(argv, prefix, *, timeout=1200, allowed_exit_codes=(0,)):
    outcome, stdout = run_command(argv, prefix, timeout=timeout)
    if outcome["exit_code"] not in allowed_exit_codes or outcome["timed_out"]:
        raise RuntimeError(prefix.name + " failed; see preserved command and logs")
    return json.loads(stdout)


def assess_result(record, execution, stdout):
    """An invocation succeeds only when its actual last-line contract agrees."""
    try:
        result = json.loads(stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        result = None
    expected = {"task": record["invocation"]["inputs"]["task"], "seed": 0,
                "runtime": "3.0.0b22", "robot": "panda", "controller": "pd_joint_pos",
                "observation": "state", "sim_backend": "cpu", "render_backend": "none",
                "max_episode_steps": record["invocation"]["inputs"]["max_episode_steps"]}
    valid = (isinstance(result, dict) and result.get("status") == "task_complete"
             and result.get("success") is True and all(result.get(k) == v for k, v in expected.items())
             and type(result.get("terminated")) is bool and result.get("truncated") is False
             and type(result.get("max_episode_steps")) is int
             and type(result.get("elapsed_steps")) is int
             and 0 < result["elapsed_steps"] < expected["max_episode_steps"])
    success = (execution["started"] and execution["exit_code"] == 0
               and not execution["timed_out"] and valid)
    return {"status": "task_complete" if success else "failed", "success": bool(success),
            "execution_performed": execution["started"], "contract_matches": bool(valid),
            "result": result, "execution": execution}


def verify_recipe(record, catalog_path, archive_path, output, work):
    skill_id = record["id"]
    evidence = output / skill_id
    evidence.mkdir()
    report = {"skill_id": skill_id, "source_commit": record["source"]["commit"],
              "source_archive_sha256": record["source"]["archive_sha256"],
              "record_version": record["maintenance"]["record_version"],
              "adapter_sha256": file_sha256(ROOT / record["preparation"]["recipe_path"] / "run.py"),
              "status": "failed", "runtime_verification": "not_run", "execution_performed": False}
    command = [sys.executable, str(CLI), "--catalog", str(catalog_path), "prepare", skill_id,
               "--project", str(work / skill_id), "--source-archive", str(archive_path),
               "--expected-source-commit", report["source_commit"],
               "--expected-record-version", report["record_version"], "--json"]
    try:
        # Prepare creates the isolated environment but does not install or execute.
        prepared = require_json_command(command, evidence / "prepare", timeout=180, allowed_exit_codes=(0, 2))
        if prepared.get("reason_code") != "dependencies_not_installed" or prepared.get("execution_performed") is not False:
            raise RuntimeError("Expected a fresh isolated preparation requiring dependency installation")
        write_json(evidence / "preparation.before.json", prepared)
        isolated_python = Path(prepared["environment_dir"]) / "bin/python"
        pip_install, _ = run_command([isolated_python, "-m", "pip", "install", "--upgrade", "pip"],
                                     evidence / "upgrade-pip", timeout=180)
        if pip_install["exit_code"] != 0 or pip_install["timed_out"]:
            raise RuntimeError("pip bootstrap failed; see preserved logs")
        # Fetch only the CPU wheel here; normal PyPI resolves its dependencies in
        # the subsequent recipe install, including build dependencies absent
        # from the specialized PyTorch wheel index.
        torch_install, _ = run_command([isolated_python, "-m", "pip", "install", "torch==2.5.1+cpu", "--no-deps",
                                        "--index-url", "https://download.pytorch.org/whl/cpu"],
                                       evidence / "install-cpu-torch", timeout=600)
        if torch_install["exit_code"] != 0 or torch_install["timed_out"]:
            raise RuntimeError("CPU torch install failed; see preserved logs")
        prepared = require_json_command(command + ["--install-deps"], evidence / "install", timeout=900)
        write_json(evidence / "preparation.after.json", prepared)
        if prepared.get("status") != "ready" or prepared.get("execution_performed") is not False:
            raise RuntimeError("CLI did not report prepared, unexecuted runtime")
        shutil.copyfile(prepared["lock_path"], evidence / "project.lock.json")
        run_command([isolated_python, "-m", "pip", "freeze"], evidence / "pip-freeze", timeout=60)
        version_script = ("import importlib.metadata as m,json,platform,sys; "
                          "print(json.dumps({'python':sys.version,'platform':platform.platform(),"
                          "'architecture':platform.machine(),'packages':{name:m.version(name) for name in "
                          "['mani_skill','torch','numpy','sapien','mplib','fast_kinematics']}}))")
        versions = require_json_command([isolated_python, "-c", version_script], evidence / "versions", timeout=60)
        write_json(evidence / "environment.json", versions)
        execution, stdout = run_command(prepared["next_command"], evidence / "task",
                                        cwd=prepared["next_command_cwd"], timeout=TASK_TIMEOUT)
        report.update(assess_result(record, execution, stdout))
        report["runtime_verification"] = "executed" if execution["started"] else "not_run"
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        report["error_type"], report["message"] = type(error).__name__, str(error)
    write_json(evidence / "report.json", report)
    print(json.dumps({"skill_id": skill_id, "status": report["status"],
                      "runtime_verification": report["runtime_verification"]}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    output, work = Path(args.output).resolve(), Path(args.work_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": "1", "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "failed", "runtime_verification": "not_run", "task_seed": 0,
              "scope": "Two CPU/state tasks, one seed each, explicit Hub 1000-step motion-planning horizon; not the default benchmark horizon. No hardware, camera/output rendering, physical GPU, publication or submission.",
              "host": {"os": platform.system(), "architecture": platform.machine(), "python": sys.version},
              "recipes": []}
    try:
        if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64") or sys.version_info[:2] != (3, 10):
            raise RuntimeError("Runtime verification requires Linux x86_64 and Python 3.10")
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        report["hub_commit"] = sha
        report["workflow_run_url"] = ("https://github.com/" + os.environ["GITHUB_REPOSITORY"] + "/actions/runs/" +
                                      os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None
        records = load_runtime_records()
        catalog_path = output / "catalog.json"
        write_json(catalog_path, {"schema_version": "1", "hub_commit": sha, "records": records})
        source = records[0]["source"]
        if any(record["source"]["archive_sha256"] != source["archive_sha256"] for record in records):
            raise RuntimeError("The verification recipes must share the exact source archive")
        sys.path.insert(0, str(CLI.parent))
        from rshlib.prepare import download_archive
        archive_path = work / "upstream.tar.gz"
        download_archive(source["archive_url"], archive_path, source["archive_sha256"])
        report["source_archive"] = {"url": source["archive_url"], "sha256": file_sha256(archive_path),
                                    "bytes": archive_path.stat().st_size}
        write_json(output / "report.json", report)
        for record in records:
            report["recipes"].append(verify_recipe(record, catalog_path, archive_path, output, work))
            write_json(output / "report.json", report)
        report["runtime_verification"] = "executed" if any(r["execution_performed"] for r in report["recipes"]) else "not_run"
        report["status"] = "passed" if all(r["status"] == "task_complete" for r in report["recipes"]) else "failed"
    except Exception as error:
        report["error_type"], report["message"] = type(error).__name__, str(error)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output / "report.json", report)
    print(json.dumps({"status": report["status"], "runtime_verification": report["runtime_verification"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
