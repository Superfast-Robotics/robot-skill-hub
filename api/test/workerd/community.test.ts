import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { Miniflare } from 'miniflare';
import { canonical } from '../../src/util.ts';

const hash = (v: string) => createHash('sha256').update(v).digest('hex');
const base = { hub_commit: 'a'.repeat(40), record_version: '1.0.0', source_commit: 'b'.repeat(40) };
const finding = (n = 0): any => ({ schema_version: '1', skill_id: 'fixture-pick', base, kind: 'working_workaround',
  summary: 'Use the explicit CPU backend ' + n, observation: 'The selected simulator requires the explicit CPU backend in this environment.',
  resolution: 'Pass the documented CPU backend argument.', environment: { runtime: 'maniskill', robot: 'panda', 'package.mesa': '23.2.1' },
  evidence: { level: 'contributor_reported', command: null, result: 'Fixture observation only; no actual simulator run.', reported_by: 'submitter' },
  attribution: { contributor_label: 'test fixture', preserve_upstream_attribution: true }, publication: { public_submission_allowed: true } });
async function runtime() {
  const script = (await build({ entryPoints: [fileURLToPath(new URL('../../src/index.ts', import.meta.url))], bundle: true, write: false, platform: 'browser', format: 'esm', target: 'es2023' })).outputFiles![0].text;
  const mf = new Miniflare({ telemetry: { enabled: false }, workers: [{ config: { name: 'community-test', compatibilityDate: '2026-10-17',
    manifest: { mainModule: 'worker.js', modules: { 'worker.js': { type: 'esm', contents: script } } },
    env: { CATALOG: { type: 'd1', id: 'community-test' }, METRICS_KEY: { type: 'text', value: 'local-community-test-key' },
      PUBLICATION_URL: { type: 'text', value: 'https://hub.superfastrobotics.com/catalog/v1/publication.json' } } } }] });
  const db = await mf.getD1Database('CATALOG');
  for (const name of ['0001_catalog.sql', '0002_page_memberships.sql', '0003_community.sql']) {
    const sql = await readFile(new URL('../../migrations-catalog/' + name, import.meta.url), 'utf8');
    await db.exec(sql.replace(/--[^\n]*/g, '').replace(/\s+/g, ' '));
  }
  await db.prepare('INSERT INTO catalog_generations(hub_commit,manifest_sha256,manifest_json,total_pages,total_records,created_at) VALUES(?,?,?,?,?,?)').bind(base.hub_commit, '0'.repeat(64), '{}', 1, 1, 1).run();
  const row = { id: 'fixture-pick', kind: 'preparation_recipe', record_version: base.record_version, source_commit: base.source_commit, license: { spdx: 'Apache-2.0' } };
  await db.prepare('INSERT INTO catalog_documents(doc_hash,id,kind,row_json,search_text) VALUES(?,?,?,?,?)').bind('d'.repeat(64), row.id, row.kind, JSON.stringify(row), 'fixture').run();
  await db.prepare('INSERT INTO catalog_members(hub_commit,id,doc_hash) VALUES(?,?,?)').bind(base.hub_commit, row.id, 'd'.repeat(64)).run();
  async function call(path: string, value?: any, token?: string, ip = '192.0.2.1') {
    const response = await mf.dispatchFetch('https://api.example.invalid/v1/community' + path, { method: value === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', 'CF-Connecting-IP': ip, DNT: '1', 'X-RSH-Telemetry': 'off', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
      ...(value === undefined ? {} : { body: JSON.stringify(value) }) });
    return { status: response.status, body: await response.json() as any };
  }
  async function enroll(ip = '192.0.2.1') {
    const token = 'csh_' + randomBytes(32).toString('base64url');
    const challenge = (await call('/challenge', undefined, undefined, ip)).body.challenge;
    let nonce = 0; while (!hash(challenge + '.' + hash(token) + '.' + nonce).startsWith('0000')) nonce++;
    const payload = { token, challenge, nonce: String(nonce) };
    const result = await call('/enroll', payload, undefined, ip);
    return { token, result, payload };
  }
  const query = (extra: Record<string, string> = {}) => '/items?' + new URLSearchParams({ skill_id: 'fixture-pick', record_version: base.record_version, source_commit: base.source_commit, ...extra });
  return { mf, db, call, enroll, query };
}

test('native self-service enrollment, immutable global dedup, exact recall, variants and outcome graph', async () => {
  const s = await runtime(); try {
    const a = await s.enroll(), b = await s.enroll();
    assert.equal(a.result.status, 201, JSON.stringify(a.result));
    assert.equal((await s.call('/enroll', a.payload)).body.replay, true);
    const value = { schema_version: '1', finding: finding() };
    assert.equal((await s.call('/items', value)).status, 401);
    const posted = await s.call('/items', value, a.token);
    assert.equal(posted.status, 201, JSON.stringify(posted));
    const id = posted.body.id;
    const repeats = await Promise.all(Array.from({ length: 4 }, () => s.call('/items', value, a.token)));
    assert.ok(repeats.every(r => r.status === 200 && r.body.id === id));
    value.finding.attribution.contributor_label = 'other installation';
    assert.equal((await s.call('/items', value, b.token)).body.id, id);
    const detail = await s.call('/items/' + id);
    assert.equal(detail.body.attestations.installations, 2);
    assert.equal(detail.body.attestations.independent_agents_verified, false);
    assert.equal(detail.body.content.finding.attribution.contributor_label, 'test fixture');
    const selected = await s.call(s.query({ environment: JSON.stringify({ 'package.mesa': '23.2.1', robot: 'PANDA' }) }));
    assert.equal(selected.body.results.length, 1);
    assert.equal(selected.body.results[0].content, undefined, 'selection is bounded summary data');
    assert.equal((await s.call(s.query({ environment: JSON.stringify({ 'package.mesa': 'other' }) }))).body.results.length, 0);
    assert.equal((await s.call(s.query({ source_commit: 'c'.repeat(40) }))).body.results.length, 0);
    const variant = await s.call('/items', { schema_version: '1', finding: finding(1), parent_id: id,
      variant: { patch: '--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-backend = None\n+backend = "cpu"\n', license_spdx: 'Apache-2.0' } }, a.token);
    assert.equal(variant.status, 201, JSON.stringify(variant));
    assert.equal(variant.body.kind, 'variant');
    const report = await s.call('/items', { schema_version: '1', finding: finding(2), parent_id: variant.body.id, outcome: 'failed' }, b.token);
    assert.equal(report.status, 201, JSON.stringify(report));
    assert.equal(report.body.kind, 'reuse_report');
    const descendants = await s.call(s.query({ parent_id: variant.body.id }));
    assert.equal(descendants.body.results[0].outcome, 'failed');
    const choices = await s.call(s.query());
    assert.equal(choices.body.results[0].id, variant.body.id, 'new variants are discoverable before older observations');
    assert.equal(choices.body.results[0].reuse_reports.failed, 1);
    assert.ok(choices.body.results.every((r: any) => r.kind !== 'reuse_report'), 'reports annotate candidates instead of crowding them out');
    const exportPage = await s.call('/export');
    assert.equal(exportPage.body.rows.length, 3);
    assert.equal(JSON.stringify(exportPage.body).includes(a.token), false);
    assert.equal(exportPage.body.rows[0].content_sha256, hash(canonical(exportPage.body.rows[0].content)));
  } finally { await s.mf.dispose(); }
});

test('native enrollment proof, source/secret/parent checks and quota rollback do not corrupt immutable data', async () => {
  const s = await runtime(); try {
    const a = await s.enroll();
    const invalid = { ...a.payload, token: 'csh_' + randomBytes(32).toString('base64url') };
    assert.equal((await s.call('/enroll', invalid, undefined, '192.0.2.2')).status, 403);
    const bad = { schema_version: '1', finding: { ...finding(), base: { ...base, source_commit: 'c'.repeat(40) } } };
    assert.equal((await s.call('/items', bad, a.token)).status, 409);
    assert.equal((await s.call('/items', { schema_version: '1', finding: { ...finding(), observation: 'Token ' + a.token } }, a.token)).status, 422);
    assert.equal((await s.call('/items', { schema_version: '1', finding: finding(), parent_id: 'exp_' + 'f'.repeat(64), outcome: 'succeeded' }, a.token)).status, 409);
    assert.equal((await s.call('/items', { schema_version: '1', finding: finding(), variant: { patch: '--- a/AGENTS.md\n+++ b/AGENTS.md\n@@ -1 +1 @@\n-a\n+b', license_spdx: 'MIT' } }, a.token)).status, 422);
    assert.equal((await s.call('/items', { schema_version: '1', finding: finding(), variant: { patch: '--- a/demo.py\n+++ b/demo.py\n@@ -1,99 +1 @@\n-a\n+b\n', license_spdx: 'Apache-2.0' } }, a.token)).status, 422, 'a header-shaped fake patch is rejected');
    assert.equal((await s.call('/items', { schema_version: '1', finding: finding(), variant: { patch: '--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-a\n+b\n', license_spdx: 'MIT' } }, a.token)).status, 422, 'upstream license cannot be relabeled');
    const value = { schema_version: '1', finding: finding() };
    const first = await s.call('/items', value, a.token);
    for (let i = 1; i < 20; i++) assert.equal((await s.call('/items', { schema_version: '1', finding: finding(i) }, a.token)).status, 201);
    const page = await s.call(s.query({ limit: '2' }));
    assert.equal(page.body.complete, false);
    const blocked = await s.call('/items', { schema_version: '1', finding: finding(20) }, a.token);
    assert.equal(blocked.status, 429, JSON.stringify(blocked));
    assert.equal((await s.db.prepare('SELECT count(*) n FROM community_items').first<any>()).n, 20, 'quota failure rolls back item and budget together');
    assert.equal((await s.call('/items', value, a.token)).body.id, first.body.id, 'quota does not reject idempotent retries');
    const next = await s.call(s.query({ limit: '2', after: String(page.body.next_after), through: String(page.body.through) }));
    assert.ok(next.body.results.every((r: any) => r.sequence < page.body.next_after));
    assert.equal((await s.db.prepare('SELECT items FROM community_storage_budget').first<any>()).items, 20);
  } finally { await s.mf.dispose(); }
});
