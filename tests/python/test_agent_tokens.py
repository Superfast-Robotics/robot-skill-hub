"""Operator registry safety checks. These tests never contact a service."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("manage_agent_tokens", ROOT / "tools/manage_agent_tokens.py")
tokens = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tokens)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.local = Path(self.temporary.name) / ".local"
        self.local.mkdir()
        self.registry = self.local / "submission-tokens.registry.json"
        self.patch = mock.patch.object(tokens, "LOCAL", self.local)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.pilot_token = "rsh_" + "a" * 43
        self.pilot_file = self.local / "pilot-token.secret"
        self.pilot_file.write_text(self.pilot_token)
        self.receipt = self.local / "receipt.json"
        self.receipt.write_text(json.dumps({"principal_id": tokens.principal_hash("pilot-1")}))

    def adopt(self):
        tokens.adopt(self.registry, "pilot-1", self.pilot_file, self.receipt, True)

    def test_adoption_needs_complete_baseline_and_matching_receipt(self):
        with self.assertRaisesRegex(ValueError, "complete"):
            tokens.adopt(self.registry, "pilot-1", self.pilot_file, self.receipt, False)
        with self.assertRaisesRegex(ValueError, "receipt"):
            tokens.adopt(self.registry, "different", self.pilot_file, self.receipt, True)
        self.assertFalse(self.registry.exists())
        self.adopt()
        entries = tokens.read_registry(self.registry)
        self.assertEqual(entries, [{"principal_id": "pilot-1", "sha256": tokens.digest(self.pilot_token)}])
        self.assertNotIn(self.pilot_token, self.registry.read_text())

    def test_adding_a_caller_preserves_every_prior_entry(self):
        self.adopt()
        old = tokens.read_registry(self.registry)
        new_file = self.local / "agent-2.secret"
        tokens.issue(self.registry, "agent-2", new_file)
        entries = tokens.read_registry(self.registry)
        self.assertEqual(entries[:1], old)
        self.assertEqual(entries[1], {"principal_id": "agent-2", "sha256": tokens.digest(new_file.read_text())})
        self.assertNotEqual(new_file.read_text(), self.pilot_token)
        self.assertEqual(len(new_file.read_text()), 47)
        with self.assertRaisesRegex(ValueError, "rotate"):
            tokens.issue(self.registry, "agent-2", self.local / "accidental.secret")
        self.assertFalse((self.local / "accidental.secret").exists())

    def test_rotation_preserves_owner_and_disables_old_tokens_only(self):
        self.adopt()
        tokens.issue(self.registry, "agent-2", self.local / "agent-2.secret")
        other = tokens.read_registry(self.registry)[1]
        tokens.issue(self.registry, "pilot-1", self.local / "pilot-rotated.secret", rotate=True)
        entries = tokens.read_registry(self.registry)
        self.assertIs(entries[0]["disabled"], True)
        self.assertEqual(entries[1], other)
        self.assertEqual(entries[2]["principal_id"], "pilot-1")
        self.assertNotIn("disabled", entries[2])
        tokens.revoke(self.registry, "pilot-1")
        self.assertTrue(all(e.get("disabled") is True for e in tokens.read_registry(self.registry) if e["principal_id"] == "pilot-1"))
        self.assertEqual(tokens.read_registry(self.registry)[1], other)

    def test_no_overwrite_no_parallel_mutation_and_no_public_paths(self):
        self.adopt()
        original = self.registry.read_bytes()
        with self.assertRaises(FileExistsError):
            self.adopt()
        with self.assertRaises(ValueError):
            tokens.issue(self.registry, "agent-2", self.local.parent / "public-token.txt")
        with tokens.registry_lock(self.registry):
            with self.assertRaisesRegex(ValueError, "locked"):
                tokens.issue(self.registry, "agent-2", self.local / "agent-2.secret")
        self.assertEqual(self.registry.read_bytes(), original)
        self.assertFalse((self.local / "agent-2.secret").exists())

    def test_output_never_contains_raw_tokens_or_hashes(self):
        self.adopt()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(tokens.main(["--registry", str(self.registry), "add", "agent-2", "--token-file", str(self.local / "agent-2.secret")]), 0)
        self.assertNotIn(self.pilot_token, output.getvalue())
        for entry in tokens.read_registry(self.registry):
            self.assertNotIn(entry["sha256"], output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "local_only")

    def test_registry_validation_rejects_collision_and_invalid_auth_config(self):
        base = {"principal_id": "pilot-1", "sha256": "a" * 64}
        for entries in ([base, {**base, "principal_id": "agent-2"}], [{**base, "disabled": "false"}],
                        [{**base, "token": "never-store-plaintext"}], [{**base, "principal_id": "bad/name"}],
                        [], [base] * 101):
            with self.assertRaises(ValueError):
                tokens.validate(entries)

    def test_complete_import_and_export_do_not_mutate_registry(self):
        source = self.local / "complete.json"
        entries = [{"principal_id": "existing-agent", "sha256": "e" * 64}, {"principal_id": "old-agent", "sha256": "a" * 64, "disabled": True}]
        source.write_text(json.dumps(entries))
        tokens.import_registry(self.registry, source, True)
        before = self.registry.read_bytes()
        export = self.local / "snapshot.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tokens.main(["--registry", str(self.registry), "export", "--output-json", str(export)]), 0)
        self.assertEqual(json.loads(export.read_text()), entries)
        self.assertEqual(self.registry.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
