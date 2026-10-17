import test from 'node:test';
import assert from 'node:assert/strict';
import { createHandler } from '../src/index.ts';
import { ApiError, receiptPath, type Bundle, type Checks, type Env, type GitHubAdapter, type Pull, type Receipt } from '../src/types.ts';
import { readReceipt, receiptMarker, sha256 } from '../src/util.ts';
import { applyPatch, parsePatch } from '../src/patch.ts';
import { GitHub } from '../src/github.ts';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join, resolve, sep } from 'node:path';

const HUB = 'a'.repeat(40); const SOURCE = 'b'.repeat(40); const TOKEN = 'pilot_token_012345678901234567890123456789';
const ID = 'maniskill-panda-pickcube'; const RECORD = `catalog/records/${ID}.json`; const DOC = `docs/recipes/${ID}.md`;
const baseRecord = {
  id: ID, source: { commit: SOURCE }, license: { spdx: 'Apache-2.0' },
  maintenance: { record_version: '1.0.0' }, contribution: { allowed_paths: [RECORD, DOC] }, compatibility: [{ runtime: 'maniskill', robot: 'panda', status: 'source_reviewed' }]
};
function bundle(): Bundle {
  return {
    schema_version: '1', skill_id: ID, base: { record_version: '1.0.0', hub_commit: HUB, source_commit: SOURCE },
    change_kind: 'docs_fix', summary: 'Clarify isolated dependency installation.',
    patch: `--- a/${DOC}\n+++ b/${DOC}\n@@ -1 +1 @@\n-Install dependencies.\n+Install dependencies in an isolated environment.\n`,
    environment: { runtime: 'maniskill', robot: 'panda', os: 'unknown' },
    evidence: { level: 'not_run', command: null, result: 'Documentation-only fix; runtime not run.', reported_by: 'submitter' },
    attribution: { contributor_label: 'Pilot (self-reported)', preserve_upstream_attribution: true }, publication: { public_submission_allowed: true }
  };
}
class FakeGitHub implements GitHubAdapter {
  head = HUB;
  files: Record<string, string> = { [RECORD]: JSON.stringify(baseRecord, null, 2) + '\n', [DOC]: 'Install dependencies.\n' };
  branches = new Map<string, { sha: string; files: Record<string, string> }>();
  pulls = new Map<string, Pull>();
  branchCreates = 0; prCreates = 0; failPR = 0; headReads = 0; ancestor = true;
  ancestry = new Map<string, boolean>(); ancestorChecks: [string, string][] = [];
  checks: Checks = { state: 'pending', reasons: [], completed: 0 };
  async findPull(id: string) { return this.pulls.get(id) || null; }
  async getBranch(id: string) { return this.branches.get(id)?.sha || null; }
  async getHead() { this.headReads++; return this.head; }
  async getFile(path: string, ref: string) {
    const branch = [...this.branches.values()].find(b => b.sha === ref);
    return (branch?.files || this.files)[path] ?? null;
  }
  async createBranch(id: string, base: string, files: Record<string, string>, receipt: Receipt) {
    await Promise.resolve();
    if (this.branches.has(id)) return false;
    this.branchCreates++;
    this.branches.set(id, { sha: String(this.branchCreates).padStart(40, '0'), files: { ...this.files, ...files, [receiptPath(id)]: JSON.stringify(receipt) } });
    return true;
  }
  async createPull(receipt: Receipt) {
    await Promise.resolve();
    const existing = this.pulls.get(receipt.submission_id); if (existing) return existing;
    if (this.failPR > 0) { this.failPR--; throw new ApiError(503, 'github_unavailable', 'Injected PR outage.'); }
    const number = ++this.prCreates;
    const pull: Pull = { number, html_url: `https://github.com/Superfast-Robotics/robot-skill-hub/pull/${number}`, body: receiptMarker(receipt), state: 'open', merged_at: null, merge_commit_sha: null, labels: [], head: { sha: this.branches.get(receipt.submission_id)!.sha, ref: 'submissions/' + receipt.submission_id } };
    this.pulls.set(receipt.submission_id, pull); return pull;
  }
  async getChecks() { return this.checks; }
  async isAncestor(ancestor: string, descendant: string) {
    this.ancestorChecks.push([ancestor, descendant]);
    return this.ancestry.get(`${ancestor}...${descendant}`) ?? this.ancestor;
  }
  async closeSuperseded(old: Pull, next: Pull, id: string) { old.body += `\n<!-- rsh-superseded-by:${id} -->`; old.state = 'closed'; }
  async findSuperseding(id: string) { return this.pulls.get(id)?.body?.match(/rsh-superseded-by:(sub_[a-f0-9]{64})/)?.[1] || null; }
}
async function setup() {
  const github = new FakeGitHub();
  const env: Env = { GITHUB_TOKEN: 'fake-never-logs', SUBMISSION_TOKENS_JSON: JSON.stringify([{ principal_id: 'pilot-1', sha256: await sha256(TOKEN) }]), PUBLICATION_URL: 'https://example.invalid/publication.json', SUBMIT_LIMITER: { async limit() { return { success: true }; } }, STATUS_LIMITER: { async limit() { return { success: true }; } } };
  let manifest: any = {}; let unavailable = false;
  const handler = createHandler(() => github, async () => { if (unavailable) throw new Error('offline'); return manifest; });
  const post = async (value: any = bundle(), key = 'same-request-key', token = TOKEN, headers: Record<string, string> = {}) => handler(new Request('https://api.example/v1/submissions', { method: 'POST', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', 'Idempotency-Key': key, ...headers }, body: typeof value === 'string' ? value : JSON.stringify(value) }), env);
  const status = async (id: string, token = TOKEN) => handler(new Request('https://api.example/v1/submissions/' + id, { headers: { Authorization: 'Bearer ' + token } }), env);
  return { github, env, post, status, setManifest(m: any) { manifest = m; }, setUnavailable(v: boolean) { unavailable = v; } };
}

test('intake creates one durable internal PR, automatic version and separate evidence', async () => {
  const s = await setup(); const response = await s.post(); assert.equal(response.status, 201);
  const data: any = await response.json(); assert.equal(data.status, 'submitted'); assert.equal(s.github.prCreates, 1);
  const receipt = readReceipt(s.github.pulls.get(data.submission_id)!.body)!;
  assert.equal(receipt.hub_validation.runtime, 'not_run'); assert.equal(receipt.evidence.level, 'not_run');
  const record = JSON.parse(s.github.branches.get(data.submission_id)!.files[RECORD]);
  assert.equal(record.maintenance.record_version, receipt.new_record_version);
  assert.equal(receipt.patch_hashes[RECORD], await sha256(s.github.branches.get(data.submission_id)!.files[RECORD]));
  assert.ok(!JSON.stringify(receipt).includes(TOKEN));
});

test('concurrent calls, lost response, stale-base retry and deleted branch retain one PR', async () => {
  const s = await setup(); const responses = await Promise.all(Array.from({ length: 10 }, () => s.post()));
  for (const r of responses) assert.ok([200, 201].includes(r.status));
  const ids = await Promise.all(responses.map(async r => (await r.json() as any).submission_id));
  assert.equal(new Set(ids).size, 1); assert.equal(s.github.prCreates, 1); assert.equal(s.github.branchCreates, 1);
  const reads = s.github.headReads; s.github.head = 'c'.repeat(40); s.github.branches.clear();
  const replay = await s.post(); assert.equal(replay.status, 200); assert.equal((await replay.json() as any).submission_id, ids[0]); assert.equal(s.github.headReads, reads);
  assert.equal((await s.status(ids[0])).status, 200);
});

test('same key different payload conflicts; independent principals cannot read each other', async () => {
  const s = await setup(); const data: any = await (await s.post()).json();
  const other = bundle(); other.summary = 'Different contents';
  const conflict = await s.post(other); assert.equal(conflict.status, 409); assert.equal((await conflict.json() as any).reason_code, 'idempotency_key_conflict');
  const token2 = 'pilot_2_012345678901234567890123456789012';
  s.env.SUBMISSION_TOKENS_JSON = JSON.stringify([{ principal_id: 'pilot-1', sha256: await sha256(TOKEN) }, { principal_id: 'pilot-2', sha256: await sha256(token2) }]);
  assert.equal((await s.status(data.submission_id, token2)).status, 404);
  assert.equal((await s.post(bundle(), 'same-request-key', token2)).status, 201); assert.equal(s.github.prCreates, 2);
});

test('base/source/version conflicts, outside path and context mismatch cause no writes', async () => {
  const scenarios: [string, (b: Bundle) => void, number][] = [
    ['stale_base', b => { b.base.hub_commit = 'c'.repeat(40); }, 409],
    ['stale_record', b => { b.base.source_commit = 'd'.repeat(40); }, 409],
    ['stale_record', b => { b.base.record_version = 'old'; }, 409],
    ['invalid_path', b => { b.patch = b.patch.replaceAll(DOC, '.github/workflows/publish.yml'); }, 422],
    ['path_not_allowed', b => { b.patch = b.patch.replaceAll(DOC, 'recipes/another-skill/run.py'); }, 422],
    ['invalid_path', b => { b.patch = b.patch.replaceAll(DOC, '../secret'); }, 422],
    ['patch_context_mismatch', b => { b.patch = b.patch.replace('-Install dependencies.', '-Wrong base text.'); }, 422],
    ['no_changes', b => { b.patch = b.patch.replace('+Install dependencies in an isolated environment.', '+Install dependencies.'); }, 422]
  ];
  for (const [code, mutate, http] of scenarios) {
    const s = await setup(); const b = bundle(); mutate(b); const response = await s.post(b);
    assert.equal(response.status, http, code); assert.equal((await response.json() as any).reason_code, code); assert.equal(s.github.branchCreates, 0);
  }
});

test('recovery after branch-only partial failure uses persisted receipt even when main changes', async () => {
  const s = await setup(); s.github.failPR = 1;
  assert.equal((await s.post()).status, 503); assert.equal(s.github.branchCreates, 1); assert.equal(s.github.prCreates, 0);
  s.github.head = 'd'.repeat(40);
  const response = await s.post(); assert.equal(response.status, 201); assert.equal(s.github.branchCreates, 1); assert.equal(s.github.prCreates, 1);
  const conflicting = bundle(); conflicting.summary = 'Conflict after partial intake'; assert.equal((await s.post(conflicting)).status, 409);
});

test('authentication, public policy, streaming byte bounds, content type and rate limits fail closed', async () => {
  const s = await setup();
  assert.equal((await s.post(bundle(), 'key-example', 'wrong')).status, 401);
  const privateBundle: any = bundle(); privateBundle.publication.public_submission_allowed = false;
  assert.equal((await s.post(privateBundle)).status, 403);
  assert.equal((await s.post('{')).status, 422);
  assert.equal((await s.post('x'.repeat(65537))).status, 413);
  assert.equal((await s.post(bundle(), 'key-example', TOKEN, { 'Content-Type': 'text/plain' })).status, 415);
  assert.equal((await s.post(bundle(), 'key-example', TOKEN, { 'Content-Encoding': 'gzip' })).status, 415);
  s.env.SUBMIT_LIMITER = { async limit() { return { success: false }; } };
  const limited = await s.post(); assert.equal(limited.status, 429); assert.equal(limited.headers.get('Retry-After'), '60');
  assert.equal(s.github.branchCreates, 0);
});

test('oversized receipt metadata is rejected before branch creation, even within 64 KiB body limit', async () => {
  const s = await setup(); const b = bundle(); b.environment.extra_notes = 'x'.repeat(26 * 1024);
  assert.ok(new TextEncoder().encode(JSON.stringify(b)).length < 64 * 1024);
  const response = await s.post(b); assert.equal(response.status, 422);
  assert.equal((await response.json() as any).reason_code, 'metadata_too_large'); assert.equal(s.github.branchCreates, 0);
});

test('checks and maintainer labels distinguish review, failed checks and unverified runtime', async () => {
  const s = await setup(); const { submission_id: id }: any = await (await s.post()).json();
  const state = async () => (await (await s.status(id)).json() as any);
  s.github.checks = { state: 'pending', reasons: [], completed: 1 }; assert.equal((await state()).status, 'checking');
  s.github.checks = { state: 'failure', reasons: ['schema'], completed: 1 }; const failed = await state(); assert.equal(failed.status, 'needs_changes'); assert.equal(failed.reason_code, 'hub_checks_failed');
  s.github.checks = { state: 'success', reasons: [], completed: 1 }; const checked = await state(); assert.equal(checked.status, 'pending_review'); assert.equal(checked.hub_validation.runtime, 'not_run');
  s.github.pulls.get(id)!.labels = [{ name: 'rsh:needs_changes' }]; assert.equal((await state()).status, 'needs_changes');
  s.github.pulls.get(id)!.state = 'closed'; assert.equal((await state()).status, 'rejected');
});

test('merged is never published without deployed version, content, receipt and ancestry proof', async () => {
  const s = await setup(); const { submission_id: id }: any = await (await s.post()).json();
  const pr = s.github.pulls.get(id)!; const receipt = readReceipt(pr.body)!;
  pr.merged_at = '2026-10-17T00:00:00Z'; pr.merge_commit_sha = 'e'.repeat(40); pr.state = 'closed'; s.github.branches.clear();
  s.github.checks = { state: 'success', reasons: [], completed: 1 };
  const state = async () => (await (await s.status(id)).json() as any);
  assert.equal((await state()).status, 'merged');
  const good = { schema_version: '1', hub_commit: 'f'.repeat(40), records: [{ id: ID, record_version: receipt.new_record_version, source_commit: SOURCE, contribution_path_hashes: receipt.patch_hashes, compatibility: baseRecord.compatibility, recipe_url: 'https://example.invalid/recipe', submission_ids: [id] }] };
  for (const bad of [
    { ...good, records: [{ ...good.records[0], submission_ids: [] }] },
    { ...good, records: [{ ...good.records[0], record_version: 'older' }] },
    { ...good, records: [{ ...good.records[0], source_commit: '1'.repeat(40) }] },
    { ...good, records: [{ ...good.records[0], contribution_path_hashes: {} }] }
  ]) { s.setManifest(bad); assert.equal((await state()).status, 'merged'); }
  s.setManifest(good); s.github.ancestor = false; assert.equal((await state()).status, 'merged');
  s.github.ancestor = true; const published = await state(); assert.equal(published.status, 'published'); assert.equal(published.published_version, receipt.new_record_version); assert.equal(published.source_commit, SOURCE);
  assert.equal(published.publication_scope, 'current'); assert.equal(published.published_hub_commit, good.hub_commit);
  assert.equal((await s.post()).status, 200); assert.equal(s.github.prCreates, 1);
});

async function historicalPublication() {
  const s = await setup(); const { submission_id: id }: any = await (await s.post()).json();
  const pull = s.github.pulls.get(id)!; const receipt = readReceipt(pull.body)!;
  const merge = 'c'.repeat(40); const originalDeployment = 'd'.repeat(40); const currentDeployment = 'f'.repeat(40);
  pull.merged_at = '2026-10-17T00:00:00Z'; pull.merge_commit_sha = merge; pull.state = 'closed';
  s.github.checks = { state: 'success', reasons: [], completed: 1 };
  const archived = { id: ID, record_version: receipt.new_record_version, source_commit: SOURCE,
    contribution_path_hashes: { ...receipt.patch_hashes }, compatibility: baseRecord.compatibility,
    recipe_url: `https://example.invalid/releases/${ID}/${receipt.new_record_version}/`, submission_ids: [id] };
  const manifest: any = { schema_version: '1', hub_commit: currentDeployment,
    // A maintainer's later documentation edit no longer has the accepted bytes.
    records: [{ ...archived, recipe_url: 'https://example.invalid/current', submission_ids: [],
      contribution_path_hashes: { ...receipt.patch_hashes, [DOC]: '0'.repeat(64) } }],
    history: [{ hub_commit: originalDeployment, records: [archived] }] };
  s.setManifest(manifest);
  return { ...s, id, pull, receipt, merge, originalDeployment, currentDeployment, archived, manifest,
    async state() { return await (await s.status(id)).json() as any; } };
}

test('later documentation edits preserve the exact previously published version through archived proof', async () => {
  const s = await historicalPublication();
  for (const records of [s.manifest.records, [], [{ ...s.archived,
    contribution_path_hashes: { ...s.receipt.patch_hashes, [DOC]: '0'.repeat(64) } }]]) {
    s.setManifest({ ...s.manifest, records }); s.github.ancestorChecks = [];
    const state = await s.state();
    assert.equal(state.status, 'published'); assert.equal(state.publication_scope, 'historical');
    assert.equal(state.published_version, s.receipt.new_record_version); assert.equal(state.source_commit, SOURCE);
    assert.equal(state.recipe_url, s.archived.recipe_url); assert.equal(state.published_hub_commit, s.originalDeployment);
    assert.deepEqual(state.compatibility, s.archived.compatibility);
    assert.deepEqual(s.github.ancestorChecks, [[s.merge, s.originalDeployment], [s.originalDeployment, s.currentDeployment]]);
  }
  assert.deepEqual(readReceipt(s.pull.body)!.patch_hashes, s.receipt.patch_hashes, 'Original receipt hashes must remain unchanged');
});

test('current exact deployment takes precedence over a matching historical deployment', async () => {
  const s = await historicalPublication();
  s.manifest.records = [{ ...s.archived, recipe_url: 'https://example.invalid/current' }]; s.setManifest(s.manifest);
  const state = await s.state();
  assert.equal(state.status, 'published'); assert.equal(state.publication_scope, 'current');
  assert.equal(state.recipe_url, 'https://example.invalid/current'); assert.equal(state.published_hub_commit, s.currentDeployment);
  assert.deepEqual(s.github.ancestorChecks, [[s.merge, s.currentDeployment]]);
});

test('history rejects foreign versions, sources, receipts and incorrect or incomplete accepted hashes', async () => {
  const s = await historicalPublication();
  const wrongRecords = [
    { ...s.archived, id: 'another-skill' },
    { ...s.archived, record_version: 'a-different-version' },
    { ...s.archived, source_commit: '1'.repeat(40) },
    { ...s.archived, submission_ids: [] },
    { ...s.archived, contribution_path_hashes: { ...s.archived.contribution_path_hashes, [DOC]: '0'.repeat(64) } },
    { ...s.archived, contribution_path_hashes: { [DOC]: s.receipt.patch_hashes[DOC] } }
  ];
  for (const record of wrongRecords) {
    s.setManifest({ ...s.manifest, history: [{ hub_commit: s.originalDeployment, records: [record] }] });
    const state = await s.state(); assert.equal(state.status, 'merged'); assert.equal(state.reason_code, 'publication_not_confirmed');
  }
  for (const history of [null, {}, [{ hub_commit: 'main', records: [s.archived] }], [{ hub_commit: s.originalDeployment, records: {} }]]) {
    s.setManifest({ ...s.manifest, history }); const state = await s.state();
    assert.equal(state.status, 'merged'); assert.equal(state.reason_code, 'publication_not_confirmed');
  }
  assert.equal(s.github.ancestorChecks.length, 0, 'Invalid proof contents must not reach ancestry checks');
});

test('historical publication requires merge-to-history and history-to-current ancestry', async () => {
  const s = await historicalPublication();
  s.github.ancestry.set(`${s.merge}...${s.originalDeployment}`, false);
  let state = await s.state(); assert.equal(state.status, 'merged'); assert.equal(state.reason_code, 'publication_not_confirmed');
  assert.deepEqual(s.github.ancestorChecks, [[s.merge, s.originalDeployment]]);
  s.github.ancestry.set(`${s.merge}...${s.originalDeployment}`, true);
  s.github.ancestry.set(`${s.originalDeployment}...${s.currentDeployment}`, false); s.github.ancestorChecks = [];
  state = await s.state(); assert.equal(state.status, 'merged'); assert.equal(state.reason_code, 'publication_not_confirmed');
  assert.deepEqual(s.github.ancestorChecks, [[s.merge, s.originalDeployment], [s.originalDeployment, s.currentDeployment]]);
  s.pull.merged_at = null; s.pull.state = 'open'; s.github.ancestorChecks = [];
  state = await s.state(); assert.equal(state.status, 'pending_review'); assert.equal(state.published_version, null);
  assert.equal(s.github.ancestorChecks.length, 0, 'An unmerged PR cannot use historical publication proof');
});

test('failed publication remains explicit and does not duplicate PR on retry', async () => {
  const s = await setup(); const { submission_id: id }: any = await (await s.post()).json();
  const pr = s.github.pulls.get(id)!; pr.merged_at = '2026-10-17T00:00:00Z'; pr.merge_commit_sha = 'e'.repeat(40);
  s.setUnavailable(true); s.github.checks = { state: 'failure', reasons: ['pages'], completed: 1 };
  assert.equal((await (await s.status(id)).json() as any).status, 'publish_failed');
  assert.equal((await s.post()).status, 200); assert.equal(s.github.prCreates, 1);
});

test('supplement closes and links only after new request has durable PR; failed intake keeps old open', async () => {
  const s = await setup(); const { submission_id: oldId }: any = await (await s.post()).json();
  const old = s.github.pulls.get(oldId)!; old.labels.push({ name: 'rsh:needs_changes' });
  const b = bundle(); b.supersedes_submission_id = oldId; b.summary = 'Add requested reproduction detail';
  s.github.failPR = 1; assert.equal((await s.post(b, 'new-request-key')).status, 503); assert.equal(old.state, 'open');
  const response = await s.post(b, 'new-request-key'); assert.equal(response.status, 201); const next: any = await response.json();
  assert.equal(old.state, 'closed'); const state: any = await (await s.status(oldId)).json(); assert.equal(state.status, 'superseded'); assert.equal(state.superseded_by, next.submission_id);
  assert.equal(s.github.prCreates, 2);
});

test('strict diff supports no-newline files and rejects counts, binary, rename and overlap', () => {
  const patch = '--- a/docs/example.md\n+++ b/docs/example.md\n@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n';
  assert.equal(applyPatch('old', parsePatch(patch)[0]), 'new');
  assert.throws(() => parsePatch(patch.replace('@@ -1 +1 @@', '@@ -1,2 +1 @@')), /count mismatch/);
  assert.throws(() => parsePatch('GIT binary patch\n'), /existing regular files/);
  assert.throws(() => parsePatch(patch.replace('+++ b/docs/example.md', '+++ b/docs/other.md')), /Renames/);
  const overlap = parsePatch('--- a/docs/a.md\n+++ b/docs/a.md\n@@ -1 +1 @@\n-a\n+b\n@@ -1 +1 @@\n-a\n+c\n')[0];
  assert.throws(() => applyPatch('a\n', overlap), /ordered/);
});

test('real adapter bounds repository, authenticates PRs and reads public checks without token permissions', async () => {
  const s = await setup(); const data: any = await (await s.post()).json(); const pr = s.github.pulls.get(data.submission_id)!; const receipt = readReceipt(pr.body)!;
  const requests: { url: string; method: string }[] = []; let lookups = 0;
  const fakeFetch: typeof fetch = async (input, init) => {
    const url = String(input); const method = init?.method || 'GET'; requests.push({ url, method });
    assert.ok(url.startsWith('https://api.github.com/repos/Superfast-Robotics/robot-skill-hub/'));
    const headers = new Headers(init?.headers);
    assert.equal(headers.get('Authorization'), url.includes('/check-runs') ? null : 'Bearer not-a-real-token');
    assert.equal(init?.redirect, 'manual');
    if (url.includes('/pulls?')) { lookups++; return Response.json(lookups === 1 ? [] : [pr]); }
    if (url.endsWith('/pulls') && method === 'POST') return Response.json({ message: 'already exists' }, { status: 422 });
    if (url.includes('/check-runs')) return Response.json({ check_runs: [{ name: 'test', status: 'completed', conclusion: 'success' }] });
    throw new Error('Unexpected URL');
  };
  const github = new GitHub('not-a-real-token', fakeFetch);
  assert.equal((await github.createPull(receipt)).number, pr.number);
  assert.equal((await github.getChecks(HUB)).state, 'success');
  assert.ok(!requests.some(r => r.url.endsWith('/status')));
});

test('public check reads reject invalid refs and fail closed without credential retries', async () => {
  let calls = 0;
  const github = new GitHub('dedicated-repository-token', async (input, init) => {
    calls++;
    assert.equal(String(input), `https://api.github.com/repos/Superfast-Robotics/robot-skill-hub/commits/${HUB}/check-runs?per_page=100&filter=latest`);
    assert.equal(new Headers(init?.headers).has('Authorization'), false);
    return Response.json({ message: 'API rate limit exceeded' }, { status: 403 });
  });
  for (const ref of ['main', '../another-repo', HUB + '?redirect=elsewhere']) {
    await assert.rejects(github.getChecks(ref), (error: unknown) => error instanceof ApiError && error.status === 503);
  }
  assert.equal(calls, 0);
  await assert.rejects(github.getChecks(HUB), (error: unknown) => error instanceof ApiError && error.status === 503);
  assert.equal(calls, 1);
});

test('failed PR mutation keeps authentication and is never retried anonymously', async () => {
  const s = await setup(); const data: any = await (await s.post()).json();
  const receipt = readReceipt(s.github.pulls.get(data.submission_id)!.body)!;
  const methods: string[] = [];
  const github = new GitHub('dedicated-repository-token', async (input, init) => {
    const method = init?.method || 'GET'; methods.push(method);
    assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer dedicated-repository-token');
    if (String(input).includes('/pulls?')) return Response.json([]);
    assert.equal(method, 'POST');
    return Response.json({ message: 'Forbidden' }, { status: 403 });
  });
  await assert.rejects(github.createPull(receipt), (error: unknown) => error instanceof ApiError && error.status === 503);
  assert.deepEqual(methods, ['GET', 'POST']);
});

test('adapter invokes fetch without a class receiver as required by the Workers runtime', async () => {
  let calls = 0;
  const receiverSensitiveFetch: typeof fetch = async function (this: unknown, input, init) {
    assert.equal(this, undefined, 'Native Workers fetch rejects the adapter as its receiver');
    calls++;
    assert.equal(String(input), 'https://api.github.com/repos/Superfast-Robotics/robot-skill-hub/git/ref/heads/main');
    assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer dedicated-repository-token');
    return Response.json({ object: { sha: HUB } });
  };
  assert.equal(await new GitHub('dedicated-repository-token', receiverSensitiveFetch).getHead(), HUB);
  assert.equal(calls, 1);
});

test('adapter rejects GitHub redirects without following or forwarding the token', async () => {
  for (const redirect of [301, 302, 303, 307, 308]) {
    let calls = 0;
    const github = new GitHub('dedicated-repository-token', async (input, init) => {
      calls++;
      assert.equal(String(input), 'https://api.github.com/repos/Superfast-Robotics/robot-skill-hub/git/ref/heads/main');
      assert.equal(init?.redirect, 'manual');
      return new Response(null, { status: redirect, headers: { Location: 'https://another-host.invalid/' } });
    });
    await assert.rejects(github.getHead(), (error: unknown) => error instanceof ApiError && error.code === 'github_unavailable' && error.status === 503);
    assert.equal(calls, 1);
  }
});

test('actual catalog record accepts a docs patch and invalidates inherited execution evidence', async () => {
  const s = await setup();
  const raw = await readFile(new URL('../../catalog/records/maniskill-panda-pick-cube.json', import.meta.url), 'utf8');
  const actual = JSON.parse(raw); const recordPath = `catalog/records/${actual.id}.json`; const docPath = `docs/recipes/${actual.id}.md`;
  const doc = await readFile(new URL('../../' + docPath, import.meta.url), 'utf8');
  s.github.files = { [recordPath]: raw, [docPath]: doc };
  const b = bundle(); b.skill_id = actual.id; b.base.record_version = actual.maintenance.record_version; b.base.source_commit = actual.source.commit;
  const firstLine = doc.split('\n')[0];
  b.patch = `--- a/${docPath}\n+++ b/${docPath}\n@@ -1 +1 @@\n-${firstLine}\n+${firstLine} (preview)\n`;
  const response = await s.post(b); assert.equal(response.status, 201, JSON.stringify(await response.clone().json()));
  const { submission_id: id }: any = await response.json();
  const changed = JSON.parse(s.github.branches.get(id)!.files[recordPath]);
  assert.equal(changed.id, actual.id); assert.equal(changed.evidence.runtime_verification, 'not_run');
  assert.deepEqual(changed.evidence.contributor_reported, b.evidence); assert.equal(changed.compatibility[0].status, 'contributor_reported');
  assert.deepEqual(changed.source, actual.source);
});

test('actual catalog evidence and compatibility verification cannot be escalated by submitter', async () => {
  for (const field of ['evidence', 'compatibility']) {
    const s = await setup();
    const raw = (await readFile(new URL('../../catalog/records/maniskill-panda-pick-cube.json', import.meta.url), 'utf8')).replaceAll('\r\n', '\n');
    const actual = JSON.parse(raw); const path = `catalog/records/${actual.id}.json`; s.github.files = { [path]: raw };
    const changed = structuredClone(actual);
    if (field === 'evidence') changed.evidence.runtime_verification = 'task_complete';
    else changed.compatibility[0].status = 'hub_verified';
    const target = JSON.stringify(changed, null, 2) + '\n';
    const b = bundle(); b.skill_id = actual.id; b.base.record_version = actual.maintenance.record_version; b.base.source_commit = actual.source.commit;
    const oldLines = raw.trimEnd().split('\n'); const newLines = target.trimEnd().split('\n');
    b.patch = `--- a/${path}\n+++ b/${path}\n@@ -1,${oldLines.length} +1,${newLines.length} @@\n` + oldLines.map(l => '-' + l + '\n').join('') + newLines.map(l => '+' + l + '\n').join('');
    const response = await s.post(b); assert.equal(response.status, 422);
    assert.equal((await response.json() as any).reason_code, field === 'evidence' ? 'protected_record_field' : 'protected_verification_status');
    assert.equal(s.github.branchCreates, 0);
  }
});

test('actual Python publication builder roundtrips accepted receipt and exact content hashes', async () => {
  const s = await setup(); const root = fileURLToPath(new URL('../../', import.meta.url));
  const raw = await readFile(join(root, 'catalog/records/maniskill-panda-pick-cube.json'), 'utf8');
  const actual = JSON.parse(raw); const recordPath = `catalog/records/${actual.id}.json`; const docPath = `docs/recipes/${actual.id}.md`;
  const doc = await readFile(join(root, docPath), 'utf8'); s.github.files = { [recordPath]: raw, [docPath]: doc };
  const b = bundle(); b.skill_id = actual.id; b.base.record_version = actual.maintenance.record_version; b.base.source_commit = actual.source.commit;
  const firstLine = doc.split('\n')[0]; b.patch = `--- a/${docPath}\n+++ b/${docPath}\n@@ -1 +1 @@\n-${firstLine}\n+${firstLine} (roundtrip)\n`;
  const response = await s.post(b); assert.equal(response.status, 201); const { submission_id: id }: any = await response.json();
  const temporary = await mkdtemp(join(tmpdir(), 'rsh-api-publication-'));
  // This is the exact test-owned temporary directory, never a computed repository path.
  assert.ok(resolve(temporary).startsWith(resolve(tmpdir()) + sep + 'rsh-api-publication-'));
  try {
    for (const folder of ['catalog', 'schemas', 'recipes', 'docs', 'web']) await cp(join(root, folder), join(temporary, folder), { recursive: true });
    for (const [path, content] of Object.entries(s.github.branches.get(id)!.files)) {
      await mkdir(join(temporary, path, '..'), { recursive: true }); await writeFile(join(temporary, path), content, 'utf8');
    }
    const script = 'import argparse,sys; from pathlib import Path; import tools.build_catalog as b; b.ROOT=Path(sys.argv[1]); b.build(argparse.Namespace(check=False,base_url="https://example.invalid",output=str(b.ROOT/"site"),hub_commit="' + 'f'.repeat(40) + '"))';
    execFileSync('python', ['-c', script, temporary], { cwd: root, stdio: 'pipe' });
    const manifest = JSON.parse(await readFile(join(temporary, 'site/catalog/v1/publication.json'), 'utf8'));
    const published = manifest.records.find((r: any) => r.id === actual.id); assert.ok(published.submission_ids.includes(id));
    const pr = s.github.pulls.get(id)!; pr.merged_at = '2026-10-17T00:00:00Z'; pr.merge_commit_sha = 'e'.repeat(40); pr.state = 'closed'; s.setManifest(manifest);
    const state: any = await (await s.status(id)).json(); assert.equal(state.status, 'published'); assert.equal(state.published_version, readReceipt(pr.body)!.new_record_version);
  } finally { await rm(temporary, { recursive: true, force: true }); }
});
