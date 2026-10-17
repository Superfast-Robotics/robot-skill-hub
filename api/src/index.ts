import { ApiError, SID, type Env, type GitHubAdapter } from './types.ts';
import { GitHub } from './github.ts';
import { authenticate, getStatus, limited, submit } from './service.ts';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...(status === 429 ? { 'Retry-After': '60' } : {}) }
  });
}
export function createHandler(factory?: (env: Env) => GitHubAdapter, publicationFetcher?: (url: string) => Promise<unknown>) {
  return async (request: Request, env: Env): Promise<Response> => {
    try {
      const url = new URL(request.url);
      if (request.method === 'GET' && url.pathname === '/healthz') return json({ service: 'robot-skill-hub-api', status: 'ok', schema_version: '1', submission_configured: Boolean(env.GITHUB_TOKEN && env.SUBMISSION_TOKENS_JSON && env.SUBMIT_LIMITER && env.STATUS_LIMITER) });
      const isPost = request.method === 'POST' && url.pathname === '/v1/submissions';
      const id = url.pathname.match(/^\/v1\/submissions\/(sub_[a-f0-9]{64})$/)?.[1];
      if (!isPost && !(request.method === 'GET' && id && SID.test(id))) return json({ status: 'failed', reason_code: 'not_found', message: 'Endpoint not found.' }, 404);
      const principal = await authenticate(request, env);
      await limited(request, principal, env, isPost);
      const adapter = factory ? factory(env) : new GitHub(env.GITHUB_TOKEN!);
      if (isPost) { const result = await submit(request, principal, adapter); return json(result.response, result.status); }
      return json(await getStatus(id!, principal, adapter, async () => {
        if (publicationFetcher) return publicationFetcher(env.PUBLICATION_URL);
        const response = await fetch(env.PUBLICATION_URL, { redirect: 'error', signal: AbortSignal.timeout(10000), headers: { 'Cache-Control': 'no-cache' } });
        if (!response.ok) { await response.body?.cancel(); throw new Error('Publication unavailable'); }
        const content = await response.text(); if (content.length > 512 * 1024) throw new Error('Publication too large');
        return JSON.parse(content);
      }));
    } catch (error) {
      if (error instanceof ApiError) return json({ status: 'blocked', reason_code: error.code, message: error.message, next_action: error.status === 409 ? 'inspect_and_prepare_new_bundle' : 'keep_local_bundle_and_continue_user_task' }, error.status);
      // No request bodies, bearer tokens, raw exceptions or upstream response bodies are logged.
      return json({ status: 'blocked', reason_code: 'service_unavailable', message: 'A temporary service failure occurred. Retry with the same idempotency key.', next_action: 'keep_local_bundle_and_continue_user_task' }, 503);
    }
  };
}
export default { fetch: createHandler() };
