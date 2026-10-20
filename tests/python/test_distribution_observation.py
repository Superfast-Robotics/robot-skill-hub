import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from observe_distribution import validate


class DistributionObservationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
        self.value = {'ok': True, 'data': {'measurement_configured': True, 'window_kind': '7d',
            'retention_days': 30, 'lifetime_total_available': False,
            'window_start': (self.now - timedelta(days=7)).isoformat(),
            'window_end': (self.now - timedelta(seconds=1)).isoformat(), 'observed_at': self.now.isoformat(),
            'observed_agent_accesses': 5,
            'groups': [{'family': 'rsh_cli', 'requests': 3, 'identified_client_days': 1},
                       {'family': 'mcp_tool', 'requests': 2, 'identified_client_days': 0}],
            'channels': [{'channel': 'task-planning', 'route': 'search', 'family': 'rsh_cli', 'requests': 3},
                         {'channel': None, 'route': 'mcp', 'family': 'mcp_tool', 'requests': 2}],
            'unexpected_field': 'not-persisted'}}

    def test_records_only_bounded_aggregates_and_not_users(self):
        result = validate(self.value, '7d', self.now)
        self.assertEqual(result['eligible_requests'], 5)
        self.assertNotIn('unexpected_field', result)
        self.assertNotIn('unique_users', result)

    def test_rejects_channel_family_mismatch_even_with_matching_total(self):
        self.value['data']['channels'][0]['requests'] = 2
        self.value['data']['channels'][1]['requests'] = 3
        with self.assertRaisesRegex(ValueError, 'disagree'):
            validate(self.value, '7d', self.now)

    def test_rejects_stale_reports_and_arbitrary_channel_values(self):
        stale = copy.deepcopy(self.value)
        stale['data']['observed_at'] = (self.now - timedelta(hours=1)).isoformat()
        with self.assertRaisesRegex(ValueError, 'stale'):
            validate(stale, '7d', self.now)
        self.value['data']['channels'][0]['channel'] = 'private-project-name'
        with self.assertRaisesRegex(ValueError, 'channel'):
            validate(self.value, '7d', self.now)

    def test_allows_small_server_clock_skew_but_not_a_future_window(self):
        self.value['data']['window_start'] = (self.now - timedelta(days=1)).isoformat()
        self.value['data']['window_end'] = (self.now + timedelta(seconds=5)).isoformat()
        self.value['data']['observed_at'] = self.value['data']['window_end']
        self.assertEqual(validate(self.value, '7d', self.now)['eligible_requests'], 5)
        self.value['data']['window_end'] = (self.now + timedelta(seconds=31)).isoformat()
        with self.assertRaisesRegex(ValueError, 'window'):
            validate(self.value, '7d', self.now)


if __name__ == '__main__': unittest.main()
