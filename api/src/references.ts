/** Bounded source identities for intake and memory checks, never executable data. */
import { ApiError, SOURCE_REVISION, type GitHubAdapter, type JsonObject } from './types.ts';
import { sha256 } from './util.ts';

const object = (value: any): value is JsonObject => value !== null && typeof value === 'object' && !Array.isArray(value);
const fields = (value: JsonObject, names: string[]) => Object.keys(value).every(key => names.includes(key));

function valid(value: any): boolean {
  return value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).every(k => ['id', 'source_commit', 'source_sha256', 'record_version'].includes(k)) &&
    typeof value.id === 'string' && value.id.length <= 80 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.id) &&
    typeof value.source_commit === 'string' && SOURCE_REVISION.test(value.source_commit) &&
    typeof value.source_sha256 === 'string' && /^[a-f0-9]{64}$/.test(value.source_sha256) &&
    value.record_version === 'source-' + value.source_sha256 &&
    (!value.source_commit.startsWith('sha256:') || value.source_commit === 'sha256:' + value.source_sha256);
}

function indexRows(raw: string, legacy = false): Map<string, JsonObject> {
  const index = JSON.parse(raw);
  if (!object(index) || index.schema_version !== '1' || !Array.isArray(index.records) || index.records.length > 5000) throw new Error('Invalid index');
  if (!legacy && !fields(index, ['schema_version', 'records'])) throw new Error('Unknown index field');
  const records = legacy ? index.records.map((r: any) => ({ id: r?.id, source_commit: r?.source?.commit || r?.source?.revision,
    source_sha256: r?.source?.sha256, record_version: 'source-' + r?.source?.sha256 })) : index.records;
  const result = new Map<string, JsonObject>();
  for (const record of records) { if (!valid(record) || result.has(record.id)) throw new Error('Invalid identity'); result.set(record.id, record); }
  return result;
}

export async function sourceIdentity(adapter: Pick<GitHubAdapter, 'getFile'>, ref: string, id: string): Promise<JsonObject | undefined> {
  const manifestRaw = await adapter.getFile('catalog/source-index-manifest.json', ref);
  if (manifestRaw !== null) {
    try {
      const manifest = JSON.parse(manifestRaw);
      if (!object(manifest) || !fields(manifest, ['schema_version', 'scheme', 'records', 'shards']) || manifest.schema_version !== '1' ||
          manifest.scheme !== 'sha256-id-prefix-2' || !Number.isSafeInteger(manifest.records) || manifest.records < 0 ||
          !object(manifest.shards) || Object.keys(manifest.shards).length > 256) throw new Error('Invalid manifest');
      let total = 0;
      for (const [prefix, shard] of Object.entries(manifest.shards)) {
        if (!/^[a-f0-9]{2}$/.test(prefix) || !object(shard) || !fields(shard, ['path', 'sha256', 'records']) ||
            shard.path !== `catalog/source-index/${prefix}.json` || typeof shard.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(shard.sha256) ||
            !Number.isSafeInteger(shard.records) || shard.records < 1 || shard.records > 5000) throw new Error('Invalid shard descriptor');
        total += shard.records;
      }
      if (total !== manifest.records) throw new Error('Invalid manifest count');
      const prefix = (await sha256(id)).slice(0, 2);
      const shard = manifest.shards[prefix];
      if (shard === undefined) return undefined;
      const raw = await adapter.getFile(shard.path, ref);
      if (raw === null || await sha256(raw) !== shard.sha256) throw new Error('Shard checksum mismatch');
      const records = indexRows(raw);
      if (records.size !== shard.records || !(await Promise.all([...records.keys()].map(async key => (await sha256(key)).slice(0, 2) === prefix))).every(Boolean)) throw new Error('Shard membership mismatch');
      return records.get(id);
    } catch { throw new ApiError(503, 'invalid_source_index', 'The pinned source identity shards require operator review.'); }
  }
  // Historical catalog commits remain readable. Never downgrade a present,
  // corrupt manifest to an older or incomplete identity list.
  const compact = await adapter.getFile('catalog/source-index.json', ref);
  const raw = compact === null ? await adapter.getFile('catalog/references.json', ref) : compact;
  if (raw === null) return undefined;
  try {
    return indexRows(raw, compact === null).get(id);
  } catch { throw new ApiError(503, 'invalid_source_index', 'The pinned source identity index requires operator review.'); }
}
