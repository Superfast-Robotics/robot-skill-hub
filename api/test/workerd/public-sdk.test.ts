/** Actual official SDK client over local HTTP to the native Workers runtime. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
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
  const search = JSON.stringify({ schema_version: '1', hub_commit: hub, counts: { recipes: 0, references: 1, memories: 1 }, records: [
    { id: 'panda-source-policy', name: 'Panda policy source', summary: 'Pinned policy artifact reference.', kind: 'source_reference', hub_prepare: false,
      capabilities: ['grasp'], aliases: [], robots: ['panda'], runtime: 'onnx', compatibility: [], record_version: 'source-' + 'b'.repeat(64), record_sha256: hash(record), source_commit: 'sha256:' + 'b'.repeat(64), source_sha256: 'b'.repeat(64) }
  ] });
  const memory_id = 'mem_' + 'c'.repeat(64);
  const memories = JSON.stringify({ schema_version: '1', hub_commit: hub, records: [{ schema_version: '1', memory_id,
    skill_id: 'panda-source-policy', base: { record_version: 'source-' + 'b'.repeat(64), source_commit: 'sha256:' + 'b'.repeat(64), hub_commit: hub },
    environment: { runtime: 'onnx', robot: 'panda' }, fingerprint: 'd'.repeat(64), content_sha256: 'e'.repeat(64),
    entry_url: 'https://hub.superfastrobotics.com/memories/' + memory_id + '.json', curation: 'maintainer_merged', interpretation: 'data_only', trust: 'contributor_reported',
    summary: 'Observed policy input requirement', observation: 'Input shapes must be checked for the selected model.', resolution: null,
    evidence: { level: 'contributor_reported', reported_by: 'submitter' } }] });
  const bundle = await build({ entryPoints: [fileURLToPath(new URL('../../src/index.ts', import.meta.url))], bundle: true, write: false, platform: 'browser', format: 'esm', target: 'es2023' });
  const outbound: string[] = [];
  let corruptMemory = false;
  const mf = new Miniflare({ telemetry: { enabled: false }, workers: [{ config: {
    name: 'robot-skill-hub-public-sdk-test', compatibilityDate: '2026-10-17',
    manifest: { mainModule: 'worker.js', modules: { 'worker.js': { type: 'esm', contents: bundle.outputFiles![0].text } } },
    env: { PUBLICATION_URL: { type: 'text', value: 'https://hub.superfastrobotics.com/catalog/v1/publication.json' } }
  }, dev: { outboundService: { type: 'fetcher', handler(request) {
    outbound.push(request.url); assert.equal(request.headers.has('Authorization'), false);
    assert.equal(request.method, 'GET'); assert.equal(request.headers.get('DNT'), '1');
    assert.equal(request.headers.get('X-RSH-Telemetry'), 'off');
    const url = new URL(request.url); assert.equal(url.origin, 'https://hub.superfastrobotics.com');
    if (url.pathname === '/catalog/v1/version.json') return RuntimeResponse.json({ schema_version: '1', hub_commit: hub, resources: { search: { sha256: hash(search) } , memories: { sha256: hash(memories) } } });
    if (url.pathname === '/catalog/v1/search.json') return new RuntimeResponse(search);
    if (url.pathname === '/references/panda-source-policy/skill.json') return new RuntimeResponse(record);
    if (url.pathname === '/catalog/v1/memories.json') return new RuntimeResponse(corruptMemory ? memories + ' ' : memories);
    assert.fail('An MCP read attempted an unexpected upstream resource: ' + request.url);
  } } } }] });
  const client = new Client({ name: 'robot-skill-hub-independent-sdk-test', version: '1.0.0' }, { capabilities: {} });
  const errors: Error[] = []; client.onerror = error => { errors.push(error); };
  try {
    const endpoint = new URL('/mcp', await mf.ready);
    const transport = new StreamableHTTPClientTransport(endpoint, { requestInit: { headers: { DNT: '1', 'User-Agent': 'robot-skill-hub-test/official-mcp-sdk' } } });
    await client.connect(transport, { timeout: 5000 });
    assert.equal(client.getServerVersion()?.name, 'robot-skill-hub'); assert.equal(transport.sessionId, undefined);
    const packageInfo = JSON.parse(await readFile(new URL('../../package.json', import.meta.url), 'utf8'));
    assert.equal(client.getServerVersion()?.version, packageInfo.version);
    assert.match(client.getInstructions() || '', /get_hub_capabilities/);
    assert.equal(outbound.length, 0, 'Initialization advertises the handoff without fetching or installing anything');
    const listed = await client.listTools(undefined, { timeout: 5000 }); assert.equal(listed.tools.length, 3);
    assert.deepEqual(listed.tools.map(tool => tool.name).sort(), ['find_robot_skills', 'get_hub_capabilities', 'inspect_robot_skill']);
    assert.ok(listed.tools.every(tool => tool.annotations?.readOnlyHint && tool.annotations?.destructiveHint === false));
    const capability = await client.callTool({ name: 'get_hub_capabilities', arguments: {} }, undefined, { timeout: 5000 }); assert.equal(capability.isError, false);
    const onboarding: any = (capability.structuredContent as any).onboarding;
    assert.equal(onboarding.agent_contract_url, 'https://hub.superfastrobotics.com/agent.json');
    assert.equal(onboarding.quickstart_url, 'https://hub.superfastrobotics.com/agent-quickstart.md');
    const skillPath = 'skills/find-robot-skills/SKILL.md';
    assert.equal(onboarding.skill_url, 'https://raw.githubusercontent.com/Superfast-Robotics/robot-skill-hub/main/' + skillPath);
    const [skill, quickstart] = await Promise.all([
      readFile(new URL('../../../' + skillPath, import.meta.url), 'utf8'),
      readFile(new URL('../../../docs/agent-quickstart.md', import.meta.url), 'utf8')
    ]);
    assert.match(skill, /^name: find-robot-skills$/m); assert.match(quickstart, /fetch-source/);
    assert.equal(onboarding.mcp_read_only, true); assert.equal(onboarding.automatic_installation, false);
    assert.equal(onboarding.source_or_robot_execution, false);
    assert.deepEqual(onboarding.source_acquisition.manifest_arguments, ['save_args', 'memories_args']);
    assert.equal(onboarding.source_acquisition.cli_command, 'fetch-source');
    assert.equal(onboarding.source_acquisition.same_project_required, true);
    assert.equal(onboarding.source_acquisition.preserves_acquired_source_pins, true);
    assert.equal(onboarding.source_acquisition.source_manifest_grants_sharing_permission, false);
    assert.equal(onboarding.task_memory.local_first, true);
    assert.deepEqual(onboarding.task_memory.cli_commands, ['save', 'memories']);
    assert.deepEqual(onboarding.task_memory.public_delivery_requires, ['memory.public_save_allowed=true', 'matching memory.allowed_skill_ids and memory.allowed_kinds', 'allowed-agent scoped token', 'minimal redacted finding']);
    assert.match(onboarding.task_memory.finding_scope, /actually observed.*user task first/);
    assert.equal(onboarding.task_memory.missing_scope_or_token, 'Keep local_saved and continue the user task.');
    assert.equal(onboarding.task_memory.repeat_permission_for_exact_authorized_scope, false);
    assert.equal(outbound.length, 2, 'Capabilities read only the pinned catalog, never follow the onboarding links or transmit findings');
    const found = await client.callTool({ name: 'find_robot_skills', arguments: { q: 'panda grasp', limit: 1 } }, undefined, { timeout: 5000 });
    assert.equal(found.isError, false); const value: any = found.structuredContent;
    assert.equal(value.execution_performed, false); assert.equal(value.results[0].id, 'panda-source-policy'); assert.equal(value.results[0].hub_prepare, false);
    assert.equal(outbound.filter(url => url.includes('/memories.json')).length, 0, 'Search does not fan out finding queries');
    const inspected = await client.callTool({ name: 'inspect_robot_skill', arguments: { skill_id: value.results[0].id, record_version: value.results[0].record_version, environment: { robot: 'panda' } } }, undefined, { timeout: 5000 });
    const detail: any = inspected.structuredContent; assert.equal(detail.record.evidence.runtime_verification, 'not_run'); assert.equal(detail.record.access.hub_prepare, false);
    assert.deepEqual(detail.record, JSON.parse(record));
    assert.equal(detail.findings.status, 'ready'); assert.equal(detail.findings.total, 1);
    assert.equal(detail.findings.results[0].memory_id, memory_id); assert.equal(detail.findings.applicability, 'needs_applicability_check');
    assert.deepEqual(detail.findings.environment_filter, { robot: 'panda' });
    corruptMemory = true;
    const degraded = await client.callTool({ name: 'inspect_robot_skill', arguments: { skill_id: value.results[0].id } }, undefined, { timeout: 5000 });
    assert.equal(degraded.isError, false); const partial: any = degraded.structuredContent;
    assert.deepEqual(partial.record, detail.record); assert.equal(partial.findings.status, 'unknown');
    assert.equal(partial.findings.reason_code, 'publication_changed'); assert.equal(partial.findings.total, null);
    assert.equal(outbound.filter(url => url.includes('/memories.json')).length, 2, 'One fixed resource read per inspection, without a retry');
    assert.equal(outbound.filter(url => url.includes('/version.json')).length, 1); assert.equal(outbound.filter(url => url.includes('/search.json')).length, 1);
    assert.deepEqual(errors.map(error => error.message), []);
  } finally { await client.close(); await mf.dispose(); }
});
