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

async function runtime(outbound: (request: RuntimeRequest) => RuntimeResponse | Promise<RuntimeResponse>) {
  return new Miniflare({
    telemetry: { enabled: false },
    workers: [{
      config: {
        name: 'robot-skill-hub-runtime-test', compatibilityDate: '2026-10-17',
        manifest: { mainModule: 'worker.js', modules: { 'worker.js': { type: 'esm', contents: await bundled } } },
        env: {
          GITHUB_TOKEN: { type: 'text', value: GITHUB_TOKEN },
          SUBMISSION_TOKENS_JSON: { type: 'text', value: JSON.stringify([{ principal_id: PRINCIPAL, sha256: hash(TOKEN) }]) },
          PUBLICATION_URL: { type: 'text', value: PUBLICATION },
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
