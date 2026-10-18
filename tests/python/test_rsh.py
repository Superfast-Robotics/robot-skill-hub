"""Contract tests; fixture task execution is not a real robotics verification."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/find-robot-skills"
sys.path.insert(0, str(SKILL / "scripts"))
from rshlib import contributions
from rshlib.core import RshError, compatibility, find, inspect, load_catalog, local_environment, validate_record
from rshlib.prepare import download_archive, extract_archive, prepare

PIN = "a" * 40
HUB = "b" * 40
DOC_PATH = "docs/recipes/fixture-pick.md"
PATCH = f"--- a/{DOC_PATH}\n+++ b/{DOC_PATH}\n@@ -1 +1 @@\n-old\n+fixed\n"


def source_archive(*, malicious=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo("fixture-" + PIN + "/module.py")
        content = b"VALUE = 42\n"
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
        if malicious == "traversal":
            member = tarfile.TarInfo("fixture-" + PIN + "/../escape.py")
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))
        elif malicious == "symlink":
            member = tarfile.TarInfo("fixture-" + PIN + "/link")
            member.type = tarfile.SYMTYPE
            member.linkname = "../../escape"
            archive.addfile(member)
    return output.getvalue()


def fixture_record(data=None):
    data = data or source_archive()
    local = local_environment()
    return {"id": "fixture-pick", "name": "Fixture pick", "summary": "Pick object in a fixture environment",
            "capabilities": ["pick", "grasping"], "aliases": ["cube"],
            "source": {"repository": "https://example.org/fixture", "commit": PIN,
                       "paths": ["module.py"], "authors": ["Fixture author"],
                       "archive_url": "https://example.org/archive/" + PIN + ".tar.gz",
                       "archive_sha256": hashlib.sha256(data).hexdigest()},
            "license": {"spdx": "Apache-2.0", "verified": True},
            "compatibility": [{"runtime": "fixture", "runtime_version": "1.0.0", "robot": "panda",
                               "controller": "pd_joint_pos", "observation": "state", "os": local["os"],
                               "architecture": local["architecture"]}],
            "requirements": {"python": ">=3.10,<4", "api_keys": []},
            "invocation": {"entrypoint": "run.py", "argv": ["{python}", "{recipe_dir}/run.py"]},
            "preparation": {"files": {"run.py": "import json\nprint(json.dumps({'fixture_task': 'complete'}))\n"},
                            "install_argv": ["{python}", "-c", "from pathlib import Path; Path('install-marker').write_text('installed')"]},
            "evidence": {"level": "not_run"}, "maintenance": {"record_version": "1.0.0"},
            "contribution": {"allowed_paths": [DOC_PATH]}}


def fixture_catalog(data=None):
    return {"schema_version": "1", "hub_commit": HUB, "records": [fixture_record(data)]}


def failed_attempt():
    return {"status": "failed", "execution_performed": True, "success": False,
            "reason_code": "task_objective_not_reached", "seed": 0, "elapsed_steps": 12,
            "terminated": False, "truncated": False, "exit_code": 1, "timed_out": False,
            "workflow_run_id": "123", "verified_hub_commit": HUB,
            "record_version": "1.0.0", "source_commit": PIN,
            "environment": {"runtime": "fixture", "runtime_version": "1.0.0", "robot": "panda",
                            "controller": "pd_joint_pos", "observation": "state", "os": local_environment()["os"]}}


def bundle():
    return {"schema_version": "1", "skill_id": "fixture-pick", "base": {"hub_commit": HUB, "source_commit": PIN, "record_version": "1.0.0"},
            "change_kind": "docs_fix", "summary": "Fix a documented reproduction step", "patch": PATCH,
            "environment": {"runtime": "unknown", "robot": "unknown"},
            "evidence": {"level": "not_run", "command": None, "result": "No runtime check", "reported_by": "submitter"},
            "attribution": {"contributor_label": "test contributor", "preserve_upstream_attribution": True},
            "publication": {"public_submission_allowed": True}}


class CatalogTests(unittest.TestCase):
    def test_failed_attempt_remains_separate_from_positive_checks_and_is_exposed(self):
        catalog = fixture_catalog()
        record = catalog["records"][0]
        attempt = failed_attempt()
        record["evidence"].update(level="import_verified", runtime_verification="import_verified",
                                  artifacts=["https://example.org/immutable/runtime-report.json"],
                                  hub_verification={"level": "import_verified", "runtime": "import_verified",
                                                    "last_task_attempt": attempt})
        validate_record(record)
        found = find(catalog, "pick", {})["results"][0]
        self.assertEqual(found["evidence_level"], "import_verified")
        self.assertEqual(found["last_task_attempt"], attempt)
        detail = inspect(catalog, record["id"])
        self.assertEqual(detail["last_task_attempt"], attempt)
        self.assertEqual(detail["evidence"]["hub_verification"]["last_task_attempt"], attempt)
        self.assertFalse(detail["execution_performed"])
        with tempfile.TemporaryDirectory() as temporary, mock.patch("urllib.request.urlopen") as network, \
                mock.patch("rshlib.prepare.venv.EnvBuilder") as environment, mock.patch("rshlib.prepare.subprocess.run") as process:
            project = Path(temporary) / "untouched"
            plan = prepare(catalog, record["id"], project, {}, plan=True)
            self.assertEqual(plan["last_task_attempt"], attempt)
            self.assertEqual(plan["evidence_level"], "import_verified")
            self.assertEqual(plan["reason_code"], "preparation_plan")
            self.assertFalse(plan["execution_performed"])
            self.assertFalse(project.exists())
            network.assert_not_called(); environment.assert_not_called(); process.assert_not_called()
        # The attempt is scoped data, not a global negation of separately retained positive evidence.
        record["evidence"].update(level="task_complete", runtime_verification="task_complete")
        record["compatibility"][0]["status"] = "hub_verified"
        validate_record(record)

    def test_failed_attempt_rejects_inconsistent_results_or_missing_provenance(self):
        for change in (lambda a: a.update(success=True), lambda a: a.update(execution_performed=False),
                       lambda a: a.update(status=""), lambda a: a.pop("source_commit"),
                       lambda a: a.update(elapsed_steps=True), lambda a: a.update(elapsed_steps=-1),
                       lambda a: a.update(timed_out="false"), lambda a: a["environment"].pop("robot")):
            with self.subTest(change=change):
                record = fixture_record()
                attempt = failed_attempt()
                change(attempt)
                record["evidence"].update(level="import_verified", artifacts=["https://example.org/report"],
                                          hub_verification={"last_task_attempt": attempt})
                with self.assertRaises(RshError) as error:
                    validate_record(record)
                self.assertEqual(error.exception.result["reason_code"], "invalid_task_attempt")
        record = fixture_record()
        record["evidence"]["hub_verification"] = {"last_task_attempt": failed_attempt()}
        with self.assertRaises(RshError):
            validate_record(record)
        self.assertNotIn("last_task_attempt", find(fixture_catalog(), "pick", {})["results"][0])

    def test_future_attempt_status_is_data_and_does_not_infer_success(self):
        catalog = fixture_catalog()
        record = catalog["records"][0]
        attempt = {"status": "future_unmeasured_outcome"}
        record["evidence"]["hub_verification"] = {"last_task_attempt": attempt}
        validate_record(record)
        found = find(catalog, "pick", {})["results"][0]
        self.assertEqual(found["last_task_attempt"], attempt)
        self.assertEqual(found["evidence_level"], "not_run")
        self.assertNotIn("success", found["last_task_attempt"])
        self.assertEqual(inspect(catalog, record["id"])["last_task_attempt"], attempt)

    def test_explicit_framework_and_version_mismatch_return_empty(self):
        catalog = fixture_catalog()
        for environment in ({"runtime": "mujoco"}, {"runtime_version": "99.0.0"}, {"robot": "ur5"},
                            {"controller": "pd_ee_delta_pose"}, {"observation": "rgb"}):
            with self.subTest(environment=environment):
                self.assertEqual(find(catalog, "pick object", environment)["results"], [])

    def test_unknown_environment_is_never_reported_as_compatible(self):
        result = find(fixture_catalog(), "grasp cube", {"runtime_version": "unknown"})["results"][0]
        self.assertEqual(result["compatibility_status"], "unknown")
        self.assertIn("runtime_version", result["missing_requirements"])

    def test_invalid_pin_and_missing_contract_keys_fail(self):
        for change, expected in ((lambda record: record["source"].update(commit="main"), "invalid_source_pin"),
                                 (lambda record: record["source"].update(archive_sha256="unknown"), "invalid_source_hash"),
                                 (lambda record: record.pop("invocation"), "missing_record_field")):
            record = fixture_record()
            change(record)
            with self.assertRaises(RshError) as error:
                validate_record(record)
            self.assertEqual(error.exception.result["reason_code"], expected)

    def test_bundled_catalog_is_valid(self):
        catalog = load_catalog()
        self.assertGreaterEqual(len(catalog["records"]), 2)
        for record in catalog["records"]:
            self.assertTrue(record["preparation"]["files"])
            if record["evidence"]["level"] == "task_complete":
                self.assertEqual(record["evidence"]["runtime_verification"], "task_complete")
                self.assertTrue(record["evidence"]["artifacts"])
                self.assertEqual(record["evidence"]["hub_verification"]["runtime"], "task_complete")

    def test_verified_evidence_levels_match_the_canonical_contract(self):
        for level in ("install_verified", "import_verified", "task_complete"):
            with self.subTest(level=level):
                record = fixture_record()
                record["evidence"]["level"] = level
                self.assertEqual(validate_record(record)["evidence"]["level"], level)
        for obsolete in ("installed", "imported"):
            record = fixture_record()
            record["evidence"]["level"] = obsolete
            with self.assertRaises(RshError):
                validate_record(record)

    def test_python_and_architecture_are_real_compatibility_constraints(self):
        catalog = fixture_catalog()
        record = catalog["records"][0]
        record["compatibility"][0]["python"] = "3.10"
        record["compatibility"][0]["architecture"] = "x86_64"
        record["requirements"]["python"] = ">=3.10,<3.11"
        self.assertEqual(find(catalog, "pick", {"python": "3.11.0"})["results"], [])
        self.assertEqual(find(catalog, "pick", {"architecture": "arm64"})["results"], [])
        result = find(catalog, "pick", {"python": "3.10.11", "architecture": "AMD64"})["results"]
        self.assertEqual(len(result), 1)


class SourcePreparationTests(unittest.TestCase):
    def test_download_hash_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b"wrong bytes")):
                with self.assertRaises(RshError) as error:
                    download_archive("https://example.org/source", Path(temporary) / "archive", "0" * 64)
            self.assertEqual(error.exception.result["reason_code"], "source_hash_mismatch")

    def test_archive_cannot_escape_source_directory(self):
        for malicious in ("traversal", "symlink"):
            with self.subTest(malicious=malicious), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "source.tar.gz"
                archive.write_bytes(source_archive(malicious=malicious))
                with self.assertRaises(RshError) as error:
                    extract_archive(archive, Path(temporary) / "source", PIN)
                self.assertEqual(error.exception.result["reason_code"], "unsafe_source_archive")
                self.assertFalse((Path(temporary) / "escape.py").exists())

    def test_clean_project_separates_download_install_and_fixture_task(self):
        data = source_archive()
        catalog = fixture_catalog(data)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "clean-project"
            with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(data)):
                first = prepare(catalog, "fixture-pick", project, {})
            self.assertEqual(first["reason_code"], "dependencies_not_installed")
            self.assertFalse(first["execution_performed"])
            self.assertTrue((Path(first["source_dir"]) / "module.py").is_file())
            self.assertFalse((Path(first["source_dir"]) / "install-marker").exists())
            second = prepare(catalog, "fixture-pick", project, {}, install_deps=True)
            self.assertEqual(second["status"], "ready")
            self.assertTrue((Path(second["source_dir"]) / "install-marker").is_file())
            self.assertFalse(second["execution_performed"])
            # Explicit, separate fixture execution proves the command is usable, not ManiSkill.
            executed = subprocess.run(second["next_command"], cwd=second["next_command_cwd"],
                                      stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, check=True)
            self.assertEqual(json.loads(executed.stdout), {"fixture_task": "complete"})
            changed = copy.deepcopy(catalog)
            changed["records"][0]["maintenance"]["record_version"] = "1.0.1"
            with self.assertRaises(RshError) as error:
                prepare(changed, "fixture-pick", project, {})
            self.assertEqual(error.exception.result["reason_code"], "existing_lock_conflict")
            original_lock = json.loads(Path(first["lock_path"]).read_text())
            self.assertEqual(original_lock["record_version"], "1.0.0")
            (Path(first["source_dir"]) / "module.py").write_text("locally fixed\n")
            with self.assertRaises(RshError) as error:
                prepare(catalog, "fixture-pick", project, {})
            self.assertEqual(error.exception.result["reason_code"], "local_source_modified")
            self.assertEqual((Path(first["source_dir"]) / "module.py").read_text(), "locally fixed\n")

    def test_missing_required_key_and_unsupported_host_do_not_download(self):
        catalog = fixture_catalog()
        catalog["records"][0]["requirements"]["api_keys"] = ["RSH_TEST_REQUIRED_KEY"]
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {}, clear=True), mock.patch("urllib.request.urlopen") as network:
            with self.assertRaises(RshError) as error:
                prepare(catalog, "fixture-pick", temporary, {})
            self.assertEqual(error.exception.result["reason_code"], "missing_api_key")
            network.assert_not_called()
            catalog["records"][0]["compatibility"][0]["os"] = "unsupported-host"
            with self.assertRaises(RshError) as error:
                prepare(catalog, "fixture-pick", temporary, {})
            self.assertEqual(error.exception.result["reason_code"], "unsupported_environment")
            network.assert_not_called()

    def test_source_only_on_unsupported_host_does_not_create_environment(self):
        data = source_archive()
        catalog = fixture_catalog(data)
        catalog["records"][0]["compatibility"][0]["os"] = "other-os"
        with tempfile.TemporaryDirectory() as temporary, mock.patch("urllib.request.urlopen", return_value=io.BytesIO(data)):
            result = prepare(catalog, "fixture-pick", temporary, {}, download_only=True)
            self.assertEqual(result["status"], "needs_configuration")
            self.assertIsNone(result["environment_dir"])
            self.assertFalse(result["environment_created"])
            self.assertTrue(Path(result["source_dir"]).is_dir())


class ContributionTests(unittest.TestCase):
    def test_empty_changes_and_forbidden_paths_are_blocked(self):
        with self.assertRaises(RshError) as error:
            contributions.patch_paths("")
        self.assertEqual(error.exception.result["reason_code"], "no_changes")
        for patch in (PATCH.replace(DOC_PATH, "../secret.txt"), PATCH.replace(DOC_PATH, ".github/workflows/publish.yml")):
            payload = bundle()
            payload["patch"] = patch
            with self.assertRaises(RshError):
                contributions.validate_bundle(payload, fixture_record())

    def test_missing_sharing_permission_blocks_before_token_or_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            draft = Path(temporary) / "contribution.json"
            draft.write_text(json.dumps(bundle()))
            with mock.patch("rshlib.contributions.request_json") as network, mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RshError) as error:
                    contributions.submit(fixture_catalog(), draft, temporary)
            self.assertEqual(error.exception.result["reason_code"], "sharing_not_allowed")
            self.assertFalse(error.exception.result["network_performed"])
            network.assert_not_called()
            self.assertTrue(draft.exists())

    def test_token_does_not_imply_public_permission(self):
        self.assertFalse(contributions.sharing_allowed({}, "fixture-pick", [DOC_PATH]))
        self.assertFalse(contributions.sharing_allowed({"publication": {"public_submission_allowed": True,
                    "allowed_paths": ["recipes/*"]}}, "fixture-pick", [DOC_PATH]))

    def test_local_bundle_remains_available_without_permission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fix.patch").write_text(PATCH)
            metadata = bundle()
            (root / "metadata.json").write_text(json.dumps(metadata))
            result = contributions.create_bundle(fixture_catalog(), "fixture-pick", root / "fix.patch", root / "metadata.json",
                                                  root / "bundle.json", root)
            self.assertEqual(result["status"], "blocked")
            self.assertFalse(result["network_performed"])
            saved = json.loads((root / "bundle.json").read_text())
            self.assertEqual(saved["patch"], PATCH)
            self.assertEqual(saved["base"]["hub_commit"], HUB)
            self.assertFalse(saved["publication"]["public_submission_allowed"])

    def test_retry_identity_is_stable_and_token_is_not_persisted(self):
        calls = []
        def fake_request(method, url, token, **kwargs):
            calls.append(kwargs["idempotency_key"])
            return {"submission_id": "rsh_fixture", "status": "submitted", "http_status": 201}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bundle.json").write_text(json.dumps(bundle()))
            (root / ".robot-skill-hub.json").write_text(json.dumps({"publication": {"public_submission_allowed": True}}))
            with mock.patch.dict(os.environ, {"RSH_SUBMISSION_TOKEN": "test-local-token-0123456789-abcdef", "RSH_API_URL": "https://api.example.org"}), mock.patch("rshlib.contributions.request_json", side_effect=fake_request):
                first = contributions.submit(fixture_catalog(), root / "bundle.json", root)
                contributions.submit(fixture_catalog(), root / "bundle.json", root)
            self.assertEqual(calls[0], calls[1])
            receipt = Path(first["receipt_path"]).read_text()
            self.assertNotIn("test-local-token", receipt)

    def test_api_redirect_does_not_forward_bearer(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/destination")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(RshError):
                contributions.request_json("GET", f"http://127.0.0.1:{server.server_port}/start", "local-secret")
            self.assertEqual(hits, ["/start"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class IndependentSkillTests(unittest.TestCase):
    def test_skill_directory_alone_and_json_anywhere_never_wait_for_stdin(self):
        with tempfile.TemporaryDirectory() as temporary:
            isolated = Path(temporary) / "installed-skill"
            shutil.copytree(SKILL, isolated, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for arguments in (["--json", "find", "pick", "--runtime", "maniskill", "--robot", "panda"],
                              ["inspect", "maniskill-panda-pick-cube", "--json"],
                              ["find", "pick", "--runtime-version", "99.0.0", "--json"],
                              ["prepare", "maniskill-panda-pick-cube", "--json"],
                              ["--json", "--catalog"]):
                with self.subTest(arguments=arguments):
                    executed = subprocess.run([sys.executable, str(isolated / "scripts/rsh.py"), "--offline", *arguments],
                                              cwd=temporary, input="", capture_output=True, text=True, timeout=15,
                                              env={**os.environ, "RSH_TELEMETRY": "off"})
                    result = json.loads(executed.stdout)
                    self.assertIn("status", result)
                    self.assertNotIn("Traceback", executed.stdout)


if __name__ == "__main__":
    unittest.main()
