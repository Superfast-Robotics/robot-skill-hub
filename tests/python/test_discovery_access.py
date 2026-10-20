"""Anonymous discovery measurement remains optional and never reads project content."""
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
discovery = importlib.import_module("rshlib.discovery")
core = importlib.import_module("rshlib.core")


class DiscoveryAccessTests(unittest.TestCase):
    def test_anonymous_identity_is_stable_and_sent_only_to_owned_api(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"RSH_CACHE_DIR": directory, "RSH_TELEMETRY": "on"}):
            first = discovery.client_headers(discovery.API_BASE + "catalog")
            second = discovery.client_headers(discovery.API_BASE + "references")
            self.assertRegex(first["X-RSH-Client"], r"^[a-f0-9]{32}$")
            self.assertEqual(first["X-RSH-Client"], second["X-RSH-Client"])
            self.assertNotIn("X-RSH-Client", discovery.client_headers("https://example.org/catalog.json"))
            self.assertNotIn("X-RSH-Client", discovery.client_headers("https://api.superfastrobotics.com.example.org/v1/catalog"))
            self.assertNotIn("Authorization", first)
            self.assertNotIn(str(ROOT), str(first))

    def test_opt_out_creates_no_identity_and_preserves_read_headers(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"RSH_CACHE_DIR": directory, "RSH_TELEMETRY": "off"}):
            headers = discovery.client_headers(discovery.API_BASE + "catalog")
            self.assertEqual(headers["DNT"], "1")
            self.assertEqual(headers["X-RSH-Telemetry"], "off")
            self.assertEqual(headers["Accept"], "application/json")
            self.assertNotIn("X-RSH-Client", headers)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_non_identity_file_and_hardlinked_private_file_are_not_sent(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"RSH_CACHE_DIR": str(Path(directory) / "cache"), "RSH_TELEMETRY": "on"}):
            path = Path(directory) / "cache/anonymous-client-id"
            path.parent.mkdir()
            path.write_text("f" * 32, encoding="ascii")
            self.assertNotIn("X-RSH-Client", discovery.client_headers(discovery.API_BASE + "catalog"))
            path.unlink()
            private = Path(directory) / "outside.txt"
            private.write_text("rsh-client-id-v1:" + "e" * 32, encoding="ascii")
            path.hardlink_to(private)
            self.assertNotIn("X-RSH-Client", discovery.client_headers(discovery.API_BASE + "catalog"))
            self.assertEqual(private.read_text(), "rsh-client-id-v1:" + "e" * 32)

    def test_api_failure_uses_published_static_catalog_without_replacing_locks(self):
        snapshot = discovery.load_catalog()
        calls = []
        def fetch(url):
            calls.append(url)
            if url == discovery.API_BASE + "catalog":
                raise OSError("API unavailable")
            return snapshot if url.endswith("index.json") else {"schema_version": "1", "records": []}
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"RSH_CACHE_DIR": directory}), mock.patch.object(discovery, "fetch_public", side_effect=fetch):
            result = discovery.load_discovery(refresh=True)
            self.assertEqual(calls[:2], [discovery.API_BASE + "catalog", discovery.BASE + "index.json"])
            self.assertEqual(result["hub_commit"], snapshot["hub_commit"])
            self.assertEqual(result["catalog_origin"], "remote")

    def test_malformed_gateway_catalog_cannot_poison_the_offline_cache(self):
        snapshot = discovery.load_catalog()
        def fetch(url):
            if url == discovery.API_BASE + "catalog":
                return {"schema_version": "1", "records": []}
            return snapshot if url.endswith("index.json") else {"schema_version": "1", "records": []}
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"RSH_CACHE_DIR": directory}), mock.patch.object(discovery, "fetch_public", side_effect=fetch):
            discovery.load_discovery(refresh=True)
            cached = discovery.load_discovery(offline=True)
            self.assertEqual(cached["hub_commit"], snapshot["hub_commit"])

    def test_malformed_gateway_and_static_outage_use_the_bundled_snapshot(self):
        def fetch(url):
            if url == discovery.API_BASE + "catalog":
                return {"schema_version": "1", "records": []}
            raise OSError("Static origin unavailable")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"RSH_CACHE_DIR": directory}), mock.patch.object(discovery, "fetch_public", side_effect=fetch):
            result = discovery.load_discovery(refresh=True)
            self.assertEqual(result["catalog_origin"], "bundled_snapshot")
            self.assertRegex(result["hub_commit"], r"^[a-f0-9]{40}$")

    def test_reference_fallback_exposes_its_own_commit_and_uses_it_for_memory_identity(self):
        snapshot = {**discovery.load_catalog(), "hub_commit": "c" * 40}
        reference = {"id": "fixture-ik", "name": "KUKA IK", "summary": "Inverse kinematics",
                     "framework": "pybullet", "capabilities": ["ik"], "robots": ["kuka"],
                     "source": {"commit": "b" * 40, "sha256": "d" * 64, "url": "https://example.org/source"}}
        old_refs = {"schema_version": "1", "hub_commit": "a" * 40, "records": [reference]}
        def fetch(url):
            if url == discovery.API_BASE + "catalog":
                return snapshot
            raise core.RshError("catalog_too_large", "Controlled oversized reference response")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"RSH_CACHE_DIR": directory}), mock.patch.object(discovery, "fetch_public", side_effect=fetch):
            discovery._write_cache("references", old_refs)
            catalog = discovery.load_discovery(refresh=True)
            found = core.find(catalog, "fixture-ik", {})
            detail = core.inspect(catalog, "fixture-ik")
            for result in (found, detail):
                self.assertEqual(result["catalog_origin"], "remote")
                self.assertEqual(result["references_origin"], "cache_fallback")
                self.assertEqual(result["catalog_hub_commit"], "c" * 40)
                self.assertEqual(result["references_hub_commit"], "a" * 40)
                self.assertEqual(result["references_discovery"]["fallback_reasons"], ["catalog_too_large"])
            self.assertEqual(found["results"][0]["memory_base"]["hub_commit"], "a" * 40)
            self.assertEqual(detail["memory_base"]["hub_commit"], "a" * 40)

    def test_explicit_remote_catalog_keeps_opt_out_and_bounded_redirect_free_transport(self):
        snapshot = discovery.load_catalog()
        raw = json.dumps(snapshot).encode()
        opener = mock.Mock()
        opener.open.return_value = io.BytesIO(raw)
        with mock.patch.dict(os.environ, {"RSH_TELEMETRY": "off"}), mock.patch("urllib.request.build_opener", return_value=opener):
            self.assertEqual(core.load_catalog(discovery.API_BASE + "catalog")["hub_commit"], snapshot["hub_commit"])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Dnt"), "1")
        self.assertEqual(request.get_header("X-rsh-telemetry"), "off")
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(discovery.PUBLIC_LIMIT, 8 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
