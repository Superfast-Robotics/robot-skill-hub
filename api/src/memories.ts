import { ApiError, MEMORY_KINDS, SHA, SOURCE_REVISION, memoryPath, type GitHubAdapter, type JsonObject, type MemoryEntry, type MemoryFinding, type MemoryGitHubAdapter } from './types.ts';
import { assert, canonical, fromBase64, rejectSubmissionSecrets, sha256, toBase64 } from './util.ts';
import { sourceIdentity } from './references.ts';

const MAX_BYTES = 16 * 1024;
const object = (value: any): value is JsonObject => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: any, min: number, max: number): value is string => typeof value === 'string' && value.trim().length >= min && value.length <= max && !value.includes('\0');
const fields = (value: JsonObject, allowed: string[]) => Object.keys(value).every(key => allowed.includes(key));
const ENV_KEYS = ['runtime', 'runtime_version', 'robot', 'controller', 'observation', 'os', 'python', 'architecture', 'sim_backend', 'render_backend'];
const PACKAGE_KEY = /^package\.[A-Za-z_][A-Za-z0-9_]{0,79}$/;
const OBVIOUS_SECRETS = [/-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----/, /\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/, /\bsk-[A-Za-z0-9_-]{24,}\b/, /\bAKIA[A-Z0-9]{16}\b/, /\brsh_[A-Za-z0-9_-]{43}\b/, /\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*/i, /https?:\/\/[^\s/@:]+:[^\s/@]+@/i];

export function validateMemory(value: any): asserts value is MemoryFinding {
  assert(object(value) && fields(value, ['schema_version', 'skill_id', 'base', 'kind', 'summary', 'observation', 'resolution', 'environment', 'evidence', 'attribution', 'publication']), 'invalid_memory', 'Only a minimal structured finding is accepted.');
  assert(value.schema_version === '1' && typeof value.skill_id === 'string' && /^[a-z0-9][a-z0-9-]{0,79}$/.test(value.skill_id), 'invalid_memory', 'Exact schema version and catalog skill ID are required.');
  assert(object(value.base) && fields(value.base, ['record_version', 'hub_commit', 'source_commit']) && text(value.base.record_version, 1, 120) && typeof value.base.hub_commit === 'string' && SHA.test(value.base.hub_commit) && typeof value.base.source_commit === 'string' && SOURCE_REVISION.test(value.base.source_commit), 'invalid_base', 'Exact catalog record, hub and source versions are required.');
  assert(MEMORY_KINDS.includes(value.kind), 'invalid_memory_kind', 'Unsupported finding kind.');
  assert(text(value.summary, 5, 300) && text(value.observation, 20, 4000) && (value.resolution === null || text(value.resolution, 1, 4000)), 'invalid_memory', 'Provide a short summary, bounded observation and optional resolution.');
  assert(object(value.environment) && Object.keys(value.environment).length <= 16 && text(value.environment.runtime, 1, 240) && text(value.environment.robot, 1, 240) && Object.entries(value.environment).every(([key, val]) => (ENV_KEYS.includes(key) || PACKAGE_KEY.test(key)) && text(val, 1, 240)), 'invalid_environment', 'Environment accepts only bounded runtime/robot fields and package versions as strings.');
  assert(object(value.evidence) && fields(value.evidence, ['level', 'command', 'result', 'reported_by']) && ['not_run', 'contributor_reported'].includes(value.evidence.level) && (value.evidence.command === null || text(value.evidence.command, 1, 2000)) && text(value.evidence.result, 1, 4000) && value.evidence.reported_by === 'submitter', 'invalid_evidence', 'Evidence must describe the actual, self-reported scope.');
  assert(object(value.attribution) && fields(value.attribution, ['contributor_label', 'preserve_upstream_attribution']) && text(value.attribution.contributor_label, 1, 150) && value.attribution.preserve_upstream_attribution === true, 'invalid_attribution', 'Preserve upstream attribution.');
  assert(object(value.publication) && fields(value.publication, ['public_submission_allowed']) && value.publication.public_submission_allowed === true, 'public_sharing_not_allowed', 'Public sharing must be explicitly permitted by project policy.', 403);
  // Check only the deliberately supplied finding, never scan the user's project.
  const content = JSON.stringify(value);
  assert(!OBVIOUS_SECRETS.some(pattern => pattern.test(content)), 'sensitive_memory', 'Remove recognizable credentials from the minimal finding before public storage.');
}

export async function findingFingerprint(finding: MemoryFinding): Promise<string> {
  return sha256(canonical({ schema_version: finding.schema_version, skill_id: finding.skill_id,
    base: { record_version: finding.base.record_version, source_commit: finding.base.source_commit },
    kind: finding.kind, summary: finding.summary, observation: finding.observation, resolution: finding.resolution,
    environment: finding.environment, evidence: finding.evidence }));
}
export const memoryContent = (entry: MemoryEntry): string => JSON.stringify(entry, null, 2) + '\n';
export const memoryMarker = (entry: MemoryEntry): string => `<!-- rsh-memory:${toBase64(JSON.stringify(entry))} -->`;
export function readMemory(body: string | null): MemoryEntry | null {
  const match = body?.match(/<!-- rsh-memory:([A-Za-z0-9+/=]+) -->/);
  if (!match) return null;
  try { return JSON.parse(fromBase64(match[1])); } catch { return null; }
}
export function requireMemoryAdapter(adapter: GitHubAdapter): asserts adapter is MemoryGitHubAdapter {
  const candidate = adapter as Partial<MemoryGitHubAdapter>;
  assert(['findMemoryPull', 'getMemoryBranch', 'createMemoryBranch', 'createMemoryPull'].every(key => typeof candidate[key as keyof MemoryGitHubAdapter] === 'function'), 'service_not_configured', 'Memory storage requires the configured repository adapter.', 503);
}
function owned(entry: MemoryEntry | null, id: string, principal: string): asserts entry is MemoryEntry {
  assert(entry && entry.memory_id === id && entry.principal_id === principal, 'memory_not_found', 'Memory not found.', 404);
}
async function original(entry: MemoryEntry, fingerprint: string): Promise<void> {
  assert(entry.fingerprint === fingerprint && await findingFingerprint(entry) === fingerprint, 'memory_receipt_conflict', 'Stored finding identity requires operator review.', 503);
}
async function readBody(request: Request): Promise<MemoryFinding> {
  assert(request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() === 'application/json', 'invalid_content_type', 'Content-Type must be application/json.', 415);
  assert(!request.headers.has('Content-Encoding'), 'unsupported_encoding', 'Compressed findings are not accepted.', 415);
  const declared = request.headers.get('Content-Length');
  assert(!declared || /^\d+$/.test(declared) && Number(declared) <= MAX_BYTES, 'payload_too_large', 'A finding is limited to 16 KiB.', 413);
  const reader = request.body?.getReader(); assert(reader, 'invalid_memory', 'A structured finding is required.');
  let size = 0; const parts: Uint8Array[] = [];
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) { await reader.cancel(); throw new ApiError(413, 'payload_too_large', 'A finding is limited to 16 KiB.'); }
      parts.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  let finding: unknown;
  try { finding = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422, 'invalid_json', 'A UTF-8 finding object is required.'); }
  validateMemory(finding); return finding;
}

export async function saveMemory(request: Request, principal: string, adapter: MemoryGitHubAdapter): Promise<{ status: number; response: JsonObject }> {
  const finding = await readBody(request);
  rejectSubmissionSecrets(finding, request.headers.get('Authorization')?.match(/^Bearer (.+)$/)?.[1]);
  const fingerprint = await findingFingerprint(finding);
  const id = 'mem_' + await sha256('rsh-memory-id-v1\0' + principal + '\0' + fingerprint);
  let pull = await adapter.findMemoryPull(id); let entry: MemoryEntry; let replay = Boolean(pull);
  if (pull) { entry = readMemory(pull.body)!; owned(entry, id, principal); await original(entry, fingerprint); }
  else {
    let branch = await adapter.getMemoryBranch(id);
    if (branch) replay = true;
    if (!branch) {
      const head = await adapter.getHead();
      assert(await adapter.isAncestor(finding.base.hub_commit, head), 'stale_base', 'The original catalog commit must belong to repository main history.', 409);
      const raw = await adapter.getFile(`catalog/records/${finding.skill_id}.json`, finding.base.hub_commit);
      let matches = false;
      if (raw !== null) {
        let record: any; try { record = JSON.parse(raw); } catch { record = null; }
        matches = Boolean(record && record.id === finding.skill_id && record.maintenance?.record_version === finding.base.record_version && record.source?.commit === finding.base.source_commit);
      } else {
        const intakeRaw = await adapter.getFile(`catalog/intake/${finding.skill_id}.json`, finding.base.hub_commit);
        let intake: any; try { intake = intakeRaw && JSON.parse(intakeRaw); } catch { intake = null; }
        if (intake?.id === finding.skill_id) {
          matches = Boolean(typeof intake.source?.sha256 === 'string' && /^[a-f0-9]{64}$/.test(intake.source.sha256) &&
            finding.base.record_version === 'source-' + intake.source.sha256 && (intake.source.commit || intake.source.revision) === finding.base.source_commit);
        } else {
          const record = await sourceIdentity(adapter, finding.base.hub_commit, finding.skill_id);
          matches = Boolean(record && record.record_version === finding.base.record_version && record.source_commit === finding.base.source_commit);
        }
      }
      assert(matches, 'stale_record', 'The finding must identify the exact recipe or source reference at its pinned hub commit.', 409);
      assert(await adapter.getFile(memoryPath(id), head) === null, 'memory_entry_exists', 'The finding already exists on main without its discoverable PR receipt; preserve it and request operator repair.', 409);
      // Normalize ordering once; the first durable entry remains authoritative.
      entry = { ...JSON.parse(canonical(finding)), memory_id: id, principal_id: principal, fingerprint,
        hub_validation: { level: 'structure_checked', runtime: 'not_run', result: 'Exact catalog pins and bounded finding fields checked; no robot execution.' }, created_at: new Date().toISOString() };
      if (!await adapter.createMemoryBranch(id, head, entry)) {
        replay = true; branch = await adapter.getMemoryBranch(id);
        assert(branch, 'memory_receipt_unavailable', 'The winning finding is temporarily unavailable; retry the same finding.', 503);
      }
    }
    if (branch) {
      const raw = await adapter.getFile(memoryPath(id), branch);
      try { entry = raw ? JSON.parse(raw) : null; } catch { throw new ApiError(503, 'memory_receipt_unavailable', 'The durable finding is temporarily unavailable.'); }
      owned(entry!, id, principal); await original(entry!, fingerprint);
    }
    assert(entry!, 'memory_receipt_unavailable', 'Retry the same minimal finding.', 503);
    pull = await adapter.createMemoryPull(entry);
    entry = readMemory(pull.body)!; owned(entry, id, principal); await original(entry, fingerprint);
  }
  return { status: replay ? 200 : 201, response: { memory_id: id, status: 'stored', status_path: `/v1/memories/${id}`, pr_url: pull.html_url,
    fingerprint, base: entry.base, content_sha256: await sha256(memoryContent(entry)), replay, next_action: 'continue_user_task' } };
}

export async function memoryStatus(id: string, principal: string, adapter: MemoryGitHubAdapter, publication: () => Promise<any>): Promise<JsonObject> {
  const pull = await adapter.findMemoryPull(id); assert(pull, 'memory_not_found', 'Memory not found.', 404);
  const entry = readMemory(pull.body); owned(entry, id, principal);
  const contentHash = await sha256(memoryContent(entry));
  const result: JsonObject = { memory_id: id, skill_id: entry.skill_id, base: entry.base, kind: entry.kind, fingerprint: entry.fingerprint,
    content_sha256: contentHash, status: 'stored', status_path: `/v1/memories/${id}`, pr_url: pull.html_url,
    contributor_evidence: entry.evidence, hub_validation: entry.hub_validation, next_action: 'continue_user_task' };
  if (pull.merged_at) {
    result.status = 'merged';
    try {
      const manifest = await publication();
      const proof = object(manifest) && manifest.schema_version === '1' && typeof manifest.hub_commit === 'string' && SHA.test(manifest.hub_commit) &&
        Array.isArray(manifest.memories) && manifest.memories.find((m: any) => object(m) && m.memory_id === id && m.skill_id === entry.skill_id &&
          m.fingerprint === entry.fingerprint && m.content_sha256 === contentHash && m.record_version === entry.base.record_version &&
          m.source_commit === entry.base.source_commit && m.base_hub_commit === entry.base.hub_commit);
      if (proof && pull.merge_commit_sha && SHA.test(pull.merge_commit_sha) && await adapter.isAncestor(pull.merge_commit_sha, manifest.hub_commit)) {
        return { ...result, status: 'published', entry_url: proof.entry_url, published_hub_commit: manifest.hub_commit };
      }
      result.reason_code = 'publication_not_confirmed';
    } catch { result.reason_code = 'publication_unavailable'; }
    return result;
  }
  if (pull.state === 'closed' || pull.labels.some(label => label.name === 'rsh:rejected')) return { ...result, status: 'rejected', reason_code: 'maintainer_rejected' };
  const checks = await adapter.getChecks(pull.head.sha);
  if (checks.state === 'failure') return { ...result, reason_code: 'memory_checks_failed' };
  if (checks.state === 'success') return { ...result, status: 'pending_review' };
  return { ...result, status: checks.completed > 0 || pull.labels.some(label => label.name === 'rsh:checking') ? 'checking' : 'stored' };
}

export function capabilities(): JsonObject {
  return { schema_version: '1', service: 'robot-skill-hub-api', api_version: 'v1', interpretation: 'data_only',
    endpoints: { session: '/v1/session', save_memory: '/v1/memories', memory_status: '/v1/memories/{memory_id}', register_skill: '/v1/skills', submit_patch: '/v1/submissions', submission_status: '/v1/submissions/{submission_id}' },
    new_skills: { mode: 'pinned_source_reference', max_body_bytes: 16 * 1024, public_review_required: true, runtime_execution: false,
      source_pins: ['Git commit (40 lowercase hex)', 'standalone artifact revision sha256:<digest>'], project_policy: 'publication.public_submission_allowed plus exact publication.allowed_new_skill_ids',
      schema_url: 'https://hub.superfastrobotics.com/schemas/intake.schema.json', receipt_status: '/v1/submissions/{submission_id}' },
    memories: { kinds: MEMORY_KINDS, max_body_bytes: MAX_BYTES, max_environment_fields: 16, environment_value_type: 'string',
      finding_targets: ['preparation_recipe', 'source_reference'], reference_record_version: 'source-<full source.sha256>',
      exact_catalog_base_required: true, public_review_required: true, append_only: true, idempotency: 'principal_and_finding_fingerprint',
      client_policy: 'Require explicit memory.public_save_allowed, allowed skills/kinds, scoped token and a minimal redacted finding. Never infer sharing permission.',
      schema_url: 'https://hub.superfastrobotics.com/schemas/memory.schema.json', published_index: 'https://hub.superfastrobotics.com/catalog/v1/memories.json',
      states: ['stored', 'checking', 'pending_review', 'rejected', 'merged', 'published'] },
    execution: 'The API stores findings for review. It never executes robot code or promotes contributor evidence to runtime verification.' };
}
