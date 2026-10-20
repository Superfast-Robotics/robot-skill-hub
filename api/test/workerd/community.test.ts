import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { Miniflare } from 'miniflare';
import { canonical } from '../../src/util.ts';
import { applyPatch, parsePatch } from '../../src/patch.ts';
import { execFileSync } from 'node:child_process';

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
  for (const name of ['0001_catalog.sql', '0002_page_memberships.sql', '0003_community.sql', '0004_community_capacity_guards.sql']) {
    const sql = await readFile(new URL('../../migrations-catalog/' + name, import.meta.url), 'utf8');
    await db.exec(sql.replace(/--[^\n]*/g, '').replace(/\s+/g, ' '));
  }
  await db.prepare('INSERT INTO catalog_generations(hub_commit,manifest_sha256,manifest_json,total_pages,total_records,created_at) VALUES(?,?,?,?,?,?)').bind(base.hub_commit, '0'.repeat(64), '{}', 1, 1, 1).run();
  const row = { id: 'fixture-pick', kind: 'preparation_recipe', record_version: base.record_version, source_commit: base.source_commit,
    license: { spdx: 'Apache-2.0', verified: true }, adapter_license: { spdx: 'MIT', verified: true } };
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

test('native variant licenses distinguish Hub-owned adapters from upstream and reject mixed scopes', async () => {
  const s = await runtime(); try {
    const writer = await s.enroll();
    const diff = (path: string) => `--- a/${path}\n+++ b/${path}\n@@ -1 +1 @@\n-a\n+b\n`;
    const owned = 'recipes/fixture-pick/run.py';
    const submit = (patch: string, license_spdx: string, n: number) => s.call('/items', {
      schema_version: '1', finding: finding(n), variant: { patch, license_spdx }
    }, writer.token);
    assert.equal((await submit(diff(owned), 'MIT', 40)).status, 201);
    assert.equal((await submit(diff('demo.py'), 'MIT', 41)).status, 422);
    assert.equal((await submit(diff('demo.py'), 'Apache-2.0', 42)).status, 201);
    assert.equal((await submit(diff(owned) + diff('demo.py'), 'MIT', 43)).status, 422);
    assert.equal((await submit(diff(owned) + diff('demo.py'), 'Apache-2.0', 44)).status, 422);
    assert.equal((await submit(diff('recipes/different-id/run.py'), 'MIT', 45)).status, 422);
    await s.db.prepare("UPDATE catalog_documents SET row_json=json_set(row_json,'$.adapter_license.verified',json('false'))").run();
    assert.equal((await submit(diff('recipes/fixture-pick/requirements.txt'), 'MIT', 46)).status, 422);
  } finally { await s.mf.dispose(); }
});

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
    await s.db.prepare('INSERT INTO catalog_active(singleton,hub_commit) VALUES(1,?)').bind(base.hub_commit).run();
    const retired = { schema_version: '1', finding: { ...finding(3), base: { ...base, hub_commit: 'c'.repeat(40) } } };
    const originalPins = await s.call('/items', retired, a.token);
    assert.equal(originalPins.status, 201, JSON.stringify(originalPins));
    assert.equal(originalPins.body.content.finding.base.hub_commit, retired.finding.base.hub_commit, 'identical active source pins do not rewrite the original generation');
    const exportPage = await s.call('/export');
    assert.equal(exportPage.body.rows.length, 4);
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
    await s.db.prepare("UPDATE catalog_documents SET row_json=json_set(row_json,'$.license.verified',json('false'))").run();
    assert.equal((await s.call('/items', { schema_version: '1', finding: finding(), variant: { patch: '--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-a\n+b\n', license_spdx: 'Apache-2.0' } }, a.token)).status, 422, 'unverified source licenses do not authorize automatic patch publication');
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

test('agent instruction and case-folded metadata patch targets are rejected before storage', async () => {
  const s = await runtime(); try {
    const a = await s.enroll();
    for (const path of ['CLAUDE.md', 'docs/GEMINI.md', 'src/.Git/config', 'src/.GITHUB/workflows/build.yml', 'src/.codex/config.toml', 'src/.agents/skills/task/instructions.md', 'docs/copilot-instructions.md', 'src/config.py.']) {
      const result = await s.call('/items', { schema_version: '1', finding: finding(), variant: {
        patch: `--- a/${path}\n+++ b/${path}\n@@ -1 +1 @@\n-a\n+b\n`, license_spdx: 'Apache-2.0'
      } }, a.token);
      assert.equal(result.status, 422, path + ': ' + JSON.stringify(result));
    }
    assert.equal((await s.db.prepare('SELECT items FROM community_storage_budget').first<any>()).items, 0);
  } finally { await s.mf.dispose(); }
});

test('revocation, quarantine, capacity and malformed input preserve original content and budgets', async () => {
  const s = await runtime(); try {
    const a = await s.enroll(), b = await s.enroll();
    const item = await s.call('/items', { schema_version: '1', finding: finding() }, a.token);
    assert.equal(item.status, 201);
    const before = await s.db.prepare('SELECT * FROM community_storage_budget').first<any>();
    await s.db.prepare('UPDATE community_items SET hidden=1 WHERE id=?').bind(item.body.id).run();
    assert.equal((await s.call('/items/' + item.body.id)).status, 404);
    assert.equal((await s.call('/items', { schema_version: '1', finding: finding() }, b.token)).status, 409);
    assert.deepEqual((await s.call(s.query())).body.results, []);
    assert.deepEqual((await s.call('/export')).body.rows, [{ sequence: 1, id: item.body.id, hidden: true }]);
    await s.db.prepare('UPDATE community_principals SET disabled=1 WHERE id=?').bind(hash(b.token)).run();
    assert.equal((await s.call('/items', { schema_version: '1', finding: finding(1) }, b.token)).status, 401);
    assert.equal((await s.call('/enroll', b.payload)).status, 401);
    assert.deepEqual(await s.db.prepare('SELECT * FROM community_storage_budget').first<any>(), before);
    await s.db.prepare('UPDATE community_storage_budget SET bytes=67108864').run();
    const full = await s.call('/items', { schema_version: '1', finding: finding(2) }, a.token);
    assert.equal(full.status, 503);
    assert.equal(full.body.reason_code, 'community_capacity');
    assert.equal((await s.db.prepare('SELECT count(*) n FROM community_items').first<any>()).n, 1);
    for (const value of [null, [], {}, {schema_version:'1',finding:null}])
      assert.equal((await s.call('/items', value, a.token)).status, 422);
    assert.equal((await s.call('/items', {padding:'x'.repeat(33000)}, a.token)).status, 413);
  } finally { await s.mf.dispose(); }
});

test('capacity guards serialize concurrent writes and preserve duplicate retries at every limit', async () => {
  const s = await runtime(); try {
    const a = await s.enroll(), b = await s.enroll();
    const values = [1,2].map(n => ({schema_version:'1',finding:finding(n)}));
    const bytes = Buffer.byteLength(canonical(values[0]));
    assert.equal(bytes, Buffer.byteLength(canonical(values[1])));
    await s.db.prepare('UPDATE community_storage_budget SET bytes=?').bind(67108864-bytes).run();
    const results = await Promise.all(values.map(v => s.call('/items',v,a.token)));
    assert.deepEqual(results.map(r=>r.status).sort(),[201,503]);
    const winner = results.findIndex(r=>r.status===201);
    assert.equal((await s.db.prepare('SELECT count(*) n FROM community_items').first<any>()).n,1);
    assert.equal((await s.db.prepare('SELECT bytes FROM community_storage_budget').first<any>()).bytes,67108864);
    assert.equal((await s.call('/items',values[winner],a.token)).status,200);
    await s.db.prepare('UPDATE community_storage_budget SET attestations=100000').run();
    assert.equal((await s.call('/items',values[winner],b.token)).status,503);
    assert.equal((await s.db.prepare('SELECT count(*) n FROM community_attestations').first<any>()).n,1);
    await s.db.prepare('UPDATE community_storage_budget SET principals=10000').run();
    assert.equal((await s.enroll('192.0.2.9')).result.status,503);
    assert.equal((await s.call('/enroll',a.payload)).status,200);
    assert.equal((await s.db.prepare('SELECT count(*) n FROM community_principals').first<any>()).n,2);
  } finally { await s.mf.dispose(); }
});

test('controlled IK task transfers a saved correction to a separate reader and reports held-out outcomes', async () => {
  const s = await runtime(); try {
    // Authored numerical fixture, not an upstream skill or autonomous LLM trial.
    // Only these exact known bytes may execute. Never execute an arbitrary Hub patch.
    const before = 'export function ik(x,y) { const b=Math.acos((x*x+y*y-2)/2); return [Math.atan(y/x)-Math.atan2(Math.sin(b),1+Math.cos(b)),b]; }\n';
    const after = before.replace('Math.atan(y/x)','Math.atan2(y,x)');
    const patch = `--- a/ik.mjs\n+++ b/ik.mjs\n@@ -1 +1 @@\n-${before}+${after}`;
    const cases = (count:number, offset:number) => Array.from({length:count},(_,i)=>{
      const angle=2*Math.PI*(i+offset)/count, radius=0.7+0.9*((i%5)/4);
      return [radius*Math.cos(angle),radius*Math.sin(angle)];
    });
    function score(source:string, points:number[][]) {
      assert.ok(source===before||source===after,'Only the authored fixture can execute');
      const runner = source + '\nconst points=JSON.parse(process.argv[1]); const errors=points.map(([x,y])=>{const[a,b]=ik(x,y);return Math.hypot(Math.cos(a)+Math.cos(a+b)-x,Math.sin(a)+Math.sin(a+b)-y)});console.log(JSON.stringify({total:errors.length,passed:errors.filter(e=>Number.isFinite(e)&&e<1e-9).length}));';
      return JSON.parse(execFileSync(process.execPath,['--input-type=module','-e',runner,JSON.stringify(points)],{encoding:'utf8',timeout:5000,maxBuffer:4096}));
    }
    const development=cases(8,0.2), heldout=cases(24,0.37);
    const baseline=score(before,development), baselineHeldout=score(before,heldout);
    assert.ok(baseline.passed<baseline.total);
    const writer=await s.enroll(), reader=await s.enroll();
    const note={...finding(),summary:'Preserve the target quadrant in planar two-link inverse kinematics',
      observation:`Controlled authored CPU fixture: ${baseline.passed}/${baseline.total} development targets passed with atan(y/x). This is not robot or simulator execution.`,
      resolution:'Use atan2(y,x) for the target bearing; preserve the elbow-angle calculation.',
      environment:{runtime:'node',robot:'planar-two-link-fixture'},
      evidence:{level:'contributor_reported',command:'node numerical IK fixture',result:'Development residual tolerance is 1e-9; this is a controlled maintainer test, not independent agent adoption.',reported_by:'submitter'}};
    const published=await s.call('/items',{schema_version:'1',finding:note,variant:{patch,license_spdx:'Apache-2.0'}},writer.token);
    assert.equal(published.status,201);
    const recalled=await s.call(s.query({environment:JSON.stringify(note.environment)}));
    assert.equal(recalled.body.results[0].id,published.body.id,'credential-free reader discovers the correction');
    const selected=(await s.call('/items/'+published.body.id)).body;
    assert.equal(hash(canonical(selected.content)),selected.content_sha256);
    assert.equal(selected.content.variant.patch,patch);
    const corrected=applyPatch(before,parsePatch(selected.content.variant.patch)[0]);
    const outcome=score(corrected,heldout);
    assert.deepEqual(outcome,{total:24,passed:24});
    assert.ok(baselineHeldout.passed<outcome.passed);
    const report=await s.call('/items',{schema_version:'1',finding:{...note,summary:'Held-out numerical target reuse result',
      observation:`Separate reader process used the retrieved exact correction: ${outcome.passed}/${outcome.total} held-out target residuals below 1e-9.`,
      evidence:{...note.evidence,result:'Controlled CPU kinematics only. No physical robot, simulator or LLM token measurement.'}},parent_id:published.body.id,outcome:'succeeded'},reader.token);
    assert.equal(report.status,201);
    assert.equal((await s.call(s.query({environment:JSON.stringify(note.environment)}))).body.results[0].reuse_reports.succeeded,1);
    assert.deepEqual((await s.call(s.query({environment:JSON.stringify({runtime:'node',robot:'different-robot'})}))).body.results,[]);
    console.log(JSON.stringify({controlled_reuse_experiment:true,baseline_development:baseline,baseline_heldout:baselineHeldout,reused_heldout:outcome,independent_agent_adoption:false,robot_execution:false}));
  } finally { await s.mf.dispose(); }
});


test('malformed environment and enrollment types are refused without widening recall or writing', async () => {
  const s=await runtime(); try {
    const a=await s.enroll();
    await s.call('/items',{schema_version:'1',finding:finding()},a.token);
    for(const environment of ['null','false','0','""','[]','{"robot":" "}','{"robot":"panda\\u0000"}']) {
      const result=await s.call(s.query({environment}));
      assert.equal(result.status,422,environment+' must not broaden to all environments');
    }
    const before=await s.db.prepare('SELECT * FROM community_storage_budget').first<any>();
    const malformed=await s.call('/enroll',{...a.payload,token:[a.token]});
    assert.equal(malformed.status,422,'token arrays must not coerce to a valid credential');
    const parent=(await s.call(s.query())).body.results[0].id;
    assert.equal((await s.call('/items',{schema_version:'1',finding:finding(2),parent_id:[parent]},a.token)).status,422);
    const unicodePatch='--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-old\n+'+'\uac00'.repeat(4000)+'\n';
    assert.equal((await s.call('/items',{schema_version:'1',finding:finding(3),variant:{patch:unicodePatch,license_spdx:'Apache-2.0'}},a.token)).status,422,'patch size is bounded in UTF-8 bytes');
    assert.deepEqual(await s.db.prepare('SELECT * FROM community_storage_budget').first<any>(),before);
  } finally {await s.mf.dispose();}
});
