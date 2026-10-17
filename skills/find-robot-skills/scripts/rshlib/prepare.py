"""Pinned source download and isolated preparation; never runs a robot task."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import venv
from pathlib import Path

from .core import (RshError, compatibility, format_argv, local_environment, lookup,
                   python_satisfies, read_json, safe_relative, validate_record, write_json)

ARCHIVE_LIMIT = 512 * 1024 * 1024
EXTRACT_LIMIT = 1536 * 1024 * 1024


def download_archive(url, destination, expected_sha256):
    digest = hashlib.sha256()
    size = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "robot-skill-hub/1"})
        with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > ARCHIVE_LIMIT:
                    raise RshError("source_too_large", "Source archive exceeds the download limit.")
                digest.update(chunk)
                output.write(chunk)
    except OSError as exc:
        raise RshError("source_unavailable", "Pinned source archive could not be downloaded.",
                       next_action="check_network_and_source_access") from exc
    if digest.hexdigest() != expected_sha256:
        raise RshError("source_hash_mismatch", "Downloaded source does not match the reviewed SHA-256.",
                       next_action="verify_catalog_source_pin")


def extract_archive(archive, destination, commit):
    """Extract regular files under one pinned root; reject links and traversal."""
    destination = Path(destination)
    total_size = 0
    hashes = {}
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            root = None
            for member in bundle:
                name = member.name.rstrip("/")
                if not safe_relative(name):
                    raise RshError("unsafe_source_archive", "Archive contains an unsafe path.")
                pieces = name.split("/", 1)
                if root is None:
                    root = pieces[0]
                    if not root.endswith(commit):
                        raise RshError("source_pin_mismatch", "Archive root does not contain the pinned commit.")
                if pieces[0] != root:
                    raise RshError("unsafe_source_archive", "Archive has multiple source roots.")
                if len(pieces) == 1:
                    if not member.isdir():
                        raise RshError("unsafe_source_archive", "Source root must be a directory.")
                    continue
                relative = pieces[1]
                target = destination / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    total_size += member.size
                    if total_size > EXTRACT_LIMIT:
                        raise RshError("source_too_large", "Expanded source exceeds the extraction limit.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = bundle.extractfile(member)
                    digest = hashlib.sha256()
                    with open(target, "wb") as output:
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            digest.update(chunk)
                            output.write(chunk)
                    hashes[relative] = digest.hexdigest()
                else:
                    raise RshError("unsafe_source_archive", "Archive links and special files are not accepted.")
    except (tarfile.TarError, OSError) as exc:
        raise RshError("invalid_source_archive", "Pinned source archive could not be extracted.") from exc
    return hashes


def source_is_unchanged(source_dir, hashes):
    for name, expected in hashes.items():
        file = Path(source_dir) / name
        if not file.is_file() or file.is_symlink():
            return False
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            return False
    return True


def prepare(catalog, skill_id, project, environment, *, install_deps=False, plan=False, download_only=False, source_archive=None):
    record = validate_record(lookup(catalog, skill_id))
    project = Path(project).expanduser().resolve()
    local = local_environment()
    supplied = dict(environment) if download_only else {**environment, "os": local["os"],
                                                       "python": local["python"], "architecture": local["architecture"]}
    matched = compatibility(record, supplied)
    details = {"skill_id": skill_id, "execution_performed": False,
               "source_commit": record["source"]["commit"],
               "record_version": record["maintenance"]["record_version"]}
    if not download_only and not python_satisfies(record["requirements"]["python"], local["python"]):
        raise RshError("unsupported_python", "The current Python interpreter is outside the reviewed recipe constraint.",
                       status="unsupported", next_action="use_documented_python", required_python=record["requirements"]["python"],
                       local_environment=local, **details)
    if matched["compatibility_status"] == "incompatible":
        raise RshError("unsupported_environment", "Host or explicit environment does not match any documented combination.",
                       status="unsupported", next_action="use_documented_environment", local_environment=local,
                       supported_combinations=record["compatibility"], **details)
    required_keys = record["requirements"].get("api_keys", [])
    missing_keys = [name for name in required_keys if not os.environ.get(name)]
    if missing_keys and not download_only:
        raise RshError("missing_api_key", "Required external API credentials are absent.", status="needs_configuration",
                       next_action="set_required_environment_variables", missing_requirements=missing_keys, **details)
    if record["license"].get("verified") is not True:
        raise RshError("unverified_license", "Automatic preparation requires a verified source license.",
                       status="unsupported", next_action="review_source_license", **details)
    # The recipe supplies its documented combination when no project metadata exists.
    # This selection is an explicit target for a new environment, never a claim about the current project.
    selected = matched["combinations"][0]
    if not download_only and selected.get("architecture", local["architecture"]) != local["architecture"]:
        raise RshError("unsupported_architecture", "This recipe has not been reviewed for the host architecture.",
                       status="unsupported", next_action="use_documented_environment", local_environment=local, **details)
    state = project / ".robot-skill-hub"
    source_dir = state / "sources" / (skill_id + "-" + record["source"]["commit"][:12])
    environment_dir = state / "environments" / skill_id
    recipe_dir = state / "recipes" / skill_id
    lock_path = state / "locks" / (skill_id + ".json")
    if any(not path.resolve().is_relative_to(project) for path in (state, source_dir, environment_dir, recipe_dir, lock_path)):
        raise RshError("preparation_path_escape", "An existing preparation path resolves outside the requested project.",
                       status="blocked", next_action="use_a_project_without_external_preparation_links", **details)
    executable = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    replacements = {"python": str(executable), "source_dir": str(source_dir),
                    "project_dir": str(project), "recipe_dir": str(recipe_dir)}
    commands = record["preparation"].get("install_commands")
    if commands is None:
        commands = [record["preparation"].get("install_argv", [])]
    install_commands = [format_argv(command, replacements) for command in commands if command]
    next_command = format_argv(record["invocation"]["argv"], replacements)
    result = {**details, "status": "needs_configuration", "source_dir": str(source_dir),
              "environment_dir": str(environment_dir), "recipe_dir": str(recipe_dir), "lock_path": str(lock_path),
              "next_command": next_command, "next_command_cwd": str(source_dir),
              "install_commands": install_commands, "planned_network": ([] if source_archive else [record["source"]["archive_url"]])
              + (["https://pypi.org", "https://files.pythonhosted.org"] if install_deps else []),
              "missing_requirements": [], "selected_compatibility": selected,
              "compatibility_status": "documented", "evidence_level": record["evidence"]["level"],
              "dependency_installation_executes_code": True}
    if plan:
        return {**result, "reason_code": "preparation_plan", "next_action": "prepare_pinned_sources",
                "preparation_performed": False}
    existing_lock = read_json(lock_path) if lock_path.exists() else None
    if existing_lock:
        if (existing_lock.get("source_commit") != record["source"]["commit"]
                or existing_lock.get("record_version") != record["maintenance"]["record_version"]
                or existing_lock.get("archive_sha256") != record["source"]["archive_sha256"]
                or existing_lock.get("compatibility") != selected):
            raise RshError("existing_lock_conflict", "This project already pins a different recipe or environment.",
                           status="needs_configuration", next_action="use_new_project_or_review_existing_lock",
                           lock_path=str(lock_path), **details)
        if not source_dir.is_dir() or not source_is_unchanged(source_dir, existing_lock.get("source_files", {})):
            raise RshError("local_source_modified", "Pinned source files are missing or locally modified; they were preserved.",
                           status="needs_configuration", next_action="preserve_local_patch_then_use_new_project",
                           lock_path=str(lock_path), **details)
    else:
        if source_dir.exists() or environment_dir.exists() or recipe_dir.exists():
            raise RshError("unmanaged_preparation_path", "A preparation path already exists without its lock.",
                           status="needs_configuration", next_action="preserve_files_and_use_new_project", **details)
        state.mkdir(parents=True, exist_ok=True)
        source_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="source-", dir=state) as temporary:
            archive = Path(temporary) / "source.tar.gz"
            extracted = Path(temporary) / "extracted"
            extracted.mkdir()
            if source_archive:
                digest = hashlib.sha256()
                with open(source_archive, "rb") as cached, open(archive, "wb") as output:
                    while True:
                        chunk = cached.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        output.write(chunk)
                if digest.hexdigest() != record["source"]["archive_sha256"]:
                    raise RshError("source_hash_mismatch", "Local source archive does not match the reviewed SHA-256.")
            else:
                download_archive(record["source"]["archive_url"], archive, record["source"]["archive_sha256"])
            hashes = extract_archive(archive, extracted, record["source"]["commit"])
            for required in record["source"]["paths"]:
                if not (extracted / required).is_file():
                    raise RshError("source_entrypoint_missing", "Pinned archive lacks a declared source path.", path=required)
            extracted.replace(source_dir)
        existing_lock = {"schema_version": "1", "skill_id": skill_id,
                         "hub_commit": catalog.get("hub_commit"), "record_version": record["maintenance"]["record_version"],
                         "source_commit": record["source"]["commit"], "archive_sha256": record["source"]["archive_sha256"],
                         "source_files": hashes, "compatibility": selected, "dependencies_installed": False,
                         "robot_execution": "not_run"}
        recipe_files = record["preparation"].get("files", {})
        for relative, content in recipe_files.items():
            if not safe_relative(relative) or not isinstance(content, str):
                raise RshError("invalid_recipe_file", "Embedded recipe files require safe paths and text content.")
        recipe_dir.mkdir(parents=True, exist_ok=True)
        for relative, content in recipe_files.items():
            target = recipe_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        write_json(lock_path, existing_lock)
    if download_only:
        return {**result, "status": "needs_configuration", "reason_code": "source_ready_runtime_not_prepared",
                "next_action": "use_documented_host_then_prepare_environment", "environment_dir": None,
                "next_command": None, "target_invocation_template": record["invocation"]["argv"],
                "preparation_performed": True, "missing_requirements": ["documented_runtime_environment"],
                "local_environment": local, "environment_created": False}
    if not executable.is_file():
        existing_lock["dependencies_installed"] = False
        write_json(lock_path, existing_lock)
        try:
            venv.EnvBuilder(with_pip=True).create(environment_dir)
        except Exception as exc:
            raise RshError("environment_creation_failed", "Isolated Python environment could not be created.",
                           next_action="check_python_venv_support", lock_path=str(lock_path), **details) from exc
    if install_deps and not existing_lock.get("dependencies_installed"):
        for command in install_commands:
            # stdout belongs exclusively to the command's JSON response.
            try:
                import sys
                completed = subprocess.run(command, cwd=source_dir, stdin=subprocess.DEVNULL,
                                           stdout=sys.stderr, stderr=sys.stderr, timeout=1800, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RshError("dependency_install_failed", "Dependency installation failed or timed out.",
                               next_action="inspect_install_output_and_keep_local_lock", lock_path=str(lock_path), **details) from exc
            if completed.returncode:
                raise RshError("dependency_install_failed", "Dependency installer returned a nonzero exit code.",
                               next_action="inspect_install_output_and_keep_local_lock", exit_code=completed.returncode,
                               lock_path=str(lock_path), **details)
        existing_lock["dependencies_installed"] = True
        try:
            frozen = subprocess.run([str(executable), "-m", "pip", "freeze"], cwd=source_dir,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=sys.stderr,
                                    timeout=60, check=True, text=True, encoding="utf-8").stdout
            (environment_dir / "requirements.freeze.txt").write_text(frozen, encoding="utf-8")
            existing_lock["environment_snapshot_file"] = str(environment_dir / "requirements.freeze.txt")
        except (OSError, subprocess.SubprocessError):
            existing_lock["environment_snapshot_status"] = "capture_failed"
        write_json(lock_path, existing_lock)
    if existing_lock.get("dependencies_installed"):
        result.update(status="ready", reason_code="prepared_not_executed", next_action="review_then_run_next_command")
    elif install_commands:
        result.update(reason_code="dependencies_not_installed", next_action="review_install_commands_then_prepare_with_install_deps",
                      missing_requirements=["isolated_dependency_installation"])
    else:
        result.update(status="ready", reason_code="prepared_not_executed", next_action="review_then_run_next_command")
    return {**result, "preparation_performed": True}
