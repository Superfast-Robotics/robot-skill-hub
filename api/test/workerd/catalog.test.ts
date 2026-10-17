import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { build } from 'esbuild';
import { Miniflare, Request as RuntimeRequest, Response as RuntimeResponse } from 'miniflare';

const ORIGIN = 'https://hub.superfastrobotics.com', API = 'https://api.example.invalid';
const KEY = 'local-native-catalog-sync-credential';
const hash = (text: string) => createHash('sha256').update(text).digest('hex');
const bundle = build({ entryPoints: [fileURLToPath(new URL('../../src/index.ts', import.meta.url))], bundle: true, write: false, platform: 'browser', format: 'esm', target: 'es2023' }).then(result => result.outputFiles![0].text);
const schema = readFile(new URL('../../migrations-catalog/0001_catalog.sql', import.meta.url), 'utf8');
function publication(commit: string, options: { duplicate?: boolean; wrongPageHash?: boolean; maliciousPath?: boolean; records?: number; memories?: number; invalidRow?: Record<string, unknown>; humanoid?: boolean } = {}) {
  const count = options.records ?? 3;
  const full = Array.from({ length: count }, (_, index) => ({ id: index === 0 ? 'maniskill-panda-pick-cube' : index === 1 ? options.humanoid ? 'h1-locomotion' : 'kuka-grasp' : 'source-' + index, access: { hub_prepare: index === 0 }, source: { commit: 'b'.repeat(40), sha256: 'c'.repeat(64) } }));
  const combos = [{ runtime: 'maniskill', runtime_version: '3.0', robot: 'panda', controller: 'pd_joint_pos', observation: 'state', os: 'linux', python: '3.10', architecture: 'x86_64' }, { runtime: 'ros2', runtime_version: 'humble', robot: 'ur5', controller: 'torque', observation: 'rgb', os: 'windows' }];
  const rows = full.map((record, index) => ({ id: record.id, name: index === 0 ? 'PickCube-v1' : index === 1 ? options.humanoid ? 'H1 locomotion' : 'KUKA iiwa grasp' : 'Source ' + index, summary: 'Pinned source for pick cube and robot grasp', kind: index === 0 ? 'preparation_recipe' : 'source_reference', hub_prepare: index === 0, record_version: index === 0 ? '1.0.0' : 'source-' + 'c'.repeat(64), record_sha256: hash(JSON.stringify(record)), source_sha256: 'c'.repeat(64), source_commit: 'b'.repeat(40), record_url: ORIGIN + (index === 0 ? '/skills/' : '/references/') + record.id + '/skill.json', capabilities: options.humanoid && index === 1 ? ['locomotion'] : ['pick cube'], aliases: [], runtime: index === 0 ? 'maniskill' : options.humanoid && index === 1 ? 'isaaclab' : 'ros2', framework: options.humanoid && index === 1 ? 'isaaclab' : 'maniskill', robots: [index === 1 ? options.humanoid ? 'h1' : 'kuka_iiwa' : 'panda'], ...(options.humanoid && index === 1 ? { robot_types: ['humanoid'] } : {}), compatibility: index === 0 ? combos : [], ...(index === 0 ? { python_requirement: '>=3.10,<3.12' } : {}) }));
  if (options.invalidRow) Object.assign(rows[1], options.invalidRow);
  const memories = Array.from({ length: options.memories ?? 1 }, (_, i) => ({ schema_version: '1', memory_id: 'mem_' + String(i + 1).repeat(64), skill_id: rows[0]?.id ?? 'absent-skill', base: { record_version: '1.0.0', source_commit: 'b'.repeat(40), hub_commit: 'a'.repeat(40) }, environment: { runtime: 'maniskill', robot: i === 0 ? 'panda' : 'ur5', os: 'linux' }, fingerprint: 'd'.repeat(64), content_sha256: 'e'.repeat(64), entry_url: ORIGIN + '/memories/mem_' + String(i + 1).repeat(64) + '.json', curation: 'maintainer_merged', interpretation: 'data_only', trust: 'contributor_reported', summary: 'Contributor finding', evidence: { level: 'contributor_reported', runtime_verification: 'not_run' } }));
  const resources = new Map<string, string>();
  full.forEach((record, index) => resources.set((index === 0 ? '/skills/' : '/references/') + record.id + '/skill.json', JSON.stringify(record)));
  const pageList = (values: any[], kind: string) => {
    const descriptors: any[] = [];
    for (let start = 0; start < values.length; start += 2) {
      const index = descriptors.length, path = `catalog/v2/generations/${commit}/${kind}/${String(index).padStart(6, '0')}.json`;
      const entries = values.slice(start, start + 2);
      if (options.duplicate && kind === 'search' && index === 1) entries[0] = values[0];
      const body = JSON.stringify({ schema_version: '2', hub_commit: commit, records: entries }); resources.set('/' + path, body);
      descriptors.push({ path: options.maliciousPath && index === 0 ? 'https://evil.invalid/x' : path, sha256: options.wrongPageHash && index === 0 ? '0'.repeat(64) : hash(body), bytes: Buffer.byteLength(body), records: entries.length });
    }
    return descriptors;
  };
  const pages = pageList(rows, 'search'), memoryPages = pageList(memories, 'memories');
  const memoryManifest = JSON.stringify({ schema_version: '2', hub_commit: commit, records: memories.length, pages: memoryPages });
  resources.set('/catalog/v2/memory-manifest.json', memoryManifest);
  const manifest = JSON.stringify({ schema_version: '2', hub_commit: commit, counts: { recipes: count ? 1 : 0, references: Math.max(0, count - 1), memories: memories.length }, records: count, pages, memory_manifest: { path: 'catalog/v2/memory-manifest.json', sha256: hash(memoryManifest), bytes: Buffer.byteLength(memoryManifest), records: memories.length } });
  resources.set('/catalog/v2/search-manifest.json', manifest);
  const version: any = { schema_version: '1', hub_commit: commit, resources: { 'search-manifest': { url: ORIGIN + '/catalog/v2/search-manifest.json', sha256: hash(manifest) }, 'memory-manifest': { url: ORIGIN + '/catalog/v2/memory-manifest.json', sha256: hash(memoryManifest) } } };
  resources.set('/catalog/v1/version.json', JSON.stringify(version));
  return { resources, rows, memories, version, full };
}
async function runtime(initial = publication('a'.repeat(40))) {
  let current = initial; const calls: string[] = [];
  const mf = new Miniflare({ telemetry: { enabled: false }, workers: [{ config: { name: 'native-catalog-test', compatibilityDate: '2026-10-17', manifest: { mainModule: 'worker.js', modules: { 'worker.js': { type: 'esm', contents: await bundle } } }, env: { CATALOG: { type: 'd1', id: 'native-catalog-test' }, CATALOG_SYNC_KEY: { type: 'text', value: KEY }, PUBLICATION_URL: { type: 'text', value: ORIGIN + '/catalog/v1/publication.json' } } }, dev: { outboundService: { type: 'fetcher', handler(request: RuntimeRequest) {
    const url = new URL(request.url); calls.push(request.url);
    assert.equal(url.origin, ORIGIN); assert.equal(request.headers.get('DNT'), '1'); assert.equal(request.headers.get('X-RSH-Telemetry'), 'off'); assert.equal(request.headers.has('Authorization'), false);
    const body = current.resources.get(url.pathname); return body === undefined ? new RuntimeResponse(null, { status: 404 }) : new RuntimeResponse(body);
  } } } }] });
  const db = await mf.getD1Database('CATALOG');
  // D1 exec accepts SQL statements, including the real FTS5 tables and triggers.
  await db.exec((await schema).replace(/--[^\n]*/g, '').replace(/\s+/g, ' '));
  const sync = (body: any = {}, key = KEY) => mf.dispatchFetch(API + '/internal/catalog-sync', { method: 'POST', headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json', DNT: '1', 'X-RSH-Telemetry': 'off' }, body: JSON.stringify(body) });
  async function complete() { for (let i = 0; i < 100; i++) { const response = await sync(), value: any = await response.json(); assert.equal(response.status, 200, JSON.stringify(value)); if (value.status === 'active') return value; } assert.fail('Sync did not finish'); }
  async function read(path: string) { const response = await mf.dispatchFetch(API + path, { headers: { DNT: '1', 'X-RSH-Telemetry': 'off' } }); return { status: response.status, body: await response.json() as any }; }
  return { mf, db, calls, sync, complete, read, set(value: ReturnType<typeof publication>) { current = value; } };
}

test('native D1 FTS stages both search and findings pages before atomically serving the matching generation', async () => {
  const published = publication('a'.repeat(40)); const s = await runtime(published); try {
    assert.equal((await s.read('/v1/search')).status, 503);
    assert.equal((await s.sync({}, 'wrong-key')).status, 401);
    const start = await s.sync(); assert.equal(start.status, 200); assert.equal((await start.json() as any).status, 'syncing');
    assert.equal((await s.read('/v1/search')).status, 503);
    const second = await s.sync(); assert.equal((await second.json() as any).status, 'syncing', 'Search is not activated before memory pages');
    const done = await s.complete(); assert.equal(done.total_pages, 3); assert.equal(done.next_page, 3);
    const pick = await s.read('/v1/search?q=PickCube'); assert.equal(pick.status, 200); assert.equal(pick.body.backend, 'd1_fts5'); assert.equal(pick.body.results[0].id, 'maniskill-panda-pick-cube');
    const kuka = await s.read('/v1/search?q=kuka'); assert.equal(kuka.body.results[0].id, 'kuka-grasp');
    const all = await s.read('/v1/search?q=pick%20cube'); assert.equal(all.body.total, 3);
    const absent = await s.read('/v1/search?q=pick%20impossible'); assert.equal(absent.body.total, 0);
    for (const query of ['!!!', '---', '🦾']) {
      const punctuation = await s.read('/v1/search?q=' + encodeURIComponent(query) + '&offset=5&limit=2');
      assert.equal(punctuation.status, 200); assert.equal(punctuation.body.backend, 'd1_fts5'); assert.equal(punctuation.body.total, 0);
      assert.deepEqual(punctuation.body.results, []); assert.equal(punctuation.body.next, null); assert.equal(punctuation.body.limit, 2); assert.equal(punctuation.body.offset, 5);
    }
    assert.equal((await s.read('/v1/search?q=%20%20')).body.total, 3, 'Whitespace keeps explicit catalog browsing');
    assert.equal((await s.read('/v1/search?q=!!!PickCube!!!')).body.total, 1, 'Mixed punctuation follows word tokenization');
    const mixed = await s.read('/v1/search?runtime=maniskill&robot=ur5'); assert.equal(mixed.body.total, 0);
    const exact = await s.read('/v1/search?runtime=maniskill&runtime_version=3.0&robot=panda&python=3.10.11&architecture=amd64'); assert.equal(exact.body.total, 1);
    assert.equal((await s.read('/v1/search?python=3.12.0')).body.total, 0);
    const first = await s.read('/v1/search?limit=1'); assert.equal(first.body.next.hub_commit, 'a'.repeat(40)); assert.equal((await s.read('/v1/search?hub_commit=' + 'f'.repeat(40))).status, 409);
    const record = await s.read('/v1/skills/maniskill-panda-pick-cube'); assert.equal(record.status, 200); assert.equal(record.body.record.access.hub_prepare, true);
    published.resources.set('/references/kuka-grasp/skill.json', '{"id":"kuka-grasp","tampered":true}');
    const tampered = await s.read('/v1/skills/kuka-grasp'); assert.equal(tampered.status, 503); assert.equal(tampered.body.reason_code, 'publication_changed');
    const mcp = await s.mf.dispatchFetch(API + '/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', DNT: '1', 'X-RSH-Telemetry': 'off' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'find_robot_skills', arguments: { q: 'kuka' } } }) });
    assert.equal((await mcp.json() as any).result.structuredContent.backend, 'd1_fts5');
    const findings = await s.read('/v1/findings?skill_id=maniskill-panda-pick-cube&record_version=1.0.0&source_commit=' + 'b'.repeat(40) + '&robot=panda'); assert.equal(findings.status, 200); assert.equal(findings.body.total, 1); assert.equal(findings.body.results[0].trust, 'contributor_reported');
    assert.equal((await s.read('/v1/findings?skill_id=maniskill-panda-pick-cube')).status, 400);
    const wrongPins = await s.read('/v1/findings?skill_id=maniskill-panda-pick-cube&record_version=1.0.1&source_commit=' + 'b'.repeat(40)); assert.equal(wrongPins.body.total, 0);
    const fts = await s.db.prepare("SELECT count(*) total FROM catalog_fts WHERE catalog_fts MATCH 'kuka*'").first<any>(); assert.equal(fts.total, 1, 'Real FTS5 executes through D1');
  } finally { await s.mf.dispose(); }
});

test('native D1 concurrent sync retries reuse documents/FTS and stale or partial generations never claim the current commit', async () => {
  const s = await runtime(); try {
    await Promise.all([s.sync(), s.sync(), s.sync()]); await s.complete();
    const before = await s.db.prepare('SELECT count(*) docs, max(rowid) last FROM catalog_documents').first<any>();
    const ftsBefore = await s.db.prepare('SELECT count(*) total FROM catalog_fts').first<any>();
    s.set(publication('c'.repeat(40))); assert.equal((await s.read('/v1/search')).status, 503);
    assert.equal((await s.sync({ hub_commit: 'a'.repeat(40) })).status, 409);
    await s.complete();
    const after = await s.db.prepare('SELECT count(*) docs, max(rowid) last FROM catalog_documents').first<any>(); assert.deepEqual(after, before);
    assert.deepEqual(await s.db.prepare('SELECT count(*) total FROM catalog_fts').first(), ftsBefore);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_memory_documents').first<any>()).total, 1);
    assert.equal((await s.read('/v1/search')).body.hub_commit, 'c'.repeat(40));
    s.set(publication('d'.repeat(40))); await s.complete();
    await s.sync();
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_generations').first<any>()).total, 2);
  } finally { await s.mf.dispose(); }
});

test('native D1 indexes declared robot types while robot models and combinations remain explicit', async () => {
  const s = await runtime(publication('a'.repeat(40), { humanoid: true })); try {
    await s.complete();
    const found = await s.read('/v1/search?q=humanoid%20locomotion');
    assert.equal(found.status, 200); assert.equal(found.body.backend, 'd1_fts5');
    assert.deepEqual(found.body.results.map((row: any) => row.id), ['h1-locomotion']);
    assert.deepEqual(found.body.results[0].robot_types, ['humanoid']);
    assert.equal(found.body.results[0].hub_prepare, false);
    assert.deepEqual(found.body.results[0].compatibility, []);
    assert.equal((await s.read('/v1/search?q=humanoid%20locomotion&runtime=isaaclab')).body.total, 1);
    for (const filter of ['robot=humanoid', 'robot=panda', 'os=linux', 'runtime=isaaclab&robot=h1']) {
      assert.equal((await s.read('/v1/search?q=humanoid%20locomotion&' + filter)).body.total, 0, filter);
    }
    assert.equal((await s.read('/v1/search?q=humanoid%20locomotion%20missingterm')).body.total, 0);
  } finally { await s.mf.dispose(); }
});

for (const options of [{ wrongPageHash: true }, { duplicate: true }, { maliciousPath: true }, { invalidRow: { record_version: '' } }, { invalidRow: { hub_prepare: true } }, { invalidRow: { record_version: 'unbound-version' } }, { invalidRow: { robot_types: 'humanoid' } }, { invalidRow: { robot_types: [null] } }]) test('native D1 rejects corrupt, duplicated or off-origin publication without activation: ' + JSON.stringify(options), async () => {
  const s = await runtime(publication('a'.repeat(40), options)); try {
    let failure = 0;
    for (let i = 0; i < 4; i++) { const result = await s.sync(); if (result.status !== 200) { failure = result.status; break; } }
    assert.equal(failure, 503); assert.equal((await s.read('/v1/search')).status, 503);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_active').first<any>()).total, 0);
    if ('duplicate' in options && options.duplicate) {
      assert.equal((await s.db.prepare('SELECT next_page FROM catalog_generations').first<any>()).next_page, 1);
      assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_pages').first<any>()).total, 1);
      assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_members').first<any>()).total, 2);
    }
  } finally { await s.mf.dispose(); }
});

test('native empty catalog with no findings is a complete generation', async () => {
  const s = await runtime(publication('a'.repeat(40), { records: 0, memories: 0 })); try { await s.complete(); const found = await s.read('/v1/search'); assert.equal(found.status, 200); assert.equal(found.body.total, 0); } finally { await s.mf.dispose(); }
});

test('native unavailable mirror falls back only to a complete checksum-bound current static view', async () => {
  const current = publication('a'.repeat(40));
  const search = JSON.stringify({ schema_version: '1', hub_commit: current.version.hub_commit, counts: { recipes: 1, references: 2, memories: 1 }, records: current.rows });
  current.resources.set('/catalog/v1/search.json', search); current.version.resources.search = { sha256: hash(search) }; current.resources.set('/catalog/v1/version.json', JSON.stringify(current.version));
  const s = await runtime(current); try {
    const result = await s.read('/v1/search?q=kuka'); assert.equal(result.status, 200); assert.equal(result.body.backend, 'static_v1_fallback'); assert.equal(result.body.total, 1); assert.equal(result.body.coverage.complete, true);
    current.resources.set('/catalog/v1/search.json', search + ' ');
    s.set(publication('c'.repeat(40))); assert.equal((await s.read('/v1/search')).status, 503, 'Older cached static data cannot claim a fresh generation');
  } finally { await s.mf.dispose(); }
});

test('native mirror accepts the complete current publisher output', { skip: !process.env.RSH_CATALOG_NATIVE_FIXTURE }, async () => {
  const directory = process.env.RSH_CATALOG_NATIVE_FIXTURE!;
  const current = publication('a'.repeat(40)); current.resources.clear();
  const load = async (path: string) => { const body = await readFile(join(directory, path), 'utf8'); current.resources.set('/' + path, body); return JSON.parse(body); };
  const version = await load('catalog/v1/version.json');
  const manifest = await load('catalog/v2/search-manifest.json'), memories = await load('catalog/v2/memory-manifest.json');
  for (const page of [...manifest.pages, ...memories.pages]) await load(page.path);
  const s = await runtime(current); try {
    const done = await s.complete(); assert.equal(done.records, manifest.records); assert.equal(done.memories, memories.records);
    const all = await s.read('/v1/search?limit=1'); assert.equal(all.body.total, manifest.records); assert.equal(all.body.hub_commit, version.hub_commit); assert.equal(all.body.backend, 'd1_fts5');
    const pick = await s.read('/v1/search?q=PickCube'); const recipe = pick.body.results.find((row: any) => row.id === 'maniskill-panda-pick-cube'); assert.ok(recipe);
    assert.ok(recipe.python_requirement); assert.match(recipe.source_url, /^https:\/\//);
    const kuka = await s.read('/v1/search?q=kuka'); assert.ok(kuka.body.total > 0);
    const docs = await s.db.prepare('SELECT count(*) total FROM catalog_documents').first<any>(); assert.equal(docs.total, manifest.records);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_memory_documents').first<any>()).total, memories.records);
  } finally { await s.mf.dispose(); }
});
