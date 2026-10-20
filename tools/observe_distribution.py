"""Read rolling access aggregates once, without creating measured Hub traffic."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from monitor_campaign import read_json, parse_time, eligible_count

API = 'https://api.superfastrobotics.com/v1/metrics'
FAMILIES = {'rsh_cli', 'recognized_agent', 'mcp_tool', 'crawler', 'unclassified'}
CHANNELS = {'task-planning', 'task-kinematics', 'task-trajectory', 'ros-mcp-example',
            'rai-example', 'hf-space', 'problem-case', 'agent-pilot'}
ROUTES = {'search', 'inspect', 'catalog', 'references', 'mcp'}


def validate(result, window, now):
    if not result.get('ok'): raise ValueError('Rolling metrics unavailable')
    value = result['data']
    start, end, observed = (parse_time(value.get(k)) for k in ['window_start', 'window_end', 'observed_at'])
    if not (value.get('measurement_configured') is True and value.get('window_kind') == window
            and value.get('retention_days') == 30 and value.get('lifetime_total_available') is False
            and start and end and observed and start <= end and (end - now).total_seconds() <= 30
            and abs((now - observed).total_seconds()) <= 300
            and (end - start).total_seconds() <= (7 if window == '7d' else 30) * 86400 + 1):
        raise ValueError('Invalid or stale rolling metrics window')
    groups, channels = value.get('groups'), value.get('channels')
    expected = eligible_count(groups)
    if expected is None or type(value.get('observed_agent_accesses')) is not int or expected != value['observed_agent_accesses']:
        raise ValueError('Eligible request total does not match client-family groups')
    clean_groups = []
    for row in groups:
        if row['family'] not in FAMILIES or type(row.get('identified_client_days')) is not int or row['identified_client_days'] < 0:
            raise ValueError('Invalid bounded family aggregate')
        clean_groups.append({k: row[k] for k in ['family', 'requests', 'identified_client_days']})
    if not isinstance(channels, list) or len(channels) > 9 * len(FAMILIES) * len(ROUTES):
        raise ValueError('Invalid channel aggregate cardinality')
    clean_channels, seen = [], set()
    for row in channels:
        key = (row.get('channel'), row.get('route'), row.get('family'))
        if (key in seen or key[0] not in CHANNELS | {None} or key[1] not in ROUTES or key[2] not in FAMILIES
                or type(row.get('requests')) is not int or row['requests'] < 0):
            raise ValueError('Invalid bounded channel aggregate')
        seen.add(key); clean_channels.append({k: row[k] for k in ['channel', 'route', 'family', 'requests']})
    for row in clean_groups:
        if sum(c['requests'] for c in clean_channels if c['family'] == row['family']) != row['requests']:
            raise ValueError('Channel and family aggregates disagree')
    if any(c['family'] not in {g['family'] for g in clean_groups} for c in clean_channels):
        raise ValueError('Channel aggregate has no matching family')
    return {'window_start': value['window_start'], 'window_end': value['window_end'],
            'api_observed_at': value['observed_at'], 'eligible_requests': expected,
            'all_requests': sum(g['requests'] for g in clean_groups), 'groups': clean_groups,
            'channels': clean_channels}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); reports = {}
    for window in ['7d', 'retained']:
        result = read_json(API + '?window=' + window)
        reports[window] = validate(result, window, datetime.now(timezone.utc))
    now = datetime.now(timezone.utc)
    value = {'schema_version': '1', 'observed_at': now.isoformat(), 'source': API, 'reports': reports,
             'maintainer_requests_opted_out': True, 'retention_days': 30,
             'limits': ['Requests are not visitors, independent agents or successful tasks.',
                        'Channels are optional self-reported labels; historical rows are unattributed.',
                        'Client-days cannot measure returning users. Pages and offline use are unobserved.',
                        'Rolling snapshots overlap; do not sum them into lifetime users or visits.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'recorded', 'eligible_requests_7d': reports['7d']['eligible_requests'],
                      'retained_requests': reports['retained']['all_requests'], 'unique_users_measured': False}))


if __name__ == '__main__': main()
