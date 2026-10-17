import test from 'node:test';
import assert from 'node:assert/strict';
import { sourceIdentity } from '../src/references.ts';
import { GitHub } from '../src/github.ts';
import { ApiError, type GitHubAdapter } from '../src/types.ts';
import { sha256 } from '../src/util.ts';

const HUB = 'a'.repeat(40), ID = 'ros2-panda-grasp', DIGEST = 'b'.repeat(64);
const identity = (id = ID) => ({ id, source_commit: 'c'.repeat(40), source_sha256: DIGEST, record_version: 'source-' + DIGEST });
async function fixture() {
  const prefix = (await sha256(ID)).slice(0, 2), path = `catalog/source-index/${prefix}.json`;
  const shard = JSON.stringify({ schema_version: '1', records: [identity()] }, null, 2) + '\n';
  const manifest: any = { schema_version: '1', scheme: 'sha256-id-prefix-2', records: 1, shards: { [prefix]: { path, sha256: await sha256(shard), records: 1 } } };
  const files: Record<string, string> = { [path]: shard };
  const reads: string[] = [];
  const adapter = { async getFile(path: string, ref: string) {
    assert.equal(ref, HUB); reads.push(path);
    if (path === 'catalog/source-index-manifest.json') return JSON.stringify(manifest);
    assert.notEqual(path, 'catalog/source-index.json', 'The flat index must not be read when a manifest exists');
    assert.notEqual(path, 'catalog/references.json', 'The aggregate must not be read when a manifest exists');
    return files[path] ?? null;
  } } satisfies Pick<GitHubAdapter, 'getFile'>;
  return { prefix, path, shard, manifest, files, reads, adapter };
}

test('source lookup verifies the exact hash of one fixed SHA-prefix shard only', async () => {
  const s = await fixture();
  const another = s.prefix === 'ff' ? 'fe' : 'ff';
  s.manifest.shards[another] = { path: `catalog/source-index/${another}.json`, sha256: '0'.repeat(64), records: 900 };
  s.manifest.records += 900;
  assert.deepEqual(await sourceIdentity(s.adapter, HUB, ID), identity());
  assert.deepEqual(s.reads, ['catalog/source-index-manifest.json', s.path]);
});

test('a manifest without the selected prefix proves absence without flat-index fallback', async () => {
  const s = await fixture(); s.manifest.records = 0; s.manifest.shards = {};
  assert.equal(await sourceIdentity(s.adapter, HUB, ID), undefined); assert.deepEqual(s.reads, ['catalog/source-index-manifest.json']);
});

test('malformed manifests fail closed before any caller-controlled or fallback path is read', async () => {
  const changes = [
    (s: any) => { s.manifest.scheme = 'anything'; }, (s: any) => { s.manifest.records = 2; },
    (s: any) => { s.manifest.shards[s.prefix].path = 'catalog/source-index/../../.local/secret'; },
    (s: any) => { s.manifest.shards[s.prefix].url = 'https://attacker.example.org/shard'; },
    (s: any) => { s.manifest.shards['gg'] = s.manifest.shards[s.prefix]; },
    (s: any) => { s.manifest.shards[s.prefix].sha256 = 'not-a-digest'; },
    (s: any) => { s.manifest.shards[s.prefix].records = 0; }, (s: any) => { s.manifest.unknown = 'field'; }
  ];
  for (const change of changes) {
    const s = await fixture(); change(s);
    await assert.rejects(sourceIdentity(s.adapter, HUB, ID), (error: unknown) => error instanceof ApiError && error.code === 'invalid_source_index');
    assert.deepEqual(s.reads, ['catalog/source-index-manifest.json']);
  }
});

test('missing shards, newline tampering, duplicate IDs and wrong hash-prefix membership are rejected', async () => {
  const changes = [
    async (s: any) => { delete s.files[s.path]; },
    async (s: any) => { s.files[s.path] = s.shard.trimEnd(); },
    async (s: any) => { s.files[s.path] = JSON.stringify({ schema_version: '1', records: [identity(), identity()] }); s.manifest.shards[s.prefix].sha256 = await sha256(s.files[s.path]); s.manifest.shards[s.prefix].records = 2; s.manifest.records = 2; },
    async (s: any) => { s.files[s.path] = JSON.stringify({ schema_version: '1', records: [identity('some-other-robot-skill')] }); s.manifest.shards[s.prefix].sha256 = await sha256(s.files[s.path]); },
    async (s: any) => { s.files[s.path] = JSON.stringify({ schema_version: '1', records: [{ ...identity(), evidence: { level: 'hub_verified' } }] }); s.manifest.shards[s.prefix].sha256 = await sha256(s.files[s.path]); }
  ];
  assert.notEqual((await sha256('some-other-robot-skill')).slice(0, 2), (await sha256(ID)).slice(0, 2));
  for (const change of changes) {
    const s = await fixture(); await change(s);
    await assert.rejects(sourceIdentity(s.adapter, HUB, ID), (error: unknown) => error instanceof ApiError && error.code === 'invalid_source_index');
    assert.ok(s.reads.every(path => path === 'catalog/source-index-manifest.json' || path === s.path));
  }
});

test('only missing manifests use bounded historical flat and legacy source indexes', async () => {
  for (const legacy of [false, true]) {
    const reads: string[] = [];
    const adapter = { async getFile(path: string) {
      reads.push(path); if (path === 'catalog/source-index-manifest.json') return null;
      if (path === 'catalog/source-index.json') return legacy ? null : JSON.stringify({ schema_version: '1', records: [identity()] });
      if (path === 'catalog/references.json') return JSON.stringify({ schema_version: '1', records: [{ id: ID, source: { commit: identity().source_commit, sha256: DIGEST } }] });
      assert.fail('Unexpected historical lookup path: ' + path);
    } } satisfies Pick<GitHubAdapter, 'getFile'>;
    assert.deepEqual(await sourceIdentity(adapter, HUB, ID), identity());
    assert.equal(reads.includes('catalog/references.json'), legacy);
  }
});

test('only exact shard paths receive 256 KiB reads and their UTF-8 BOM is preserved for hashing', async () => {
  let raw = 'x'.repeat(150 * 1024);
  const adapter = new GitHub('test-only-token', async () => Response.json({ type: 'file', encoding: 'base64', size: Buffer.byteLength(raw), content: Buffer.from(raw).toString('base64') }));
  assert.equal((await adapter.getFile('catalog/source-index/ab.json', HUB))!.length, raw.length);
  for (const path of ['catalog/source-index/AB.json', 'catalog/source-index/abc.json', 'catalog/source-index/../ab.json', 'catalog/source-index-manifest.json'])
    await assert.rejects(adapter.getFile(path, HUB), (error: unknown) => error instanceof ApiError && error.code === 'unsupported_base_file');
  raw = '\ufeff' + JSON.stringify({ schema_version: '1', records: [identity()] });
  const received = await adapter.getFile('catalog/source-index/ab.json', HUB); assert.equal(received, raw);
  assert.equal(await sha256(received!), await sha256(raw)); assert.notEqual(await sha256(received!), await sha256(raw.slice(1)));
  raw = 'x'.repeat(256 * 1024 + 1);
  await assert.rejects(adapter.getFile('catalog/source-index/ab.json', HUB), (error: unknown) => error instanceof ApiError && error.code === 'unsupported_base_file');
});
