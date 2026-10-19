"""Measure CLI text serialization only; never infer task cost or model accuracy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/find-robot-skills'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline-cli', type=Path, help='Optional checkout of the exact baseline rsh.py for direct output equality checks')
    args = parser.parse_args()
    import tiktoken  # Optional benchmark dependency; the CLI itself has no dependency.
    plan_raw = (ROOT / 'benchmarks/reuse/plan.json').read_bytes()
    plan = json.loads(plan_raw)
    snapshot = SKILL / 'assets/catalog.snapshot.json'
    raw = snapshot.read_bytes()
    records = sorted(json.loads(raw)['records'], key=lambda row: row['id'])
    assert len(records) == plan['case_count'], 'Changed catalog needs a new declared benchmark plan.'
    encodings = {name: tiktoken.get_encoding(name) for name in (plan['primary_encoding'], plan['sensitivity_encoding'])}
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    with tempfile.TemporaryDirectory(prefix='rsh-token-benchmark-') as cache:
        env = {**os.environ, 'PYTHONUTF8': '1', 'RSH_TELEMETRY': 'off', 'RSH_CACHE_DIR': cache}
        for record in records:
            suffix = ['inspect', record['id'], '--catalog', str(snapshot), '--offline', '--json']
            compact = subprocess.check_output([sys.executable, '-X', 'utf8', str(SKILL / 'scripts/rsh.py'), *suffix], env=env, timeout=30)
            result = json.loads(compact)
            assert result['status'] == 'ready'
            # Normalize platform line endings; both representations end in one newline.
            compact_text = compact.decode('utf-8').replace('\r\n', '\n')
            assert compact_text == json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n'
            pretty_text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
            if args.baseline_cli:
                previous = subprocess.check_output([sys.executable, '-X', 'utf8', str(args.baseline_cli), *suffix], env=env, timeout=30).decode('utf-8').replace('\r\n', '\n')
                assert previous == pretty_text, 'Baseline CLI must emit the identical object in the previous format.'
            assert json.loads(pretty_text) == json.loads(compact_text)
            stem = record['id']
            (args.output / (stem + '.pretty.json')).write_bytes(pretty_text.encode('utf-8'))
            (args.output / (stem + '.compact.json')).write_bytes(compact_text.encode('utf-8'))
            counts = {}
            for name, encoding in encodings.items():
                before, after = len(encoding.encode(pretty_text)), len(encoding.encode(compact_text))
                counts[name] = {'before': before, 'after': after, 'reduction_percent': 100 * (1 - after / before)}
            rows.append({'id': stem, 'identical_information': True, 'pretty_sha256': digest(pretty_text.encode('utf-8')),
                         'compact_sha256': digest(compact_text.encode('utf-8')), 'tokens': counts})
    summary = {}
    for name in encodings:
        before = sum(row['tokens'][name]['before'] for row in rows)
        after = sum(row['tokens'][name]['after'] for row in rows)
        reductions = [row['tokens'][name]['reduction_percent'] for row in rows]
        summary[name] = {'before': before, 'after': after, 'aggregate_reduction_percent': 100 * (1 - after / before),
                         'median_reduction_percent': statistics.median(reductions),
                         'min_reduction_percent': min(reductions), 'max_reduction_percent': max(reductions)}
    receipt = {'schema_version': '1', 'plan_sha256': digest(plan_raw), 'snapshot_sha256': digest(raw),
               'tiktoken_version': tiktoken.__version__, 'actual_baseline_cli_checked': bool(args.baseline_cli),
               'cases': rows, 'summary': summary, 'llm_calls': 0, 'total_task_token_savings_measured': False,
               'billing_savings_measured': False, 'robot_execution': False}
    (args.output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'cases': len(rows), 'summary': summary, 'actual_baseline_cli_checked': bool(args.baseline_cli)}))


if __name__ == '__main__':
    main()
