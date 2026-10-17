import { ApiError, branchName, receiptPath, type GitHubAdapter, type Pull, type Receipt, type Checks, SID } from './types.ts';
import { fromBase64, readReceipt, receiptMarker } from './util.ts';

// Deliberately fixed: callers cannot supply a repository, host or base branch.
export const REPOSITORY = 'Superfast-Robotics/robot-skill-hub';
const PREFIX = `https://api.github.com/repos/${REPOSITORY}`;
export class GitHub implements GitHubAdapter {
  token: string;
  fetcher: typeof fetch;
  constructor(token: string, fetcher: typeof fetch = fetch) { this.token = token; this.fetcher = fetcher; }
  private async request(path: string, method = 'GET', body?: unknown, allowed: number[] = [], access: 'authenticated' | 'public-checks' = 'authenticated'): Promise<any> {
    // Public check-run reads need no Checks permission. Never downgrade other
    // requests or retry a failed mutation without the dedicated repository token.
    const publicChecks = access === 'public-checks';
    if (publicChecks && (method !== 'GET' || !/^\/commits\/[a-f0-9]{40}\/check-runs\?per_page=100&filter=latest$/.test(path))) {
      throw new ApiError(503, 'github_unavailable', 'Unexpected public check-run request.');
    }
    const response = await this.fetcher(PREFIX + path, {
      method, redirect: 'error', signal: AbortSignal.timeout(12000),
      headers: { ...(publicChecks ? {} : { Authorization: `Bearer ${this.token}` }), Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'robot-skill-hub-api', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    if (allowed.includes(response.status)) { await response.body?.cancel(); return { _status: response.status }; }
    if (!response.ok) {
      await response.body?.cancel();
      // Do not echo upstream response bodies, request headers or credentials.
      throw new ApiError(503, 'github_unavailable', `GitHub operation failed (${response.status}); retry with the same idempotency key.`);
    }
    return response.status === 204 ? null : response.json();
  }
  async findPull(id: string): Promise<Pull | null> {
    const pulls = await this.request(`/pulls?state=all&head=${encodeURIComponent('Superfast-Robotics:' + branchName(id))}&base=main&per_page=100`);
    if (!Array.isArray(pulls)) throw new ApiError(503, 'github_unavailable', 'Unexpected GitHub response.');
    const matches = pulls.filter(p => readReceipt(p.body)?.submission_id === id);
    if (matches.length > 1) throw new ApiError(503, 'ambiguous_receipt', 'Multiple receipts require operator review.');
    return matches[0] || null;
  }
  async getBranch(id: string): Promise<string | null> {
    const ref = await this.request(`/git/ref/heads/${branchName(id)}`, 'GET', undefined, [404]);
    return ref._status === 404 ? null : ref.object.sha;
  }
  async getHead(): Promise<string> { return (await this.request('/git/ref/heads/main')).object.sha; }
  async getFile(path: string, ref: string): Promise<string | null> {
    const data = await this.request(`/contents/${path.split('/').map(encodeURIComponent).join('/')}?ref=${encodeURIComponent(ref)}`, 'GET', undefined, [404]);
    if (data._status === 404) return null;
    if (data.type !== 'file' || data.encoding !== 'base64' || data.size > 128 * 1024 || data.submodule_git_url) throw new ApiError(422, 'unsupported_base_file', 'Only existing small UTF-8 files can be changed.');
    try { return fromBase64(data.content.replace(/\s/g, '')); } catch { throw new ApiError(422, 'unsupported_base_file', 'The base file is not UTF-8 text.'); }
  }
  async createBranch(id: string, base: string, files: Record<string, string>, receipt: Receipt): Promise<boolean> {
    const commit = await this.request(`/git/commits/${base}`);
    const tree = await this.request('/git/trees', 'POST', {
      base_tree: commit.tree.sha,
      tree: Object.entries({ ...files, [receiptPath(id)]: JSON.stringify(receipt, null, 2) + '\n' }).map(([path, content]) => ({ path, mode: '100644', type: 'blob', content }))
    });
    const next = await this.request('/git/commits', 'POST', {
      message: `Submission ${id}\n\n${receipt.summary.replace(/[\r\n]/g, ' ')}`,
      tree: tree.sha, parents: [base]
    });
    const created = await this.request('/git/refs', 'POST', { ref: `refs/heads/${branchName(id)}`, sha: next.sha }, [409, 422]);
    if (!created._status) return true;
    // Creating this ref is the compare-and-set lock. Never overwrite a winner.
    if (await this.getBranch(id)) return false;
    throw new ApiError(503, 'github_unavailable', 'Branch creation failed; retry with the same idempotency key.');
  }
  async createPull(receipt: Receipt): Promise<Pull> {
    const prior = await this.findPull(receipt.submission_id); if (prior) return prior;
    const body = [
      '## Submitted change', receipt.summary.replace(/[<>]/g, ''),
      '', `Skill: \`${receipt.skill_id}\` · Kind: \`${receipt.change_kind}\``,
      '', '**Contributor evidence:** self-reported; not hub runtime verification.',
      `Evidence level: \`${receipt.evidence.level}\`.`,
      '', '**Hub checks at intake:** base/source pins, schema, exact patch context and allowlisted paths checked. Robot execution: **not_run**.',
      '', 'Review and merge are manual. A merged PR is not published until the deployed catalog manifest proves inclusion.',
      '', receiptMarker(receipt)
    ].join('\n');
    const created = await this.request('/pulls', 'POST', {
      title: `[contribution] ${receipt.skill_id}: ${receipt.summary.replace(/[\r\n]/g, ' ').slice(0, 120)}`,
      head: branchName(receipt.submission_id), base: 'main', draft: true, body,
      maintainer_can_modify: true
    }, [422]);
    if (!created._status) return created;
    // GitHub rejects concurrent open PRs with the same head/base. Re-read the winner.
    const winner = await this.findPull(receipt.submission_id); if (winner) return winner;
    throw new ApiError(503, 'github_unavailable', 'PR creation did not finish; retry with the same idempotency key.');
  }
  async getChecks(sha: string): Promise<Checks> {
    const runs = await this.request(`/commits/${sha}/check-runs?per_page=100&filter=latest`, 'GET', undefined, [], 'public-checks');
    const checks = runs.check_runs || [];
    const failures = checks.filter((r: any) => r.status === 'completed' && !['success', 'neutral', 'skipped'].includes(r.conclusion)).map((r: any) => r.name);
    if (failures.length) return { state: 'failure', reasons: failures, completed: checks.filter((r: any) => r.status === 'completed').length };
    if (checks.some((r: any) => r.status !== 'completed')) return { state: 'pending', reasons: [], completed: checks.length };
    const completed = checks.length;
    return { state: completed ? 'success' : 'pending', reasons: [], completed };
  }
  async isAncestor(ancestor: string, descendant: string): Promise<boolean> {
    const result = await this.request(`/compare/${ancestor}...${descendant}`, 'GET', undefined, [404]);
    return result._status !== 404 && ['ahead', 'identical'].includes(result.status) && result.merge_base_commit?.sha === ancestor;
  }
  async closeSuperseded(old: Pull, newPull: Pull, id: string): Promise<void> {
    const marker = `<!-- rsh-superseded-by:${id} -->`;
    if (old.body?.includes(marker) && old.state === 'closed') return;
    const prior = old.body?.match(/<!-- rsh-superseded-by:(sub_[a-f0-9]{64}) -->/);
    if (prior && prior[1] !== id) return; // Concurrent supplements cannot overwrite the first durable link.
    await this.request(`/pulls/${old.number}`, 'PATCH', {
      state: 'closed', body: `${old.body || ''}\n\nSuperseded by ${newPull.html_url}.\n${marker}`
    });
  }
  async findSuperseding(id: string): Promise<string | null> {
    const old = await this.findPull(id);
    const next = old?.body?.match(/<!-- rsh-superseded-by:(sub_[a-f0-9]{64}) -->/)?.[1];
    return next && SID.test(next) ? next : null;
  }
}
