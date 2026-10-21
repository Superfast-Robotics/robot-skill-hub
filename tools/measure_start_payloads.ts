/** Reproducible byte comparison; no model calls or token/cost extrapolation. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import assert from 'node:assert/strict';

const args = process.argv.slice(2);
const option = (name: string, fallback: string) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const site = resolve(option('--site', 'site'));
assert.ok(args.includes('--live'), 'Pass --live to measure the deployed public API; requests opt out of usage telemetry.');
const API = 'https://api.superfastrobotics.com';
const headers = { DNT: '1', 'X-RSH-Telemetry': 'off', 'User-Agent': 'robot-skill-hub/maintainer-response-check' };
const read = async (url: string) => {
  const response = await fetch(url, { headers, signal: AbortSignal.timeout(30000) });
  const raw = await response!.text();
  assert.equal(response?.status, 200, url + ': ' + (response?.status === 200 ? '' : raw));
  return { bytes: Buffer.byteLength(raw), value: JSON.parse(raw) };
};
const tasks = JSON.parse(await readFile(resolve(site, 'tasks/index.json'), 'utf8')).tasks;
const ids = [...new Set(['pythonrobotics-astar-planner', 'ruckig-offline-trajectory', 'pybullet-ik-skill', ...tasks.map((t: any) => t.skill_id)])];
const measurements = [];
for (const id of ids) {
  const query = new URLSearchParams({ q: String(id), query_mode: 'all_terms', limit: '1' });
  const full = await read(API + '/v1/start?' + query + '&detail=full');
  query.set('hub_commit', full.value.hub_commit);
  const compact = await read(API + '/v1/start?' + query);
  assert.equal(compact.value.selected.id, id);
  assert.equal(compact.value.detail, 'compact');
  assert.deepEqual(compact.value.selected.record.evidence, full.value.selected.record.evidence);
  const contract = await read(compact.value.selected.contract_url);
  for (const field of ['interface', 'invocation', 'completion', 'source', 'license', 'requirements', 'evidence'])
    assert.deepEqual(contract.value.record[field], full.value.selected.record[field], `${id}:${field}`);
  assert.ok(compact.bytes < full.bytes, String(id));
  measurements.push({ id, hub_commit: full.value.hub_commit, full_bytes: full.bytes, compact_bytes: compact.bytes,
    contract_bytes: contract.bytes, compact_plus_contract_bytes: compact.bytes + contract.bytes,
    first_response_reduction_pct: 100 * (1 - compact.bytes / full.bytes) });
}
const sum = (key: string) => measurements.reduce((n, row: any) => n + row[key], 0);
const report = { schema_version: '1', measured_at: new Date().toISOString(), mode: 'live_api',
  method: 'Exact-ID queries, all_terms, limit=1 in both modes. UTF-8 uncompressed HTTP body bytes, not tokens. Same pinned record and full evidence; full contract equality asserted.',
  limits: 'No model trials or latency claim. Compact omits full recall bodies; reading applicable recall adds bytes. Contract read is required before execution unless already held at the same pins. Historical model experiment is unchanged.',
  measurements, totals: { full_bytes: sum('full_bytes'), compact_bytes: sum('compact_bytes'), contract_bytes: sum('contract_bytes'),
    first_response_reduction_pct: 100 * (1 - sum('compact_bytes') / sum('full_bytes')),
    compact_plus_contract_reduction_pct: 100 * (1 - sum('compact_plus_contract_bytes') / sum('full_bytes')) } };
const output = resolve(option('--output', '.local/compact-agent-responses/payloads.json'));
await mkdir(dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ output, cases: measurements.length, ...report.totals }));
