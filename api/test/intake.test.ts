import test from 'node:test';
import assert from 'node:assert/strict';
import { createHandler } from '../src/index.ts';
import { ApiError, receiptPath, type Checks, type Env, type GitHubAdapter, type Pull, type Receipt } from '../src/types.ts';
import { readReceipt, receiptMarker, sha256 } from '../src/util.ts';

const HUB = 'a'.repeat(40), SOURCE = 'b'.repeat(40), DIGEST = 'c'.repeat(64);
const TOKEN = 'new_skill_pilot_012345678901234567890123456789';
const ID = 'ros2-panda-grasp'; const PATH = `catalog/intake/${ID}.json`;
function bundle(): any {
  return { schema_version: '1', base: { hub_commit: HUB }, skill: {
    id: ID, name: 'ROS 2 Panda grasp action', summary: 'An upstream ROS 2 grasp action source reference.', framework: 'ros2', kind: 'community_skill', capabilities: ['grasp'], aliases: [], robots: ['panda'],
    source: { repository: 'https://github.com/frankaemika/franka_ros2', commit: SOURCE, path: 'examples/grasp.cpp', url: `https://github.com/frankaemika/franka_ros2/blob/${SOURCE}/examples/grasp.cpp`, sha256: DIGEST, bytes: 2000, authors: ['Upstream maintainers'] },
    license: { spdx: 'Apache-2.0', url: `https://github.com/frankaemika/franka_ros2/blob/${SOURCE}/LICENSE`, scope: 'Referenced source only; robot hardware and assets have separate terms.' },
    artifact: { kind: 'code', format: 'cpp' }, requirements: { python: null, packages: [], hardware: ['panda'], system: ['ROS 2'], notes: 'Inspect upstream setup before controlling hardware.' },
    invocation: { entrypoint: 'ROS 2 action client', notes: 'Hardware operation requires project-specific authorization and safety setup.' }, setup_url: 'https://frankarobotics.github.io/docs/',
    compatibility: [{ runtime: 'ros2', runtime_version: 'unknown', robot: 'panda', controller: 'unknown', observation: 'unknown', os: 'linux' }] },
    attribution: { contributor_label: 'Intake test agent', preserve_upstream_attribution: true }, publication: { public_submission_allowed: true } };
}
class IntakeGitHub implements GitHubAdapter {
  head = HUB; creates = 0; prCreates = 0; failPR = false; headReads = 0;
  files: Record<string, string> = { 'catalog/references.json': JSON.stringify({ schema_version: '1', records: [] }) };
  branches = new Map<string, { sha: string; files: Record<string, string> }>(); pulls = new Map<string, Pull>();
  async getHead() { this.headReads++; return this.head; }
  async getFile(path: string, ref: string) { return [...this.branches.values()].find(b => b.sha === ref)?.files[path] ?? this.files[path] ?? null; }
  async findPull(id: string) { return this.pulls.get(id) || null; }
  async getBranch(id: string) { return this.branches.get(id)?.sha || null; }
  async createBranch(id: string, base: string, files: Record<string, string>, receipt: Receipt) {
    await Promise.resolve(); if (this.branches.has(id)) return false;
    this.creates++; this.branches.set(id, { sha: String(this.creates).padStart(40, '0'), files: { ...files, [receiptPath(id)]: JSON.stringify(receipt) } }); return true;
  }
  async createPull(receipt: Receipt) {
    await Promise.resolve(); const existing = this.pulls.get(receipt.submission_id); if (existing) return existing;
    if (this.failPR) { this.failPR = false; throw new ApiError(503, 'github_unavailable', 'Injected PR failure'); }
    const number = ++this.prCreates;
    const pull: Pull = { number, html_url: `https://github.com/Superfast-Robotics/robot-skill-hub/pull/${number}`, body: receiptMarker(receipt), state: 'open', merged_at: null, merge_commit_sha: null, head: { sha: this.branches.get(receipt.submission_id)!.sha, ref: 'submissions/' + receipt.submission_id }, labels: [] };
    this.pulls.set(receipt.submission_id, pull); return pull;
  }
  async getChecks(): Promise<Checks> { return { state: 'success', reasons: [], completed: 1 }; }
  async isAncestor() { return true; }
  async closeSuperseded() { throw Error('Not supported for new skills'); }
  async findSuperseding() { return null; }
}
async function setup() {
  const github = new IntakeGitHub(); let manifest: any = {};
  const env: Env = { GITHUB_TOKEN: 'dummy', SUBMISSION_TOKENS_JSON: JSON.stringify([{ principal_id: 'intake-agent', sha256: await sha256(TOKEN) }]), PUBLICATION_URL: 'https://example.invalid/publication.json', SUBMIT_LIMITER: { async limit() { return { success: true }; } }, STATUS_LIMITER: { async limit() { return { success: true }; } } };
  const handler = createHandler(() => github, async () => manifest);
  const post = (value: any = bundle(), key = 'intake-request-1', headers: Record<string, string> = {}) => handler(new Request('https://api.example/v1/skills', { method: 'POST', headers: { Authorization: 'Bearer ' + TOKEN, 'Content-Type': 'application/json', 'Idempotency-Key': key, ...headers }, body: typeof value === 'string' ? value : JSON.stringify(value) }), env);
  const status = (id: string, token = TOKEN) => handler(new Request('https://api.example/v1/submissions/' + id, { headers: { Authorization: 'Bearer ' + token } }), env);
  return { github, env, post, status, setManifest(value: any) { manifest = value; } };
}

test('new non-Python skill creates only a server-selected data reference and draft receipt', async () => {
  const s = await setup(); const response = await s.post(); assert.equal(response.status, 201);
  const body: any = await response.json(); const branch = s.github.branches.get(body.submission_id)!;
  assert.deepEqual(Object.keys(branch.files).sort(), [PATH, receiptPath(body.submission_id)].sort());
  const record = JSON.parse(branch.files[PATH]); assert.equal(record.requirements.python, null); assert.equal(record.access.hub_prepare, false);
  assert.equal(record.evidence.runtime_verification, 'not_run'); assert.equal(record.license.verified, false); assert.equal(record.compatibility[0].status, 'contributor_reported');
  const receipt = readReceipt(s.github.pulls.get(body.submission_id)!.body)!;
  assert.equal(receipt.change_kind, 'new_skill'); assert.equal(receipt.patch_hashes[PATH], await sha256(branch.files[PATH]));
  assert.ok(!JSON.stringify(receipt).includes(TOKEN));
});

test('standalone policy artifact uses content revision without pretending to be a Git commit', async () => {
  const s = await setup(); const value = bundle(); delete value.skill.source.commit;
  value.skill.source.revision = 'sha256:' + DIGEST; value.skill.source.url = 'https://models.robotics.org/policies/panda.onnx'; value.skill.artifact = { kind: 'policy', format: 'onnx' };
  const response = await s.post(value); assert.equal(response.status, 201);
  const body: any = await response.json(); const receipt = readReceipt(s.github.pulls.get(body.submission_id)!.body)!;
  assert.equal(receipt.base.source_commit, 'sha256:' + DIGEST);
  assert.equal(JSON.parse(s.github.branches.get(body.submission_id)!.files[PATH]).source.commit, undefined);
});

test('concurrent intake, changed main, lost response and deleted branch replay one durable PR', async () => {
  const s = await setup(); const replies = await Promise.all(Array.from({ length: 8 }, () => s.post()));
  const values = await Promise.all(replies.map(r => r.json() as Promise<any>)); assert.equal(new Set(values.map(v => v.submission_id)).size, 1);
  assert.equal(s.github.creates, 1); assert.equal(s.github.prCreates, 1);
  const reads = s.github.headReads; s.github.head = 'd'.repeat(40); s.github.branches.clear();
  assert.equal((await s.post()).status, 200); assert.equal(s.github.headReads, reads);
  const changed = bundle(); changed.skill.summary = 'A different request body.'; assert.equal((await s.post(changed)).status, 409);
});

test('branch-only intake recovers its original data after PR outage and main changes', async () => {
  const s = await setup(); s.github.failPR = true; assert.equal((await s.post()).status, 503);
  s.github.head = 'd'.repeat(40); assert.equal((await s.post()).status, 201); assert.equal(s.github.creates, 1); assert.equal(s.github.prCreates, 1);
});

test('invalid pins, consent, execution claims, unsafe sources and secret patterns cause no writes', async () => {
  const cases: [(v: any) => void, number][] = [
    [v => { v.base.hub_commit = 'd'.repeat(40); }, 409], [v => { v.publication.public_submission_allowed = false; }, 403],
    [v => { v.skill.evidence = { level: 'task_complete' }; }, 422], [v => { v.skill.access = { hub_prepare: true }; }, 422],
    [v => { v.skill.compatibility[0].status = 'hub_verified'; }, 422], [v => { v.skill.source.path = '../private'; }, 422],
    [v => { v.skill.source.url = 'https://127.0.0.1/private'; }, 422], [v => { v.skill.source.url += '?token=secret'; }, 422],
    [v => { v.skill.source.url = 'https://github.com/upstream/project/blob/main/main.py'; }, 422],
    [v => { v.skill.summary = 'rsh_' + 'x'.repeat(43); }, 422], [v => { v.skill.summary = TOKEN; }, 422], [v => { v.skill.source.bytes = -1; }, 422],
    [v => { v.skill.source.revision = 'sha256:' + DIGEST; }, 422]
  ];
  for (const [mutate, code] of cases) { const s = await setup(); const value = bundle(); mutate(value); assert.equal((await s.post(value)).status, code); assert.equal(s.github.creates, 0); }
});

test('duplicate skill IDs in recipe, aggregate reference and per-entry reference are rejected', async () => {
  for (const path of [`catalog/records/${ID}.json`, PATH, 'catalog/references.json']) {
    const s = await setup(); s.github.files[path] = path === 'catalog/references.json' ? JSON.stringify({ schema_version: '1', records: [{ id: ID, source: bundle().skill.source }] }) : '{}';
    assert.equal((await s.post()).status, 409); assert.equal(s.github.creates, 0);
  }
});

test('compact source index avoids the large source catalog and rejects malformed identities', async () => {
  const s = await setup();
  s.github.files['catalog/references.json'] = 'THIS AGGREGATE MUST NOT BE PARSED';
  s.github.files['catalog/source-index.json'] = JSON.stringify({ schema_version: '1', records: [{ id: ID, source_commit: SOURCE, source_sha256: DIGEST, record_version: 'source-' + DIGEST }] });
  assert.equal((await s.post()).status, 409); assert.equal(s.github.creates, 0);
  s.github.files['catalog/source-index.json'] = JSON.stringify({ schema_version: '1', records: [{ id: ID, source_commit: 'main', source_sha256: DIGEST, record_version: 'source-' + DIGEST }] });
  const bad = await s.post(); assert.equal(bad.status, 503); assert.equal((await bad.json() as any).reason_code, 'invalid_source_index');
});

test('new-skill uniqueness reads only its checksum-bound source identity shard', async () => {
  const s = await setup(); const prefix = (await sha256(ID)).slice(0, 2); const path = `catalog/source-index/${prefix}.json`;
  const raw = JSON.stringify({ schema_version: '1', records: [{ id: ID, source_commit: SOURCE, source_sha256: DIGEST, record_version: 'source-' + DIGEST }] }) + '\n';
  s.github.files['catalog/source-index-manifest.json'] = JSON.stringify({ schema_version: '1', scheme: 'sha256-id-prefix-2', records: 1, shards: { [prefix]: { path, sha256: await sha256(raw), records: 1 } } });
  s.github.files[path] = raw; s.github.files['catalog/source-index.json'] = 'DO NOT READ THIS FLAT INDEX'; s.github.files['catalog/references.json'] = 'DO NOT READ THIS AGGREGATE';
  assert.equal((await s.post()).status, 409); assert.equal(s.github.creates, 0);
  s.github.files[path] += ' ';
  const changed = await s.post(); assert.equal(changed.status, 503); assert.equal((await changed.json() as any).reason_code, 'invalid_source_index');
});

test('publication requires exact new reference bytes and owning principal', async () => {
  const s = await setup(); const body: any = await (await s.post()).json(); const pull = s.github.pulls.get(body.submission_id)!; const receipt = readReceipt(pull.body)!;
  pull.merged_at = '2026-10-18T00:00:00Z'; pull.merge_commit_sha = 'd'.repeat(40);
  const record = { id: ID, record_version: receipt.new_record_version, source_commit: SOURCE, submission_ids: [body.submission_id], contribution_path_hashes: receipt.patch_hashes, recipe_url: bundle().skill.source.url, compatibility: [] };
  s.setManifest({ schema_version: '1', hub_commit: 'e'.repeat(40), records: [record] });
  assert.equal((await (await s.status(body.submission_id)).json() as any).status, 'published');
  record.contribution_path_hashes = { [PATH]: '0'.repeat(64) }; assert.equal((await (await s.status(body.submission_id)).json() as any).status, 'merged');
  const other = 'other_intake_pilot_012345678901234567890123456789';
  s.env.SUBMISSION_TOKENS_JSON = JSON.stringify([{ principal_id: 'other', sha256: await sha256(other) }]);
  assert.equal((await s.status(body.submission_id, other)).status, 404);
});

test('body limit and compressed requests fail before any intake mutation', async () => {
  const s = await setup(); assert.equal((await s.post(' '.repeat(16 * 1024 + 1))).status, 413);
  assert.equal((await s.post(bundle(), 'intake-request-2', { 'Content-Encoding': 'gzip' })).status, 415); assert.equal(s.github.creates, 0);
});
