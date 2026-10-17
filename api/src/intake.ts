/** Data-only onboarding for a new robot skill. No uploaded code is executed. */
import { ApiError, SHA, receiptPath, type GitHubAdapter, type JsonObject, type Receipt } from './types.ts';
import { assert, canonical, readReceipt, rejectSubmissionSecrets, sha256 } from './util.ts';
import { readBody } from './service.ts';
import { sourceIdentity } from './references.ts';

const object = (v: any): v is JsonObject => v !== null && typeof v === 'object' && !Array.isArray(v);
const text = (v: any, max = 500): v is string => typeof v === 'string' && v.trim().length > 0 && v.length <= max && !/[\u0000-\u001f]/.test(v);
const keys = (v: JsonObject, allowed: string[]) => Object.keys(v).every(k => allowed.includes(k));
const strings = (v: any, max = 20, empty = false) => Array.isArray(v) && (empty || v.length > 0) && v.length <= max && v.every(x => text(x, 240)) && new Set(v).size === v.length;
const PIN = /^(?:[a-f0-9]{40}|sha256:[a-f0-9]{64})$/;
const SECRET = [/-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----/, /\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/, /\bsk-[A-Za-z0-9_-]{24,}\b/, /\bAKIA[A-Z0-9]{16}\b/, /\brsh_[A-Za-z0-9_-]{43}\b/, /\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*/i];

export function publicUrl(value: unknown): boolean {
  if (!text(value, 1500)) return false;
  try {
    const url = new URL(value);
    // Reference URLs are public durable identifiers, never signed download credentials.
    return url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash && !url.port &&
      /^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$/i.test(url.hostname) && !/(?:^|\.)(?:localhost|local|internal|invalid|test|example)$/.test(url.hostname);
  } catch { return false; }
}

export function validateIntake(value: any): void {
  assert(object(value) && keys(value, ['schema_version', 'base', 'skill', 'attribution', 'publication']), 'invalid_intake', 'Only a minimal new-skill reference is accepted.');
  assert(value.schema_version === '1' && object(value.base) && keys(value.base, ['hub_commit']) && typeof value.base.hub_commit === 'string' && SHA.test(value.base.hub_commit), 'invalid_base', 'An exact current hub commit is required.');
  const r = value.skill;
  assert(object(r) && keys(r, ['id', 'name', 'summary', 'framework', 'kind', 'capabilities', 'aliases', 'robots', 'source', 'license', 'artifact', 'requirements', 'invocation', 'compatibility', 'setup_url']), 'invalid_intake', 'Unknown skill metadata or verification claim.');
  assert(typeof r.id === 'string' && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(r.id) && r.id.length <= 80 && text(r.name, 150) && text(r.summary, 1000) && text(r.framework, 120), 'invalid_intake', 'A stable skill ID, name, summary and framework are required.');
  assert(r.kind === 'community_skill' && strings(r.capabilities) && strings(r.aliases, 20, true) && strings(r.robots), 'invalid_intake', 'Describe capabilities, aliases and robot families without claiming universal compatibility.');
  assert(object(r.source) && keys(r.source, ['repository', 'commit', 'revision', 'path', 'url', 'sha256', 'bytes', 'authors']) && publicUrl(r.source.repository) && text(r.source.path, 500) && !r.source.path.includes('\\') && !r.source.path.startsWith('/') && !r.source.path.split('/').some((s: string) => !s || s === '.' || s === '..') && publicUrl(r.source.url) && typeof r.source.sha256 === 'string' && /^[a-f0-9]{64}$/.test(r.source.sha256) && Number.isSafeInteger(r.source.bytes) && r.source.bytes > 0 && r.source.bytes <= 50 * 1024 ** 3 && strings(r.source.authors), 'invalid_source', 'Supply a public pinned source, safe path, SHA-256, byte count and upstream authors.');
  const pin = r.source.commit || r.source.revision;
  assert(typeof pin === 'string' && PIN.test(pin) && (r.source.commit ? SHA.test(r.source.commit) && r.source.revision === undefined : r.source.commit === undefined && r.source.revision === `sha256:${r.source.sha256}`), 'invalid_source', 'Use an exact Git commit or a standalone sha256 revision, never both.');
  if (!r.source.commit) assert(r.source.revision === `sha256:${r.source.sha256}`, 'invalid_source', 'A standalone artifact content pin must match its SHA-256.');
  else assert(new URL(r.source.url).pathname.split('/').includes(r.source.commit), 'invalid_source', 'A Git source URL must contain its exact commit as a path segment.');
  assert(object(r.license) && keys(r.license, ['spdx', 'url', 'scope']) && text(r.license.spdx, 120) && publicUrl(r.license.url) && text(r.license.scope, 1000), 'invalid_license', 'Declare the upstream license identifier, public license URL and exact scope. License review remains manual.');
  assert(object(r.artifact) && keys(r.artifact, ['kind', 'format']) && ['code', 'policy', 'model', 'dataset', 'workflow', 'robot_description', 'documentation', 'tool', 'other'].includes(r.artifact.kind) && text(r.artifact.format, 120), 'invalid_artifact', 'Describe the artifact kind and format.');
  assert(object(r.requirements) && keys(r.requirements, ['python', 'packages', 'hardware', 'system', 'notes']) && (r.requirements.python === null || text(r.requirements.python, 120)) && strings(r.requirements.packages, 30, true) && strings(r.requirements.hardware, 20, true) && strings(r.requirements.system, 20, true) && text(r.requirements.notes, 2000), 'invalid_requirements', 'Requirements must be explicit; Python may be null for non-Python artifacts.');
  assert(object(r.invocation) && keys(r.invocation, ['entrypoint', 'notes']) && text(r.invocation.entrypoint, 500) && text(r.invocation.notes, 2000) && publicUrl(r.setup_url), 'invalid_invocation', 'Provide an upstream entrypoint, invocation limitations and public setup URL.');
  assert(Array.isArray(r.compatibility) && r.compatibility.length > 0 && r.compatibility.length <= 20 && r.compatibility.every((c: any) => object(c) && keys(c, ['runtime', 'runtime_version', 'robot', 'controller', 'observation', 'os']) && ['runtime', 'runtime_version', 'robot', 'controller', 'observation', 'os'].every(k => text(c[k], 120))), 'invalid_compatibility', 'Explicit compatibility combinations are required; use unknown for unobserved values.');
  assert(object(value.attribution) && keys(value.attribution, ['contributor_label', 'preserve_upstream_attribution']) && text(value.attribution.contributor_label, 150) && value.attribution.preserve_upstream_attribution === true, 'invalid_attribution', 'Upstream attribution must be preserved.');
  assert(object(value.publication) && keys(value.publication, ['public_submission_allowed']) && value.publication.public_submission_allowed === true, 'public_sharing_not_allowed', 'Public sharing must be explicitly permitted by project policy. A token is not consent.', 403);
  assert(!SECRET.some(p => p.test(JSON.stringify(value))), 'sensitive_intake', 'Remove recognizable credentials from the deliberately supplied metadata.');
}

function owned(receipt: Receipt | null, id: string, principal: string, hash: string, key: string): asserts receipt is Receipt {
  assert(receipt?.submission_id === id && receipt.principal_id === principal && receipt.change_kind === 'new_skill', 'submission_not_found', 'Submission not found.', 404);
  assert(receipt.payload_hash === hash && receipt.key_hash === key, 'idempotency_key_conflict', 'This key was already used with a different payload.', 409);
}

export async function submitSkill(request: Request, principal: string, adapter: GitHubAdapter): Promise<{ response: JsonObject; status: number }> {
  const key = request.headers.get('Idempotency-Key');
  assert(key && /^[A-Za-z0-9_.:-]{8,128}$/.test(key), 'invalid_idempotency_key', 'Idempotency-Key must contain 8 to 128 simple ASCII characters.');
  let value: any;
  try { value = JSON.parse(await readBody(request, 16 * 1024)); } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(422, 'invalid_json', 'A UTF-8 JSON object is required.'); }
  validateIntake(value);
  rejectSubmissionSecrets(value, request.headers.get('Authorization')?.match(/^Bearer (.+)$/)?.[1]);
  const id = 'sub_' + await sha256(`rsh-new-skill-v1\0${principal}\0${key}`);
  const payloadHash = await sha256(canonical(value)); const keyHash = await sha256(key);
  let pull = await adapter.findPull(id); const replay = Boolean(pull); let receipt: Receipt;
  if (pull) { receipt = readReceipt(pull.body)!; owned(receipt, id, principal, payloadHash, keyHash); }
  else {
    const branch = await adapter.getBranch(id);
    if (branch) {
      let existing: any; try { existing = JSON.parse((await adapter.getFile(receiptPath(id), branch)) || 'null'); } catch { throw new ApiError(503, 'receipt_unavailable', 'Stored intake receipt requires operator review.'); }
      owned(existing, id, principal, payloadHash, keyHash); receipt = existing;
    } else {
      const head = await adapter.getHead();
      assert(head === value.base.hub_commit, 'stale_base', 'Hub main changed. Refresh the catalog and explicitly prepare the intake again.', 409);
      const path = `catalog/intake/${value.skill.id}.json`;
      const reference = await sourceIdentity(adapter, head, value.skill.id);
      assert(!(await adapter.getFile(`catalog/records/${value.skill.id}.json`, head)) && !(await adapter.getFile(path, head)) && !reference, 'skill_already_exists', 'This skill ID already exists. Submit a scoped finding or request maintainer review of the existing reference.', 409);
      const version = 'intake-' + id.slice(4, 20); const date = new Date().toISOString().slice(0, 10);
      const record = { ...value.skill, access: { mode: 'source_reference', hub_prepare: false, instructions: 'Inspect the exact pinned upstream artifact and setup instructions. This record has no Hub runtime adapter.', setup_url: value.skill.setup_url },
        license: { ...value.skill.license, verified: false }, compatibility: value.skill.compatibility.map((c: any) => ({ ...c, status: 'contributor_reported' })),
        evidence: { level: 'contributor_reported', runtime_verification: 'not_run', checked_at: date, inspection: 'Data-only intake structure checked. Source content, checksum, license and runtime claims require maintainer review; no submitted code was executed.' },
        maintenance: { record_version: version, last_checked: date, upstream_status: 'contributor_reported' } };
      delete record.setup_url;
      const content = JSON.stringify(record, null, 2) + '\n';
      receipt = { schema_version: '1', submission_id: id, principal_id: principal, key_hash: keyHash, payload_hash: payloadHash, skill_id: record.id,
        base: { hub_commit: head, record_version: 'absent', source_commit: record.source.commit || record.source.revision }, new_record_version: version, change_kind: 'new_skill', summary: record.summary,
        environment: { runtime: record.framework, robot: record.robots.join(', ') }, evidence: { level: 'not_run', command: null, result: 'New source reference only; no runtime execution.', reported_by: 'submitter' }, attribution: value.attribution,
        hub_validation: { level: 'structure_checked', runtime: 'not_run', result: 'Data-only metadata, explicit permission, unique ID, source pin and bounded server-selected destination checked. Source bytes, license and runtime require review.' },
        patch_paths: [path], patch_hashes: { [path]: await sha256(content) }, created_at: new Date().toISOString() };
      const won = await adapter.createBranch(id, head, { [path]: content }, receipt);
      if (!won) {
        const winner = await adapter.getBranch(id); assert(winner, 'receipt_unavailable', 'Concurrent intake receipt is not available; retry the same key.', 503);
        let existing: any; try { existing = JSON.parse((await adapter.getFile(receiptPath(id), winner)) || 'null'); } catch { throw new ApiError(503, 'receipt_unavailable', 'Stored intake receipt requires operator review.'); }
        owned(existing, id, principal, payloadHash, keyHash); receipt = existing;
      }
    }
    pull = await adapter.createPull(receipt); const persisted = readReceipt(pull.body); owned(persisted, id, principal, payloadHash, keyHash);
  }
  return { status: replay ? 200 : 201, response: { submission_id: id, skill_id: receipt.skill_id, status: 'submitted', status_path: `/v1/submissions/${id}`, pr_url: pull.html_url, published_version: null, next_action: 'continue_user_task', replay } };
}
