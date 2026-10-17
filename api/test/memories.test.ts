import test from 'node:test';
import assert from 'node:assert/strict';
import { createHandler } from '../src/index.ts';
import { findingFingerprint, memoryContent, memoryMarker, readMemory } from '../src/memories.ts';
import { ApiError, memoryPath, type Checks, type Env, type MemoryEntry, type MemoryFinding, type MemoryGitHubAdapter, type Pull } from '../src/types.ts';
import { canonical, sha256 } from '../src/util.ts';
import { GitHub } from '../src/github.ts';

const HUB = 'a'.repeat(40), HEAD = 'c'.repeat(40), SOURCE = 'b'.repeat(40);
const TOKEN = 'memory_pilot_012345678901234567890123456789';
const SKILL = 'maniskill-panda-pick-cube';
function finding(): MemoryFinding {
  return { schema_version: '1', skill_id: SKILL, base: { record_version: '1.0.0', hub_commit: HUB, source_commit: SOURCE },
    kind: 'missing_requirement', summary: 'Report missing planner dependency', observation: 'The source preparation completed, but the requested planner dependency was absent.',
    resolution: null, environment: { runtime: 'maniskill', robot: 'panda', os: 'linux', 'package.mplib': 'missing' },
    evidence: { level: 'contributor_reported', command: 'python -c "import mplib"', result: 'ModuleNotFoundError for mplib; simulator was not run.', reported_by: 'submitter' },
    attribution: { contributor_label: 'Memory pilot', preserve_upstream_attribution: true }, publication: { public_submission_allowed: true } };
}
class MemoryGitHub implements MemoryGitHubAdapter {
  head = HEAD; headReads = 0; branchCreates = 0; prCreates = 0; failPR = 0; ancestor = true;
  checks: Checks = { state: 'pending', completed: 0, reasons: [] };
  branches = new Map<string, { sha: string; base: string; files: Record<string, string> }>();
  pulls = new Map<string, Pull>(); ancestry = new Map<string, boolean>(); calls: [string, string][] = [];
  records: Record<string, any> = { [HUB]: { id: SKILL, maintenance: { record_version: '1.0.0' }, source: { commit: SOURCE } } };
  references: Record<string, any> = {}; referenceReads = 0;
  mainFiles: Record<string, string> = {};
  async getHead() { this.headReads++; return this.head; }
  async getFile(path: string, ref: string) {
    const branch = [...this.branches.values()].find(value => value.sha === ref);
    if (branch) return branch.files[path] ?? null;
    if (ref === this.head && this.mainFiles[path] !== undefined) return this.mainFiles[path];
    if (path === 'catalog/references.json') { this.referenceReads++; return this.references[ref] ? JSON.stringify(this.references[ref]) : null; }
    return path === `catalog/records/${SKILL}.json` && this.records[ref] ? JSON.stringify(this.records[ref]) : null;
  }
  async isAncestor(ancestor: string, descendant: string) { this.calls.push([ancestor, descendant]); return this.ancestry.get(`${ancestor}...${descendant}`) ?? this.ancestor; }
  async getChecks() { return this.checks; }
  async findMemoryPull(id: string) { return this.pulls.get(id) ?? null; }
  async getMemoryBranch(id: string) { return this.branches.get(id)?.sha ?? null; }
  async createMemoryBranch(id: string, base: string, entry: MemoryEntry) {
    await Promise.resolve(); if (this.branches.has(id)) return false;
    this.branchCreates++; this.branches.set(id, { sha: String(this.branchCreates).padStart(40, '0'), base, files: { [memoryPath(id)]: memoryContent(entry) } }); return true;
  }
  async createMemoryPull(entry: MemoryEntry) {
    await Promise.resolve(); const prior = this.pulls.get(entry.memory_id); if (prior) return prior;
    if (this.failPR-- > 0) throw new ApiError(503, 'github_unavailable', 'Injected PR outage.');
    this.prCreates++; const pull: Pull = { number: this.prCreates, html_url: `https://github.com/Superfast-Robotics/robot-skill-hub/pull/${this.prCreates}`,
      body: memoryMarker(entry), state: 'open', merged_at: null, merge_commit_sha: null, labels: [], head: { sha: this.branches.get(entry.memory_id)!.sha, ref: `memories/${entry.memory_id}` } };
    this.pulls.set(entry.memory_id, pull); return pull;
  }
  async findPull(): Promise<never> { throw new Error('Patch endpoint must not be used'); }
  async getBranch(): Promise<never> { throw new Error('Patch endpoint must not be used'); }
  async createBranch(): Promise<never> { throw new Error('Patch endpoint must not be used'); }
  async createPull(): Promise<never> { throw new Error('Patch endpoint must not be used'); }
  async closeSuperseded(): Promise<never> { throw new Error('Patch endpoint must not be used'); }
  async findSuperseding(): Promise<never> { throw new Error('Patch endpoint must not be used'); }
}
async function setup() {
  const github = new MemoryGitHub();
  const env: Env = { GITHUB_TOKEN: 'dummy-token', SUBMISSION_TOKENS_JSON: JSON.stringify([{ principal_id: 'memory-pilot', sha256: await sha256(TOKEN) }]),
    PUBLICATION_URL: 'https://example.invalid/publication.json', SUBMIT_LIMITER: { async limit() { return { success: true }; } }, STATUS_LIMITER: { async limit() { return { success: true }; } } };
  let manifest: any = {}; let unavailable = false;
  const handler = createHandler(() => github, async () => { if (unavailable) throw Error('offline'); return manifest; });
  const post = (body: any = finding(), token = TOKEN, headers: Record<string, string> = {}) => handler(new Request('https://api.example/v1/memories', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...headers }, body: typeof body === 'string' ? body : JSON.stringify(body) }), env);
  const status = (id: string, token = TOKEN) => handler(new Request(`https://api.example/v1/memories/${id}`, { headers: { Authorization: `Bearer ${token}` } }), env);
  return { github, env, handler, post, status, setManifest(value: any) { manifest = value; }, setUnavailable() { unavailable = true; } };
}

test('memory fingerprint is portable, ignores attribution and catalog HEAD, and preserves the first finding', async () => {
  const s = await setup(); const first: any = await (await s.post()).json();
  assert.match(first.memory_id, /^mem_[a-f0-9]{64}$/); assert.equal(first.status, 'stored');
  const branch = s.github.branches.get(first.memory_id)!; assert.equal(branch.base, HEAD);
  assert.deepEqual(Object.keys(branch.files), [memoryPath(first.memory_id)]);
  assert.equal(first.content_sha256, await sha256(branch.files[memoryPath(first.memory_id)]));
  const entry = readMemory(s.github.pulls.get(first.memory_id)!.body)!;
  const expected = finding(); const { attribution, publication, base, ...content } = expected;
  assert.equal(entry.fingerprint, await sha256(canonical({ ...content, base: { record_version: base.record_version, source_commit: base.source_commit } })));
  assert.equal(entry.hub_validation.runtime, 'not_run'); assert.equal(entry.evidence.level, 'contributor_reported');
  const duplicate = finding(); duplicate.base.hub_commit = HEAD; duplicate.attribution.contributor_label = 'A different label';
  s.github.records[HEAD] = s.github.records[HUB];
  const response = await s.post(duplicate); assert.equal(response.status, 200); const replay: any = await response.json();
  assert.equal(replay.memory_id, first.memory_id); assert.equal(replay.content_sha256, first.content_sha256); assert.deepEqual(replay.base, first.base);
  assert.equal(readMemory(s.github.pulls.get(first.memory_id)!.body)!.attribution.contributor_label, 'Memory pilot');
  assert.equal(s.github.branchCreates, 1); assert.equal(s.github.prCreates, 1);
});

test('concurrent memory saves and branch-only recovery create one durable PR without replacing receipts', async () => {
  const s = await setup(); const replies = await Promise.all(Array.from({ length: 10 }, () => s.post()));
  const data: any[] = []; for (const reply of replies) { assert.ok([200, 201].includes(reply.status)); data.push(await reply.json()); }
  assert.equal(new Set(data.map(value => value.memory_id)).size, 1); assert.equal(new Set(data.map(value => value.content_sha256)).size, 1);
  assert.equal(s.github.branchCreates, 1); assert.equal(s.github.prCreates, 1);
  const recovery = await setup(); recovery.github.failPR = 1; assert.equal((await recovery.post()).status, 503);
  const saved = [...recovery.github.branches.values()][0].files; const reads = recovery.github.headReads;
  recovery.github.head = 'd'.repeat(40); const response = await recovery.post(); assert.equal(response.status, 200);
  assert.equal(recovery.github.branchCreates, 1); assert.equal(recovery.github.prCreates, 1); assert.equal(recovery.github.headReads, reads);
  assert.deepEqual([...recovery.github.branches.values()][0].files, saved);
});

test('memory intake validates the exact original catalog record and main-history base before writing', async () => {
  for (const mutate of [(f: MemoryFinding) => { f.base.record_version = 'wrong'; }, (f: MemoryFinding) => { f.base.source_commit = 'd'.repeat(40); }, (f: MemoryFinding) => { f.skill_id = 'unknown-skill'; }]) {
    const s = await setup(); const body = finding(); mutate(body); const response = await s.post(body);
    assert.equal(response.status, 409); assert.equal((await response.json() as any).reason_code, 'stale_record'); assert.equal(s.github.branchCreates, 0);
  }
  const s = await setup(); s.github.ancestor = false; const response = await s.post(); assert.equal(response.status, 409);
  assert.equal((await response.json() as any).reason_code, 'stale_base'); assert.equal(s.github.branchCreates, 0);
});

test('an existing main memory is never overwritten if its PR linkage needs operator repair', async () => {
  const s = await setup(); const saved: any = await (await s.post()).json();
  const path = memoryPath(saved.memory_id); const bytes = s.github.branches.get(saved.memory_id)!.files[path];
  s.github.mainFiles[path] = bytes; s.github.pulls.clear(); s.github.branches.clear();
  const response = await s.post(); assert.equal(response.status, 409); const body: any = await response.json();
  assert.equal(body.reason_code, 'memory_entry_exists'); assert.equal(body.next_action, 'keep_local_finding_and_continue_user_task');
  assert.equal(s.github.mainFiles[path], bytes); assert.equal(s.github.branchCreates, 1); assert.equal(s.github.prCreates, 1);
});

test('pinned source references accept findings without granting recipe preparation capability', async () => {
  const s = await setup(); const body = finding(); const sourceHash = '4'.repeat(64);
  body.skill_id = 'mujoco-basic'; body.base.record_version = 'source-' + sourceHash; body.environment = { runtime: 'mujoco', robot: 'unknown' };
  const reference = { id: body.skill_id, source: { commit: SOURCE, sha256: sourceHash }, access: { mode: 'source_reference', hub_prepare: false } };
  s.github.references[HUB] = { schema_version: '1', records: [reference] };
  const response = await s.post(body); assert.equal(response.status, 201); const saved: any = await response.json();
  const entry = readMemory(s.github.pulls.get(saved.memory_id)!.body)!;
  assert.equal(entry.skill_id, body.skill_id); assert.equal(entry.base.record_version, 'source-' + sourceHash); assert.equal(s.github.referenceReads, 1);
  assert.deepEqual(reference.access, { mode: 'source_reference', hub_prepare: false });
  assert.equal(entry.hub_validation.runtime, 'not_run'); assert.deepEqual(Object.keys(s.github.branches.get(saved.memory_id)!.files), [memoryPath(saved.memory_id)]);
});

test('source-reference findings reject wrong hash versions, source commits and arbitrary IDs', async () => {
  const sourceHash = '4'.repeat(64);
  for (const mutate of [(f: MemoryFinding) => { f.base.record_version = 'source-' + sourceHash.slice(0, 16); },
    (f: MemoryFinding) => { f.base.record_version = 'source-' + '5'.repeat(64); },
    (f: MemoryFinding) => { f.base.source_commit = 'd'.repeat(40); }, (f: MemoryFinding) => { f.skill_id = 'arbitrary-source'; }]) {
    const s = await setup(); s.github.references[HUB] = { schema_version: '1', records: [{ id: 'mujoco-basic', source: { commit: SOURCE, sha256: sourceHash } }] };
    const body = finding(); body.skill_id = 'mujoco-basic'; body.base.record_version = 'source-' + sourceHash; mutate(body);
    const response = await s.post(body); assert.equal(response.status, 409); assert.equal((await response.json() as any).reason_code, 'stale_record'); assert.equal(s.github.branchCreates, 0);
  }
  const s = await setup(); const body = finding(); body.base.record_version = 'source-' + sourceHash;
  s.github.references[HUB] = { schema_version: '1', records: [{ id: SKILL, source: { commit: SOURCE, sha256: sourceHash } }] };
  const response = await s.post(body); assert.equal(response.status, 409); assert.equal(s.github.referenceReads, 0, 'An existing canonical record cannot be bypassed through reference fallback');
});

test('only the pinned reference index receives a bounded 256 KiB GitHub read allowance', async () => {
  let bytes = 150 * 1024;
  const adapter = new GitHub('dedicated-token', async () => {
    const content = 'x'.repeat(bytes); return Response.json({ type: 'file', encoding: 'base64', size: bytes, content: Buffer.from(content).toString('base64') });
  });
  assert.equal((await adapter.getFile('catalog/references.json', HUB))!.length, bytes);
  await assert.rejects(adapter.getFile(`catalog/records/${SKILL}.json`, HUB), (error: unknown) => error instanceof ApiError && error.code === 'unsupported_base_file');
  await assert.rejects(adapter.getFile('catalog/other-index.json', HUB), (error: unknown) => error instanceof ApiError && error.code === 'unsupported_base_file');
  bytes = 256 * 1024 + 1;
  await assert.rejects(adapter.getFile('catalog/references.json', HUB), (error: unknown) => error instanceof ApiError && error.code === 'unsupported_base_file');
});

test('memory policy, bounded fields and recognizable credentials fail before any repository write', async () => {
  const changes: [string, (f: any) => void, number][] = [
    ['public_sharing_not_allowed', f => f.publication.public_submission_allowed = false, 403],
    ['invalid_memory', f => f.transcript = 'Do not accept a whole session.', 422],
    ['invalid_memory', f => f.patch = 'Do not accept source uploads.', 422],
    ['invalid_memory', f => f.observation = 'x'.repeat(4001), 422],
    ['invalid_environment', f => f.environment.password = 'sensitive', 422],
    ['invalid_environment', f => f.environment.runtime = { nested: 'not allowed' }, 422],
    ['invalid_environment', f => f.environment['package.python'] = 3.10, 422],
    ['invalid_environment', f => delete f.environment.robot, 422],
    ['invalid_evidence', f => f.evidence.level = 'hub_verified', 422],
    ['invalid_evidence', f => f.evidence.stdout = 'No raw logs field.', 422]
  ];
  for (const [code, mutate, http] of changes) { const s = await setup(); const body = finding(); mutate(body); const response = await s.post(body);
    assert.equal(response.status, http, code); assert.equal((await response.json() as any).reason_code, code); assert.equal(s.github.branchCreates, 0); }
  for (const secret of ['ghp_' + 'a'.repeat(30), 'github_pat_' + 'a'.repeat(30), 'sk-' + 'a'.repeat(30), 'AKIA' + 'A'.repeat(16), 'Bearer ' + 'a'.repeat(32), 'https://user:password@example.invalid', '-----BEGIN PRIVATE KEY-----']) {
    const s = await setup(); const body = finding(); body.observation += ' ' + secret; const response = await s.post(body);
    assert.equal(response.status, 422); assert.equal((await response.json() as any).reason_code, 'sensitive_memory'); assert.equal(s.github.branchCreates, 0);
  }
  const s = await setup(); assert.equal((await s.post('x'.repeat(16385))).status, 413);
  assert.equal((await s.post(finding(), TOKEN, { 'Content-Type': 'text/plain' })).status, 415);
  assert.equal((await s.post(finding(), TOKEN, { 'Content-Encoding': 'gzip' })).status, 415); assert.equal(s.github.branchCreates, 0);
});

test('memory ownership, principal-scoped deduplication and shared rate limits are enforced', async () => {
  const s = await setup(); assert.equal((await s.post(finding(), 'invalid')).status, 401);
  const first: any = await (await s.post()).json(); const otherToken = 'second_memory_token_012345678901234567890';
  s.env.SUBMISSION_TOKENS_JSON = JSON.stringify([{ principal_id: 'memory-pilot', sha256: await sha256(TOKEN) }, { principal_id: 'other-pilot', sha256: await sha256(otherToken) }]);
  assert.equal((await s.status(first.memory_id, otherToken)).status, 404);
  const other: any = await (await s.post(finding(), otherToken)).json(); assert.notEqual(other.memory_id, first.memory_id);
  s.env.SUBMIT_LIMITER = { async limit() { return { success: false }; } }; const response = await s.post();
  assert.equal(response.status, 429); assert.equal(response.headers.get('Retry-After'), '60');
  s.env.STATUS_LIMITER = { async limit() { return { success: false }; } }; assert.equal((await s.status(first.memory_id)).status, 429);
});

test('memory review states and exact publication proof never imply runtime verification', async () => {
  const s = await setup(); const saved: any = await (await s.post()).json(); const pull = s.github.pulls.get(saved.memory_id)!;
  const state = async () => await (await s.status(saved.memory_id)).json() as any;
  assert.equal((await state()).status, 'stored'); s.github.checks = { state: 'pending', completed: 1, reasons: [] }; assert.equal((await state()).status, 'checking');
  s.github.checks = { state: 'success', completed: 1, reasons: [] }; assert.equal((await state()).status, 'pending_review');
  pull.labels = [{ name: 'rsh:rejected' }]; assert.equal((await state()).status, 'rejected'); pull.labels = [];
  pull.merged_at = '2026-10-17T00:00:00Z'; pull.merge_commit_sha = 'e'.repeat(40); pull.state = 'closed';
  assert.equal((await state()).status, 'merged');
  const proof = { memory_id: saved.memory_id, skill_id: SKILL, fingerprint: saved.fingerprint, content_sha256: saved.content_sha256,
    record_version: saved.base.record_version, source_commit: saved.base.source_commit, base_hub_commit: saved.base.hub_commit, entry_url: 'https://example.invalid/memory.json' };
  const manifest = { schema_version: '1', hub_commit: 'f'.repeat(40), memories: [proof] };
  for (const field of ['memory_id', 'skill_id', 'fingerprint', 'content_sha256', 'record_version', 'source_commit', 'base_hub_commit']) {
    s.setManifest({ ...manifest, memories: [{ ...proof, [field]: 'wrong' }] }); assert.equal((await state()).status, 'merged', field);
  }
  s.setManifest(manifest); s.github.ancestor = false; assert.equal((await state()).status, 'merged');
  s.github.ancestor = true; s.github.branches.clear(); const published = await state();
  assert.equal(published.status, 'published'); assert.equal(published.entry_url, proof.entry_url); assert.equal(published.hub_validation.runtime, 'not_run');
  assert.equal((await s.post()).status, 200); assert.equal(s.github.prCreates, 1);
  s.setUnavailable(); assert.equal((await state()).reason_code, 'publication_unavailable');
});

test('capabilities is public structured metadata and never requires repository or token access', async () => {
  const s = await setup(); s.env.GITHUB_TOKEN = undefined;
  const response = await s.handler(new Request('https://api.example/v1/capabilities'), s.env); assert.equal(response.status, 200);
  const body: any = await response.json(); assert.equal(body.memories.append_only, true); assert.equal(body.memories.max_body_bytes, 16384);
  assert.equal(body.interpretation, 'data_only'); assert.equal(s.github.headReads, 0);
});

test('real memory adapter writes one generated path on the fixed repository and opens only a draft internal PR', async () => {
  const s = await setup(); const saved: any = await (await s.post()).json(); const entry = readMemory(s.github.pulls.get(saved.memory_id)!.body)!;
  let fileWrites = 0; let draftPR = false;
  const adapter = new GitHub('dedicated-token', async (input, init) => {
    const url = String(input); assert.ok(url.startsWith('https://api.github.com/repos/Superfast-Robotics/robot-skill-hub/'));
    assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer dedicated-token'); assert.equal(init?.redirect, 'manual');
    if (url.endsWith('/git/commits/' + HEAD)) return Response.json({ tree: { sha: 'base-tree' } });
    if (url.endsWith('/git/trees')) { const body = JSON.parse(String(init?.body)); assert.deepEqual(body.tree.map((row: any) => row.path), [memoryPath(entry.memory_id)]); assert.equal(body.tree[0].content, memoryContent(entry)); fileWrites++; return Response.json({ sha: 'tree' }); }
    if (url.endsWith('/git/commits')) return Response.json({ sha: 'next-commit' });
    if (url.endsWith('/git/refs')) return Response.json({});
    if (url.includes('/pulls?')) return Response.json([]);
    if (url.endsWith('/pulls')) { const body = JSON.parse(String(init?.body)); assert.equal(body.base, 'main'); assert.equal(body.head, 'memories/' + entry.memory_id); assert.equal(body.draft, true); assert.equal(readMemory(body.body)!.fingerprint, entry.fingerprint); draftPR = true; return Response.json(s.github.pulls.get(saved.memory_id)); }
    assert.fail('Unexpected URL ' + url);
  });
  assert.equal(await adapter.createMemoryBranch(entry.memory_id, HEAD, entry), true); await adapter.createMemoryPull(entry);
  assert.equal(fileWrites, 1); assert.equal(draftPR, true);
});
