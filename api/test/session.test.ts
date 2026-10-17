import test from 'node:test';
import assert from 'node:assert/strict';
import { createHandler } from '../src/index.ts';
import { sha256 } from '../src/util.ts';
import type { Env } from '../src/types.ts';

const TOKEN = 'session-test-token-012345678901234567890123456789';
async function setup(disabled = false, allowed = true) {
  const counts = { github: 0, publication: 0, status: 0, submit: 0 };
  const env: Env = {
    GITHUB_TOKEN: 'dummy-not-used', PUBLICATION_URL: 'https://example.invalid/publication.json',
    SUBMISSION_TOKENS_JSON: JSON.stringify([{ principal_id: 'session-agent', sha256: await sha256(TOKEN), disabled }]),
    STATUS_LIMITER: { async limit() { counts.status++; return { success: allowed }; } },
    SUBMIT_LIMITER: { async limit() { counts.submit++; return { success: true }; } }
  };
  const handler = createHandler(() => { counts.github++; throw Error('Must not contact GitHub'); },
    async () => { counts.publication++; throw Error('Must not read publication'); });
  return { counts, call: (token?: string, method = 'GET') => handler(new Request('https://api.example/v1/session', {
    method, headers: token ? { Authorization: `Bearer ${token}` } : {}
  }), env) };
}

test('session checks an active credential without a repository read or sharing grant', async () => {
  const s = await setup(); const response = await s.call(TOKEN); const body: any = await response.json();
  assert.equal(response.status, 200); assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(body.authenticated, true);
  assert.equal(body.principal_id, await sha256('rsh-principal-v1\0session-agent'));
  assert.equal(body.authorization.project_memory_scope, 'client_policy_required');
  assert.ok(!JSON.stringify(body).includes(TOKEN)); assert.ok(!JSON.stringify(body).includes('session-agent'));
  assert.deepEqual(s.counts, { github: 0, publication: 0, status: 1, submit: 0 });
});

test('session rejects missing, invalid and revoked credentials before any adapter access', async () => {
  for (const [disabled, token] of [[false, undefined], [false, 'invalid-012345678901234567890123456789'], [true, TOKEN]] as const) {
    const s = await setup(disabled); const response = await s.call(token);
    assert.equal(response.status, 401); const body: any = await response.json();
    assert.equal(body.reason_code, 'invalid_token'); assert.equal(body.next_action, 'check_local_configuration');
    assert.deepEqual(s.counts, { github: 0, publication: 0, status: 0, submit: 0 });
  }
});

test('session uses the shared status limiter and accepts no write method', async () => {
  const s = await setup(false, false); const response = await s.call(TOKEN);
  assert.equal(response.status, 429); assert.equal(response.headers.get('Retry-After'), '60');
  assert.deepEqual(s.counts, { github: 0, publication: 0, status: 1, submit: 0 });
  assert.equal((await s.call(TOKEN, 'POST')).status, 404);
});
