"""Anonymous discovery measurement remains optional and never reads project content."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
discovery = importlib.import_module("rshlib.discovery")


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


if __name__ == "__main__":
    unittest.main()
