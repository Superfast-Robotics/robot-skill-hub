/** Public immutable experience, explicitly separate from reviewed catalog code. */
import type { Env, MemoryFinding } from './types.ts';
import { ApiError } from './types.ts';
import { assert, canonical, sha256, rejectSubmissionSecrets } from './util.ts';
import { validateMemory, findingFingerprint } from './memories.ts';
import { indexedRow, type CatalogDatabase, type Row } from './catalog.ts';
import { memoryEnvironmentKey } from './memory-environment.ts';
import { parsePatch } from './patch.ts';

const PREFIX = '/v1/community';
const ID = /^exp_[a-f0-9]{64}$/;
const TOKEN = /^csh_[A-Za-z0-9_-]{43}$/;
const MAX_BYTES = 32768;
const fields = (v: any, keys: string[]) => v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).every(k => keys.includes(k));
const first = async (db: CatalogDatabase, sql: string, ...args: unknown[]) => (await db.prepare(sql).bind(...args).all()).results[0];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: {
  'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
  'Access-Control-Allow-Origin': '*', ...(status === 429 ? { 'Retry-After': '3600' } : {}) } });
async function body(request: Request): Promise<Row> {
  assert(request.headers.get('Content-Type')?.split(';')[0] === 'application/json' && !request.headers.has('Content-Encoding'), 'invalid_content_type', 'Send uncompressed application/json.', 415);
  assert(Number(request.headers.get('Content-Length') || 0) <= MAX_BYTES, 'payload_too_large', 'Experience is limited to 32 KiB.', 413);
  const reader = request.body?.getReader(); assert(reader, 'invalid_body', 'A JSON body is required.');
  const chunks: Uint8Array[] = []; let size = 0;
  try { while (true) { const part = await reader.read(); if (part.done) break; size += part.value.length;
    if (size > MAX_BYTES) { await reader.cancel(); throw new ApiError(413, 'payload_too_large', 'Experience is limited to 32 KiB.'); } chunks.push(part.value); }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422, 'invalid_json', 'A UTF-8 JSON object is required.'); }
}
async function mac(env: Env, text: string) {
  assert(env.METRICS_KEY, 'community_not_configured', 'Enrollment is temporarily unavailable.', 503);
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(env.METRICS_KEY), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return [...new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode('community-v1\0' + text)))].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function address(env: Env, request: Request, day: string) {
  // Cloudflare overwrites this header. Never persist a raw address or use it for analytics.
  const ip = request.headers.get('CF-Connecting-IP');
  assert(ip, 'enrollment_unavailable', 'Enrollment requires the edge address binding.', 503);
  return mac(env, day + '\0' + ip);
}
async function credential(request: Request, db: CatalogDatabase) {
  const token = request.headers.get('Authorization')?.match(/^Bearer (.+)$/)?.[1];
  assert(token && TOKEN.test(token), 'community_auth_required', 'Enroll a community installation first.', 401);
  const id = await sha256(token);
  assert(await first(db, 'SELECT id FROM community_principals WHERE id=? AND disabled=0', id), 'community_auth_required', 'This installation is unavailable or revoked.', 401);
  return { id, token };
}
export interface Experience { schema_version: '1'; finding: MemoryFinding; parent_id?: string; variant?: { patch: string; license_spdx: string }; outcome?: 'succeeded' | 'failed' | 'not_applicable' }
export async function identity(value: Experience) {
  return 'exp_' + await sha256(canonical({ finding: await findingFingerprint(value.finding),
    parent_id: value.parent_id || null, variant: value.variant || null, outcome: value.outcome || null }));
}
export function validateExperience(value: any): asserts value is Experience {
  assert(fields(value, ['schema_version', 'finding', 'parent_id', 'variant', 'outcome']) && value.schema_version === '1', 'invalid_experience', 'Use the documented experience envelope.');
  validateMemory(value.finding);
  if (value.parent_id !== undefined) assert(ID.test(value.parent_id), 'invalid_parent', 'Use the exact parent experience ID.');
  if (value.variant !== undefined) {
    assert(fields(value.variant, ['patch', 'license_spdx']) && typeof value.variant.patch === 'string' && value.variant.patch.length <= 12000
      && /^--- (?:a\/)?[^\r\n]+\r?\n\+\+\+ (?:b\/)?[^\r\n]+/m.test(value.variant.patch)
      && typeof value.variant.license_spdx === 'string' && /^[A-Za-z0-9.+-]{2,80}$/.test(value.variant.license_spdx), 'invalid_variant', 'A variant needs a bounded unified diff and the applicable upstream SPDX license.');
    assert(value.finding.resolution && !value.outcome, 'invalid_variant', 'Describe the reusable change separately from a later reuse outcome.');
    // Inert patch data is downloadable, never applied by the Hub or injected into instructions.
    const paths = parsePatch(value.variant.patch).map(file => file.path);
    assert(paths.every((path: string) => /^[A-Za-z0-9_.\/-]+$/.test(path) && !path.startsWith('/')
      && !path.split('/').some(p => p.endsWith('.') || ['..', '.git', '.github', '.agents', '.claude', '.codex', '.cursor', '.gemini', '.vscode'].includes(p.toLowerCase()))
      && !/(?:^|\/)(?:\.env(?:\..*)?|AGENTS\.md|SKILL\.md|CLAUDE\.md|GEMINI\.md|copilot-instructions\.md)$/i.test(path)), 'invalid_variant_path', 'Patch paths must be relative source paths, excluding credentials and agent instructions.');
  }
  if (value.outcome !== undefined) assert(value.parent_id && ['succeeded', 'failed', 'not_applicable'].includes(value.outcome)
    && value.finding.evidence.level === 'contributor_reported', 'invalid_outcome', 'Reuse reports require an exact parent and an actual reported result.');
  rejectSubmissionSecrets(value);
  assert(!/\bcsh_[A-Za-z0-9_-]{43}\b/.test(JSON.stringify(value)), 'sensitive_submission', 'Remove community credentials before sharing.');
}
function unpack(row: Row) {
  return { id: row.id, sequence: row.seq, kind: row.kind, content: JSON.parse(row.content_json), content_sha256: row.content_sha256,
    created_at: row.created_at, trust: 'contributor_reported', interpretation: 'data_only', canonical_catalog_changed: false,
    ...(row.kind === 'variant' ? { patch_base: 'exact_catalog_source', patch_application: 'caller_checks_context_then_applies_in_authorized_workspace' } : {}),
    validation: { schema: 'checked', source_pins: 'checked_against_retained_or_active_catalog', original_hub_commit: 'contributor_supplied', runtime: 'not_run' } };
}
function summary(row: Row) {
  const full = unpack(row), value = full.content, finding = value.finding;
  return { id: full.id, sequence: full.sequence, kind: full.kind, summary: finding.summary,
    base: finding.base, environment: finding.environment, evidence_level: finding.evidence.level,
    parent_id: value.parent_id || null, outcome: value.outcome || null, trust: full.trust,
    detail_path: PREFIX + '/items/' + full.id, content_sha256: full.content_sha256,
    applicability: 'caller_must_check', execution_performed: false };
}
export async function communityQuery(db: CatalogDatabase, input: Row) {
  assert(fields(input, ['skill_id', 'record_version', 'source_commit', 'environment', 'limit', 'after', 'through', 'parent_id']), 'invalid_query', 'Use documented exact-scope query fields.');
  assert(/^[a-z0-9][a-z0-9-]{0,79}$/.test(input.skill_id || '') && typeof input.record_version === 'string' && input.record_version.length <= 120 && input.record_version.length > 0
    && /^(?:[a-f0-9]{40}|sha256:[a-f0-9]{64})$/.test(input.source_commit || ''), 'invalid_scope', 'Exact skill, record version and source revision are required.');
  const limit = input.limit === undefined ? 5 : Number(input.limit), after = Number(input.after || 0);
  assert(Number.isSafeInteger(limit) && limit >= 1 && limit <= 20 && Number.isSafeInteger(after) && after >= 0, 'invalid_pagination', 'Use limit 1..20 and a nonnegative cursor.');
  const through = input.through === undefined ? Number((await first(db, 'SELECT coalesce(max(seq),0) n FROM community_items')).n) : Number(input.through);
  assert(Number.isSafeInteger(through) && through >= after, 'invalid_pagination', 'Keep the same through watermark on subsequent pages.');
  const environment = input.environment || {};
  assert(environment && typeof environment === 'object' && !Array.isArray(environment) && Object.keys(environment).length <= 16 && Object.entries(environment).every(([k,v]) => memoryEnvironmentKey(k) && typeof v === 'string' && v.length > 0 && v.length <= 240), 'invalid_environment', 'Use explicit bounded environment labels.');
  const clauses = ['skill_id=?', 'record_version=?', 'source_commit=?', 'seq<?', 'seq<=?', 'hidden=0'];
  const values: unknown[] = [input.skill_id, input.record_version, input.source_commit, after || through + 1, through];
  for (const [key, value] of Object.entries(environment)) { clauses.push('lower(json_extract(environment_json,?))=lower(?)'); values.push('$.' + JSON.stringify(key), value); }
  if (input.parent_id) { assert(ID.test(input.parent_id), 'invalid_parent', 'Use an experience ID.'); clauses.push('parent_id=?'); values.push(input.parent_id); }
  else clauses.push("kind!='reuse_report'");
  const rows = (await db.prepare(`SELECT * FROM community_items WHERE ${clauses.join(' AND ')} ORDER BY seq DESC LIMIT ?`).bind(...values, limit + 1).all()).results;
  const more = rows.length > limit, page = rows.slice(0, limit);
  const results = [];
  for (const row of page) {
    const reports = (await db.prepare(`SELECT a.principal_id,c.content_json FROM community_items c JOIN community_attestations a ON a.item_id=c.id
      WHERE c.parent_id=? AND c.kind='reuse_report' AND c.hidden=0 AND c.seq<=? ORDER BY a.seq DESC LIMIT 101`).bind(row.id, through).all()).results;
    const latest = new Map<string, string>();
    for (const report of reports.slice(0,100)) {
      const content = JSON.parse(report.content_json);
      if (Object.entries(environment).every(([k,v]) => String(content.finding.environment[k] || '').toLowerCase() === String(v).toLowerCase()) && !latest.has(report.principal_id)) latest.set(report.principal_id, content.outcome);
    }
    results.push({ ...summary(row), reuse_reports: { succeeded: [...latest.values()].filter(v => v === 'succeeded').length,
      failed: [...latest.values()].filter(v => v === 'failed').length, not_applicable: [...latest.values()].filter(v => v === 'not_applicable').length,
      basis: 'latest_matching_report_per_pseudonymous_installation', independent_agents_verified: false, complete: reports.length <= 100 } });
  }
  return { schema_version: '1', status: 'ready', results, through, next_after: more ? page.at(-1)!.seq : null,
    complete: !more, trust: 'contributor_reported', selection: 'exact_source_and_requested_environment_then_newest; reports_attached_not_popularity_ranked',
    next_action: 'check_applicability_then_inspect_selected_variant; report_actual_reuse_outcome' };
}
export async function communityForSelection(env: Env, row: Row, environment: Row = {}) {
  try { assert(env.CATALOG, 'community_unavailable', 'Community storage is unavailable.', 503);
    return await communityQuery(env.CATALOG, { skill_id: row.id, record_version: row.record_version, source_commit: row.source_commit, environment, limit: 3 });
  } catch { return { status: 'unknown', reason_code: 'community_unavailable', results: [], complete: false }; }
}
export async function handleCommunity(request: Request, env: Env): Promise<Response | null> {
  const url = new URL(request.url); if (!url.pathname.startsWith(PREFIX + '/') && url.pathname !== PREFIX) return null;
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type, Authorization, DNT, X-RSH-Telemetry' } });
  try {
    const db = env.CATALOG; assert(db, 'community_unavailable', 'Community storage is unavailable.', 503);
    const now = Math.floor(Date.now() / 1000), day = new Date(now * 1000).toISOString().slice(0,10);
    if (env.STATUS_LIMITER) assert((await env.STATUS_LIMITER.limit({ key: 'community:' + (request.headers.get('CF-Connecting-IP') || 'unknown') })).success, 'rate_limited', 'Retry later with the same content.', 429);
    if (request.method === 'GET' && url.pathname === PREFIX + '/challenge') {
      const tag = await address(env, request, day), expires = now + 600;
      const payload = expires + '.' + tag;
      return json({ schema_version: '1', challenge: payload + '.' + await mac(env, payload), difficulty_hex_zeros: 4, expires_at: expires,
        algorithm: 'sha256(challenge + "." + sha256(token) + "." + nonce)', token_format: 'csh_ plus 43 base64url characters', registration: PREFIX + '/enroll' });
    }
    if (request.method === 'POST' && url.pathname === PREFIX + '/enroll') {
      const v = await body(request);
      assert(fields(v, ['token', 'challenge', 'nonce']) && TOKEN.test(v.token || '') && typeof v.challenge === 'string' && /^\d{10}\.[a-f0-9]{64}\.[a-f0-9]{64}$/.test(v.challenge)
        && typeof v.nonce === 'string' && /^\d{1,16}$/.test(v.nonce), 'invalid_enrollment', 'Supply a generated installation token and solved challenge.');
      const id = await sha256(v.token), existing = await first(db, 'SELECT disabled FROM community_principals WHERE id=?', id);
      if (existing) { assert(!existing.disabled, 'community_auth_required', 'Installation revoked.', 401); return json({ status: 'ready', principal_id: id, replay: true }); }
      const [expiration, tag, signature] = v.challenge.split('.'), expires = Number(expiration);
      assert(expires > now && expires <= now + 600 && tag === await address(env, request, day) && signature === await mac(env, expiration + '.' + tag), 'expired_challenge', 'Fetch a fresh challenge.', 403);
      assert((await sha256(v.challenge + '.' + id + '.' + v.nonce)).startsWith('0000'), 'invalid_proof', 'Solve the bounded enrollment proof.', 403);
      await db.prepare('INSERT OR IGNORE INTO community_principals(id,created_at,day,ip_day_hash) VALUES(?,?,?,?)').bind(id, now, day, tag).run();
      return json({ status: 'ready', principal_id: id, identity: 'pseudonymous_installation', daily_writes: 20 }, 201);
    }
    if (request.method === 'GET' && url.pathname === PREFIX + '/items') {
      const input: Row = Object.fromEntries(url.searchParams); if (input.environment) { try { input.environment = JSON.parse(input.environment); } catch { throw new ApiError(422, 'invalid_environment', 'Environment must be a JSON object.'); } }
      return json(await communityQuery(db, input));
    }
    const detail = url.pathname.match(/^\/v1\/community\/items\/(exp_[a-f0-9]{64})$/);
    if (request.method === 'GET' && detail) {
      const row = await first(db, 'SELECT * FROM community_items WHERE id=? AND hidden=0', detail[1]); assert(row, 'not_found', 'Experience unavailable.', 404);
      const attestations = await first(db, 'SELECT count(*) n FROM community_attestations WHERE item_id=?', detail[1]);
      return json({ ...unpack(row), attestations: { installations: attestations.n, independent_agents_verified: false } });
    }
    if (request.method === 'POST' && url.pathname === PREFIX + '/items') {
      const principal = await credential(request, db), value = await body(request); validateExperience(value); rejectSubmissionSecrets(value, principal.token);
      const id = await identity(value), existing = await first(db, 'SELECT * FROM community_items WHERE id=?', id);
      assert(!existing?.hidden, 'item_unavailable', 'This content has been quarantined.', 409);
      if (existing && await first(db, 'SELECT seq FROM community_attestations WHERE item_id=? AND principal_id=?', id, principal.id))
        return json({ status: 'stored', ...unpack(existing), replay: true, next_action: 'continue_user_task' });
      const finding = value.finding, base = finding.base;
      if (!existing) {
        let row = await indexedRow(db, base.hub_commit, finding.skill_id);
        if (!row) {
          // Documentation-only releases must not strand an agent's original
          // pins when a catalog generation is retired. Never silently rebase.
          const active = await first(db, 'SELECT hub_commit FROM catalog_active WHERE singleton=1');
          if (active) row = await indexedRow(db, active.hub_commit, finding.skill_id);
        }
        assert(row && row.record_version === base.record_version && row.source_commit === base.source_commit, 'unknown_source_pins', 'Use a retained published catalog version with these exact source pins.', 409);
        if (value.variant) assert(row.license?.verified === true && !/^(?:NOASSERTION|LicenseRef-)/.test(row.license?.spdx || '') && row.license?.spdx === value.variant.license_spdx,
          'license_mismatch', 'Automatic patch publication requires the verified license of the pinned upstream catalog record.');
        if (value.parent_id) {
          const parent = await first(db, 'SELECT * FROM community_items WHERE id=? AND hidden=0', value.parent_id);
          assert(parent && parent.skill_id === finding.skill_id && parent.source_commit === base.source_commit && parent.record_version === base.record_version, 'parent_scope_mismatch', 'The parent must belong to this exact source and record version.', 409);
          assert(parent.kind !== 'reuse_report', 'invalid_parent', 'Report or branch from a finding or variant, not a report.');
        }
      }
      const content = canonical(value), digest = await sha256(content), kind = value.outcome ? 'reuse_report' : value.variant ? 'variant' : 'finding';
      await db.batch([
        db.prepare('INSERT OR IGNORE INTO community_items(id,skill_id,record_version,source_commit,kind,parent_id,environment_json,content_json,content_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)')
          .bind(id, finding.skill_id, base.record_version, base.source_commit, kind, value.parent_id || null, canonical(finding.environment), content, digest, now),
        db.prepare('INSERT OR IGNORE INTO community_attestations(item_id,principal_id,day,created_at) VALUES(?,?,?,?)').bind(id, principal.id, day, now)
      ]);
      const stored = await first(db, 'SELECT * FROM community_items WHERE id=?', id);
      return json({ status: 'stored', ...unpack(stored), replay: Boolean(existing), next_action: 'continue_user_task' }, existing ? 200 : 201);
    }
    // Bounded, anonymous export is also the source of the append-only GitHub archive.
    if (request.method === 'GET' && url.pathname === PREFIX + '/export') {
      assert([...url.searchParams.keys()].every(k => ['after', 'through', 'stream'].includes(k)), 'invalid_query', 'Use an export cursor.');
      const after = Number(url.searchParams.get('after') || 0), stream = url.searchParams.get('stream') || 'items';
      assert(['items', 'attestations'].includes(stream) && Number.isSafeInteger(after) && after >= 0, 'invalid_query', 'Use a valid export stream and cursor.');
      const table = stream === 'items' ? 'community_items' : 'community_attestations';
      const through = Number(url.searchParams.get('through') ?? (await first(db, `SELECT coalesce(max(seq),0) n FROM ${table}`)).n);
      assert(Number.isSafeInteger(through) && through >= after, 'invalid_query', 'Use the original export watermark.');
      const rows = (await db.prepare(`SELECT ${stream === 'items' ? '*' : 'seq,item_id,principal_id,created_at'} FROM ${table} WHERE seq>? AND seq<=? ORDER BY seq LIMIT 20`).bind(after, through).all()).results;
      return json({ schema_version: '1', stream, through, rows: stream === 'items' ? rows.map(r => r.hidden ? { sequence: r.seq, id: r.id, hidden: true } : unpack(r)) : rows,
        next_after: rows.length && rows.at(-1)!.seq < through ? rows.at(-1)!.seq : null, contains_credentials: false });
    }
    return json({ status: 'blocked', reason_code: 'not_found' }, 404);
  } catch (error) {
    if (error instanceof ApiError) return json({ status: 'blocked', reason_code: error.code, message: error.message, next_action: 'keep_local_experience_and_continue_user_task' }, error.status);
    const quota = error instanceof Error && /community_(registration|write)_quota/.test(error.message);
    const capacity = error instanceof Error && /community_capacity|CHECK constraint failed.*(?:bytes|items|principals|attestations)/.test(error.message);
    return json({ status: 'blocked', reason_code: quota ? 'daily_community_budget' : capacity ? 'community_capacity' : 'community_unavailable', next_action: 'keep_local_experience_and_retry_later' }, quota ? 429 : 503);
  }
}
