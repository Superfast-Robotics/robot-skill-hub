export type JsonObject = Record<string, any>;
export interface Env {
  GITHUB_TOKEN?: string;
  SUBMISSION_TOKENS_JSON?: string;
  PUBLICATION_URL: string;
  SUBMIT_LIMITER?: { limit(input: { key: string }): Promise<{ success: boolean }> };
  STATUS_LIMITER?: { limit(input: { key: string }): Promise<{ success: boolean }> };
}
export interface Bundle {
  schema_version: '1';
  skill_id: string;
  base: { record_version: string; hub_commit: string; source_commit: string };
  change_kind: string;
  summary: string;
  patch: string;
  environment: JsonObject;
  evidence: { level: string; command: string | null; result: string; reported_by: 'submitter' };
  attribution: { contributor_label: string; preserve_upstream_attribution: true };
  publication: { public_submission_allowed: true };
  supersedes_submission_id?: string;
}
export interface Receipt {
  schema_version: '1';
  submission_id: string;
  principal_id: string;
  key_hash: string;
  payload_hash: string;
  skill_id: string;
  base: Bundle['base'];
  new_record_version: string;
  change_kind: string;
  summary: string;
  environment: JsonObject;
  evidence: Bundle['evidence'];
  attribution: Bundle['attribution'];
  hub_validation: { level: 'structure_checked'; runtime: 'not_run'; result: string };
  patch_paths: string[];
  patch_hashes: Record<string, string>;
  created_at: string;
  supersedes_submission_id?: string;
}
export const MEMORY_KINDS = ['failure_observation', 'missing_requirement', 'working_workaround', 'compatibility_note', 'docs_correction', 'successful_invocation'] as const;
export interface MemoryFinding {
  schema_version: '1';
  skill_id: string;
  base: Bundle['base'];
  kind: typeof MEMORY_KINDS[number];
  summary: string;
  observation: string;
  resolution: string | null;
  environment: Record<string, string>;
  evidence: Bundle['evidence'];
  attribution: Bundle['attribution'];
  publication: Bundle['publication'];
}
export interface MemoryEntry extends MemoryFinding {
  memory_id: string;
  principal_id: string;
  fingerprint: string;
  hub_validation: { level: 'structure_checked'; runtime: 'not_run'; result: string };
  created_at: string;
}
export interface Pull {
  number: number;
  html_url: string;
  body: string | null;
  state: string;
  merged_at: string | null;
  merge_commit_sha: string | null;
  head: { sha: string; ref: string };
  labels: { name: string }[];
}
export interface Checks {
  state: 'pending' | 'success' | 'failure';
  reasons: string[];
  completed: number;
}
export interface GitHubAdapter {
  findPull(id: string): Promise<Pull | null>;
  getBranch(id: string): Promise<string | null>;
  getHead(): Promise<string>;
  getFile(path: string, ref: string): Promise<string | null>;
  createBranch(id: string, base: string, files: Record<string, string>, receipt: Receipt): Promise<boolean>;
  createPull(receipt: Receipt): Promise<Pull>;
  getChecks(sha: string): Promise<Checks>;
  isAncestor(ancestor: string, descendant: string): Promise<boolean>;
  closeSuperseded(old: Pull, newPull: Pull, id: string): Promise<void>;
  findSuperseding(id: string): Promise<string | null>;
}
export interface MemoryGitHubAdapter extends GitHubAdapter {
  findMemoryPull(id: string): Promise<Pull | null>;
  getMemoryBranch(id: string): Promise<string | null>;
  createMemoryBranch(id: string, base: string, entry: MemoryEntry): Promise<boolean>;
  createMemoryPull(entry: MemoryEntry): Promise<Pull>;
}
export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message); this.status = status; this.code = code;
  }
}
export const SID = /^sub_[a-f0-9]{64}$/;
export const SHA = /^[a-f0-9]{40}$/;
export const MID = /^mem_[a-f0-9]{64}$/;
export const receiptPath = (id: string) => `.hub/submissions/${id}.json`;
export const branchName = (id: string) => `submissions/${id}`;
export const memoryPath = (id: string) => `.hub/memories/${id}.json`;
export const memoryBranchName = (id: string) => `memories/${id}`;
