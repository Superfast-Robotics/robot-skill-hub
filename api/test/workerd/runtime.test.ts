import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { Miniflare, Request as RuntimeRequest, Response as RuntimeResponse } from 'miniflare';

// Only dummy credentials are used. Every outbound request is intercepted locally.
const TOKEN = 'runtime-fake-token-00000000000000000000000000000000';
const GITHUB_TOKEN = 'fake-invalid-github-token';
const PRINCIPAL = 'runtime-local-test';
const ID = 'sub_' + '0'.repeat(64);
const API = 'https://api.github.com/repos/Superfast-Robotics/robot-skill-hub';
const PUBLICATION = 'https://catalog.example.invalid/publication.json';
const hash = (value: string) => createHash('sha256').update(value).digest('hex');
const bundled = build({
  entryPoints: [fileURLToPath(new URL('../../src/index.ts', import.meta.url))],
  bundle: true, write: false, platform: 'browser', format: 'esm', target: 'es2023'
}).then(result => result.outputFiles![0].text);

async function runtime(outbound: (request: RuntimeRequest) => RuntimeResponse | Promise<RuntimeResponse>, publicationURL = PUBLICATION) {
  return new Miniflare({
    telemetry: { enabled: false },
    workers: [{
      config: {
        name: 'robot-skill-hub-runtime-test', compatibilityDate: '2026-10-17',
        manifest: { mainModule: 'worker.js', modules: { 'worker.js': { type: 'esm', contents: await bundled } } },
        env: {
          GITHUB_TOKEN: { type: 'text', value: GITHUB_TOKEN },
          SUBMISSION_TOKENS_JSON: { type: 'text', value: JSON.stringify([{ principal_id: PRINCIPAL, sha256: hash(TOKEN) }]) },
          PUBLICATION_URL: { type: 'text', value: publicationURL },
          SUBMIT_LIMITER: { type: 'rate-limit', namespace: '78345101', simple: { limit: 10, period: 60 } },
          STATUS_LIMITER: { type: 'rate-limit', namespace: '78345102', simple: { limit: 60, period: 60 } }
        }
      },
      dev: { outboundService: { type: 'fetcher', handler: outbound } }
    }]
  });
}

async function status(mf: Miniflare) {
  return mf.dispatchFetch(`https://api.example.invalid/v1/submissions/${ID}`, {
    headers: { Authorization: `Bearer ${TOKEN}` }
  });
}

test('native session authentication makes no outbound calls and exposes no token', async () => {
  let calls = 0;
  const mf = await runtime(() => { calls++; throw Error('Session must not call outbound services'); });
  try {
    const response = await mf.dispatchFetch('https://api.example.invalid/v1/session', {
      headers: { Authorization: `Bearer ${TOKEN}` }
    });
    assert.equal(response.status, 200); const body: any = await response.json();
    assert.equal(body.authenticated, true); assert.equal(body.principal_id, hash('rsh-principal-v1\0' + PRINCIPAL));
    assert.equal(body.authorization.project_memory_scope, 'client_policy_required');
    assert.ok(!JSON.stringify(body).includes(TOKEN)); assert.equal(calls, 0);
  } finally { await mf.dispose(); }
});

test('native Workers fetch reaches GitHub and returns the structured upstream error', async () => {
  let calls = 0;
  const mf = await runtime(request => {
    calls++;
    assert.equal(new URL(request.url).origin, 'https://api.github.com');
    assert.ok(request.url.startsWith(API + '/pulls?'));
    assert.equal(request.headers.get('Authorization'), `Bearer ${GITHUB_TOKEN}`);
    return RuntimeResponse.json({ message: 'Bad credentials' }, { status: 401 });
  });
  try {
    const response = await status(mf);
    assert.equal(response.status, 503);
    const body: any = await response.json();
    assert.equal(body.reason_code, 'github_unavailable');
    assert.match(body.message, /GitHub operation failed \(401\)/);
    assert.equal(calls, 1);
  } finally { await mf.dispose(); }
});

function mergedFixture() {
  const skill = 'maniskill-panda-pick-cube';
  const merge = 'e'.repeat(40); const head = 'f'.repeat(40); const source = 'b'.repeat(40);
  const path = `docs/recipes/${skill}.md`; const contentHash = 'd'.repeat(64);
  const receipt = {
    schema_version: '1', submission_id: ID, principal_id: hash('rsh-principal-v1\0' + PRINCIPAL),
    skill_id: skill, base: { record_version: '1.0.0', hub_commit: 'a'.repeat(40), source_commit: source },
    new_record_version: 'contrib-runtime-test', patch_hashes: { [path]: contentHash },
    evidence: { level: 'not_run', command: null, result: 'Runtime transport test only.', reported_by: 'submitter' },
    attribution: { contributor_label: 'Runtime test', preserve_upstream_attribution: true },
    hub_validation: { level: 'structure_checked', runtime: 'not_run', result: 'Test fixture.' }
  };
  const pull = {
    number: 1, html_url: 'https://github.com/Superfast-Robotics/robot-skill-hub/pull/1',
    body: `<!-- rsh-receipt:${Buffer.from(JSON.stringify(receipt)).toString('base64')} -->`,
    state: 'closed', merged_at: '2026-10-17T00:00:00Z', merge_commit_sha: merge,
    labels: [], head: { sha: merge, ref: 'submissions/' + ID }
  };
  const manifest = {
    schema_version: '1', hub_commit: head,
    records: [{ id: skill, record_version: receipt.new_record_version, source_commit: source,
      submission_ids: [ID], contribution_path_hashes: { [path]: contentHash }, compatibility: [], recipe_url: '/recipe' }]
  };
  return { pull, manifest, merge, head };
}

for (const proofStatus of ['valid', '404', 'corrupt', 'redirect']) test('native per-receipt publication proof preference: ' + proofStatus, async () => {
  const fixture = mergedFixture(); const calls: string[] = [];
  const origin = 'https://hub.superfastrobotics.com', legacy = origin + '/catalog/v1/publication.json';
  const proof = origin + '/catalog/v2/submissions/' + ID + '.json';
  const mf = await runtime(request => {
    calls.push(request.url);
    if (request.url.startsWith(API + '/pulls?')) return RuntimeResponse.json([fixture.pull]);
    if (request.url === proof || request.url === legacy) {
      assert.equal(request.headers.get('DNT'), '1'); assert.equal(request.headers.get('X-RSH-Telemetry'), 'off'); assert.equal(request.headers.has('Authorization'), false);
      if (request.url === legacy || proofStatus === 'valid') return RuntimeResponse.json(fixture.manifest);
      if (proofStatus === '404') return new RuntimeResponse(null, { status: 404 });
      if (proofStatus === 'redirect') return new RuntimeResponse(null, { status: 302, headers: { Location: 'https://evil.invalid/proof' } });
      return new RuntimeResponse('{broken');
    }
    if (request.url === `${API}/commits/${fixture.merge}/check-runs?per_page=100&filter=latest`) return RuntimeResponse.json({ check_runs: [{ name: 'Checks', status: 'completed', conclusion: 'success' }] });
    if (request.url === `${API}/compare/${fixture.merge}...${fixture.head}`) return RuntimeResponse.json({ status: 'ahead', merge_base_commit: { sha: fixture.merge } });
    assert.fail('Unexpected native per-receipt request: ' + request.url);
  }, legacy);
  try {
    const result = await status(mf); assert.equal(result.status, 200); const body: any = await result.json();
    assert.ok(calls.includes(proof)); assert.equal(calls.includes(legacy), proofStatus === '404');
    assert.equal(body.status, ['valid', '404'].includes(proofStatus) ? 'published' : 'merged');
    if (['corrupt', 'redirect'].includes(proofStatus)) assert.equal(body.reason_code, 'publication_unavailable');
  } finally { await mf.dispose(); }
});

for (const redirected of [true, false]) {
  test(`native publication fetch ${redirected ? 'rejects redirects without following them' : 'confirms matching deployed publication'}`, async () => {
    const fixture = mergedFixture(); const calls: string[] = [];
    const redirectTarget = 'https://redirected.example.invalid/manifest.json';
    const mf = await runtime(request => {
      calls.push(request.url);
      if (request.url.startsWith(API + '/pulls?')) {
        assert.equal(request.headers.get('Authorization'), `Bearer ${GITHUB_TOKEN}`);
        return RuntimeResponse.json([fixture.pull]);
      }
      if (request.url === PUBLICATION) {
        assert.equal(request.headers.has('Authorization'), false);
        return redirected ? new RuntimeResponse(null, { status: 302, headers: { Location: redirectTarget } }) : RuntimeResponse.json(fixture.manifest);
      }
      if (request.url === redirectTarget) return RuntimeResponse.json(fixture.manifest);
      if (request.url === `${API}/commits/${fixture.merge}/check-runs?per_page=100&filter=latest`) {
        assert.equal(request.headers.has('Authorization'), false);
        return RuntimeResponse.json({ check_runs: [{ name: 'Checks', status: 'completed', conclusion: 'success' }] });
      }
      if (request.url === `${API}/compare/${fixture.merge}...${fixture.head}`) {
        return RuntimeResponse.json({ status: 'ahead', merge_base_commit: { sha: fixture.merge } });
      }
      assert.fail('Unexpected intercepted runtime request: ' + request.url);
    });
    try {
      const response = await status(mf); assert.equal(response.status, 200);
      const body: any = await response.json();
      assert.ok(calls.includes(PUBLICATION), 'Publication must reach the native fetch transport');
      assert.equal(calls.includes(redirectTarget), false, 'Publication redirects must never be followed');
      if (redirected) {
        assert.equal(body.status, 'merged'); assert.equal(body.reason_code, 'publication_unavailable');
        assert.equal(body.published_version, null);
        assert.equal(calls.some(url => url.includes('/compare/')), false);
      } else {
        assert.equal(body.status, 'published'); assert.equal(body.published_version, 'contrib-runtime-test');
        assert.equal(body.published_hub_commit, fixture.head);
      }
    } finally { await mf.dispose(); }
  });
}

test('native memory save stores one bounded finding and confirms its exact merged publication', async () => {
  const hub = 'a'.repeat(40), head = 'c'.repeat(40), source = 'b'.repeat(40), merge = 'e'.repeat(40), deployed = 'f'.repeat(40);
  const skill = 'maniskill-panda-pick-cube'; let pull: any; let stored = ''; let memoryId = ''; let manifest: any; let proofReads = 0;
  const canonical = 'https://hub.superfastrobotics.com';
  const finding = { schema_version: '1', skill_id: skill, base: { hub_commit: hub, source_commit: source, record_version: '1.0.0' },
    kind: 'failure_observation', summary: 'Report a missing planner package', observation: 'The planner package was missing from the isolated source preparation environment.', resolution: null,
    environment: { runtime: 'maniskill', robot: 'panda' }, evidence: { level: 'contributor_reported', command: null, result: 'Package missing; no robot execution.', reported_by: 'submitter' },
    attribution: { contributor_label: 'Transport test', preserve_upstream_attribution: true }, publication: { public_submission_allowed: true } };
  const mf = await runtime(async request => {
    if (request.url === canonical + '/catalog/v2/memories/' + memoryId + '.json') {
      proofReads++; assert.equal(request.headers.has('Authorization'), false); assert.equal(request.headers.get('DNT'), '1'); assert.equal(request.headers.get('X-RSH-Telemetry'), 'off');
      return RuntimeResponse.json(manifest);
    }
    assert.ok(request.url.startsWith(API + '/'));
    const publicChecks = request.url.includes('/check-runs');
    assert.equal(request.headers.get('Authorization'), publicChecks ? null : `Bearer ${GITHUB_TOKEN}`);
    if (request.url.startsWith(API + '/pulls?')) return RuntimeResponse.json(pull ? [pull] : []);
    if (request.url.startsWith(API + '/git/ref/heads/memories/')) return new RuntimeResponse(null, { status: 404 });
    if (request.url === API + '/git/ref/heads/main') return RuntimeResponse.json({ object: { sha: head } });
    if (request.url === `${API}/compare/${hub}...${head}`) return RuntimeResponse.json({ status: 'ahead', merge_base_commit: { sha: hub } });
    if (request.url === `${API}/compare/${merge}...${deployed}`) return RuntimeResponse.json({ status: 'ahead', merge_base_commit: { sha: merge } });
    if (request.url.startsWith(`${API}/contents/catalog/records/${skill}.json?`)) {
      assert.equal(new URL(request.url).searchParams.get('ref'), hub);
      const raw = JSON.stringify({ id: skill, maintenance: { record_version: '1.0.0' }, source: { commit: source } });
      return RuntimeResponse.json({ type: 'file', encoding: 'base64', size: raw.length, content: Buffer.from(raw).toString('base64') });
    }
    if (request.url.startsWith(API + '/contents/.hub/memories/')) return new RuntimeResponse(null, { status: 404 });
    if (request.url === API + '/git/commits/' + head) return RuntimeResponse.json({ tree: { sha: 'base-tree' } });
    if (request.url === API + '/git/trees') {
      const body: any = await request.json(); assert.equal(body.tree.length, 1);
      stored = body.tree[0].content; const entry = JSON.parse(stored); memoryId = entry.memory_id;
      assert.equal(body.tree[0].path, `.hub/memories/${memoryId}.json`); assert.equal(entry.hub_validation.runtime, 'not_run');
      return RuntimeResponse.json({ sha: 'new-tree' });
    }
    if (request.url === API + '/git/commits') return RuntimeResponse.json({ sha: '1'.repeat(40) });
    if (request.url === API + '/git/refs') return RuntimeResponse.json({});
    if (request.url === API + '/pulls') {
      const body: any = await request.json(); assert.equal(body.draft, true); assert.equal(body.base, 'main'); assert.equal(body.head, 'memories/' + memoryId);
      pull = { number: 2, html_url: 'https://github.com/Superfast-Robotics/robot-skill-hub/pull/2', body: body.body, state: 'open', merged_at: null,
        merge_commit_sha: null, labels: [], head: { sha: '1'.repeat(40), ref: body.head } };
      return RuntimeResponse.json(pull);
    }
    if (publicChecks) return RuntimeResponse.json({ check_runs: [{ name: 'Checks', status: 'completed', conclusion: 'success' }] });
    assert.fail('Unexpected memory runtime request: ' + request.url);
  }, canonical + '/catalog/v1/publication.json');
  try {
    const response = await mf.dispatchFetch('https://api.example.invalid/v1/memories', { method: 'POST', headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }, body: JSON.stringify(finding) });
    assert.equal(response.status, 201); const saved: any = await response.json(); assert.equal(saved.memory_id, memoryId); assert.equal(saved.content_sha256, hash(stored));
    const read = () => mf.dispatchFetch(`https://api.example.invalid/v1/memories/${memoryId}`, { headers: { Authorization: `Bearer ${TOKEN}` } });
    assert.equal((await (await read()).json() as any).status, 'pending_review');
    pull.merged_at = '2026-10-17T00:00:00Z'; pull.merge_commit_sha = merge; pull.state = 'closed';
    manifest = { schema_version: '1', hub_commit: deployed, memories: [{ memory_id: memoryId, skill_id: skill, fingerprint: saved.fingerprint,
      content_sha256: saved.content_sha256, record_version: '1.0.0', source_commit: source, base_hub_commit: hub, entry_url: 'https://catalog.example.invalid/memory.json' }] };
    const published: any = await (await read()).json(); assert.equal(published.status, 'published'); assert.equal(published.hub_validation.runtime, 'not_run');
    assert.equal(published.entry_url, manifest.memories[0].entry_url);
    assert.equal(proofReads, 1);
  } finally { await mf.dispose(); }
});

test('native new-skill intake stores data only, creates an internal draft PR and replays it', async () => {
  const hub = 'a'.repeat(40), source = 'b'.repeat(40), digest = 'c'.repeat(64), skill = 'ros2-panda-grasp';
  let pull: any; let receipt: any; let reference: any; let treeWrites = 0; let prWrites = 0;
  const input = { schema_version: '1', base: { hub_commit: hub }, skill: {
    id: skill, name: 'Panda grasp action', summary: 'Pinned ROS 2 source for a Panda grasp action.', framework: 'ros2', kind: 'community_skill', capabilities: ['grasp'], aliases: [], robots: ['panda'],
    source: { repository: 'https://github.com/upstream/robot', commit: source, path: 'grasp.cpp', url: `https://github.com/upstream/robot/blob/${source}/grasp.cpp`, sha256: digest, bytes: 2000, authors: ['Upstream authors'] },
    license: { spdx: 'Apache-2.0', url: `https://github.com/upstream/robot/blob/${source}/LICENSE`, scope: 'Source code only.' }, artifact: { kind: 'code', format: 'cpp' },
    requirements: { python: null, packages: [], hardware: ['panda'], system: ['ROS 2'], notes: 'Inspect upstream setup before hardware use.' },
    invocation: { entrypoint: 'ROS 2 action client', notes: 'Hardware execution needs project authorization.' }, setup_url: 'https://docs.ros.org/en/rolling/',
    compatibility: [{ runtime: 'ros2', runtime_version: 'unknown', robot: 'panda', controller: 'unknown', observation: 'unknown', os: 'linux' }] },
    attribution: { contributor_label: 'Runtime intake test', preserve_upstream_attribution: true }, publication: { public_submission_allowed: true } };
  const mf = await runtime(async request => {
    assert.ok(request.url.startsWith(API + '/'), 'Submitted source URLs must never be fetched by intake');
    assert.equal(request.headers.get('Authorization'), `Bearer ${GITHUB_TOKEN}`);
    if (request.url.startsWith(API + '/pulls?')) return RuntimeResponse.json(pull ? [pull] : []);
    if (request.url.startsWith(API + '/git/ref/heads/submissions/')) return new RuntimeResponse(null, { status: 404 });
    if (request.url === API + '/git/ref/heads/main') return RuntimeResponse.json({ object: { sha: hub } });
    if (request.url.startsWith(API + '/contents/catalog/source-index-manifest.json?')) {
      const raw = JSON.stringify({ schema_version: '1', scheme: 'sha256-id-prefix-2', records: 0, shards: {} });
      return RuntimeResponse.json({ type: 'file', encoding: 'base64', size: raw.length, content: Buffer.from(raw).toString('base64') });
    }
    if (request.url.startsWith(API + '/contents/catalog/records/') || request.url.startsWith(API + '/contents/catalog/intake/')) return new RuntimeResponse(null, { status: 404 });
    if (request.url === API + '/git/commits/' + hub) return RuntimeResponse.json({ tree: { sha: 'base-tree' } });
    if (request.url === API + '/git/trees') {
      treeWrites++; const body: any = await request.json(); assert.equal(body.tree.length, 2);
      const file = body.tree.find((r: any) => r.path === `catalog/intake/${skill}.json`); assert.ok(file); reference = JSON.parse(file.content);
      receipt = JSON.parse(body.tree.find((r: any) => r.path.startsWith('.hub/submissions/')).content);
      assert.equal(receipt.patch_hashes[file.path], hash(file.content)); assert.equal(reference.access.hub_prepare, false);
      assert.equal(reference.license.verified, false); assert.equal(reference.evidence.runtime_verification, 'not_run');
      return RuntimeResponse.json({ sha: 'new-tree' });
    }
    if (request.url === API + '/git/commits') return RuntimeResponse.json({ sha: '1'.repeat(40) });
    if (request.url === API + '/git/refs') return RuntimeResponse.json({});
    if (request.url === API + '/pulls') {
      prWrites++; const body: any = await request.json(); assert.equal(body.draft, true); assert.equal(body.base, 'main');
      assert.equal(body.head, 'submissions/' + receipt.submission_id);
      pull = { number: 3, html_url: 'https://github.com/Superfast-Robotics/robot-skill-hub/pull/3', body: body.body, state: 'open', merged_at: null,
        merge_commit_sha: null, labels: [], head: { sha: '1'.repeat(40), ref: body.head } };
      return RuntimeResponse.json(pull);
    }
    assert.fail('Unexpected native intake request: ' + request.url);
  });
  try {
    const post = () => mf.dispatchFetch('https://api.example.invalid/v1/skills', { method: 'POST', headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json', 'Idempotency-Key': 'native-new-skill-1' }, body: JSON.stringify(input) });
    const first = await post(); assert.equal(first.status, 201); const saved: any = await first.json();
    const repeated = await post(); assert.equal(repeated.status, 200); assert.equal((await repeated.json() as any).submission_id, saved.submission_id);
    assert.equal(treeWrites, 1); assert.equal(prWrites, 1); assert.equal(reference.requirements.python, null);
  } finally { await mf.dispose(); }
});
