import { ApiError, MID, SID, type Env, type GitHubAdapter } from './types.ts';
import { GitHub } from './github.ts';
import { authenticate, getStatus, limited, submit } from './service.ts';
import { capabilities, memoryStatus, requireMemoryAdapter, saveMemory } from './memories.ts';
import { submitSkill } from './intake.ts';
import { handlePublicRequest } from './public.ts';
import { pruneMeasurements, type Background } from './metrics.ts';
import { readPublication } from './publication.ts';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...(status === 429 ? { 'Retry-After': '60' } : {}) }
  });
}
export function createHandler(factory?: (env: Env) => GitHubAdapter, publicationFetcher?: (url: string) => Promise<unknown>) {
  return async (request: Request, env: Env, ctx?: { waitUntil(promise: Promise<unknown>): void }): Promise<Response> => {
    let memoryRequest = false;
    let sessionRequest = false;
    try {
      const url = new URL(request.url);
      const publicResponse = await handlePublicRequest(request, env, ctx);
      if (publicResponse) return publicResponse;
      memoryRequest = url.pathname.startsWith('/v1/memories');
      sessionRequest = request.method === 'GET' && url.pathname === '/v1/session';
      if (request.method === 'GET' && url.pathname === '/healthz') return json({ service: 'robot-skill-hub-api', status: 'ok', schema_version: '1', submission_configured: Boolean(env.GITHUB_TOKEN && env.SUBMISSION_TOKENS_JSON && env.SUBMIT_LIMITER && env.STATUS_LIMITER) });
      if (request.method === 'GET' && url.pathname === '/v1/capabilities') return json(capabilities());
      const isPost = request.method === 'POST' && url.pathname === '/v1/submissions';
      const isSkillPost = request.method === 'POST' && url.pathname === '/v1/skills';
      const isMemoryPost = request.method === 'POST' && url.pathname === '/v1/memories';
      const id = url.pathname.match(/^\/v1\/submissions\/(sub_[a-f0-9]{64})$/)?.[1];
      const memoryId = url.pathname.match(/^\/v1\/memories\/(mem_[a-f0-9]{64})$/)?.[1];
      if (!sessionRequest && !isPost && !isSkillPost && !isMemoryPost && !(request.method === 'GET' && (id && SID.test(id) || memoryId && MID.test(memoryId)))) return json({ status: 'failed', reason_code: 'not_found', message: 'Endpoint not found.' }, 404);
      const principal = await authenticate(request, env);
      await limited(request, principal, env, isPost || isSkillPost || isMemoryPost);
      if (sessionRequest) return json({ schema_version: '1', authenticated: true, principal_id: principal,
        authorization: { api_submission_allowed: true, project_memory_scope: 'client_policy_required' },
        next_action: 'check_project_policy' });
      const adapter = factory ? factory(env) : new GitHub(env.GITHUB_TOKEN!);
      if (isPost) { const result = await submit(request, principal, adapter); return json(result.response, result.status); }
      if (isSkillPost) { const result = await submitSkill(request, principal, adapter); return json(result.response, result.status); }
      if (isMemoryPost) { requireMemoryAdapter(adapter); const result = await saveMemory(request, principal, adapter); return json(result.response, result.status); }
      const publication = async () => {
        if (publicationFetcher) return publicationFetcher(env.PUBLICATION_URL);
        const response = await fetch(env.PUBLICATION_URL, { redirect: 'manual', signal: AbortSignal.timeout(10000), headers: { 'Cache-Control': 'no-cache' } });
        return readPublication(response);
      };
      if (memoryId) { requireMemoryAdapter(adapter); return json(await memoryStatus(memoryId, principal, adapter, publication)); }
      return json(await getStatus(id!, principal, adapter, publication));
    } catch (error) {
      if (error instanceof ApiError) return json({ status: 'blocked', reason_code: error.code, message: error.message, next_action: sessionRequest ? 'check_local_configuration' : memoryRequest ? 'keep_local_finding_and_continue_user_task' : error.status === 409 ? 'inspect_and_prepare_new_bundle' : 'keep_local_bundle_and_continue_user_task' }, error.status);
      // No request bodies, bearer tokens, raw exceptions or upstream response bodies are logged.
      return json({ status: 'blocked', reason_code: 'service_unavailable', message: memoryRequest ? 'A temporary service failure occurred. Preserve and retry the same minimal finding.' : 'A temporary service failure occurred. Retry with the same idempotency key.', next_action: memoryRequest ? 'keep_local_finding_and_continue_user_task' : 'keep_local_bundle_and_continue_user_task' }, 503);
    }
  };
}
export default { fetch: createHandler(), scheduled(_event: unknown, env: Env, ctx: Background) { ctx.waitUntil(pruneMeasurements(env)); } };
