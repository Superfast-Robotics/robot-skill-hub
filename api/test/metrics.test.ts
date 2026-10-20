import test from 'node:test';
import assert from 'node:assert/strict';
import { accessFamily, measure, measurementReport, pruneMeasurements, recordAccess, type MetricsEnv, type Statement } from '../src/metrics.ts';
import { createPublicHandler } from '../src/public.ts';
import { createHash } from 'node:crypto';

const NOW = Date.parse('2026-10-18T12:00:00Z'), START = Date.parse('2026-10-17T15:47:38Z');
type Event = { ts: number; route: string; family: string; client_hash: string | null; channel?: string | null };
class Database {
  events: Event[] = []; queries: { sql: string; values: unknown[] }[] = []; fail = false;
  prepare(sql: string): Statement {
    const database = this; let values: unknown[] = [];
    return { bind(...input: unknown[]) { values = input; return this; }, async run() {
      database.queries.push({ sql, values }); if (database.fail) throw Error('Synthetic database failure');
      if (sql.startsWith('INSERT')) database.events.push({ ts: Number(values[0]), route: String(values[1]), family: String(values[2]), client_hash: values[3] as string | null, channel: values[4] as string | null });
      else if (sql.startsWith('DELETE')) {
        const expired = database.events.filter(event => event.ts < Number(values[0])).slice(0, 1000);
        database.events = database.events.filter(event => !expired.includes(event));
      }
      return {};
    }, async all<T>() {
      database.queries.push({ sql, values }); if (database.fail) throw Error('Synthetic database failure');
      const groups = new Map<string, Event[]>(), channelQuery = sql.includes('GROUP BY channel');
      for (const event of database.events.filter(event => event.ts >= Number(values[0]) && event.ts < Number(values[1]))) {
        const key = channelQuery ? JSON.stringify([event.channel ?? null, event.route, event.family]) : event.family;
        groups.set(key, [...(groups.get(key) || []), event]);
      }
      return { results: [...groups.entries()].map(([key, events]) => channelQuery
        ? { channel: events[0].channel ?? null, route: events[0].route, family: events[0].family, requests: events.length }
        : { family: key, requests: events.length, identified_client_days: new Set(events.map(event => event.client_hash).filter(Boolean)).size }) as T[] };
    } };
  }
}
function setup() {
  const database = new Database();
  const env: MetricsEnv = { METRICS: database, METRICS_KEY: 'test-HMAC-secret-never-persist', METRICS_TEST_KEY: 'internal-validation-key', CAMPAIGN_STARTED_AT: new Date(START).toISOString() };
  return { database, env };
}
const request = (ua = 'robot-skill-hub/0.2', headers: Record<string, string> = {}) => new Request('https://api.superfastrobotics.com/v1/search?q=private-task-description', { headers: { 'User-Agent': ua, ...headers } });

test('classification keeps crawlers and unknown clients separate from recognized agent traffic', () => {
  assert.equal(accessFamily(request()), 'rsh_cli'); assert.equal(accessFamily(request('Codex/1.0')), 'recognized_agent');
  assert.equal(accessFamily(request('Claude-Code/2.0')), 'recognized_agent'); assert.equal(accessFamily(request('Mozilla/5.0')), 'unclassified');
  assert.equal(accessFamily(request('Googlebot')), 'crawler'); assert.equal(accessFamily(request('Googlebot'), true), 'crawler');
  assert.equal(accessFamily(request('MCP SDK client'), true), 'mcp_tool');
  assert.equal(accessFamily(request('Codex', { DNT: '1' }), true), null); assert.equal(accessFamily(request('Codex', { 'X-RSH-Telemetry': 'off' })), null);
});

test('stored measurements contain only aggregate fields and a daily keyed client pseudonym', async () => {
  const s = setup();
  const req = request('Codex', { 'X-RSH-Client': 'installation_private_123', 'CF-Connecting-IP': '192.0.2.123', 'X-Forwarded-For': '192.0.2.124' });
  await recordAccess(req, s.env, 'search', false, NOW); await recordAccess(req, s.env, 'inspect', false, NOW);
  assert.equal(s.database.events.length, 2); const first = s.database.events[0]; assert.match(first.client_hash!, /^[a-f0-9]{64}$/);
  assert.equal(s.database.events[1].client_hash, first.client_hash);
  await recordAccess(req, s.env, 'search', false, NOW + 86400000); assert.notEqual(s.database.events[2].client_hash, first.client_hash);
  const stored = JSON.stringify(s.database.queries);
  for (const secret of ['private-task-description', 'installation_private_123', '192.0.2.123', '192.0.2.124', s.env.METRICS_KEY!, 'Codex']) assert.ok(!stored.includes(secret));
});

test('opt-outs, internal validation keys and missing configuration do not create rows', async () => {
  const s = setup();
  const scopes: Record<string, string>[] = [{ DNT: '1' }, { 'X-RSH-Telemetry': 'off' }, { 'X-RSH-Test-Key': 'internal-validation-key' }];
  for (const headers of scopes) await recordAccess(request('Codex', headers), s.env, 'search', false, NOW);
  await recordAccess(request(), { METRICS: s.database }, 'search', false, NOW);
  await recordAccess(request(), { METRICS_KEY: 'configured-without-db' }, 'search', false, NOW);
  assert.equal(s.database.events.length, 0); assert.equal(s.database.queries.length, 0);
});

test('missing or malformed client IDs never trigger IP-derived identity fallback', async () => {
  const s = setup();
  for (const client of [undefined, 'x', 'x'.repeat(81), 'contains spaces']) await recordAccess(request('Codex', { 'CF-Connecting-IP': '192.0.2.10', ...(client ? { 'X-RSH-Client': client } : {}) }), s.env, 'search', false, NOW);
  assert.ok(s.database.events.every(event => event.client_hash === null));
});

test('campaign totals use the exact 24-hour window and only eligible request families', async () => {
  const s = setup(); const start = Math.floor(START / 1000), deadline = start + 86400;
  const add = (family: string, ts = start + 100) => s.database.events.push({ ts, route: 'search', family, client_hash: null });
  for (let n = 0; n < 98; n++) add('rsh_cli'); add('recognized_agent');
  for (let n = 0; n < 200; n++) { add('crawler'); add('unclassified'); }
  add('mcp_tool', start - 1); add('recognized_agent', deadline); add('rsh_cli', deadline + 1);
  let report = await measurementReport(s.env, NOW); assert.equal(report.observed_agent_accesses, 99); assert.equal(report.target_reached, false); assert.equal(report.window_closed, false);
  add('mcp_tool'); report = await measurementReport(s.env, NOW); assert.equal(report.observed_agent_accesses, 100); assert.equal(report.target_reached, false);
  for (let n = 0; n < 9899; n++) add('rsh_cli');
  report = await measurementReport(s.env, NOW); assert.equal(report.observed_agent_accesses, 9999); assert.equal(report.target_reached, false); assert.equal(report.target_agent_accesses, 10000);
  add('mcp_tool'); report = await measurementReport(s.env, NOW); assert.equal(report.observed_agent_accesses, 10000); assert.equal(report.target_reached, true);
  report = await measurementReport(s.env, START + 86400000 + 5000); assert.equal(report.observed_agent_accesses, 10000); assert.equal(report.target_reached, true); assert.equal(report.window_closed, true);
  assert.equal(report.window_start, '2026-10-17T15:47:38.000Z'); assert.equal(report.window_end, '2026-10-18T15:47:38.000Z');
  assert.equal(Date.parse(report.window_end) - Date.parse(report.window_start), 86400000);
  const absent = await measurementReport({}, NOW); assert.equal(absent.observed_agent_accesses, null); assert.equal(absent.target_reached, false); assert.equal(absent.measurement_configured, false);
});

test('optional database failures cannot block public discovery reads or background scheduling', async () => {
  const s = setup(); s.database.fail = true;
  await measure(request(), s.env, 'search');
  const pending: Promise<unknown>[] = []; await measure(request(), s.env, 'search', { waitUntil(promise) { pending.push(promise); } });
  await Promise.all(pending);
  const search = JSON.stringify({ schema_version: '1', hub_commit: 'a'.repeat(40), records: [] });
  const handler = createPublicHandler(async input => Response.json(new URL(String(input)).pathname.endsWith('version.json')
    ? { schema_version: '1', hub_commit: 'a'.repeat(40), resources: { search: { sha256: createHash('sha256').update(search).digest('hex') } } }
    : JSON.parse(search)));
  const response = await handler(request(), { ...s.env, PUBLICATION_URL: 'https://hub.superfastrobotics.com/catalog/v1/publication.json' });
  assert.equal(response!.status, 200); assert.equal((await response!.json() as any).total, 0);
});

test('retention cleanup deletes bounded batches older than 30 days', async () => {
  const s = setup(); const cutoff = Math.floor(NOW / 1000) - 30 * 86400;
  for (let n = 0; n < 1500; n++) s.database.events.push({ ts: cutoff - 1, route: 'search', family: 'rsh_cli', client_hash: null });
  s.database.events.push({ ts: cutoff, route: 'inspect', family: 'rsh_cli', client_hash: null });
  await pruneMeasurements(s.env, NOW); assert.equal(s.database.events.length, 501); assert.match(s.database.queries[0].sql, /LIMIT 1000/);
  await pruneMeasurements(s.env, NOW); assert.equal(s.database.events.length, 1); assert.equal(s.database.events[0].ts, cutoff);
});

test('channel attribution keeps fixed labels and rejects free-text referrals without changing opt-outs', async () => {
  const s = setup();
  await recordAccess(request('robot-skill-hub/task-skill-v1', { 'X-RSH-Channel': 'task-planning' }), s.env, 'search', false, NOW);
  await recordAccess(request('Codex', { 'X-RSH-Channel': 'private-company-project' }), s.env, 'inspect', false, NOW);
  await recordAccess(request('Codex', { 'X-RSH-Channel': 'rai-example', DNT: '1' }), s.env, 'search', false, NOW);
  assert.equal(s.database.events.length, 2);
  assert.equal(s.database.events[0].channel, 'task-planning'); assert.equal(s.database.events[1].channel, null);
  assert.ok(!JSON.stringify(s.database.queries).includes('private-company-project'));
});

test('rolling and retained reports include later events without redefining the launch result', async () => {
  const s = setup(), later = START + 10 * 86400000;
  s.database.events.push({ ts: START / 1000 + 100, route: 'search', family: 'rsh_cli', client_hash: 'day-one' });
  s.database.events.push({ ts: later / 1000 - 60, route: 'inspect', family: 'mcp_tool', client_hash: null, channel: 'rai-example' });
  s.database.events.push({ ts: later / 1000 - 30, route: 'search', family: 'crawler', client_hash: null });
  const launch = await measurementReport(s.env, later); assert.equal(launch.observed_agent_accesses, 1);
  const week = await measurementReport(s.env, later, '7d'); assert.equal(week.observed_agent_accesses, 1);
  assert.equal(week.window_start, new Date(later - 7 * 86400000).toISOString());
  assert.ok('channels' in week && week.channels?.some((r: any) => r.channel === 'rai-example' && r.requests === 1));
  const retained = await measurementReport(s.env, later, 'retained'); assert.equal(retained.observed_agent_accesses, 2);
  assert.equal(retained.lifetime_total_available, false);
  const future = await measurementReport(s.env, START + 60 * 86400000, 'retained');
  assert.equal(future.window_start, new Date(START + 30 * 86400000).toISOString());
});

test('public metrics validates windows and bounds repeat database reads with a short cache', async () => {
  const s = setup(); let clock = NOW;
  const handler = createPublicHandler(fetch, () => clock);
  const env = { ...s.env, PUBLICATION_URL: 'https://hub.superfastrobotics.com/catalog/v1/publication.json' };
  for (const suffix of ['?window=forever', '?window=7d&query=private']) {
    assert.equal((await handler(new Request('https://api.superfastrobotics.com/v1/metrics' + suffix), env))!.status, 400);
  }
  const request = () => new Request('https://api.superfastrobotics.com/v1/metrics?window=7d');
  assert.equal((await handler(request(), env))!.status, 200); const count = s.database.queries.length;
  await handler(request(), env); assert.equal(s.database.queries.length, count);
  clock += 60001; await handler(request(), env); assert.ok(s.database.queries.length > count);
});
