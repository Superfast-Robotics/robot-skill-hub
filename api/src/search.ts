/** Basic discovery grammar; native unicode61 additionally has its own case/accent rules. */
export function wordTerms(value: string): string[] {
  return value.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
}

/** Query-only spelling for canonical algorithm literals, never document tokens.
 * Keep identifiers and repeated stars in the existing word-prefix grammar.
 */
export function queryTerms(value: string): string[] {
  const normalized = value.replace(/(?<![\p{L}\p{N}\p{M}_*])(rrt|[ad])\*(?![\p{L}\p{N}\p{M}_*])/giu,
    (_, algorithm: string) => algorithm.toLowerCase() + 'star');
  return wordTerms(normalized);
}

export function containsWordPrefixes(value: string, terms: readonly string[]): boolean {
  const words = wordTerms(value);
  return terms.every(term => words.some(word => word.startsWith(term)));
}

// Frozen task-lexical-v1.json SHA b40a2f135e61da7dcf34117cf5160bcf44d0d2f6891b0941623a39ff870e0612.
export const TASK_VERSION = 'task_lexical_v1', TASK_LIMIT = 512;
const STOP = new Set('a an the and or to of for from with by in on at as is are be been being was were it its this that these those i me my we our you your please find show help need want use using'.split(' '));
const WEIGHTS: Record<string, number> = { id: 8, name: 8, aliases: 8, capabilities: 6, robots: 5, framework: 5, summary: 2 };
type Row = Record<string, any>;
export class TaskQueryError extends Error {
  code: string;
  constructor(code: string, message: string) { super(message); this.code = code; }
}
export function taskStem(original: string): string {
  let word = original;
  if (!/^[a-z]{5,}$/.test(word) || ['astar', 'dstar', 'rrtstar'].includes(word)) return word;
  for (const suffix of ['ies', 'ing', 'ed', 'es', 's']) {
    if (word.endsWith(suffix) && word.length - suffix.length >= 3 && !(suffix === 's' && word.endsWith('ss'))) {
      word = word.slice(0, -suffix.length);
      if (suffix === 'ing' && word.length >= 2 && word.at(-1) === word.at(-2) && 'bdfgmnprt'.includes(word.at(-1)!)) word = word.slice(0, -1);
      break;
    }
  }
  for (const suffix of ['ion', 'ment']) if (word.endsWith(suffix) && word.length - suffix.length >= 4) { word = word.slice(0, -suffix.length); break; }
  if (word.length >= 5 && /[ey]$/.test(word)) word = word.slice(0, -1);
  return word;
}
export function taskTerms(query: string): string[] {
  if (typeof query !== 'string' || query.length > 240) throw new TaskQueryError('invalid_task_query', 'Task queries must be strings of at most 240 characters.');
  if (/[^\x00-\x7f]/.test(query)) throw new TaskQueryError('unsupported_task_query', 'Task mode supports ASCII English queries; use all_terms for Unicode queries.');
  const terms = [...new Set(queryTerms(query).filter(term => !STOP.has(term)).map(taskStem))];
  if (terms.length > 16) throw new TaskQueryError('invalid_task_query', 'Task queries support at most 16 distinct content terms; narrow the query.');
  return terms;
}
function taskFields(row: Row): Record<string, string[]> {
  const combinations: Row[] = Array.isArray(row.compatibility) ? row.compatibility : [];
  const values = (key: string) => [...new Set(combinations.map(combo => combo[key]).filter(value => value && value !== 'unknown'))] as string[];
  const runtimes = values('runtime');
  return { id: [row.id], name: [row.name || ''], aliases: row.aliases || [], capabilities: row.capabilities || [],
    robots: row.robots?.length ? row.robots : values('robot'), framework: [row.framework || (runtimes.length === 1 ? runtimes[0] : 'unknown')], summary: [row.summary || ''] };
}
export function taskScore(row: Row, terms: string[]): Row | null {
  const fields = Object.fromEntries(Object.entries(taskFields(row)).map(([key, values]) => [key, values.map(wordTerms)]));
  const matched: string[] = [], unmatched: string[] = []; let score = 0, anchored = false;
  for (const term of terms) {
    let best = 0, exact = false;
    for (const [field, groups] of Object.entries(fields)) {
      const found = groups.flat().filter(word => word.startsWith(term));
      if (found.length && WEIGHTS[field] > best) { best = WEIGHTS[field]; exact = found.some(word => taskStem(word) === term); }
      else if (found.length && WEIGHTS[field] === best) exact ||= found.some(word => taskStem(word) === term);
    }
    if (best) { matched.push(term); score += best + Number(exact); anchored ||= best >= 5; } else unmatched.push(term);
  }
  if (!terms.length || matched.length < Math.min(2, terms.length) || !anchored) return null;
  let phrase = false;
  for (const key of ['name', 'aliases']) for (const group of fields[key]) {
    const normalized = group.filter(word => !STOP.has(word)).map(taskStem);
    for (let i = 0; i <= normalized.length - terms.length; i++) if (terms.every((term, j) => normalized[i + j] === term)) phrase = true;
  }
  return { model: TASK_VERSION, score: score + 12 * Number(phrase) - unmatched.length, matched_terms: matched, unmatched_terms: unmatched };
}
export function rankTaskRows(candidates: Row[], query: string, terms: string[]) {
  if (candidates.length > TASK_LIMIT) throw new TaskQueryError('query_too_broad', 'Task ranking exceeds 512 hard-filtered records; narrow runtime, robot or other environment filters. More query text does not reduce this bound.');
  const rows: Row[] = candidates.flatMap(row => { const match = taskScore(row, terms); return match ? [{ ...row, query_match: match }] : []; });
  rows.sort((a, b) => Number(b.id === query.toLowerCase()) - Number(a.id === query.toLowerCase()) || b.query_match.score - a.query_match.score || Number(b.kind === 'preparation_recipe') - Number(a.kind === 'preparation_recipe') || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return rows;
}
export function taskMetadata(terms: string[], count: number) {
  return { query_mode: 'task', search_semantics: TASK_VERSION, query_terms: terms,
    candidate_scope: 'hard_filtered_records', candidate_count: count, candidate_limit: TASK_LIMIT };
}
