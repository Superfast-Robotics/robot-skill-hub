/** Actual official SDK client over local HTTP to the native Workers runtime. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { Miniflare, Response as RuntimeResponse } from 'miniflare';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const hash = (value: string) => createHash('sha256').update(value).digest('hex');
test('official MCP SDK initializes, lists and calls read-only tools over native Workers HTTP', { timeout: 20000 }, async () => {
  const hub = 'a'.repeat(40);
  const record = JSON.stringify({ id: 'panda-source-policy', name: 'Panda policy source', summary: 'Pinned policy artifact reference.',
    source: { revision: 'sha256:' + 'b'.repeat(64), sha256: 'b'.repeat(64) }, access: { mode: 'source_reference', hub_prepare: false },
    evidence: { level: 'source_reviewed', runtime_verification: 'not_run' } });
  const search = JSON.stringify({ schema_version: '1', hub_commit: hub, counts: { recipes: 0, references: 1, memories: 0 }, records: [
    { id: 'panda-source-policy', name: 'Panda policy source', summary: 'Pinned policy artifact reference.', kind: 'source_reference', hub_prepare: false,
      capabilities: ['grasp'], aliases: [], robots: ['panda'], runtime: 'onnx', compatibility: [], record_version: 'source-' + 'b'.repeat(64), record_sha256: hash(record) }
  ] });
  const bundle = await build({ entryPoints: [fileURLToPath(new URL('../../src/index.ts', import.meta.url))], bundle: true, write: false, platform: 'browser', format: 'esm', target: 'es2023' });
  const outbound: string[] = [];
  const mf = new Miniflare({ telemetry: { enabled: false }, workers: [{ config: {
    name: 'robot-skill-hub-public-sdk-test', compatibilityDate: '2026-10-17',
    manifest: { mainModule: 'worker.js', modules: { 'worker.js': { type: 'esm', contents: bundle.outputFiles![0].text } } },
    env: { PUBLICATION_URL: { type: 'text', value: 'https://hub.superfastrobotics.com/catalog/v1/publication.json' } }
  }, dev: { outboundService: { type: 'fetcher', handler(request) {
    outbound.push(request.url); assert.equal(request.headers.has('Authorization'), false);
    const url = new URL(request.url); assert.equal(url.origin, 'https://hub.superfastrobotics.com');
    if (url.pathname === '/catalog/v1/version.json') return RuntimeResponse.json({ schema_version: '1', hub_commit: hub, resources: { search: { sha256: hash(search) } } });
    if (url.pathname === '/catalog/v1/search.json') return new RuntimeResponse(search);
    if (url.pathname === '/references/panda-source-policy/skill.json') return new RuntimeResponse(record);
    assert.fail('An MCP read attempted an unexpected upstream resource: ' + request.url);
  } } } }] });
  const client = new Client({ name: 'robot-skill-hub-independent-sdk-test', version: '1.0.0' }, { capabilities: {} });
  const errors: Error[] = []; client.onerror = error => { errors.push(error); };
  try {
    const endpoint = new URL('/mcp', await mf.ready);
    const transport = new StreamableHTTPClientTransport(endpoint, { requestInit: { headers: { DNT: '1', 'User-Agent': 'robot-skill-hub-test/official-mcp-sdk' } } });
    await client.connect(transport, { timeout: 5000 });
    assert.equal(client.getServerVersion()?.name, 'robot-skill-hub'); assert.equal(transport.sessionId, undefined);
    const listed = await client.listTools(undefined, { timeout: 5000 }); assert.equal(listed.tools.length, 3);
    assert.ok(listed.tools.every(tool => tool.annotations?.readOnlyHint && tool.annotations?.destructiveHint === false));
    const found = await client.callTool({ name: 'find_robot_skills', arguments: { q: 'panda grasp', limit: 1 } }, undefined, { timeout: 5000 });
    assert.equal(found.isError, false); const value: any = found.structuredContent;
    assert.equal(value.execution_performed, false); assert.equal(value.results[0].id, 'panda-source-policy'); assert.equal(value.results[0].hub_prepare, false);
    const inspected = await client.callTool({ name: 'inspect_robot_skill', arguments: { skill_id: value.results[0].id, record_version: value.results[0].record_version } }, undefined, { timeout: 5000 });
    const detail: any = inspected.structuredContent; assert.equal(detail.record.evidence.runtime_verification, 'not_run'); assert.equal(detail.record.access.hub_prepare, false);
    const capability = await client.callTool({ name: 'get_hub_capabilities', arguments: {} }, undefined, { timeout: 5000 }); assert.equal(capability.isError, false);
    assert.equal(outbound.filter(url => url.includes('/version.json')).length, 1); assert.equal(outbound.filter(url => url.includes('/search.json')).length, 1);
    assert.deepEqual(errors.map(error => error.message), []);
  } finally { await client.close(); await mf.dispose(); }
});
