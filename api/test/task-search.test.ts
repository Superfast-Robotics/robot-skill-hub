import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { taskTerms, rankTaskRows, TaskQueryError } from '../src/search.ts';
const spec = JSON.parse(await readFile(new URL('../../benchmarks/search/task-lexical-v1.json', import.meta.url), 'utf8'));
test('task ranking uses the frozen shared normalization and integer-score vectors', () => {
  for (const vector of spec.normalization_vectors) {
    if (vector.error) assert.throws(() => taskTerms(vector.query), (error: unknown) => error instanceof TaskQueryError && error.code === vector.error);
    else assert.deepEqual(taskTerms(vector.query), vector.terms);
  }
  for (const vector of spec.ranking_vectors) {
    const rows = rankTaskRows(vector.rows, vector.query, taskTerms(vector.query));
    assert.deepEqual(rows.map(row => row.id), vector.expected_ids);
    assert.deepEqual(rows.map(row => row.query_match.score), vector.expected_scores);
    assert.deepEqual(rows.map(row => row.query_match.matched_terms), rows.map(() => taskTerms(vector.query)));
  }
  assert.deepEqual(rankTaskRows([{ id: 'red-robot' }], 'the and please', []), []);
  assert.throws(() => taskTerms(Array.from({ length: 17 }, (_, i) => 'word' + i).join(' ')), (e: any) => e.code === 'invalid_task_query');
});
