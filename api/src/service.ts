import { ApiError, SHA, SID, receiptPath, type Bundle, type Env, type GitHubAdapter, type JsonObject, type Pull, type Receipt } from './types.ts';
import { assert, canonical, readReceipt, sha256 } from './util.ts';
import { applyPatch, parsePatch } from './patch.ts';

const MAX_BYTES = 64 * 1024;
const object = (v: any): v is JsonObject => v !== null && typeof v === 'object' && !Array.isArray(v);
const text = (v: any, max = 2000): v is string => typeof v === 'string' && v.length > 0 && v.length <= max && !v.includes('\0');

export function validateBundle(value: any): asserts value is Bundle {
  assert(object(value), 'invalid_schema', 'Expected a JSON object.');
  assert(Object.keys(value).every(k => ['schema_version', 'skill_id', 'base', 'change_kind', 'summary', 'patch', 'environment', 'evidence', 'attribution', 'publication', 'supersedes_submission_id'].includes(k)), 'invalid_schema', 'Unknown submission field.');
  assert(value.schema_version === '1' && /^[a-z0-9][a-z0-9-]{0,79}$/.test(value.skill_id), 'invalid_schema', 'Unsupported schema_version or skill_id.');
  assert(object(value.base) && text(value.base.record_version, 120) && SHA.test(value.base.hub_commit) && SHA.test(value.base.source_commit), 'invalid_base', 'Exact hub/source commits and record version are required.');
  assert(['dependency_fix', 'invocation_fix', 'docs_fix', 'compatibility_fix', 'test_fix'].includes(value.change_kind), 'unsupported_change_kind', 'Unsupported change kind.');
  assert(text(value.summary, 500) && text(value.patch, MAX_BYTES), 'invalid_schema', 'A short summary and text unified diff are required.');
  assert(object(value.environment) && text(value.environment.runtime, 120) && text(value.environment.robot, 120), 'invalid_schema', 'environment.runtime and environment.robot are required; use unknown for missing observations.');
  assert(object(value.evidence) && ['not_run', 'contributor_reported'].includes(value.evidence.level) && (value.evidence.command === null || text(value.evidence.command, 2000)) && text(value.evidence.result, 4000) && value.evidence.reported_by === 'submitter', 'invalid_evidence', 'Submitter evidence must be explicitly self-reported or not_run.');
  assert(object(value.attribution) && text(value.attribution.contributor_label, 150) && value.attribution.preserve_upstream_attribution === true, 'invalid_attribution', 'Preserve upstream attribution and provide a self-reported contributor label.');
  assert(object(value.publication) && value.publication.public_submission_allowed === true, 'public_sharing_not_allowed', 'Public submission must be allowed by the project sharing policy. A token is not consent.', 403);
  assert(value.supersedes_submission_id === undefined || SID.test(value.supersedes_submission_id), 'invalid_supersedes', 'Invalid supersedes submission ID.');
}

export async function authenticate(request: Request, env: Env): Promise<string> {
  if (!env.GITHUB_TOKEN || !env.SUBMISSION_TOKENS_JSON) throw new ApiError(503, 'service_not_configured', 'Submission service is not configured. Keep the local bundle.');
  const authorization = request.headers.get('Authorization') || '';
  const match = authorization.match(/^Bearer ([A-Za-z0-9_.~-]{32,256})$/);
  assert(match, 'invalid_token', 'A limited submission Bearer token is required.', 401);
  let configured: any;
  try { configured = JSON.parse(env.SUBMISSION_TOKENS_JSON); } catch { throw new ApiError(503, 'service_not_configured', 'Submission credentials require operator configuration.'); }
  assert(Array.isArray(configured) && configured.length <= 100 && configured.every(t => object(t) && /^[A-Za-z0-9_.-]{1,80}$/.test(t.principal_id) && /^[a-f0-9]{64}$/.test(t.sha256)), 'service_not_configured', 'Submission credentials require operator configuration.', 503);
  const hash = await sha256(match[1]);
  // Only token hashes enter the Worker configuration. Never persist the raw token.
  const principal = configured.find(t => t.sha256 === hash && t.disabled !== true);
  assert(principal, 'invalid_token', 'The submission token is invalid or disabled.', 401);
  return sha256('rsh-principal-v1\0' + principal.principal_id);
}

async function readBody(request: Request): Promise<string> {
  const declared = request.headers.get('Content-Length');
  assert(!declared || (/^\d+$/.test(declared) && +declared <= MAX_BYTES), 'payload_too_large', 'Submission limit is 64 KiB.', 413);
  assert(request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() === 'application/json', 'invalid_content_type', 'Content-Type must be application/json.', 415);
  assert(!request.headers.has('Content-Encoding'), 'unsupported_encoding', 'Compressed submission bodies are not accepted.', 415);
  const reader = request.body?.getReader(); assert(reader, 'invalid_schema', 'A JSON body is required.');
  let size = 0; const parts: Uint8Array[] = [];
  try {
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) { await reader.cancel(); throw new ApiError(413, 'payload_too_large', 'Submission limit is 64 KiB.'); }
      parts.push(value);
    }
  } finally { reader.releaseLock(); }
  const joined = new Uint8Array(size); let offset = 0; for (const part of parts) { joined.set(part, offset); offset += part.length; }
  try { return new TextDecoder('utf-8', { fatal: true }).decode(joined); } catch { throw new ApiError(422, 'invalid_json', 'The submission must be UTF-8 JSON.'); }
}

function owned(receipt: Receipt | null, id: string, principal: string): asserts receipt is Receipt {
  assert(receipt && receipt.submission_id === id && receipt.principal_id === principal, 'submission_not_found', 'Submission not found.', 404);
}
function samePayload(receipt: Receipt, payloadHash: string, keyHash: string): void {
  assert(receipt.payload_hash === payloadHash && receipt.key_hash === keyHash, 'idempotency_key_conflict', 'This key was already used with a different payload.', 409);
}
async function branchReceipt(adapter: GitHubAdapter, id: string, sha: string): Promise<Receipt> {
  const raw = await adapter.getFile(receiptPath(id), sha);
  try { assert(raw, 'receipt_unavailable', 'The persisted receipt is unavailable.', 503); return JSON.parse(raw); } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(503, 'receipt_unavailable', 'The persisted receipt is invalid.'); }
}
function allowedPaths(record: JsonObject, id: string): Set<string> {
  const paths = record.contribution?.allowed_paths;
  const recordFile = `catalog/records/${id}.json`;
  assert(Array.isArray(paths) && paths.length > 0 && paths.length <= 8 && paths.includes(recordFile), 'contribution_not_enabled', 'This skill does not have a server-managed contribution allowlist.');
  assert(paths.every(p => typeof p === 'string' && (p === recordFile || p === `docs/recipes/${id}.md` || (p.startsWith(`recipes/${id}/`) && /^[A-Za-z0-9._/-]+$/.test(p) && !p.split('/').some(s => s === '..' || s === '.' || !s)))), 'invalid_catalog_allowlist', 'The server catalog allowlist requires operator repair.', 503);
  return new Set(paths);
}

export async function submit(request: Request, principal: string, adapter: GitHubAdapter): Promise<{ response: JsonObject; status: number }> {
  const key = request.headers.get('Idempotency-Key');
  assert(key && /^[A-Za-z0-9_.:-]{8,128}$/.test(key), 'invalid_idempotency_key', 'Idempotency-Key must contain 8–128 simple ASCII characters.');
  const raw = await readBody(request); let bundle: Bundle;
  try { bundle = JSON.parse(raw); } catch { throw new ApiError(422, 'invalid_json', 'Invalid JSON submission.'); }
  validateBundle(bundle);
  const keyHash = await sha256(key);
  const id = 'sub_' + await sha256(`rsh-submission-v1\0${principal}\0${key}`);
  const payloadHash = await sha256(canonical(bundle));
  // Duplicate discovery deliberately precedes current-main/base validation.
  let pull = await adapter.findPull(id);
  let receipt: Receipt;
  const replay = Boolean(pull);
  if (pull) { receipt = readReceipt(pull.body)!; owned(receipt, id, principal); samePayload(receipt, payloadHash, keyHash); }
  else {
    const existing = await adapter.getBranch(id);
    if (existing) { receipt = await branchReceipt(adapter, id, existing); owned(receipt, id, principal); samePayload(receipt, payloadHash, keyHash); }
    else {
      if (bundle.supersedes_submission_id) {
        const prior = await adapter.findPull(bundle.supersedes_submission_id);
        assert(prior, 'invalid_supersedes', 'The previous submission was not found.');
        const priorReceipt = readReceipt(prior.body); owned(priorReceipt, bundle.supersedes_submission_id, principal);
        const needsChanges = prior.labels.some(l => l.name === 'rsh:needs_changes') || (await adapter.getChecks(prior.head.sha)).state === 'failure';
        assert(priorReceipt.skill_id === bundle.skill_id && !prior.merged_at && prior.state === 'open' && needsChanges, 'invalid_supersedes', 'Only your open needs_changes submission for the same skill can be supplemented.');
      }
      const head = await adapter.getHead();
      assert(head === bundle.base.hub_commit, 'stale_base', 'Hub main changed. Inspect the latest catalog and explicitly prepare a new bundle.', 409);
      const path = `catalog/records/${bundle.skill_id}.json`;
      const recordRaw = await adapter.getFile(path, head);
      assert(recordRaw, 'unknown_skill', 'No server catalog record exists for this skill.');
      let record: JsonObject;
      try { record = JSON.parse(recordRaw); } catch { throw new ApiError(503, 'invalid_catalog_record', 'The server catalog record requires operator repair.'); }
      assert(record.id === bundle.skill_id && record.maintenance?.record_version === bundle.base.record_version && record.source?.commit === bundle.base.source_commit, 'stale_record', 'Record version or upstream source pin differs from the current server catalog.', 409);
      const allowed = allowedPaths(record, bundle.skill_id);
      const patches = parsePatch(bundle.patch);
      const changed: Record<string, string> = {};
      for (const patch of patches) {
        assert(allowed.has(patch.path), 'path_not_allowed', 'The patch changes a path outside this skill contribution allowlist.');
        const original = patch.path === path ? recordRaw : await adapter.getFile(patch.path, head);
        assert(original !== null, 'unsupported_base_file', 'Only existing regular text files may be changed.');
        changed[patch.path] = applyPatch(original, patch);
      }
      let nextRecord = record;
      if (changed[path]) {
        try { nextRecord = JSON.parse(changed[path]); } catch { throw new ApiError(422, 'invalid_record_patch', 'Changed record must remain valid JSON.'); }
        // A contribution cannot expand its own permission set, rewrite upstream credit or change the pinned origin.
        for (const field of ['schema_version', 'id', 'source', 'license', 'attribution', 'contribution', 'evidence']) assert(canonical(record[field]) === canonical(nextRecord[field]), 'protected_record_field', `The record ${field} field is protected. Use a maintainer review outside the submission API.`);
        assert(object(nextRecord.maintenance), 'invalid_record_patch', 'The record maintenance field is required.');
      }
      const version = 'contrib-' + id.slice(4, 20);
      assert(Array.isArray(nextRecord.compatibility) && nextRecord.compatibility.length > 0 && nextRecord.compatibility.every((c: any) => object(c)), 'invalid_record_patch', 'Compatibility combinations are required.');
      for (const combo of nextRecord.compatibility) {
        const sameEnvironment = (value: any) => canonical({ ...value, status: undefined }) === canonical({ ...combo, status: undefined });
        const prior = record.compatibility?.find(sameEnvironment);
        assert(['unknown', 'contributor_reported'].includes(combo.status) || (prior && prior.status === combo.status), 'protected_verification_status', 'A submitter cannot promote a compatibility combination to hub verification.');
      }
      // New code/requirements cannot inherit runtime verification from the previous version.
      nextRecord = {
        ...nextRecord,
        compatibility: nextRecord.compatibility.map((c: any) => ({ ...c, status: 'contributor_reported' })),
        maintenance: { ...nextRecord.maintenance, record_version: version },
        evidence: {
          level: 'not_run', verified_by: 'Robot Skill Hub API structural intake', date: new Date().toISOString().slice(0, 10),
          environment: { runtime: 'not_run' }, commands: ['API schema, exact base/source pin, allowlist and strict unified diff checks'],
          result: 'Intake structure checks only. Changed recipe runtime, dependency installation, imports and robot tasks were not run by the hub.',
          artifacts: [], runtime_verification: 'not_run', contributor_reported: bundle.evidence,
          hub_verification: { level: 'structure_checked', runtime: 'not_run' }
        }
      };
      changed[path] = JSON.stringify(nextRecord, null, 2) + '\n';
      const hashes: Record<string, string> = {};
      for (const [file, content] of Object.entries(changed)) hashes[file] = await sha256(content);
      receipt = {
        schema_version: '1', submission_id: id, principal_id: principal, key_hash: keyHash, payload_hash: payloadHash,
        skill_id: bundle.skill_id, base: bundle.base, new_record_version: version, change_kind: bundle.change_kind,
        summary: bundle.summary, environment: bundle.environment, evidence: bundle.evidence, attribution: bundle.attribution,
        hub_validation: { level: 'structure_checked', runtime: 'not_run', result: 'Exact pins, allowlisted paths and strict patch application checked; submitted code was not executed.' },
        patch_paths: Object.keys(changed), patch_hashes: hashes, created_at: new Date().toISOString(),
        ...(bundle.supersedes_submission_id ? { supersedes_submission_id: bundle.supersedes_submission_id } : {})
      };
      assert(new TextEncoder().encode(JSON.stringify(receipt)).length <= 24 * 1024, 'metadata_too_large', 'Submission receipt metadata exceeds 24 KiB. Keep only the minimal environment and evidence.', 422);
      const won = await adapter.createBranch(id, head, changed, receipt);
      if (!won) {
        const winner = await adapter.getBranch(id); assert(winner, 'receipt_unavailable', 'Concurrent receipt is not available; retry the same key.', 503);
        receipt = await branchReceipt(adapter, id, winner); owned(receipt, id, principal); samePayload(receipt, payloadHash, keyHash);
      }
    }
    pull = await adapter.createPull(receipt);
    const persisted = readReceipt(pull.body); owned(persisted, id, principal); samePayload(persisted, payloadHash, keyHash);
    receipt = persisted;
  }
  if (receipt.supersedes_submission_id) {
    const old = await adapter.findPull(receipt.supersedes_submission_id);
    if (old) {
      const priorReceipt = readReceipt(old.body); owned(priorReceipt, receipt.supersedes_submission_id, principal);
      await adapter.closeSuperseded(old, pull, id);
    }
  }
  return { status: replay ? 200 : 201, response: { submission_id: id, status: 'submitted', status_path: `/v1/submissions/${id}`, pr_url: pull.html_url, published_version: null, next_action: 'continue_user_task', replay } };
}

function matchingPublication(records: unknown, receipt: Receipt): JsonObject | undefined {
  if (!Array.isArray(records) || !object(receipt.patch_hashes) || Object.keys(receipt.patch_hashes).length === 0) return;
  return records.find(r => object(r) && r.id === receipt.skill_id && r.record_version === receipt.new_record_version &&
    r.source_commit === receipt.base.source_commit && Array.isArray(r.submission_ids) && r.submission_ids.includes(receipt.submission_id) &&
    object(r.contribution_path_hashes) && Object.entries(receipt.patch_hashes).every(([path, hash]) =>
      typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash) && r.contribution_path_hashes[path] === hash));
}

export async function getStatus(id: string, principal: string, adapter: GitHubAdapter, publication: () => Promise<any>): Promise<JsonObject> {
  const pull = await adapter.findPull(id); assert(pull, 'submission_not_found', 'Submission not found.', 404);
  const receipt = readReceipt(pull.body); owned(receipt, id, principal);
  const result: JsonObject = {
    submission_id: id, skill_id: receipt.skill_id, status: 'submitted', status_path: `/v1/submissions/${id}`,
    pr_url: pull.html_url, published_version: null, contributor_evidence: receipt.evidence,
    contributor_attribution: { ...receipt.attribution, identity_verification: 'self_reported' }, hub_validation: receipt.hub_validation,
    next_action: 'continue_user_task'
  };
  const superseding = await adapter.findSuperseding(id);
  if (superseding) {
    const next = await adapter.findPull(superseding); const nextReceipt = next && readReceipt(next.body);
    if (nextReceipt?.principal_id === principal && nextReceipt.supersedes_submission_id === id) return { ...result, status: 'superseded', superseded_by: superseding };
  }
  if (pull.merged_at) {
    result.status = 'merged';
    try {
      const manifest = await publication();
      if (object(manifest) && manifest.schema_version === '1' && typeof manifest.hub_commit === 'string' && SHA.test(manifest.hub_commit) &&
        pull.merge_commit_sha && SHA.test(pull.merge_commit_sha)) {
        const published = (record: JsonObject, commit: string, scope: 'current' | 'historical'): JsonObject => ({
          ...result, status: 'published', published_version: record.record_version, source_commit: record.source_commit,
          compatibility: record.compatibility, recipe_url: record.recipe_url, published_hub_commit: commit, publication_scope: scope
        });
        const deployed = matchingPublication(manifest.records, receipt);
        if (deployed && await adapter.isAncestor(pull.merge_commit_sha, manifest.hub_commit)) {
          return published(deployed, manifest.hub_commit, 'current');
        }
        // History contains operator-preserved, actually deployed proofs. Never
        // relabel changed current bytes with an old receipt's accepted hashes.
        for (const release of Array.isArray(manifest.history) ? manifest.history : []) {
          if (!object(release) || typeof release.hub_commit !== 'string' || !SHA.test(release.hub_commit)) continue;
          const archived = matchingPublication(release.records, receipt);
          if (archived && await adapter.isAncestor(pull.merge_commit_sha, release.hub_commit) &&
            await adapter.isAncestor(release.hub_commit, manifest.hub_commit)) {
            return published(archived, release.hub_commit, 'historical');
          }
        }
      }
      result.reason_code = 'publication_not_confirmed';
    } catch { result.reason_code = 'publication_unavailable'; }
    const checks = await adapter.getChecks(pull.merge_commit_sha || pull.head.sha);
    if (checks.state === 'failure' || pull.labels.some(l => l.name === 'rsh:publish_failed')) { result.status = 'publish_failed'; result.reason_code = 'publication_checks_failed'; }
    return result;
  }
  if (pull.state === 'closed') return { ...result, status: 'rejected', reason_code: 'closed_without_merge' };
  const labels = pull.labels.map(l => l.name);
  if (labels.includes('rsh:rejected')) return { ...result, status: 'rejected', reason_code: 'maintainer_rejected' };
  if (labels.includes('rsh:needs_changes')) return { ...result, status: 'needs_changes', reason_code: 'maintainer_requested_changes' };
  const checks = await adapter.getChecks(pull.head.sha);
  if (checks.state === 'failure') return { ...result, status: 'needs_changes', reason_code: 'hub_checks_failed', check_failures: checks.reasons };
  if (checks.state === 'success') return { ...result, status: 'pending_review' };
  return { ...result, status: checks.completed > 0 || labels.includes('rsh:checking') ? 'checking' : 'submitted' };
}

export async function limited(request: Request, principal: string, env: Env, submission: boolean): Promise<void> {
  const limiter = submission ? env.SUBMIT_LIMITER : env.STATUS_LIMITER;
  assert(limiter, 'service_not_configured', 'The API rate limiter requires operator configuration.', 503);
  const { success } = await limiter.limit({ key: principal });
  assert(success, 'rate_limited', 'Request limit reached. Continue the user task and retry after 60 seconds.', 429);
}
