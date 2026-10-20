import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Miniflare } from 'miniflare';
import { measurementReport, recordAccess, type MetricsEnv } from '../../src/metrics.ts';

test('native metrics migration preserves historical data and separates fixed, rolling and attributed reads', async () => {
  const mf = new Miniflare({ telemetry: { enabled: false }, workers: [{ config: {
    name: 'metrics-native-test', compatibilityDate: '2026-10-17',
    manifest: { mainModule: 'worker.js', modules: { 'worker.js': { type: 'esm', contents: 'export default {fetch(){return new Response("ok")}}' } } },
    env: { METRICS: { type: 'd1', id: 'metrics-native-test' } }
  } }] });
  try {
    const db = await mf.getD1Database('METRICS');
    await db.exec((await readFile(new URL('../../migrations/0001_agent_access.sql', import.meta.url), 'utf8')).replace(/--[^\n]*/g, '').replace(/\s+/g, ' '));
    const start = Date.parse('2026-10-17T15:47:38Z'), now = start + 10 * 86400000;
    await db.prepare('INSERT INTO agent_access(ts,route,family,client_hash) VALUES(?,?,?,?)').bind(start / 1000 + 30, 'search', 'rsh_cli', 'old-day').run();
    await db.exec((await readFile(new URL('../../migrations/0002_access_channels.sql', import.meta.url), 'utf8')).replace(/--[^\n]*/g, '').replace(/\s+/g, ' '));
    const env: MetricsEnv = { METRICS: db as unknown as MetricsEnv['METRICS'], METRICS_KEY: 'local-test-key', CAMPAIGN_STARTED_AT: new Date(start).toISOString() };
    await recordAccess(new Request('https://api.example.invalid/v1/search', { headers: { 'User-Agent': 'robot-skill-hub/task-skill-v1', 'X-RSH-Channel': 'task-trajectory' } }), env, 'search', false, now - 1000);
    const historical = await db.prepare('SELECT channel FROM agent_access WHERE client_hash=?').bind('old-day').first();
    assert.equal(historical!.channel, null);
    assert.equal((await measurementReport(env, now)).observed_agent_accesses, 1);
    const week = await measurementReport(env, now, '7d'); assert.equal(week.observed_agent_accesses, 1);
    assert.deepEqual(week.channels, [{ channel: 'task-trajectory', route: 'search', family: 'rsh_cli', requests: 1 }]);
    const retained = await measurementReport(env, now, 'retained'); assert.equal(retained.observed_agent_accesses, 2);
    await assert.rejects(db.prepare('INSERT INTO agent_access(ts,route,family,channel) VALUES(?,?,?,?)').bind(now / 1000, 'search', 'rsh_cli', 'private-referral-text').run());
  } finally { await mf.dispose(); }
});
