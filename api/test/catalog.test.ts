import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createCatalogSync, type CatalogDatabase } from '../src/catalog.ts';

const HUB = 'a'.repeat(40), ORIGIN = 'https://hub.superfastrobotics.com';
const KEY = 'local-catalog-quota-test';
const QUOTA = "Your account has exceeded D1's free tier daily row write limit. Upgrade to a paid plan or wait until tomorrow (midnight UTC) to continue.";
const hash = (value: string) => createHash('sha256').update(value).digest('hex');

function fixture(error: unknown, instant = Date.parse('2026-10-18T12:00:00Z')) {
  const memory = JSON.stringify({ schema_version: '2', hub_commit: HUB, records: 0, pages: [] });
  const manifest = JSON.stringify({ schema_version: '2', hub_commit: HUB, records: 0, counts: { recipes: 0, references: 0, memories: 0 }, pages: [], memory_manifest: { path: 'catalog/v2/memory-manifest.json', sha256: hash(memory), bytes: Buffer.byteLength(memory), records: 0 } });
  const version = JSON.stringify({ hub_commit: HUB, resources: { 'search-manifest': { url: ORIGIN + '/catalog/v2/search-manifest.json', sha256: hash(manifest) }, 'memory-manifest': { url: ORIGIN + '/catalog/v2/memory-manifest.json', sha256: hash(memory) } } });
  const resources = new Map([['/catalog/v1/version.json', version], ['/catalog/v2/search-manifest.json', manifest], ['/catalog/v2/memory-manifest.json', memory]]);
  let reads = 0, databaseCalls = 0;
  const fetcher: typeof fetch = async (input, init) => {
    reads++;
    const url = new URL(String(input));
    assert.equal(url.origin, ORIGIN); assert.equal(init?.redirect, 'manual');
    const headers = new Headers(init?.headers);
    assert.equal(headers.get('DNT'), '1'); assert.equal(headers.get('X-RSH-Telemetry'), 'off'); assert.equal(headers.has('Authorization'), false);
    assert.ok(resources.has(url.pathname)); return new Response(resources.get(url.pathname));
  };
  const db: CatalogDatabase = {
    prepare() { databaseCalls++; throw error; },
    async batch() { assert.fail('The rejected database read cannot reach a write batch'); }
  };
  const handler = createCatalogSync(fetcher, () => instant);
  const sync = (key = KEY) => handler(new Request('https://api.example.invalid/internal/catalog-sync', { method: 'POST', headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' }, body: JSON.stringify({ hub_commit: HUB }) }), { CATALOG: db, CATALOG_SYNC_KEY: KEY });
  return { sync, counts: () => ({ reads, databaseCalls }) };
}

test('sync recognizes the explicit D1 daily write limit through bounded binding error causes without exposing provider text', async () => {
  const provider = new Error('D1_ERROR: ' + QUOTA + ' private-provider-detail');
  provider.name = 'D1_ERROR';
  const wrapped = new Error('D1 batch failed', { cause: new Error('Binding failure', { cause: provider }) });
  const s = fixture(wrapped); const response = await s.sync();
  assert.equal(response.status, 503); assert.equal(response.headers.get('Retry-After'), '43200');
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  const value = await response.json() as any;
  assert.equal(value.reason_code, 'catalog_write_limit'); assert.match(value.message, /same commit.*midnight UTC.*progress is preserved/);
  assert.doesNotMatch(JSON.stringify(value), /private-provider-detail|Upgrade|D1_ERROR|Binding failure/);
  assert.deepEqual(s.counts(), { reads: 3, databaseCalls: 1 });
});

for (const [time, seconds] of [['2026-10-18T00:00:00Z', '86400'], ['2026-10-18T23:59:59.250Z', '1'], ['2028-02-29T23:59:58Z', '2']]) {
  test('sync Retry-After reaches the next UTC midnight from ' + time, async () => {
    const response = await fixture(new Error(QUOTA), Date.parse(time)).sync();
    assert.equal(response.status, 503); assert.equal(response.headers.get('Retry-After'), seconds);
    assert.equal((await response.json() as any).reason_code, 'catalog_write_limit');
  });
}

test('sync leaves other D1 and malformed errors generic rather than treating all 7500 failures as write quota', async () => {
  const cycle: any = new Error('D1_ERROR: unrelated failure'); cycle.cause = cycle;
  for (const error of [Object.assign(new Error('D1 query failed: private detail'), { code: 7500 }), new Error("Your account has exceeded D1's free tier daily row read limit."), new Error('D1_ERROR: database or disk is full'), cycle, { code: 7500 }, null]) {
    const response = await fixture(error).sync();
    assert.equal(response.status, 503); assert.equal(response.headers.has('Retry-After'), false);
    assert.deepEqual(await response.json(), { reason_code: 'catalog_unavailable', message: 'Catalog synchronization failed; retry the same commit.' });
  }
});

test('unauthenticated sync does not probe publication or disclose quota state', async () => {
  const s = fixture(new Error(QUOTA)); const response = await s.sync('wrong-key');
  assert.equal(response.status, 401); assert.equal(response.headers.has('Retry-After'), false);
  assert.deepEqual(await response.json(), { reason_code: 'unauthorized' });
  assert.deepEqual(s.counts(), { reads: 0, databaseCalls: 0 });
});
