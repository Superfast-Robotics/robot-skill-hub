import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { build } from 'esbuild';
import { Miniflare, Request as RuntimeRequest, Response as RuntimeResponse } from 'miniflare';
import { createCatalogSync, indexedFindings, indexedSearch, pruneCatalog, staticFindings, type CatalogDatabase } from '../../src/catalog.ts';

const ORIGIN = 'https://hub.superfastrobotics.com', API = 'https://api.example.invalid';
const KEY = 'local-native-catalog-sync-credential';
const hash = (text: string) => createHash('sha256').update(text).digest('hex');
const bundle = build({ entryPoints: [fileURLToPath(new URL('../../src/index.ts', import.meta.url))], bundle: true, write: false, platform: 'browser', format: 'esm', target: 'es2023' }).then(result => result.outputFiles![0].text);
const schema = readFile(new URL('../../migrations-catalog/0001_catalog.sql', import.meta.url), 'utf8');
const membershipSchema = readFile(new URL('../../migrations-catalog/0002_page_memberships.sql', import.meta.url), 'utf8');
function publication(commit: string, options: { duplicate?: boolean; duplicateMemory?: boolean; changedSource?: boolean; distinctMemoryPins?: boolean; pageSize?: number; wrongPageHash?: boolean; maliciousPath?: boolean; records?: number; memories?: number; invalidRow?: Record<string, unknown>; humanoid?: boolean; rowOverrides?: Record<string, unknown>[]; memoryOverrides?: Record<string, unknown>[] } = {}) {
  const count = options.records ?? 3;
  const full = Array.from({ length: count }, (_, index) => ({ id: index === 0 ? 'maniskill-panda-pick-cube' : index === 1 ? options.humanoid ? 'h1-locomotion' : 'kuka-grasp' : 'source-' + index, access: { hub_prepare: index === 0 }, source: { commit: 'b'.repeat(40), sha256: 'c'.repeat(64) } }));
  if (options.changedSource) full[1].source = { commit: 'd'.repeat(40), sha256: 'e'.repeat(64) };
  const combos = [{ runtime: 'maniskill', runtime_version: '3.0', robot: 'panda', controller: 'pd_joint_pos', observation: 'state', os: 'linux', python: '3.10', architecture: 'x86_64' }, { runtime: 'ros2', runtime_version: 'humble', robot: 'ur5', controller: 'torque', observation: 'rgb', os: 'windows' }];
  const rows = full.map((record, index) => ({ id: record.id, name: index === 0 ? 'PickCube-v1' : index === 1 ? options.humanoid ? 'H1 locomotion' : 'KUKA iiwa grasp' : 'Source ' + index, summary: 'Pinned source for pick cube and robot grasp', kind: index === 0 ? 'preparation_recipe' : 'source_reference', hub_prepare: index === 0, record_version: index === 0 ? '1.0.0' : 'source-' + record.source.sha256, record_sha256: hash(JSON.stringify(record)), source_sha256: record.source.sha256, source_commit: record.source.commit, record_url: ORIGIN + (index === 0 ? '/skills/' : '/references/') + record.id + '/skill.json', capabilities: options.humanoid && index === 1 ? ['locomotion'] : ['pick cube'], aliases: [], runtime: index === 0 ? 'maniskill' : options.humanoid && index === 1 ? 'isaaclab' : 'ros2', framework: options.humanoid && index === 1 ? 'isaaclab' : 'maniskill', robots: [index === 1 ? options.humanoid ? 'h1' : 'kuka_iiwa' : 'panda'], ...(options.humanoid && index === 1 ? { robot_types: ['humanoid'] } : {}), compatibility: index === 0 ? combos : [], ...(index === 0 ? { python_requirement: '>=3.10,<3.12' } : {}) }));
  options.rowOverrides?.forEach((values, index) => Object.assign(rows[index], values));
  if (options.invalidRow) Object.assign(rows[1], options.invalidRow);
  const memoryHash = (index: number) => index < 9 ? String(index + 1).repeat(64) : hash('finding-' + index);
  const memories = Array.from({ length: options.memories ?? 1 }, (_, i) => ({ schema_version: '1', memory_id: 'mem_' + memoryHash(i), skill_id: rows[options.distinctMemoryPins ? i : 0]?.id ?? 'absent-skill', base: { record_version: options.distinctMemoryPins ? rows[i].record_version : '1.0.0', source_commit: 'b'.repeat(40), hub_commit: 'a'.repeat(40) }, environment: { runtime: 'maniskill', robot: i === 0 ? 'panda' : 'ur5', os: 'linux' }, fingerprint: 'd'.repeat(64), content_sha256: 'e'.repeat(64), entry_url: ORIGIN + '/memories/mem_' + memoryHash(i) + '.json', curation: 'maintainer_merged', interpretation: 'data_only', trust: 'contributor_reported', summary: 'Contributor finding', evidence: { level: 'contributor_reported', runtime_verification: 'not_run' } }));
  options.memoryOverrides?.forEach((values, index) => Object.assign(memories[index], values));
  const resources = new Map<string, string>();
  full.forEach((record, index) => resources.set((index === 0 ? '/skills/' : '/references/') + record.id + '/skill.json', JSON.stringify(record)));
  const pageList = (values: any[], kind: string) => {
    const descriptors: any[] = [];
    const pageSize = options.pageSize ?? 2;
    for (let start = 0; start < values.length; start += pageSize) {
      const index = descriptors.length, path = `catalog/v2/generations/${commit}/${kind}/${String(index).padStart(6, '0')}.json`;
      const entries = values.slice(start, start + pageSize);
      if ((options.duplicate && kind === 'search' || options.duplicateMemory && kind === 'memories') && index === 1) entries[0] = values[kind === 'search' ? 1 : 0];
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

// Seed exactly the pre-migration storage protocol, including receipts without a
// group hash. This also proves the additive schema accepts old Worker writes.
async function seedLegacy(db: Awaited<ReturnType<typeof runtime>>['db'], published: ReturnType<typeof publication>, pages: number, active = false) {
  const manifestText = published.resources.get('/catalog/v2/search-manifest.json')!, manifest = JSON.parse(manifestText);
  const memory = JSON.parse(published.resources.get('/catalog/v2/memory-manifest.json')!);
  const descriptors = [...manifest.pages, ...memory.pages], commit = manifest.hub_commit;
  await db.prepare('INSERT INTO catalog_generations(hub_commit,manifest_sha256,manifest_json,total_pages,total_records,created_at) VALUES(?,?,?,?,?,?)').bind(commit, hash(manifestText), manifestText, descriptors.length, manifest.records, Date.now()).run();
  for (let index = 0; index < pages; index++) {
    const isMemory = index >= manifest.pages.length, descriptor = descriptors[index];
    const page = JSON.parse(published.resources.get('/' + descriptor.path)!);
    const data = JSON.stringify(page.records.map((row: any) => ({ hash: hash(JSON.stringify(row)), row: !isMemory && row.kind === 'preparation_recipe' ? { ...row, _python_min: 3010000, _python_max: 3011999, _python_exclude: [] } : row, text: isMemory ? '' : [row.id, row.name, row.summary, ...(row.capabilities || []), ...(row.aliases || []), ...(row.robots || []), ...(row.robot_types || []), row.runtime || '', row.framework || ''].join(' ').replace(/[-_/]/g, ' ') })));
    await db.batch([
      db.prepare(isMemory ? `INSERT OR IGNORE INTO catalog_memory_documents(doc_hash,memory_id,skill_id,record_version,source_commit,row_json) SELECT json_extract(value,'$.hash'),json_extract(value,'$.row.memory_id'),json_extract(value,'$.row.skill_id'),json_extract(value,'$.row.base.record_version'),json_extract(value,'$.row.base.source_commit'),json_extract(value,'$.row') FROM json_each(?)` : `INSERT OR IGNORE INTO catalog_documents(doc_hash,id,kind,row_json,search_text) SELECT json_extract(value,'$.hash'),json_extract(value,'$.row.id'),json_extract(value,'$.row.kind'),json_extract(value,'$.row'),json_extract(value,'$.text') FROM json_each(?)`).bind(data),
      db.prepare(isMemory ? `INSERT INTO catalog_memory_members(hub_commit,memory_id,doc_hash) SELECT ?,json_extract(value,'$.row.memory_id'),json_extract(value,'$.hash') FROM json_each(?)` : `INSERT INTO catalog_members(hub_commit,id,doc_hash) SELECT ?,json_extract(value,'$.row.id'),json_extract(value,'$.hash') FROM json_each(?)`).bind(commit, data),
      db.prepare('INSERT INTO catalog_pages(hub_commit,page_index,sha256,records) VALUES(?,?,?,?)').bind(commit, index, descriptor.sha256, descriptor.records),
      db.prepare('UPDATE catalog_generations SET next_page=next_page+1 WHERE hub_commit=?').bind(commit)
    ]);
  }
  if (active) { assert.equal(pages, descriptors.length); await db.prepare('INSERT INTO catalog_active(singleton,hub_commit) VALUES(1,?)').bind(commit).run(); }
}

test('native additive migration preserves old active reads and resumes mixed legacy/group staging without rewriting legacy pages', async () => {
  const old = publication('a'.repeat(40)), s = await runtime(old, { legacySchemaOnly: true }); try {
    await seedLegacy(s.db, old, 3, true);
    const blocked = await s.sync(); assert.equal(blocked.status, 503); assert.equal((await blocked.json() as any).reason_code, 'catalog_schema_required');
    assert.equal((await s.db.prepare('SELECT next_page FROM catalog_generations').first<any>()).next_page, 3);
    await s.migrate();
    const legacyRead = await s.read('/v1/search?q=kuka'); assert.equal(legacyRead.status, 200); assert.equal(legacyRead.body.backend, 'd1_fts5'); assert.equal(legacyRead.body.total, 1);
    const current = publication('c'.repeat(40)); s.set(current);
    await seedLegacy(s.db, current, 1);
    await s.complete();
    const receipts = await s.db.prepare('SELECT page_index,group_hash FROM catalog_pages WHERE hub_commit=? ORDER BY page_index').bind(current.version.hub_commit).all<any>();
    assert.equal(receipts.results[0].group_hash, null); assert.ok(receipts.results[1].group_hash); assert.ok(receipts.results[2].group_hash);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_members WHERE hub_commit=?').bind(current.version.hub_commit).first<any>()).total, 2);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_all_members WHERE hub_commit=?').bind(current.version.hub_commit).first<any>()).total, 3);
    assert.equal((await s.read('/v1/search?runtime=maniskill&robot=panda&python=3.10.11&architecture=amd64')).body.total, 1);
    assert.equal((await s.read('/v1/skills/kuka-grasp')).body.record.source.sha256, 'c'.repeat(64));
    assert.equal((await s.read('/v1/findings?skill_id=maniskill-panda-pick-cube&record_version=1.0.0&source_commit=' + 'b'.repeat(40))).body.total, 1);
  } finally { await s.mf.dispose(); }
});

test('native new pages reject an identity already staged by the legacy Worker before advancing the cursor', async () => {
  const current = publication('c'.repeat(40), { duplicate: true }), s = await runtime(); try {
    await s.complete(); await seedLegacy(s.db, current, 1); s.set(current);
    const failed = await s.sync(); assert.equal(failed.status, 503); assert.equal((await failed.json() as any).reason_code, 'invalid_publication');
    assert.equal((await s.db.prepare('SELECT next_page FROM catalog_generations WHERE hub_commit=?').bind(current.version.hub_commit).first<any>()).next_page, 1);
    assert.equal((await s.db.prepare('SELECT hub_commit FROM catalog_active').first<any>()).hub_commit, 'a'.repeat(40));
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_all_members WHERE hub_commit=?').bind(current.version.hub_commit).first<any>()).total, 2);
  } finally { await s.mf.dispose(); }
});

test('native page groups reuse unchanged search/finding contents and isolate a changed source pin', async () => {
  const s = await runtime(); try {
    const bindings = async (commit: string) => (await s.db.prepare('SELECT group_hash FROM catalog_pages WHERE hub_commit=? ORDER BY page_index').bind(commit).all<any>()).results.map((row: any) => row.group_hash);
    await s.complete(); const initial = await bindings('a'.repeat(40));
    s.set(publication('b'.repeat(40))); await s.complete(); assert.deepEqual(await bindings('b'.repeat(40)), initial);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_page_members').first<any>()).total, 3);
    s.set(publication('c'.repeat(40), { memories: 2 })); await s.complete(); const moreMemories = await bindings('c'.repeat(40));
    assert.deepEqual(moreMemories.slice(0, 2), initial.slice(0, 2)); assert.notEqual(moreMemories[2], initial[2]);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_page_members').first<any>()).total, 3);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_documents').first<any>()).total, 3);
    s.set(publication('d'.repeat(40), { memories: 2, changedSource: true })); await s.complete(); const changed = await bindings('d'.repeat(40));
    assert.notEqual(changed[0], moreMemories[0]); assert.deepEqual(changed.slice(1), moreMemories.slice(1));
    const found = await s.read('/v1/search?q=kuka'); assert.equal(found.body.results[0].source_commit, 'd'.repeat(40)); assert.equal(found.body.results[0].record_version, 'source-' + 'e'.repeat(64));
    const full = await s.read('/v1/skills/kuka-grasp?record_version=' + found.body.results[0].record_version); assert.equal(full.status, 200); assert.equal(full.body.record.source.sha256, 'e'.repeat(64));
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_documents').first<any>()).total, 4);
    assert.equal((await s.db.prepare("SELECT count(*) total FROM catalog_fts WHERE catalog_fts MATCH 'kuka*'").first<any>()).total, 2, 'Old immutable content remains stored without entering the selected generation twice');
  } finally { await s.mf.dispose(); }
});

test('native finding identities cannot repeat across content groups and leave the old generation active', async () => {
  const s = await runtime(); try {
    await s.complete(); s.set(publication('c'.repeat(40), { memories: 3, duplicateMemory: true }));
    for (let i = 0; i < 3; i++) assert.equal((await s.sync()).status, 200);
    const failed = await s.sync(); assert.equal(failed.status, 503); assert.equal((await failed.json() as any).reason_code, 'invalid_publication');
    assert.equal((await s.db.prepare('SELECT next_page FROM catalog_generations WHERE hub_commit=?').bind('c'.repeat(40)).first<any>()).next_page, 3);
    assert.equal((await s.db.prepare('SELECT hub_commit FROM catalog_active').first<any>()).hub_commit, 'a'.repeat(40));
  } finally { await s.mf.dispose(); }
});

test('native activation checks distinct identities even when every receipt and total count is complete', async () => {
  const current = publication('c'.repeat(40), { duplicate: true }), s = await runtime(); try {
    await s.complete(); s.set(current); assert.equal((await s.sync()).status, 200);
    const row = current.rows[1], documentHash = hash(JSON.stringify(row));
    const groupHash = hash(JSON.stringify(['rsh-catalog-page-members-v1', 'search', [[row.id, documentHash]]]));
    const manifest = JSON.parse(current.resources.get('/catalog/v2/search-manifest.json')!);
    const memory = JSON.parse(current.resources.get('/catalog/v2/memory-manifest.json')!);
    const oldMemoryGroup = (await s.db.prepare('SELECT group_hash FROM catalog_pages WHERE hub_commit=? AND page_index=2').bind('a'.repeat(40)).first<any>()).group_hash;
    // Seed the remaining correctly hashed receipts directly to exercise final
    // validation independently of the earlier per-page duplicate guard.
    await s.db.batch([
      s.db.prepare('INSERT INTO catalog_page_groups(group_hash,kind,records) VALUES(?,?,1)').bind(groupHash, 'search'),
      s.db.prepare('INSERT INTO catalog_page_members(group_hash,id,doc_hash) VALUES(?,?,?)').bind(groupHash, row.id, documentHash),
      s.db.prepare('INSERT INTO catalog_pages(hub_commit,page_index,sha256,records,group_hash) VALUES(?,1,?,1,?)').bind(current.version.hub_commit, manifest.pages[1].sha256, groupHash),
      s.db.prepare('INSERT INTO catalog_pages(hub_commit,page_index,sha256,records,group_hash) VALUES(?,2,?,1,?)').bind(current.version.hub_commit, memory.pages[0].sha256, oldMemoryGroup),
      s.db.prepare('UPDATE catalog_generations SET next_page=total_pages WHERE hub_commit=?').bind(current.version.hub_commit)
    ]);
    const counts = await s.db.prepare("SELECT count(*) total,count(DISTINCT m.id) identities,sum(d.kind='preparation_recipe') recipes FROM catalog_all_members m JOIN catalog_documents d ON d.doc_hash=m.doc_hash WHERE hub_commit=?").bind(current.version.hub_commit).first<any>();
    assert.deepEqual(counts, { total: 3, identities: 2, recipes: 1 });
    const failed = await s.sync(); assert.equal(failed.status, 503); assert.equal((await failed.json() as any).reason_code, 'invalid_publication');
    assert.equal((await s.db.prepare('SELECT hub_commit FROM catalog_active').first<any>()).hub_commit, 'a'.repeat(40));
  } finally { await s.mf.dispose(); }
});

test('native cached memberships never bypass current fixed-page checksum and path validation', async () => {
  for (const options of [{ wrongPageHash: true }, { maliciousPath: true }]) {
    const s = await runtime(); try {
      await s.complete(); const before = await s.db.prepare('SELECT count(*) total FROM catalog_page_groups').first();
      s.set(publication('c'.repeat(40), options)); const failed = await s.sync(); assert.equal(failed.status, 503);
      assert.equal((await s.db.prepare('SELECT hub_commit FROM catalog_active').first<any>()).hub_commit, 'a'.repeat(40));
      assert.deepEqual(await s.db.prepare('SELECT count(*) total FROM catalog_page_groups').first(), before);
      assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_pages WHERE hub_commit=?').bind('c'.repeat(40)).first<any>()).total, 0);
    } finally { await s.mf.dispose(); }
  }
});

test('native bounded GC keeps shared memberships after their original generation retires and collects whole orphan groups', async () => {
  const s = await runtime(); try {
    await s.complete(); const shared = (await s.db.prepare('SELECT group_hash FROM catalog_pages WHERE hub_commit=? ORDER BY page_index').bind('a'.repeat(40)).all<any>()).results.map((row: any) => row.group_hash);
    s.set(publication('b'.repeat(40))); await s.complete(); s.set(publication('c'.repeat(40))); await s.complete();
    await pruneCatalog({ CATALOG: s.db as unknown as CatalogDatabase });
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_generations WHERE hub_commit=?').bind('a'.repeat(40)).first<any>()).total, 0);
    for (const groupHash of shared) assert.ok(await s.db.prepare('SELECT group_hash FROM catalog_page_groups WHERE group_hash=?').bind(groupHash).first());
    const docs = (await s.db.prepare('SELECT id,doc_hash FROM catalog_documents ORDER BY id').all<any>()).results;
    const orphans: string[] = [];
    for (const a of docs) for (const b of docs) {
      if (a.id === b.id || orphans.length >= 6) continue;
      const groupHash = hash(JSON.stringify(['rsh-catalog-page-members-v1', 'search', [[a.id, a.doc_hash], [b.id, b.doc_hash]]]));
      if (await s.db.prepare('SELECT 1 found FROM catalog_page_groups WHERE group_hash=?').bind(groupHash).first()) continue;
      await s.db.batch([
        s.db.prepare('INSERT INTO catalog_page_groups(group_hash,kind,records) VALUES(?,?,2)').bind(groupHash, 'search'),
        s.db.prepare('INSERT INTO catalog_page_members(group_hash,id,doc_hash) VALUES(?,?,?),(?,?,?)').bind(groupHash, a.id, a.doc_hash, groupHash, b.id, b.doc_hash)
      ]); orphans.push(groupHash);
    }
    assert.ok(orphans.length >= 4);
    const count = async () => (await s.db.prepare('SELECT count(*) total FROM catalog_page_groups').first<any>()).total;
    const before = await count(); await pruneCatalog({ CATALOG: s.db as unknown as CatalogDatabase });
    assert.equal(before - await count(), 2, 'One prune deletes at most two complete groups');
    const partial = await s.db.prepare("SELECT g.group_hash FROM catalog_page_groups g LEFT JOIN catalog_page_members m ON m.group_hash=g.group_hash WHERE g.kind='search' GROUP BY g.group_hash HAVING count(m.id)<>g.records").all();
    assert.deepEqual(partial.results, [], 'Remaining group headers always describe complete membership');
    for (let i = 0; i < 4; i++) await pruneCatalog({ CATALOG: s.db as unknown as CatalogDatabase });
    for (const groupHash of shared) assert.ok(await s.db.prepare('SELECT group_hash FROM catalog_page_groups WHERE group_hash=?').bind(groupHash).first());
    assert.equal((await s.read('/v1/search?q=kuka')).body.total, 1);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_documents').first<any>()).total, 3);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_fts').first<any>()).total, 3);
  } finally { await s.mf.dispose(); }
});

test('native cleanup quota failure before activation retains old active and resumes the already committed page', async () => {
  const current = publication('c'.repeat(40)), s = await runtime(); try {
    await s.complete(); s.set(current); await s.sync(); await s.sync();
    const row = current.rows[1], documentHash = hash(JSON.stringify(row)), groupHash = hash(JSON.stringify(['rsh-catalog-page-members-v1', 'search', [[row.id, documentHash]]]));
    await s.db.batch([
      s.db.prepare('INSERT INTO catalog_page_groups(group_hash,kind,records) VALUES(?,?,1)').bind(groupHash, 'search'),
      s.db.prepare('INSERT INTO catalog_page_members(group_hash,id,doc_hash) VALUES(?,?,?)').bind(groupHash, row.id, documentHash)
    ]);
    await s.db.exec("CREATE TRIGGER test_cleanup_quota BEFORE DELETE ON catalog_page_groups BEGIN SELECT RAISE(ABORT, 'Your account has exceeded D1''s free tier daily row write limit.'); END;");
    const failed = await s.sync(); assert.equal(failed.status, 503); assert.equal((await failed.json() as any).reason_code, 'catalog_write_limit');
    assert.equal((await s.db.prepare('SELECT next_page FROM catalog_generations WHERE hub_commit=?').bind(current.version.hub_commit).first<any>()).next_page, 3);
    assert.equal((await s.db.prepare('SELECT hub_commit FROM catalog_active').first<any>()).hub_commit, 'a'.repeat(40));
    await s.db.exec('DROP TRIGGER test_cleanup_quota;'); await s.complete();
    assert.equal((await s.read('/v1/search')).body.hub_commit, current.version.hub_commit);
  } finally { await s.mf.dispose(); }
});

test('native selective FTS and exact finding pins avoid materializing all shared memberships', async () => {
  const s = await runtime(publication('a'.repeat(40), { records: 1272, memories: 1272, pageSize: 100, distinctMemoryPins: true })); try {
    await s.complete();
    const measurements: { sql: string; values: unknown[]; reads: number; writes: number }[] = [];
    function statement(sql: string, native: any, values: unknown[] = []): any {
      return { native, sql, values,
        bind(...bound: unknown[]) { return statement(sql, native.bind(...bound), bound); },
        async all() { const result = await native.all(); measurements.push({ sql, values, reads: result.meta.rows_read, writes: result.meta.rows_written }); return result; },
        async run() { assert.fail('Public reads cannot run a write statement'); }
      };
    }
    const db: CatalogDatabase = {
      prepare(sql) { return statement(sql, s.db.prepare(sql)); },
      async batch(statements: any[]) {
        const results = await s.db.batch(statements.map(value => value.native));
        results.forEach((result: any, index: number) => measurements.push({ sql: statements[index].sql, values: statements[index].values, reads: result.meta.rows_read, writes: result.meta.rows_written }));
        return results as any;
      }
    };
    const search = await indexedSearch(db, 'a'.repeat(40), { q: 'source-1271', limit: 2 });
    assert.equal(search.total, 1); assert.deepEqual(search.results.map(row => row.id), ['source-1271']);
    const searchReads = measurements.reduce((total, value) => total + value.reads, 0);
    assert.ok(searchReads < 200, 'Selective native FTS must not read all 1272 generation memberships: ' + searchReads);
    measurements.length = 0;
    const findings = await indexedFindings(db, 'a'.repeat(40), { skill_id: 'maniskill-panda-pick-cube', record_version: '1.0.0', source_commit: 'b'.repeat(40), robot: 'panda', limit: 2 });
    assert.equal(findings.total, 1); assert.equal(findings.results[0].skill_id, 'maniskill-panda-pick-cube');
    const findingReads = measurements.reduce((total, value) => total + value.reads, 0);
    assert.ok(findingReads < 200, 'Exact pins must use the native document index rather than scan all 1272 findings: ' + findingReads);
    assert.ok(measurements.every(value => value.writes === 0));
    for (const value of measurements) {
      const plan = await s.db.prepare('EXPLAIN QUERY PLAN ' + value.sql).bind(...value.values as any[]).all<any>();
      const details = plan.results.map((row: any) => row.detail).join('\n');
      assert.match(details, /catalog_memory_pins/);
      assert.doesNotMatch(details, /MATERIALIZE.*catalog_all_memory_members/);
    }
  } finally { await s.mf.dispose(); }
});
async function runtime(initial = publication('a'.repeat(40)), options: { legacySchemaOnly?: boolean } = {}) {
  let current = initial; const calls: string[] = [];
  const mf = new Miniflare({ telemetry: { enabled: false }, workers: [{ config: { name: 'native-catalog-test', compatibilityDate: '2026-10-17', manifest: { mainModule: 'worker.js', modules: { 'worker.js': { type: 'esm', contents: await bundle } } }, env: { CATALOG: { type: 'd1', id: 'native-catalog-test' }, CATALOG_SYNC_KEY: { type: 'text', value: KEY }, PUBLICATION_URL: { type: 'text', value: ORIGIN + '/catalog/v1/publication.json' } } }, dev: { outboundService: { type: 'fetcher', handler(request: RuntimeRequest) {
    const url = new URL(request.url); calls.push(request.url);
    assert.equal(url.origin, ORIGIN); assert.equal(request.headers.get('DNT'), '1'); assert.equal(request.headers.get('X-RSH-Telemetry'), 'off'); assert.equal(request.headers.has('Authorization'), false);
    const body = current.resources.get(url.pathname); return body === undefined ? new RuntimeResponse(null, { status: 404 }) : new RuntimeResponse(body);
  } } } }] });
  const db = await mf.getD1Database('CATALOG');
  // D1 exec accepts SQL statements, including the real FTS5 tables and triggers.
  await db.exec((await schema).replace(/--[^\n]*/g, '').replace(/\s+/g, ' '));
  const migrate = async () => { await db.exec((await membershipSchema).replace(/--[^\n]*/g, '').replace(/\s+/g, ' ')); };
  if (!options.legacySchemaOnly) await migrate();
  const sync = (body: any = {}, key = KEY) => mf.dispatchFetch(API + '/internal/catalog-sync', { method: 'POST', headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json', DNT: '1', 'X-RSH-Telemetry': 'off' }, body: JSON.stringify(body) });
  async function complete() { for (let i = 0; i < 100; i++) { const response = await sync(), value: any = await response.json(); assert.equal(response.status, 200, JSON.stringify(value)); if (value.status === 'active') return value; } assert.fail('Sync did not finish'); }
  async function read(path: string) { const response = await mf.dispatchFetch(API + path, { headers: { DNT: '1', 'X-RSH-Telemetry': 'off' } }); return { status: response.status, body: await response.json() as any }; }
  return { mf, db, calls, sync, complete, read, migrate, set(value: ReturnType<typeof publication>) { current = value; } };
}

test('native and static finding recall binds flat package/backend fields to one exact-pin finding and preserves pagination', async () => {
  const environment = { runtime: 'maniskill', robot: 'panda', sim_backend: 'cpu', render_backend: 'none', 'package.mesa': '23.2.1' };
  const base = { record_version: '1.0.0', source_commit: 'b'.repeat(40), hub_commit: 'a'.repeat(40) };
  const published = publication('a'.repeat(40), { memories: 9, memoryOverrides: [
    { environment }, { environment: { ...environment, sim_backend: 'CPU' } },
    { environment: { ...environment, sim_backend: 'gpu' } },
    // A nested lookalike must not satisfy the approved flat package.mesa key.
    { environment: { runtime: 'maniskill', robot: 'panda', sim_backend: 'cpu', render_backend: 'none', package: { mesa: '23.2.1' } } },
    { environment: { ...environment, 'package.mesa': 'other' } },
    { environment, base: { ...base, source_commit: 'f'.repeat(40) } },
    { environment, base: { ...base, record_version: '1.0.1' } },
    { environment, skill_id: 'kuka-grasp' },
    { environment: { runtime: 'maniskill', robot: 'panda', 'package.long_name': 'x'.repeat(240) } }
  ] });
  const s = await runtime(published); try {
    await s.complete();
    const aggregate = JSON.stringify({ schema_version: '1', hub_commit: 'a'.repeat(40), records: published.memories });
    const fallbackVersion = { hub_commit: 'a'.repeat(40), resources: { memories: { sha256: hash(aggregate) } } };
    const staticFetch: typeof fetch = async input => { assert.equal(new URL(String(input)).pathname, '/catalog/v1/memories.json'); return new Response(aggregate); };
    const pins = { skill_id: 'maniskill-panda-pick-cube', record_version: '1.0.0', source_commit: 'b'.repeat(40) };
    const query = { ...pins, ...environment, limit: '1' };
    const read = (input: Record<string, string>) => s.read('/v1/findings?' + new URLSearchParams(input));
    const first = await read(query); assert.equal(first.status, 200); assert.equal(first.body.backend, 'd1');
    assert.equal(first.body.total, 2); assert.equal(first.body.results[0].memory_id, published.memories[0].memory_id);
    assert.deepEqual(first.body.next, { ...query, limit: 1, offset: 1, hub_commit: 'a'.repeat(40) });
    const secondQuery = Object.fromEntries(Object.entries(first.body.next).map(([key, value]) => [key, String(value)]));
    const second = await read(secondQuery); assert.equal(second.body.total, 2); assert.equal(second.body.next, null);
    assert.equal(second.body.results[0].memory_id, published.memories[1].memory_id);
    for (const input of [query, secondQuery, { ...query, 'package.mesa': 'unavailable' }, { ...query, sim_backend: 'metal' },
      { ...pins, 'package.long_name': 'x'.repeat(240) }]) {
      const native = await read(input); assert.equal(native.status, 200);
      const fallback = await staticFindings(staticFetch, fallbackVersion, input);
      assert.deepEqual({ ...native.body, backend: 'static_v1_fallback' }, fallback);
    }
    assert.equal((await read({ ...query, hub_commit: 'f'.repeat(40) })).status, 409);
    for (const bad of [{ ...query, 'package.mesa': 'x'.repeat(241) }, { ...query, 'package.mesa': '' },
      { ...query, 'package.mesa': '  ' }, { ...query, 'package.mesa': '\0' }, { ...query, 'package.mesa.extra': 'x' },
      { ...query, 'package.mesa-name': 'x' }, { ...query, 'package.mesa" OR 1=1 --': 'x' },
      { ...pins, ...Object.fromEntries(Array.from({ length: 17 }, (_, i) => ['package.p' + i, '1'])) }]) {
      assert.equal((await read(bad)).status, 400);
      await assert.rejects(staticFindings(staticFetch, fallbackVersion, bad), (error: any) => error.code === 'invalid_findings');
    }
    assert.equal((await read({ ...pins, ...Object.fromEntries(Array.from({ length: 16 }, (_, i) => ['package.p' + i, '1'])) })).status, 200);
    assert.equal((await read({ ...pins, ['package.' + 'x'.repeat(80)]: '1' })).status, 200);
    assert.equal((await read({ ...pins, ['package.' + 'x'.repeat(81)]: '1' })).status, 400);
    assert.equal((await s.read('/v1/search?sim_backend=cpu')).status, 400);
    assert.equal((await s.read('/v1/search?package.mesa=23.2.1')).status, 400);
  } finally { await s.mf.dispose(); }
});

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
    await pruneCatalog({ CATALOG: s.db as unknown as CatalogDatabase });
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_generations').first<any>()).total, 2);
  } finally { await s.mf.dispose(); }
});

test('native D1 quota failure rolls back one page, preserves the active generation and resumes at the same cursor', async () => {
  const s = await runtime(); try {
    await s.complete();
    s.set(publication('c'.repeat(40), { records: 4 }));
    const start = await s.sync(); assert.equal(start.status, 200); assert.equal((await start.json() as any).next_page, 1);
    const before = async () => ({
      generation: await s.db.prepare('SELECT next_page,total_pages FROM catalog_generations WHERE hub_commit=?').bind('c'.repeat(40)).first(),
      active: await s.db.prepare('SELECT hub_commit FROM catalog_active').first(),
      members: await s.db.prepare('SELECT count(*) total FROM catalog_all_members WHERE hub_commit=?').bind('c'.repeat(40)).first(),
      pages: await s.db.prepare('SELECT count(*) total FROM catalog_pages WHERE hub_commit=?').bind('c'.repeat(40)).first(),
      documents: await s.db.prepare('SELECT count(*) total FROM catalog_documents').first(),
      fts: await s.db.prepare('SELECT count(*) total FROM catalog_fts').first(),
      groups: await s.db.prepare('SELECT count(*) total FROM catalog_page_groups').first(),
      groupMembers: await s.db.prepare('SELECT count(*) total FROM catalog_page_members').first()
    });
    const snapshot = await before();
    assert.deepEqual(snapshot.generation, { next_page: 1, total_pages: 3 });
    assert.deepEqual(snapshot.active, { hub_commit: 'a'.repeat(40) });
    const quota = "Your account has exceeded D1's free tier daily row write limit. Upgrade to a paid plan or wait until tomorrow (midnight UTC) to continue. private-provider-detail";
    await s.db.exec("CREATE TRIGGER test_write_quota BEFORE INSERT ON catalog_page_members BEGIN SELECT RAISE(ABORT, '" + quota.replaceAll("'", "''") + "'); END;");
    for (let attempt = 0; attempt < 2; attempt++) {
      const response = await s.sync(); assert.equal(response.status, 503);
      const seconds = Number(response.headers.get('Retry-After'));
      assert.ok(Number.isInteger(seconds) && seconds >= 1 && seconds <= 86400);
      const instant = Date.now(), midnight = (Math.floor(instant / 86400000) + 1) * 86400000;
      assert.ok(Math.abs(instant + seconds * 1000 - midnight) < 2000, 'Retry-After is next midnight UTC');
      const value = await response.json() as any;
      assert.equal(value.reason_code, 'catalog_write_limit');
      assert.doesNotMatch(JSON.stringify(value), /Upgrade|private-provider-detail|D1_ERROR|test_write_quota/);
      assert.deepEqual(await before(), snapshot, 'Failed native D1 batch cannot advance the cursor, add documents/FTS or replace the active generation');
    }
    await s.db.exec('DROP TRIGGER test_write_quota;');
    const done = await s.complete(); assert.equal(done.next_page, 3); assert.equal(done.status, 'active');
    assert.equal((await s.read('/v1/search')).body.total, 4);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_documents').first<any>()).total, 4);
  } finally { await s.mf.dispose(); }
});

test('native exact active generation sync performs only reads and leaves retirement to explicit pruning', async () => {
  const current = publication('a'.repeat(40)), s = await runtime(current); try {
    const done = await s.complete(); const statements: string[] = [];
    const db: CatalogDatabase = {
      prepare(sql) { statements.push(sql); assert.match(sql, /^\s*SELECT\b/i, 'Active-generation retry cannot even prepare INSERT OR IGNORE, UPDATE or cleanup'); return s.db.prepare(sql) as any; },
      async batch() { assert.fail('Active-generation retry cannot submit a write batch'); }
    };
    const fetcher: typeof fetch = async (input, init) => {
      const url = new URL(String(input)); assert.equal(url.origin, ORIGIN);
      assert.equal(new Headers(init?.headers).get('DNT'), '1'); assert.equal(new Headers(init?.headers).get('X-RSH-Telemetry'), 'off');
      const body = current.resources.get(url.pathname); assert.notEqual(body, undefined); return new Response(body);
    };
    const handler = createCatalogSync(fetcher);
    const response = await handler(new Request(API + '/internal/catalog-sync', { method: 'POST', headers: { Authorization: 'Bearer ' + KEY, 'Content-Type': 'application/json' }, body: JSON.stringify({ hub_commit: current.version.hub_commit }) }), { CATALOG: db, CATALOG_SYNC_KEY: KEY });
    assert.equal(response.status, 200); assert.deepEqual(await response.json(), done);
    assert.equal(statements.length, 2, 'Only the schema gate and real SQLite generation/active-state lookup are needed');
    assert.equal(response.headers.has('Retry-After'), false);
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
      assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_all_members').first<any>()).total, 2);
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

test('native and static MCP/search agree on basic word prefixes, strict filters, source pins and two-page queries', async () => {
  const current = publication('a'.repeat(40), { rowOverrides: [
    { name: 'Model predictive speed and steer control', summary: 'Path tracking sample', aliases: ['MPC', 'steering control', 'kuka grasp'] },
    { name: 'Dynamic window approach', summary: 'Navigation sample', aliases: ['DWA'], capabilities: ['navigation'] },
    { name: 'Hardware SDK', summary: '\uB85C\uBD07 SDK sample', aliases: [] }
  ] });
  const search = JSON.stringify({ schema_version: '1', hub_commit: current.version.hub_commit, counts: { recipes: 1, references: 2, memories: 1 }, records: current.rows });
  current.resources.set('/catalog/v1/search.json', search); current.version.resources.search = { sha256: hash(search) }; current.resources.set('/catalog/v1/version.json', JSON.stringify(current.version));
  const s = await runtime(current); try {
    const queries = ['DWA', '!!!DWA!!!', 'dyn nav', 'dynamic\u2013window/navigation', 'ware', 'DWA missingterm', 'DWA OR hardware', 'MPC', 'speed steering', 'model predictive speed steering', '\uB85C\uBD07 SDK', '\uC5C6\uB294\uB2E8\uC5B4', '---', '!!!', '/_', '', '  '];
    const paths = [...queries.map(q => '/v1/search?q=' + encodeURIComponent(q)),
      '/v1/search?q=DWA&runtime=ros2', '/v1/search?q=DWA&robot=kuka_iiwa', '/v1/search?q=DWA&runtime=ros2&robot=kuka_iiwa',
      '/v1/search?q=DWA&os=linux', '/v1/search?q=DWA&kind=preparation_recipe', '/v1/search?q=---&limit=2&offset=5',
      '/v1/search?q=kuka-grasp&limit=1'];
    const staticResults = new Map<string, any>();
    for (const path of paths) {
      const result = await s.read(path); assert.equal(result.status, 200); assert.equal(result.body.backend, 'static_v1_fallback');
      assert.equal(result.body.search_semantics, 'all_terms_word_prefix'); staticResults.set(path, result.body);
    }
    assert.deepEqual(staticResults.get('/v1/search?q=DWA').results.map((row: any) => row.id), ['kuka-grasp']);
    assert.equal(staticResults.get('/v1/search?q=speed%20steering').total, 1);
    assert.equal(staticResults.get('/v1/search?q=ware').total, 0);
    assert.equal(staticResults.get('/v1/search?q=DWA&runtime=ros2&robot=kuka_iiwa').total, 0, 'Discovery labels cannot manufacture a compatibility combination');
    assert.equal(staticResults.get('/v1/search?q=kuka-grasp&limit=1').results[0].id, 'kuka-grasp', 'Exact source ID precedes a matching recipe alias');
    const mcp = async () => {
      const response = await s.mf.dispatchFetch(API + '/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', DNT: '1', 'X-RSH-Telemetry': 'off' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'find_robot_skills', arguments: { q: '!!!DWA!!!', limit: 1, offset: 0, hub_commit: current.version.hub_commit } } }) });
      assert.equal(response.status, 200); const body = await response.json() as any; assert.equal(body.result.isError, false); return body.result.structuredContent;
    };
    const staticMcp = await mcp(); assert.equal(staticMcp.backend, 'static_v1_fallback'); assert.equal(staticMcp.total, 1);
    const pages = async () => {
      const first = await s.read('/v1/search?q=sample&limit=2');
      assert.equal(first.body.total, 3); assert.deepEqual(first.body.next, { q: 'sample', limit: 2, offset: 2, hub_commit: current.version.hub_commit });
      const second = await s.read('/v1/search?' + new URLSearchParams(first.body.next));
      assert.equal(second.body.next, null); assert.equal(second.body.results.length, 1);
      const rows = [...first.body.results, ...second.body.results];
      assert.equal(new Set(rows.map(row => row.id)).size, 3);
      rows.forEach(row => { assert.equal(row.source_commit, 'b'.repeat(40)); assert.equal(row.source_sha256, 'c'.repeat(64)); });
      return [first.body, second.body];
    };
    const staticPages = await pages(); await s.complete();
    const withoutBackend = ({ backend, ...body }: any) => body;
    for (const path of paths) {
      const result = await s.read(path); assert.equal(result.status, 200); assert.equal(result.body.backend, 'd1_fts5');
      assert.deepEqual(withoutBackend(result.body), withoutBackend(staticResults.get(path)), path);
    }
    const nativeMcp = await mcp(); assert.equal(nativeMcp.backend, 'd1_fts5'); assert.deepEqual(withoutBackend(nativeMcp), withoutBackend(staticMcp));
    const nativePages = await pages();
    assert.deepEqual(nativePages.map(withoutBackend), staticPages.map(withoutBackend));
    const fts = await s.db.prepare("SELECT count(*) total FROM catalog_fts WHERE catalog_fts MATCH 'dwa*'").first<any>(); assert.equal(fts.total, 1, 'Real native FTS excludes Hardware');
  } finally { await s.mf.dispose(); }
});

test('native FTS and static/MCP agree on query-only A*/D* literals and rejected embedded spellings', async () => {
  const current = publication('a'.repeat(40), { rowOverrides: [
    { name: 'Hybrid AStar grid planner', summary: 'Grid route', aliases: ['AStar', 'A*', 'Hybrid AStar'] },
    { name: 'DStarLite incremental planner', summary: 'Incremental route', aliases: ['DStarLite', 'D* Lite'] },
    { name: 'Algebra dynamics', summary: 'Ordinary algorithm terms and literal A* D* text',
      aliases: ['RA', 'A B', 'D B', 'A variable', '\u00e9A', '\uB85C\uBD07A', 'A*', 'D*'] }
  ] });
  const search = JSON.stringify({ schema_version: '1', hub_commit: current.version.hub_commit, counts: { recipes: 1, references: 2, memories: 1 }, records: current.rows });
  current.resources.set('/catalog/v1/search.json', search); current.version.resources.search = { sha256: hash(search) }; current.resources.set('/catalog/v1/version.json', JSON.stringify(current.version));
  const cases: [string, string[]][] = [
    ...['A*', 'a*', '!!!A*!!!', '(A*)/grid', 'AStar grid', 'Hybrid A*'].map(q => [q, ['maniskill-panda-pick-cube']] as [string, string[]]),
    ...['D*', 'd* lite', '(D*)/incremental', 'DStarLite'].map(q => [q, ['kuka-grasp']] as [string, string[]]),
    ...['RA*', 'A*B', 'D*B', 'a_variable*', '\u00e9A*', '\uB85C\uBD07A*', 'algebra dynamics'].map(q => [q, ['source-2']] as [string, string[]]),
    ...['A**', '*A*', '_A*', 'A*_', '\u0301A*', 'A*\u0301', 'a'].map(q => [q, ['maniskill-panda-pick-cube', 'source-2']] as [string, string[]]),
    ['D**', ['kuka-grasp', 'source-2']], ['A* impossible', []], ['A* OR dynamics', []]
  ];
  const s = await runtime(current); try {
    const outputs = new Map<string, any>();
    const mcp = async (q: string) => {
      const response = await s.mf.dispatchFetch(API + '/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', DNT: '1', 'X-RSH-Telemetry': 'off' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'find_robot_skills', arguments: { q } } }) });
      assert.equal(response.status, 200); const body = await response.json() as any; assert.equal(body.result.isError, false); return body.result.structuredContent;
    };
    for (const [q, expected] of cases) {
      const result = await s.read('/v1/search?q=' + encodeURIComponent(q));
      assert.equal(result.status, 200); assert.equal(result.body.backend, 'static_v1_fallback');
      assert.deepEqual(result.body.results.map((row: any) => row.id), expected, 'Static ' + q);
      outputs.set(q, result.body);
    }
    const staticMcp = await mcp('D* Lite'); assert.equal(staticMcp.backend, 'static_v1_fallback'); assert.deepEqual(staticMcp.results.map((row: any) => row.id), ['kuka-grasp']);
    await s.complete();
    const withoutBackend = ({ backend, ...body }: any) => body;
    for (const [q, expected] of cases) {
      const result = await s.read('/v1/search?q=' + encodeURIComponent(q));
      assert.equal(result.status, 200); assert.equal(result.body.backend, 'd1_fts5');
      assert.equal(result.body.search_semantics, 'all_terms_word_prefix');
      assert.deepEqual(result.body.results.map((row: any) => row.id), expected, 'Native ' + q);
      assert.deepEqual(withoutBackend(result.body), withoutBackend(outputs.get(q)), q);
    }
    const nativeMcp = await mcp('D* Lite'); assert.equal(nativeMcp.backend, 'd1_fts5'); assert.deepEqual(withoutBackend(nativeMcp), withoutBackend(staticMcp));
    const literalOnly = await s.db.prepare("SELECT count(*) total FROM catalog_fts WHERE catalog_fts MATCH 'astar*'").first<any>();
    assert.equal(literalOnly.total, 1, 'Document A* literals remain ordinary a tokens; only a declared AStar word matches');
  } finally { await s.mf.dispose(); }
});

test('native FTS and MCP preserve plain RRT prefixes while canonical RRT* selects its named variant', async () => {
  const current = publication('a'.repeat(40), { rowOverrides: [
    { name: 'RRT planner', summary: 'Sampling routes', aliases: ['RRT', 'Rapidlyexploring random tree'] },
    { name: 'RRTStar planner', summary: 'Optimal routes', aliases: ['RRTStar', 'RRT*', 'Rapidlyexploring random tree star'] },
    { name: 'Query syntax notes', summary: 'Literal RRT* notation', aliases: ['RRRT', 'RRT B', '2RRT', '\u00e9RRT', '\uB85C\uBD07RRT', 'RRT*'] }
  ] });
  const search = JSON.stringify({ schema_version: '1', hub_commit: current.version.hub_commit, counts: { recipes: 1, references: 2, memories: 1 }, records: current.rows });
  current.resources.set('/catalog/v1/search.json', search); current.version.resources.search = { sha256: hash(search) }; current.resources.set('/catalog/v1/version.json', JSON.stringify(current.version));
  const cases: [string, string[]][] = [
    ...['RRT*', 'rrt*', 'rRt*', '!!!RRT*!!!', '(RRT*)/planner', 'RRTStar', 'RRT Star'].map(q => [q, ['kuka-grasp']] as [string, string[]]),
    ...['RRRT*', 'RRT*B', '2RRT*', '\u00e9RRT*', '\uB85C\uBD07RRT*'].map(q => [q, ['source-2']] as [string, string[]]),
    ...['RRT', 'rr', 'RRT**', '*RRT*', '_RRT*', 'RRT*_', '\u0301RRT*', 'RRT*\u0301'].map(q => [q, ['maniskill-panda-pick-cube', 'kuka-grasp', 'source-2']] as [string, string[]]),
    ['RRT planner', ['maniskill-panda-pick-cube', 'kuka-grasp']], ['RRT* sampling', []], ['RRT* impossible', []], ['RRT* OR sampling', []]
  ];
  const s = await runtime(current); try {
    const outputs = new Map<string, any>();
    const mcp = async (q: string) => {
      const response = await s.mf.dispatchFetch(API + '/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', DNT: '1', 'X-RSH-Telemetry': 'off' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'find_robot_skills', arguments: { q } } }) });
      assert.equal(response.status, 200); const body = await response.json() as any; assert.equal(body.result.isError, false); return body.result.structuredContent;
    };
    for (const [q, expected] of cases) {
      const result = await s.read('/v1/search?q=' + encodeURIComponent(q));
      assert.equal(result.status, 200); assert.equal(result.body.backend, 'static_v1_fallback');
      assert.deepEqual(result.body.results.map((row: any) => row.id), expected, 'Static ' + q); assert.equal(result.body.total, expected.length);
      outputs.set(q, result.body);
    }
    const staticMcp = await mcp('RRT*'); assert.equal(staticMcp.backend, 'static_v1_fallback'); assert.deepEqual(staticMcp.results.map((row: any) => row.id), ['kuka-grasp']);
    await s.complete();
    const withoutBackend = ({ backend, ...body }: any) => body;
    for (const [q, expected] of cases) {
      const result = await s.read('/v1/search?q=' + encodeURIComponent(q));
      assert.equal(result.status, 200); assert.equal(result.body.backend, 'd1_fts5');
      assert.equal(result.body.search_semantics, 'all_terms_word_prefix');
      assert.deepEqual(result.body.results.map((row: any) => row.id), expected, 'Native ' + q);
      assert.deepEqual(withoutBackend(result.body), withoutBackend(outputs.get(q)), q);
    }
    const nativeMcp = await mcp('RRT*'); assert.equal(nativeMcp.backend, 'd1_fts5'); assert.deepEqual(withoutBackend(nativeMcp), withoutBackend(staticMcp));
    const literalOnly = await s.db.prepare("SELECT count(*) total FROM catalog_fts WHERE catalog_fts MATCH 'rrtstar*'").first<any>();
    assert.equal(literalOnly.total, 1, 'Literal-only RRT* documents do not acquire the RRTStar word');
    const filtered = await s.read('/v1/search?q=RRT*&kind=preparation_recipe'); assert.equal(filtered.body.total, 0);
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
    const algorithmQueries: Array<[string, string[]]> = [
      ['A*', ['pythonrobotics-pathplanning-astar-a-star-py', 'pythonrobotics-pathplanning-hybridastar-hybrid-a-star-py', 'pyrobosim-pyrobosim-examples-demo-astar-py', 'nav2-smac-hybrid-planner']],
      ['D* Lite', ['pythonrobotics-pathplanning-dstarlite-d-star-lite-py']],
      ['Hybrid A* path planning', ['pythonrobotics-pathplanning-hybridastar-hybrid-a-star-py', 'nav2-smac-hybrid-planner']],
      ['rapidly exploring random tree', ['pyrobosim-pyrobosim-examples-demo-rrt-py', 'pythonrobotics-pathplanning-rrt-rrt-py']],
      ['RRT*', ['pyrobosim-pyrobosim-examples-demo-rrt-py', 'pythonrobotics-pathplanning-rrtstar-rrt-star-py']],
      ['SLAM', ['pythonrobotics-slam-ekfslam-ekf-slam-py', 'pythonrobotics-slam-fastslam1-fast-slam1-py']],
      ['EKF localization PythonRobotics', ['pythonrobotics-localization-extended-kalman-filter-extended-kalman-filter-py']],
      ['pure pursuit', ['pythonrobotics-pathtracking-pure-pursuit-pure-pursuit-py', 'nav2-regulated-pure-pursuit-controller']],
      ['Stanley steering', ['pythonrobotics-pathtracking-stanley-control-stanley-control-py']],
      ['IK pinocchio', ['pinocchio-examples-inverse-kinematics-3d-cpp', 'pinocchio-examples-inverse-kinematics-3d-py', 'pinocchio-examples-inverse-kinematics-cpp', 'pinocchio-examples-inverse-kinematics-py']],
    ];
    for (const [query, expectedIds] of algorithmQueries) {
      const result = await s.read('/v1/search?' + new URLSearchParams({ q: query, limit: '50' }));
      assert.equal(result.body.backend, 'd1_fts5', query);
      assert.equal(result.body.total, expectedIds.length, query);
      assert.deepEqual(result.body.results.map((row: any) => row.id).sort(), [...expectedIds].sort(), query);
    }
    const newSourceIds = [
      'pythonrobotics-localization-extended-kalman-filter-extended-kalman-filter-py',
      'pythonrobotics-pathplanning-rrt-rrt-py', 'pythonrobotics-pathplanning-rrtstar-rrt-star-py',
      'pythonrobotics-pathtracking-pure-pursuit-pure-pursuit-py',
      'pythonrobotics-pathtracking-stanley-control-stanley-control-py',
      'pythonrobotics-slam-ekfslam-ekf-slam-py', 'pythonrobotics-slam-fastslam1-fast-slam1-py',
    ];
    for (const id of newSourceIds) {
      const record = await load('references/' + id + '/skill.json');
      const inspected = await s.read('/v1/skills/' + id + '?record_version=source-' + record.source.sha256);
      assert.equal(inspected.status, 200, id);
      assert.deepEqual(inspected.body.record, record, id);
      assert.equal(inspected.body.record.evidence.runtime_verification, 'not_run', id);
    }
    const docs = await s.db.prepare('SELECT count(*) total FROM catalog_documents').first<any>(); assert.equal(docs.total, manifest.records);
    assert.equal((await s.db.prepare('SELECT count(*) total FROM catalog_memory_documents').first<any>()).total, memories.records);
  } finally { await s.mf.dispose(); }
});
