"""Truthful fixed-window reporting and a monitor that generates no discovery traffic."""
import importlib.util
import json
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("campaign_monitor", ROOT / "tools/monitor_campaign.py")
MONITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MONITOR)


class CampaignMonitorTests(unittest.TestCase):
    def setUp(self):
        self.now = MONITOR.WINDOW_START + timedelta(hours=1)
        self.metrics = {
            "measurement_configured": True, "observed_at": MONITOR.iso(self.now),
            "window_start": MONITOR.iso(MONITOR.WINDOW_START), "window_end": MONITOR.iso(MONITOR.WINDOW_END),
            "target_agent_accesses": 10000, "observed_agent_accesses": 7, "target_reached": False,
            "groups": [{"family": "rsh_cli", "requests": 4}, {"family": "mcp_tool", "requests": 3},
                       {"family": "crawler", "requests": 1000}, {"family": "unclassified", "requests": 90}],
        }

    def assess(self, data=None):
        return MONITOR.assess_metrics({"ok": True, "data": self.metrics if data is None else data}, self.now)

    def test_only_eligible_families_count_and_crawlers_cannot_reach_target(self):
        result = self.assess()
        self.assertEqual(result["observed_agent_accesses"], 7)
        self.assertIs(result["target_reached"], False)
        self.metrics["groups"].append({"family": "recognized_agent", "requests": 93})
        self.metrics.update(observed_agent_accesses=100, target_reached=False)
        self.assertIs(self.assess()["target_reached"], False)

    def test_target_boundary_requires_10000_eligible_accesses(self):
        for count, reached in ((100, False), (9999, False), (10000, True)):
            data = {**self.metrics, "observed_agent_accesses": count, "target_reached": reached,
                    "groups": [{"family": "rsh_cli", "requests": count}, {"family": "crawler", "requests": 100000}]}
            with self.subTest(count=count):
                result = self.assess(data)
                self.assertEqual(result["status"], "target_reached" if reached else "below_target")
                self.assertEqual(result["observed_agent_accesses"], count)
                self.assertIs(result["target_reached"], reached)

    def test_legacy_100_target_is_rejected_even_when_counts_and_reached_flag_agree(self):
        legacy = {**self.metrics, "target_agent_accesses": 100, "observed_agent_accesses": 10000,
                  "target_reached": True, "groups": [{"family": "mcp_tool", "requests": 10000}]}
        result = self.assess(legacy)
        self.assertEqual(result["status"], "invalid_report")
        self.assertIsNone(result["observed_agent_accesses"])
        self.assertIsNone(result["target_reached"])

    def test_unconfigured_or_missing_metrics_are_unknown(self):
        self.assertIsNone(MONITOR.assess_metrics({"ok": False}, self.now)["observed_agent_accesses"])
        self.metrics["measurement_configured"] = False
        result = self.assess()
        self.assertEqual(result["status"], "unconfigured")
        self.assertIsNone(result["observed_agent_accesses"])
        self.assertIsNone(result["target_reached"])

    def test_fixed_window_cannot_slide_with_a_new_deployment(self):
        self.assertEqual(MONITOR.iso(MONITOR.WINDOW_START), "2026-10-17T15:47:38Z")
        self.assertEqual(MONITOR.iso(MONITOR.WINDOW_END), "2026-10-18T15:47:38Z")
        self.metrics["window_start"] = MONITOR.iso(MONITOR.WINDOW_START + timedelta(minutes=1))
        result = self.assess()
        self.assertEqual(result["status"], "window_mismatch")
        self.assertIsNone(result["observed_agent_accesses"])

    def test_malformed_inconsistent_or_stale_metrics_are_unknown(self):
        variants = [
            {"observed_agent_accesses": True}, {"observed_agent_accesses": 999},
            {"target_agent_accesses": 1}, {"target_reached": True},
            {"observed_at": MONITOR.iso(self.now - timedelta(minutes=6))},
            {"groups": [{"family": "rsh_cli", "requests": -1}]},
            {"groups": [{"family": "rsh_cli", "requests": True}]},
            {"groups": [{"family": "rsh_cli", "requests": 3}, {"family": "rsh_cli", "requests": 4}]},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                result = self.assess({**self.metrics, **changes})
                self.assertEqual(result["status"], "invalid_report")
                self.assertIsNone(result["observed_agent_accesses"])

    def test_monitor_reads_only_metadata_endpoints_and_preserves_unknowns(self):
        urls = []
        def reader(url):
            urls.append(url)
            return {"url": url, "ok": False, "http_status": 404, "error": "http_error"}
        result = MONITOR.collect_snapshot(reader=reader, clock=lambda: self.now)
        self.assertEqual(set(urls), set(MONITOR.ENDPOINTS.values()))
        self.assertTrue(all("/v1/search" not in url and "/mcp" not in url for url in urls))
        self.assertIsNone(result["measurement"]["observed_agent_accesses"])
        self.assertEqual(MONITOR.HEADERS["DNT"], "1")
        self.assertEqual(MONITOR.HEADERS["X-RSH-Telemetry"], "off")
        self.assertFalse(result["monitor"]["eligible_accesses_generated"])

    def test_deadline_wait_stops_at_the_original_window_end(self):
        delays = []
        MONITOR.wait_for_next(300, clock=lambda: MONITOR.WINDOW_END - timedelta(seconds=10), sleeper=delays.append)
        MONITOR.wait_for_next(300, clock=lambda: MONITOR.WINDOW_END + timedelta(seconds=10), sleeper=delays.append)
        self.assertEqual(delays, [10, 0])

    def test_snapshots_are_timestamped_and_previous_observations_are_preserved(self):
        def reader(url):
            return {"url": url, "ok": True, "http_status": 200,
                    "data": self.metrics if url.endswith("/v1/metrics") else {}}
        snapshot = MONITOR.collect_snapshot(reader=reader, clock=lambda: self.now)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            first = MONITOR.save_snapshot(snapshot, output)
            second = MONITOR.save_snapshot(snapshot, output)
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertEqual(json.loads((output / "latest.json").read_text()), snapshot)
            self.assertEqual(len(list(output.glob("*.json"))), 3)

    def test_public_reads_send_opt_out_without_authentication(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, maximum): return b'{"status":"ok"}'
        with patch.object(MONITOR.urllib.request, "urlopen", return_value=Response()) as opener:
            result = MONITOR.read_json(MONITOR.ENDPOINTS["health"])
        request = opener.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertTrue(result["ok"])
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(headers["dnt"], "1")
        self.assertEqual(headers["x-rsh-telemetry"], "off")
        self.assertNotIn("authorization", headers)


if __name__ == "__main__":
    unittest.main()
