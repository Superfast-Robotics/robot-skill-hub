/** Fixed-source, bounded D1 mirror. Catalog metadata is data, never executable. */
import { wordTerms } from './search.ts';

export const HUB_ORIGIN = 'https://hub.superfastrobotics.com';
export const INTERNAL_HEADERS = { Accept: 'application/json', 'Cache-Control': 'no-cache', DNT: '1', 'X-RSH-Telemetry': 'off', 'User-Agent': 'robot-skill-hub-api/catalog' };
export const COMMIT = /^[a-f0-9]{40}$/;
export const HASH = /^[a-f0-9]{64}$/;
export const IDENTIFIER = /^[a-z0-9][a-z0-9-]{0,79}$/;
export type Row = Record<string, any>;
export interface CatalogStatement {
  bind(...values: unknown[]): CatalogStatement;
  all<T = Row>(): Promise<{ results: T[] }>;
  run(): Promise<unknown>;
}
export interface CatalogDatabase {
  prepare(sql: string): CatalogStatement;
  batch(statements: CatalogStatement[]): Promise<{ results: Row[] }[]>;
}
export interface CatalogEnv { CATALOG?: CatalogDatabase; CATALOG_SYNC_KEY?: string }
export class CatalogError extends Error {
  status: number; code: string;
  constructor(status: number, code: string, message: string) { super(message); this.status = status; this.code = code; }
}
export const reject = (status: number, code: string, message: string): never => { throw new CatalogError(status, code, message); };
export async function sha256(bytes: Uint8Array): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes as BufferSource)), x => x.toString(16).padStart(2, '0')).join('');
}
export async function bounded(response: Response, maximum: number): Promise<Uint8Array> {
  if (!response.ok || Number(response.headers.get('Content-Length')) > maximum) { await response.body?.cancel(); return reject(503, 'catalog_unavailable', 'The published resource is unavailable or exceeds its read bound.'); }
  const reader = response.body?.getReader(); if (!reader) return reject(503, 'catalog_unavailable', 'The published resource has no body.');
  const chunks: Uint8Array[] = []; let length = 0;
  try {
    while (true) { const { done, value } = await reader.read(); if (done) break; length += value.length;
      if (length > maximum) { await reader.cancel(); return reject(503, 'catalog_too_large', 'The published resource exceeds its read bound.'); } chunks.push(value); }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; } return bytes;
}
export const decode = (bytes: Uint8Array): Row => JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
export async function ownedRead(fetcher: typeof fetch, path: string, maximum: number) {
  return bounded(await fetcher(HUB_ORIGIN + path, { redirect: 'manual', signal: AbortSignal.timeout(10000), headers: INTERNAL_HEADERS }), maximum);
}
export async function publishedVersion(fetcher: typeof fetch): Promise<Row> {
  const version = decode(await ownedRead(fetcher, '/catalog/v1/version.json', 32 * 1024));
  if (!COMMIT.test(version.hub_commit || '')) return reject(503, 'invalid_publication', 'The catalog version identity is invalid.');
  return version;
}
function validRow(row: Row) {
  const kind = row?.kind;
  return row && IDENTIFIER.test(row.id || '') && ['preparation_recipe', 'source_reference'].includes(kind)
    && HASH.test(row.record_sha256 || '') && HASH.test(row.source_sha256 || '')
    && /^(?:[a-f0-9]{40}|sha256:[a-f0-9]{64})$/.test(row.source_commit || '')
    && typeof row.record_version === 'string' && row.record_version.length > 0 && row.record_version.length <= 120
    && row.hub_prepare === (kind === 'preparation_recipe')
    && (kind === 'preparation_recipe' || row.record_version === 'source-' + row.source_sha256)
    && row.record_url === HUB_ORIGIN + (kind === 'preparation_recipe' ? '/skills/' : '/references/') + row.id + '/skill.json'
    && ['name', 'summary'].every(key => typeof row[key] === 'string')
    && ['capabilities', 'aliases', 'robots', 'robot_types', 'compatibility'].every(key => row[key] === undefined || Array.isArray(row[key]))
    && (row.robot_types === undefined || row.robot_types.every((value: unknown) => typeof value === 'string' && value.length > 0 && value.length <= 80));
}
const text = (row: Row) => [row.id, row.name, row.summary, ...(row.capabilities || []), ...(row.aliases || []), ...(row.robots || []), ...(row.robot_types || []), row.runtime || '', row.framework || ''].join(' ').replace(/[-_/]/g, ' ');
function validMemory(row: Row) {
  return row && /^mem_[a-f0-9]{64}$/.test(row.memory_id || '') && IDENTIFIER.test(row.skill_id || '')
    && HASH.test(row.fingerprint || '') && HASH.test(row.content_sha256 || '')
    && COMMIT.test(row.base?.hub_commit || '') && typeof row.base?.record_version === 'string' && row.base.record_version.length > 0 && row.base.record_version.length <= 120
    && /^(?:[a-f0-9]{40}|sha256:[a-f0-9]{64})$/.test(row.base?.source_commit || '')
    && row.entry_url === HUB_ORIGIN + '/memories/' + row.memory_id + '.json'
    && row.curation === 'maintainer_merged' && row.interpretation === 'data_only' && row.trust === 'contributor_reported'
    && row.environment && typeof row.environment === 'object' && !Array.isArray(row.environment);
}
async function first(db: CatalogDatabase, sql: string, ...values: unknown[]) { return (await db.prepare(sql).bind(...values).all()).results[0]; }
export async function activeCatalog(db: CatalogDatabase, commit: string): Promise<Row | null> {
  const value = await first(db, `SELECT g.manifest_json FROM catalog_active a JOIN catalog_generations g ON g.hub_commit=a.hub_commit WHERE a.singleton=1 AND a.hub_commit=? AND g.next_page=g.total_pages`, commit);
  return value ? JSON.parse(value.manifest_json) : null;
}
export async function indexedRow(db: CatalogDatabase, commit: string, id: string): Promise<Row | undefined> {
  const value = await first(db, `SELECT d.row_json FROM catalog_members m JOIN catalog_documents d ON d.doc_hash=m.doc_hash WHERE m.hub_commit=? AND m.id=?`, commit, id);
  return value ? JSON.parse(value.row_json) : undefined;
}
export const FILTERS = ['runtime', 'runtime_version', 'robot', 'controller', 'observation', 'os', 'python', 'architecture'];
export function validateSearch(input: Row, commit: string) {
  if (Object.keys(input).some(key => !['q', ...FILTERS, 'kind', 'limit', 'offset', 'hub_commit'].includes(key))) reject(400, 'invalid_search', 'Use only documented search parameters.');
  const limit = input.limit === undefined ? 10 : Number(input.limit), offset = input.offset === undefined ? 0 : Number(input.offset);
  if (!Number.isInteger(limit) || limit < 1 || limit > 50 || !Number.isInteger(offset) || offset < 0 || offset > 1000000) reject(400, 'invalid_pagination', 'limit must be 1..50 and offset a nonnegative bounded integer.');
  for (const [key, value] of Object.entries(input)) if (!['limit', 'offset'].includes(key) && (typeof value !== 'string' || value.length > (key === 'q' ? 240 : 80))) reject(400, 'invalid_search', 'Search values must be bounded strings.');
  if (input.hub_commit && input.hub_commit !== commit) reject(409, 'catalog_changed', 'Refresh the query before continuing pagination on a new catalog version.');
  if (input.kind && !['preparation_recipe', 'source_reference'].includes(input.kind)) reject(400, 'invalid_kind', 'kind must be preparation_recipe or source_reference.');
  return { limit, offset };
}
function versionNumber(value: string) { const parts = value.split('.').map(Number); return parts[0] * 1000000 + (parts[1] || 0) * 1000 + (parts[2] || 0); }
// The same simple comparator conjunction supported by the local CLI.
function pythonConstraint(expression: string, value: string) {
  if (!/^\d+\.\d+(?:\.\d+)?$/.test(value)) return false;
  return String(expression || '').split(',').every(part => {
    const match = part.trim().match(/^(>=|<=|==|>|<)\s*(\d+(?:\.\d+){0,2})$/); if (!match) return false;
    const actual = versionNumber(value), required = versionNumber(match[2]);
    return ({ '>=': actual >= required, '<=': actual <= required, '==': actual === required, '!=': actual !== required, '>': actual > required, '<': actual < required } as Row)[match[1] || '=='];
  });
}
export function combinationMatches(row: Row, input: Row): boolean {
  const filters = FILTERS.filter(key => input[key]);
  if (!filters.length) return true;
  if (filters.length === 1 && filters[0] === 'runtime' && [row.runtime, row.framework].some(value => String(value || '').toLowerCase() === input.runtime.toLowerCase())) return true;
  if (filters.length === 1 && filters[0] === 'robot' && (row.robots || []).some((value: string) => value.toLowerCase() === input.robot.toLowerCase())) return true;
  const recipe = row.kind === 'preparation_recipe';
  if (recipe && input.python && !pythonConstraint(row.python_requirement, input.python)) return false;
  return (row.compatibility || []).some((combo: Row) => filters.every(key => {
    if (recipe && ['python', 'architecture'].includes(key) && combo[key] === undefined) return true;
    let value = input[key].toLowerCase();
    if (recipe && key === 'architecture') value = ({ amd64: 'x86_64', aarch64: 'arm64' } as Row)[value] || value;
    if (recipe && key === 'python') value = value.split('.').slice(0, 2).join('.');
    return String(combo[key] || '').toLowerCase() === value;
  }));
}
function sqlFilters(input: Row) {
  const clauses: string[] = []; const values: unknown[] = [];
  if (input.kind) { clauses.push('d.kind=?'); values.push(input.kind); }
  const keys = FILTERS.filter(key => input[key]);
  if (keys.length === 1 && ['runtime', 'robot'].includes(keys[0])) {
    const key = keys[0]; clauses.push(`d.doc_hash IN(SELECT doc_hash FROM catalog_labels WHERE field=? AND value=? UNION SELECT doc_hash FROM catalog_combinations WHERE ${key}=?)`); values.push(key, input[key].toLowerCase(), input[key].toLowerCase());
  }
  else if (keys.length) {
    const fields: string[] = [];
    for (const key of keys) {
      const rawValue = input[key].toLowerCase(); let value = rawValue; if (key === 'architecture') value = ({ amd64: 'x86_64', aarch64: 'arm64' } as Row)[value] || value;
      const field = `c.${key}`;
      if (['python', 'architecture'].includes(key)) {
        const normalized = key === 'python' ? value.split('.').slice(0, 2).join('.') : value;
        fields.push(`((${field}=? OR ${field} IS NULL) AND cd.kind='preparation_recipe' OR ${field}=? AND cd.kind='source_reference')`); values.push(normalized, rawValue);
      } else { fields.push(`${field}=?`); values.push(value); }
    }
    clauses.push(`d.doc_hash IN(SELECT c.doc_hash FROM catalog_combinations c JOIN catalog_documents cd ON cd.doc_hash=c.doc_hash WHERE ${fields.join(' AND ')})`);
    if (input.python) {
      // Requirements are compiled into a numeric interval/exclusions at staging time.
      const number = /^\d+\.\d+(?:\.\d+)?$/.test(input.python) ? versionNumber(input.python) : -1;
      clauses.push(`(d.kind<>'preparation_recipe' OR (json_extract(d.row_json,'$._python_min')<=? AND json_extract(d.row_json,'$._python_max')>=? AND NOT EXISTS(SELECT 1 FROM json_each(d.row_json,'$._python_exclude') x WHERE x.value=?)))`); values.push(number, number, number);
    }
  }
  return { clauses, values };
}
export async function indexedSearch(db: CatalogDatabase, commit: string, input: Row) {
  const { limit, offset } = validateSearch(input, commit);
  const terms = wordTerms(String(input.q || ''));
  if (String(input.q || '').trim() && !terms.length) return { results: [], total: 0, limit, offset };
  const { clauses, values } = sqlFilters(input);
  const fts = terms.length ? ' JOIN catalog_fts ON catalog_fts.rowid=d.rowid' : '';
  const where = ['m.hub_commit=?', ...(terms.length ? ['catalog_fts MATCH ?'] : []), ...clauses].join(' AND ');
  const bound = [commit, ...(terms.length ? [terms.map(term => '"' + term + '"*').join(' AND ')] : []), ...values];
  const from = `FROM catalog_members m JOIN catalog_documents d ON d.doc_hash=m.doc_hash${fts} WHERE ${where}`;
  const noFilters = !terms.length && !input.kind && !FILTERS.some(key => input[key]);
  const results = await db.batch([
    noFilters ? db.prepare('SELECT total_records total FROM catalog_generations WHERE hub_commit=?').bind(commit) : db.prepare(`SELECT count(*) total ${from}`).bind(...bound),
    db.prepare(`SELECT d.row_json ${from} ORDER BY (d.id=?) DESC,(d.kind='preparation_recipe') DESC,d.id LIMIT ? OFFSET ?`).bind(...bound, String(input.q || '').toLowerCase(), limit, offset)
  ]);
  return { results: results[1].results.map(value => cleanRow(JSON.parse(value.row_json))), total: Number(results[0].results[0].total), limit, offset };
}
function findingsInput(input: Row, commit: string) {
  const allowed = ['skill_id', 'record_version', 'source_commit', ...FILTERS, 'limit', 'offset', 'hub_commit'];
  if (Object.keys(input).some(key => !allowed.includes(key)) || !IDENTIFIER.test(input.skill_id || '') || typeof input.record_version !== 'string' || !input.record_version || input.record_version.length > 120 || !/^(?:[a-f0-9]{40}|sha256:[a-f0-9]{64})$/.test(input.source_commit || '')) reject(400, 'invalid_findings', 'Exact skill_id, record_version and source_commit pins are required.');
  for (const key of [...FILTERS, 'hub_commit']) if (input[key] !== undefined && (typeof input[key] !== 'string' || input[key].length > 80)) reject(400, 'invalid_findings', 'Environment filters must be bounded strings.');
  const limit = input.limit === undefined ? 10 : Number(input.limit), offset = input.offset === undefined ? 0 : Number(input.offset);
  if (!Number.isInteger(limit) || limit < 1 || limit > 50 || !Number.isInteger(offset) || offset < 0 || offset > 1000000) reject(400, 'invalid_pagination', 'limit must be 1..50 and offset a nonnegative bounded integer.');
  if (input.hub_commit && input.hub_commit !== commit) reject(409, 'catalog_changed', 'Refresh findings before continuing pagination on a new catalog version.');
  return { limit, offset };
}
function findingsResult(commit: string, input: Row, results: Row[], total: number, limit: number, offset: number, backend: string) {
  return { schema_version: '1', interpretation: 'data_only', trust: 'contributor_reported', hub_commit: commit, backend, coverage: { complete: true }, results, total, limit, offset,
    next: offset + limit < total ? { ...input, limit, offset: offset + limit, hub_commit: commit } : null, execution_performed: false };
}
export async function indexedFindings(db: CatalogDatabase, commit: string, input: Row) {
  const { limit, offset } = findingsInput(input, commit);
  const keys = FILTERS.filter(key => input[key]);
  const where = ['m.hub_commit=?', 'd.skill_id=?', 'd.record_version=?', 'd.source_commit=?', ...keys.map(key => `lower(json_extract(d.row_json,'$.environment.${key}'))=?`)].join(' AND ');
  const values = [commit, input.skill_id, input.record_version, input.source_commit, ...keys.map(key => input[key].toLowerCase())];
  const from = `FROM catalog_memory_documents d JOIN catalog_memory_members m ON m.doc_hash=d.doc_hash WHERE ${where}`;
  const results = await db.batch([db.prepare(`SELECT count(*) total ${from}`).bind(...values), db.prepare(`SELECT d.row_json ${from} ORDER BY d.memory_id LIMIT ? OFFSET ?`).bind(...values, limit, offset)]);
  return findingsResult(commit, input, results[1].results.map(row => JSON.parse(row.row_json)), Number(results[0].results[0].total), limit, offset, 'd1');
}
export async function staticFindings(fetcher: typeof fetch, version: Row, input: Row) {
  const { limit, offset } = findingsInput(input, version.hub_commit);
  const resource = version.resources?.memories;
  if (!HASH.test(resource?.sha256 || '')) reject(503, 'catalog_sync_required', 'The findings mirror is not ready and no verified complete static view is published.');
  const bytes = await ownedRead(fetcher, '/catalog/v1/memories.json?v=' + version.hub_commit, 8 * 1024 * 1024);
  if (await sha256(bytes) !== resource.sha256) reject(503, 'publication_changed', 'The findings changed during this read.');
  const index = decode(bytes);
  if (index.schema_version !== '1' || index.hub_commit !== version.hub_commit || !Array.isArray(index.records) || index.coverage?.complete === false) reject(503, 'catalog_sync_required', 'A complete findings index is not ready.');
  const matches = index.records.filter((row: Row) => row.skill_id === input.skill_id && row.base?.record_version === input.record_version && row.base?.source_commit === input.source_commit && FILTERS.every(key => !input[key] || String(row.environment?.[key] || '').toLowerCase() === input[key].toLowerCase())).sort((a: Row, b: Row) => a.memory_id.localeCompare(b.memory_id));
  return findingsResult(version.hub_commit, input, matches.slice(offset, offset + limit), matches.length, limit, offset, 'static_v1_fallback');
}
function cleanRow(row: Row) { const { _python_min, _python_max, _python_exclude, ...value } = row; return value; }
function compilePython(row: Row) {
  if (row.kind !== 'preparation_recipe') return row;
  let minimum = 0, maximum = Number.MAX_SAFE_INTEGER; const exclude: number[] = [];
  for (const part of String(row.python_requirement || '').split(',')) {
    const match = part.trim().match(/^(>=|<=|==|>|<)\s*(\d+(?:\.\d+){0,2})$/);
    if (!match) { maximum = -1; break; } const required = versionNumber(match[2]);
    switch (match[1] || '==') { case '>=': minimum = Math.max(minimum, required); break; case '>': minimum = Math.max(minimum, required + 1); break; case '<=': maximum = Math.min(maximum, required); break; case '<': maximum = Math.min(maximum, required - 1); break; case '!=': exclude.push(required); break; default: minimum = Math.max(minimum, required); maximum = Math.min(maximum, required); }
  }
  return { ...row, _python_min: minimum, _python_max: maximum, _python_exclude: exclude };
}
async function cleanupCatalog(db: CatalogDatabase, commit: string) {
  const retained = `SELECT hub_commit FROM catalog_generations WHERE hub_commit=? OR hub_commit=(SELECT hub_commit FROM catalog_active WHERE singleton=1) OR hub_commit=(SELECT hub_commit FROM catalog_generations WHERE next_page=total_pages AND hub_commit<>? ORDER BY created_at DESC LIMIT 1) OR hub_commit=(SELECT hub_commit FROM catalog_generations WHERE next_page<total_pages ORDER BY created_at DESC LIMIT 1)`;
  await db.batch([
    db.prepare(`DELETE FROM catalog_members WHERE rowid IN(SELECT rowid FROM catalog_members WHERE hub_commit NOT IN(${retained}) LIMIT 200)`).bind(commit, commit),
    db.prepare(`DELETE FROM catalog_memory_members WHERE rowid IN(SELECT rowid FROM catalog_memory_members WHERE hub_commit NOT IN(${retained}) LIMIT 200)`).bind(commit, commit),
    db.prepare(`DELETE FROM catalog_pages WHERE rowid IN(SELECT rowid FROM catalog_pages WHERE hub_commit NOT IN(${retained}) LIMIT 200)`).bind(commit, commit),
    db.prepare(`DELETE FROM catalog_generations WHERE hub_commit IN(SELECT g.hub_commit FROM catalog_generations g WHERE g.hub_commit NOT IN(${retained}) AND NOT EXISTS(SELECT 1 FROM catalog_members m WHERE m.hub_commit=g.hub_commit) AND NOT EXISTS(SELECT 1 FROM catalog_memory_members m WHERE m.hub_commit=g.hub_commit) AND NOT EXISTS(SELECT 1 FROM catalog_pages p WHERE p.hub_commit=g.hub_commit) LIMIT 10)`).bind(commit, commit),
    db.prepare(`DELETE FROM catalog_documents WHERE doc_hash IN(SELECT d.doc_hash FROM catalog_documents d WHERE NOT EXISTS(SELECT 1 FROM catalog_members m WHERE m.doc_hash=d.doc_hash) LIMIT 100)`),
    db.prepare(`DELETE FROM catalog_memory_documents WHERE doc_hash IN(SELECT d.doc_hash FROM catalog_memory_documents d WHERE NOT EXISTS(SELECT 1 FROM catalog_memory_members m WHERE m.doc_hash=d.doc_hash) LIMIT 100)`)
  ]);
}
export async function pruneCatalog(env: CatalogEnv): Promise<void> {
  if (!env.CATALOG) return;
  const generation = await first(env.CATALOG, `SELECT hub_commit FROM catalog_generations WHERE next_page<total_pages ORDER BY created_at DESC LIMIT 1`)
    || await first(env.CATALOG, 'SELECT hub_commit FROM catalog_active WHERE singleton=1');
  if (generation) await cleanupCatalog(env.CATALOG, generation.hub_commit);
}
function isDailyWriteLimit(error: unknown) {
  // D1 bindings can wrap the provider message in Error.cause. Code 7500 also
  // covers unrelated failures, so only recognize the explicit quota wording.
  const seen = new Set<unknown>();
  for (let depth = 0; depth < 6 && error && typeof error === 'object' && !seen.has(error); depth++) {
    seen.add(error);
    const value = error as { message?: unknown; cause?: unknown };
    if (typeof value.message === 'string' && /\bYour account has exceeded D1's free tier daily row write limit\b/i.test(value.message.slice(0, 4096))) return true;
    error = value.cause;
  }
  return false;
}
export function createCatalogSync(fetcher: typeof fetch = fetch, now: () => number = Date.now) {
  return async function sync(request: Request, env: CatalogEnv): Promise<Response> {
    const response = (value: unknown, status = 200, headers: Record<string, string> = {}) => Response.json(value, { status, headers: { 'Cache-Control': 'no-store', ...headers } });
    try {
      if (request.method !== 'POST') return response({ reason_code: 'method_not_allowed' }, 405);
      // Hash both operands before comparing: fixed-length work and no secret output.
      const supplied = request.headers.get('Authorization') || '';
      if (!env.CATALOG_SYNC_KEY || await sha256(new TextEncoder().encode(supplied)) !== await sha256(new TextEncoder().encode('Bearer ' + env.CATALOG_SYNC_KEY))) return response({ reason_code: 'unauthorized' }, 401);
      if (!env.CATALOG) return response({ reason_code: 'catalog_not_configured' }, 503);
      if (!request.headers.get('Content-Type')?.startsWith('application/json') || request.headers.has('Content-Encoding')) return response({ reason_code: 'invalid_sync' }, 415);
      let input: Row;
      try { input = decode(await bounded(new Response(request.body), 1024)); } catch { return response({ reason_code: 'invalid_sync' }, 400); }
      if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(key => key !== 'hub_commit') || (input.hub_commit !== undefined && !COMMIT.test(input.hub_commit))) return response({ reason_code: 'invalid_sync' }, 400);
      const db = env.CATALOG, version = await publishedVersion(fetcher), commit = version.hub_commit;
      if (input.hub_commit && input.hub_commit !== commit) return response({ reason_code: 'catalog_changed', hub_commit: commit }, 409);
      const resource = version.resources?.['search-manifest'];
      if (!HASH.test(resource?.sha256 || '') || resource.url !== HUB_ORIGIN + '/catalog/v2/search-manifest.json') reject(503, 'invalid_publication', 'The version has no verified v2 search manifest.');
      const bytes = await ownedRead(fetcher, '/catalog/v2/search-manifest.json?v=' + commit, 128 * 1024);
      if (await sha256(bytes) !== resource.sha256) reject(503, 'publication_changed', 'The catalog changed during synchronization.');
      const manifest = decode(bytes);
      if (manifest.schema_version !== '2' || manifest.hub_commit !== commit || !Array.isArray(manifest.pages) || !Number.isSafeInteger(manifest.records) || manifest.records < 0
          || !manifest.counts || ['recipes', 'references', 'memories'].some(key => !Number.isSafeInteger(manifest.counts[key]) || manifest.counts[key] < 0)
          || manifest.records !== manifest.counts.recipes + manifest.counts.references) reject(503, 'invalid_publication', 'The search manifest is invalid.');
      let count = 0;
      manifest.pages.forEach((page: Row, index: number) => {
        if (page.path !== `catalog/v2/generations/${commit}/search/${String(index).padStart(6, '0')}.json` || !HASH.test(page.sha256 || '') || !Number.isInteger(page.bytes) || page.bytes < 1 || page.bytes > 128 * 1024 || !Number.isInteger(page.records) || page.records < 1 || page.records > 100) reject(503, 'invalid_publication', 'The search page identity or bound is invalid.'); count += page.records;
      });
      if (count !== manifest.records || manifest.pages.length > 999999) reject(503, 'invalid_publication', 'The manifest record count is invalid.');
      const memoryDescriptor = manifest.memory_manifest;
      const memoryResource = version.resources?.['memory-manifest'];
      if (memoryDescriptor?.path !== 'catalog/v2/memory-manifest.json' || !HASH.test(memoryDescriptor.sha256 || '') || memoryDescriptor.sha256 !== memoryResource?.sha256 || memoryResource.url !== HUB_ORIGIN + '/catalog/v2/memory-manifest.json' || !Number.isInteger(memoryDescriptor.bytes) || memoryDescriptor.bytes < 1 || memoryDescriptor.bytes > 128 * 1024 || memoryDescriptor.records !== manifest.counts.memories) reject(503, 'invalid_publication', 'The memory manifest descriptor is invalid.');
      const memoryBytes = await ownedRead(fetcher, '/catalog/v2/memory-manifest.json?v=' + commit, 128 * 1024);
      if (memoryBytes.length !== memoryDescriptor.bytes || await sha256(memoryBytes) !== memoryDescriptor.sha256) reject(503, 'publication_changed', 'The memory manifest checksum or byte count does not match.');
      const memory = decode(memoryBytes); let memoryCount = 0;
      if (memory.schema_version !== '2' || memory.hub_commit !== commit || memory.records !== manifest.counts.memories || !Array.isArray(memory.pages)) reject(503, 'invalid_publication', 'The memory manifest is invalid.');
      memory.pages.forEach((page: Row, index: number) => {
        if (page.path !== `catalog/v2/generations/${commit}/memories/${String(index).padStart(6, '0')}.json` || !HASH.test(page.sha256 || '') || !Number.isInteger(page.bytes) || page.bytes < 1 || page.bytes > 128 * 1024 || !Number.isInteger(page.records) || page.records < 1 || page.records > 100) reject(503, 'invalid_publication', 'The memory page identity or bound is invalid.'); memoryCount += page.records;
      });
      if (memoryCount !== memory.records || memory.pages.length > 999999) reject(503, 'invalid_publication', 'The memory record count is invalid.');
      const allPages = [...manifest.pages, ...memory.pages];
      let generation = await first(db, 'SELECT g.*,a.hub_commit active_hub_commit FROM catalog_generations g LEFT JOIN catalog_active a ON a.singleton=1 WHERE g.hub_commit=?', commit);
      if (generation && generation.manifest_sha256 !== resource.sha256) reject(503, 'invalid_publication', 'A catalog commit cannot change its manifest.');
      if (generation?.active_hub_commit === commit && generation.next_page === generation.total_pages && generation.total_pages === allPages.length && generation.total_records === manifest.records) {
        return response({ hub_commit: commit, status: 'active', next_page: generation.next_page, total_pages: generation.total_pages, records: generation.total_records, memories: memory.records });
      }
      if (!generation) {
        await db.prepare(`INSERT OR IGNORE INTO catalog_generations(hub_commit,manifest_sha256,manifest_json,total_pages,total_records,created_at) VALUES(?,?,?,?,?,?)`).bind(commit, resource.sha256, JSON.stringify(manifest), allPages.length, manifest.records, now()).run();
        generation = await first(db, 'SELECT * FROM catalog_generations WHERE hub_commit=?', commit);
      }
      if (generation.manifest_sha256 !== resource.sha256) reject(503, 'invalid_publication', 'A catalog commit cannot change its manifest.');
      const pageIndex = Number(generation.next_page);
      if (pageIndex < allPages.length) {
        const isMemory = pageIndex >= manifest.pages.length;
        const descriptor = allPages[pageIndex], pageBytes = await ownedRead(fetcher, '/' + descriptor.path, 128 * 1024);
        if (pageBytes.length !== descriptor.bytes || await sha256(pageBytes) !== descriptor.sha256) reject(503, 'publication_changed', 'The search page checksum or byte count does not match.');
        const page = decode(pageBytes);
        if (page.schema_version !== '2' || page.hub_commit !== commit || !Array.isArray(page.records) || page.records.length !== descriptor.records || page.records.some((row: Row) => !(isMemory ? validMemory(row) : validRow(row))) || new Set(page.records.map((row: Row) => isMemory ? row.memory_id : row.id)).size !== page.records.length) reject(503, 'invalid_publication', 'The page contains invalid or duplicate identities.');
        const rows = await Promise.all(page.records.map(async (row: Row) => ({ hash: await sha256(new TextEncoder().encode(JSON.stringify(row))), row: isMemory ? row : compilePython(row), text: isMemory ? '' : text(row) })));
        const data = JSON.stringify(rows);
        // Conditional membership insertion plus page receipt/cursor commit is one transaction.
        // Retried/concurrent calls for the same page cannot skip a cursor or rewrite FTS.
        await db.batch([
          db.prepare(isMemory ? `INSERT OR IGNORE INTO catalog_memory_documents(doc_hash,memory_id,skill_id,record_version,source_commit,row_json) SELECT json_extract(value,'$.hash'),json_extract(value,'$.row.memory_id'),json_extract(value,'$.row.skill_id'),json_extract(value,'$.row.base.record_version'),json_extract(value,'$.row.base.source_commit'),json_extract(value,'$.row') FROM json_each(?)` : `INSERT OR IGNORE INTO catalog_documents(doc_hash,id,kind,row_json,search_text) SELECT json_extract(value,'$.hash'),json_extract(value,'$.row.id'),json_extract(value,'$.row.kind'),json_extract(value,'$.row'),json_extract(value,'$.text') FROM json_each(?)`).bind(data),
          db.prepare(isMemory ? `INSERT INTO catalog_memory_members(hub_commit,memory_id,doc_hash) SELECT ?,json_extract(value,'$.row.memory_id'),json_extract(value,'$.hash') FROM json_each(?) WHERE NOT EXISTS(SELECT 1 FROM catalog_pages WHERE hub_commit=? AND page_index=?)` : `INSERT INTO catalog_members(hub_commit,id,doc_hash) SELECT ?,json_extract(value,'$.row.id'),json_extract(value,'$.hash') FROM json_each(?) WHERE NOT EXISTS(SELECT 1 FROM catalog_pages WHERE hub_commit=? AND page_index=?)`).bind(commit, data, commit, pageIndex),
          db.prepare(`INSERT OR IGNORE INTO catalog_pages(hub_commit,page_index,sha256,records) VALUES(?,?,?,?)`).bind(commit, pageIndex, descriptor.sha256, descriptor.records),
          db.prepare(`UPDATE catalog_generations SET next_page=next_page+1 WHERE hub_commit=? AND next_page=?`).bind(commit, pageIndex)
        ]);
      }
      const progress = await first(db, 'SELECT next_page,total_pages,total_records FROM catalog_generations WHERE hub_commit=?', commit);
      if (progress.next_page === progress.total_pages) {
        const latest = await publishedVersion(fetcher);
        if (latest.hub_commit !== commit || latest.resources?.['search-manifest']?.sha256 !== resource.sha256) return response({ reason_code: 'catalog_changed', hub_commit: latest.hub_commit }, 409);
        const complete = await first(db, `SELECT count(*) total,sum(d.kind='preparation_recipe') recipes FROM catalog_members m JOIN catalog_documents d ON d.doc_hash=m.doc_hash WHERE m.hub_commit=?`, commit);
        const receipts = await first(db, 'SELECT count(*) pages,coalesce(sum(records),0) records FROM catalog_pages WHERE hub_commit=?', commit);
        const memories = await first(db, 'SELECT count(*) total FROM catalog_memory_members WHERE hub_commit=?', commit);
        if (Number(complete.total) !== manifest.records || Number(complete.recipes || 0) !== manifest.counts.recipes || Number(memories.total) !== memory.records || Number(receipts.pages) !== allPages.length || Number(receipts.records) !== manifest.records + memory.records) reject(503, 'invalid_publication', 'The complete generation count does not match its manifest.');
        await db.prepare(`INSERT INTO catalog_active(singleton,hub_commit) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET hub_commit=excluded.hub_commit WHERE catalog_active.hub_commit<>excluded.hub_commit`).bind(commit).run();
      }
      // Bounded retirement converges to current/previous plus staging, and continues
      // on the hourly cron if a post-deploy caller stops immediately after activation.
      await cleanupCatalog(db, commit);
      return response({ hub_commit: commit, status: progress.next_page === progress.total_pages ? 'active' : 'syncing', next_page: progress.next_page, total_pages: progress.total_pages, records: progress.total_records, memories: memory.records });
    } catch (error) {
      if (isDailyWriteLimit(error)) {
        const instant = now(), midnight = (Math.floor(instant / 86400000) + 1) * 86400000;
        return response({ reason_code: 'catalog_write_limit', message: 'The daily catalog write limit was reached. Retry the same commit after midnight UTC; staging progress is preserved.' }, 503, { 'Retry-After': String(Math.max(1, Math.ceil((midnight - instant) / 1000))) });
      }
      return response({ reason_code: error instanceof CatalogError ? error.code : 'catalog_unavailable', message: error instanceof CatalogError ? error.message : 'Catalog synchronization failed; retry the same commit.' }, error instanceof CatalogError ? error.status : 503);
    }
  };
}
export const handleCatalogSync = createCatalogSync();
