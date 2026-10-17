import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createPublicHandler } from '../src/public.ts';

const HUB = 'a'.repeat(40), ORIGIN = 'https://hub.superfastrobotics.com';
const hash = (bytes: string | Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const env = { PUBLICATION_URL: ORIGIN + '/catalog/v1/publication.json' };
function fixture(options: { badSearchHash?: boolean; badRecordHash?: boolean; redirect?: boolean; indexLimit?: boolean } = {}) {
  let instant = Date.parse('2026-10-18T00:00:00Z');
  const combo = (runtime: string, robot: string, controller = 'pd_joint_pos', observation = 'state', os = 'linux') => ({ runtime, runtime_version: '1', robot, controller, observation, os, status: 'source_reviewed' });
  const source = { repository: 'https://github.com/upstream/robot', commit: 'b'.repeat(40), sha256: 'c'.repeat(64), url: 'https://github.com/upstream/robot/blob/' + 'b'.repeat(40) + '/task.py' };
  const details = [
    { id: 'alpha-pick', name: 'Alpha pick', summary: 'Pick a cube', source, access: { mode: 'preparation_recipe', hub_prepare: true }, maintenance: { record_version: '1.0.0' }, evidence: { level: 'source_reviewed', runtime_verification: 'not_run' } },
    { id: 'beta-grasp', name: 'Beta grasp', summary: 'ROS grasp source', source, access: { mode: 'source_reference', hub_prepare: false }, evidence: { level: 'source_reviewed', runtime_verification: 'not_run' } },
    { id: 'gamma-policy', name: 'Gamma policy', summary: 'Pinned ONNX policy source', source: { revision: 'sha256:' + 'd'.repeat(64), sha256: 'd'.repeat(64) }, access: { mode: 'source_reference', hub_prepare: false }, evidence: { level: 'contributor_reported', runtime_verification: 'not_run' } }
  ];
  const text = details.map(d => JSON.stringify(d));
  const rows = details.map((d, index) => ({ id: d.id, name: d.name, summary: d.summary, kind: index === 0 ? 'preparation_recipe' : 'source_reference',
    hub_prepare: index === 0, record_version: index === 0 ? '1.0.0' : 'source-' + d.source.sha256, record_sha256: hash(text[index]),
    capabilities: [index === 0 ? 'pick' : 'grasp', ...(index === 2 ? ['locomotion'] : [])], aliases: index === 0 ? ['cube transfer'] : [], robots: [index === 1 ? 'ur5' : 'panda'], robot_types: index === 2 ? ['humanoid'] : [], runtime: index === 1 ? 'ros2' : 'maniskill', framework: index === 2 ? 'openpi' : 'maniskill',
    compatibility: index === 0 ? [combo('maniskill', 'panda'), combo('mujoco', 'ur5', 'torque', 'rgb', 'windows')] : index === 1 ? [combo('ros2', 'ur5')] : [],
    record_url: 'https://attacker.example.org/ignored-destination.json', evidence: d.evidence }));
  const search = JSON.stringify({ schema_version: '1', hub_commit: HUB, counts: { recipes: 1, references: 2, memories: 0 }, records: rows });
  const catalog = JSON.stringify({ schema_version: '1', hub_commit: HUB, records: [details[0]] });
  const references = JSON.stringify({ schema_version: '1', records: details.slice(1) });
  const version = JSON.stringify({ schema_version: '1', hub_commit: HUB, resources: { search: { sha256: options.badSearchHash ? '0'.repeat(64) : hash(search) }, index: { sha256: hash(catalog) }, references: { sha256: hash(references) } } });
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetcher: typeof fetch = async (input, init) => {
    const url = String(input); calls.push({ url, init });
    assert.ok(url.startsWith(ORIGIN + '/'), 'Only fixed Hub publication resources may be fetched');
    assert.equal(init?.redirect, 'manual'); assert.equal(new Headers(init?.headers).has('Authorization'), false);
    if (options.redirect) return new Response(null, { status: 302, headers: { Location: 'https://attacker.example.org/leak' } });
    const path = new URL(url).pathname;
    if (path === '/catalog/v1/version.json') return new Response(version);
    if (path === '/catalog/v1/search.json') return new Response(options.indexLimit ? 'x'.repeat(2 * 1024 * 1024 + 1) : search);
    if (path === '/catalog/v1/index.json') return new Response(catalog);
    if (path === '/catalog/v1/references.json') return new Response(references);
    if (path === '/openapi.json') return Response.json({ openapi: '3.1.0' });
    const id = path.match(/^\/(?:skills|references)\/([^/]+)\/skill.json$/)?.[1];
    const index = details.findIndex(row => row.id === id);
    if (index >= 0) return new Response(options.badRecordHash ? text[index] + ' ' : text[index]);
    assert.fail('Unexpected publication resource: ' + url);
  };
  const handler = createPublicHandler(fetcher, () => instant);
  const request = (path: string, init?: RequestInit, configuration = env) => handler(new Request('https://api.superfastrobotics.com' + path, init), configuration);
  const rpc = (method: string, params: any = {}, extra: Record<string, string> = {}, id: number | undefined = 1) => request('/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25', ...extra }, body: JSON.stringify({ jsonrpc: '2.0', ...(id === undefined ? {} : { id }), method, params }) });
  return { request, rpc, calls, rows, details, catalog, references, advance(ms: number) { instant += ms; }, handler };
}

test('public search and inspect need no credentials and preserve recipe/reference evidence distinctions', async () => {
  const s = fixture(); const response = await s.request('/v1/search?q=cube'); assert.equal(response!.status, 200);
  const body: any = await response!.json(); assert.equal(body.results.length, 1); assert.equal(body.results[0].id, 'alpha-pick'); assert.equal(body.execution_performed, false);
  const reference: any = await (await s.request('/v1/skills/beta-grasp'))!.json(); assert.equal(reference.record.access.hub_prepare, false); assert.equal(reference.record.evidence.runtime_verification, 'not_run');
  const policy: any = await (await s.request('/v1/skills/gamma-policy'))!.json(); assert.equal(policy.record.source.commit, undefined); assert.match(policy.record.source.revision, /^sha256:/);
  assert.ok(s.calls.every(call => !call.url.startsWith('https://attacker.example.org')));
});

test('capabilities expose bounded finding and complete manifest discovery without credentials', async () => {
  const s = fixture();
  const response = await s.request('/v1/capabilities');
  assert.equal(response!.status, 200);
  const body: any = await response!.json();
  assert.equal(body.public_discovery.findings, 'https://api.superfastrobotics.com/v1/findings');
  assert.equal(body.public_discovery.search_manifest, ORIGIN + '/catalog/v2/search-manifest.json');
  assert.equal(body.memories.complete_manifest, ORIGIN + '/catalog/v2/memory-manifest.json');
  assert.equal(body.public_discovery.authentication_required, false);
  assert.ok(s.calls.every(call => !new Headers(call.init?.headers).has('Authorization')));
});

test('environment filters match one compatibility combination and never combine unrelated observations', async () => {
  const s = fixture();
  const exact: any = await (await s.request('/v1/search?runtime=maniskill&robot=panda&controller=pd_joint_pos&os=linux'))!.json();
  assert.deepEqual(exact.results.map((r: any) => r.id), ['alpha-pick']);
  const mixed: any = await (await s.request('/v1/search?runtime=maniskill&robot=ur5'))!.json(); assert.equal(mixed.total, 0);
  const unknown: any = await (await s.request('/v1/search?robot=panda&os=linux&kind=source_reference'))!.json(); assert.equal(unknown.total, 0);
});

test('single robot discovery uses explicit robot metadata without inventing an environment combination', async () => {
  const s = fixture();
  const known: any = await (await s.request('/v1/search?robot=panda&kind=source_reference'))!.json();
  assert.deepEqual(known.results.map((row: any) => row.id), ['gamma-policy']);
  assert.equal(known.results[0].hub_prepare, false);
  assert.equal(known.results[0].evidence.runtime_verification, 'not_run');
  assert.deepEqual(known.results[0].compatibility, []);
  const absent: any = await (await s.request('/v1/search?robot=kuka'))!.json(); assert.equal(absent.total, 0);
  const mixed: any = await (await s.request('/v1/search?robot=panda&runtime=ros2&kind=source_reference'))!.json(); assert.equal(mixed.total, 0);
  const framework: any = await (await s.request('/v1/search?runtime=openpi'))!.json(); assert.deepEqual(framework.results.map((row: any) => row.id), ['gamma-policy']);
  const guessed: any = await (await s.request('/v1/search?runtime=openpi&robot=panda'))!.json(); assert.equal(guessed.total, 0);
});

test('pagination is stable, bounded and pinned to its original catalog commit', async () => {
  const s = fixture(); const first: any = await (await s.request('/v1/search?limit=1'))!.json();
  assert.equal(first.total, 3); assert.equal(first.results[0].id, 'alpha-pick'); assert.equal(first.next.offset, 1); assert.equal(first.next.hub_commit, HUB);
  const second: any = await (await s.request('/v1/search?' + new URLSearchParams(first.next)))!.json(); assert.equal(second.results[0].id, 'beta-grasp');
  assert.equal((await s.request('/v1/search?hub_commit=' + 'f'.repeat(40)))!.status, 409);
  for (const query of ['limit=0', 'limit=51', 'offset=-1', 'offset=1.5', 'limit=NaN', 'offset=1000001', 'kind=anything', 'url=https://evil.example.org']) assert.equal((await s.request('/v1/search?' + query))!.status, 400);
});

test('static search includes declared robot types without turning them into robot compatibility', async () => {
  const s = fixture();
  const found: any = await (await s.request('/v1/search?q=humanoid%20locomotion'))!.json();
  assert.deepEqual(found.results.map((row: any) => row.id), ['gamma-policy']);
  assert.deepEqual(found.results[0].robot_types, ['humanoid']);
  assert.equal(found.results[0].hub_prepare, false);
  assert.deepEqual(found.results[0].compatibility, []);
  const framework: any = await (await s.request('/v1/search?q=openpi'))!.json();
  assert.deepEqual(framework.results.map((row: any) => row.id), ['gamma-policy']);
  assert.equal((await (await s.request('/v1/search?q=humanoid%20locomotion&robot=humanoid'))!.json() as any).total, 0);
  assert.equal((await (await s.request('/v1/search?q=humanoid%20locomotion&runtime=openpi&robot=panda'))!.json() as any).total, 0);
  assert.equal((await (await s.request('/v1/search?q=humanoid%20locomotion&os=linux'))!.json() as any).total, 0);
});

test('record version conflicts and absent IDs never fall through to arbitrary upstream fetches', async () => {
  const s = fixture(); assert.equal((await s.request('/v1/skills/alpha-pick?record_version=older'))!.status, 409);
  assert.equal((await s.request('/v1/skills/nonexistent'))!.status, 404);
  assert.equal(s.calls.some(call => /\/skills\//.test(call.url)), false);
  assert.equal(await s.request('/v1/not-a-route'), null);
});

test('search snapshot and record bytes require published SHA-256 and bounded redirect-free reads', async () => {
  for (const options of [{ badSearchHash: true }, { redirect: true }, { indexLimit: true }]) {
    const s = fixture(options); const response = await s.request('/v1/search'); assert.equal(response!.status, 503);
  }
  const record = fixture({ badRecordHash: true }); const response = await record.request('/v1/skills/alpha-pick'); assert.equal(response!.status, 503);
  assert.equal((await response!.json() as any).reason_code, 'publication_changed');
});

test('snapshot caching coalesces concurrent reads and expires without mixing publication identities', async () => {
  const s = fixture(); await Promise.all(Array.from({ length: 8 }, () => s.request('/v1/search')));
  assert.equal(s.calls.filter(call => call.url.includes('/version.json')).length, 1); assert.equal(s.calls.filter(call => call.url.includes('/search.json')).length, 1);
  await s.request('/v1/skills/alpha-pick'); await s.request('/v1/skills/alpha-pick'); assert.equal(s.calls.filter(call => call.url.includes('/skills/alpha-pick/')).length, 1);
  s.advance(60001); await s.request('/v1/search'); assert.equal(s.calls.filter(call => call.url.includes('/version.json')).length, 2);
});

test('HEAD, OPTIONS, capabilities and invalid methods use their documented read-only contracts', async () => {
  const s = fixture();
  const capability = await s.request('/v1/capabilities'); assert.equal(capability!.status, 200); assert.equal(s.calls.length, 0);
  const head = await s.request('/v1/search', { method: 'HEAD' }); assert.equal(head!.status, 200); assert.equal(await head!.text(), '');
  const options = await s.request('/mcp', { method: 'OPTIONS' }); assert.equal(options!.status, 204); assert.match(options!.headers.get('Access-Control-Allow-Headers')!, /MCP-Protocol-Version/i);
  assert.equal((await s.request('/v1/search', { method: 'POST' }))!.status, 405);
});

test('MCP initialize, notifications, list and tool calls follow JSON-RPC and advertise read-only tools', async () => {
  const s = fixture();
  const initialized: any = await (await s.rpc('initialize', { protocolVersion: '2025-11-25', clientInfo: { name: 'Independent test client', version: '1' }, capabilities: {} }))!.json();
  assert.equal(initialized.result.protocolVersion, '2025-11-25'); assert.equal(s.calls.length, 0);
  const notification = await s.request('/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) });
  assert.equal(notification!.status, 202); assert.equal(await notification!.text(), '');
  const tools: any = await (await s.rpc('tools/list'))!.json(); assert.equal(tools.result.tools.length, 3);
  assert.ok(tools.result.tools.every((tool: any) => tool.annotations.readOnlyHint && tool.annotations.destructiveHint === false));
  const found: any = await (await s.rpc('tools/call', { name: 'find_robot_skills', arguments: { q: 'cube' } }))!.json();
  assert.equal(found.result.isError, false); assert.equal(found.result.structuredContent.results[0].id, 'alpha-pick');
  const detail: any = await (await s.rpc('tools/call', { name: 'inspect_robot_skill', arguments: { skill_id: 'beta-grasp' } }))!.json(); assert.equal(detail.result.structuredContent.record.access.hub_prepare, false);
});

test('MCP rejects unknown methods, bad arguments, unsafe origins and unsupported transports without mutation', async () => {
  const s = fixture();
  const unknown: any = await (await s.rpc('resources/write'))!.json(); assert.equal(unknown.error.code, -32601);
  const tool: any = await (await s.rpc('tools/call', { name: 'execute_robot', arguments: {} }))!.json(); assert.equal(tool.error.code, -32602);
  const bad: any = await (await s.rpc('tools/call', { name: 'inspect_robot_skill', arguments: { skill_id: 'alpha-pick', command: 'run' } }))!.json(); assert.equal(bad.result.isError, true);
  for (const limit of [true, '2', 0, 51, 1.5]) {
    const value: any = await (await s.rpc('tools/call', { name: 'find_robot_skills', arguments: { limit } }))!.json(); assert.equal(value.result.isError, true);
  }
  assert.equal((await s.rpc('tools/list', {}, { Origin: 'https://evil.example.org' }))!.status, 403);
  assert.equal((await s.rpc('tools/list', {}, { 'MCP-Protocol-Version': '1900-01-01' }))!.status, 400);
  assert.equal((await s.request('/mcp', { headers: { Accept: 'text/event-stream' } }))!.status, 405);
  assert.equal((await s.rpc('tools/list', {}, { Accept: 'text/event-stream' }))!.status, 406);
  assert.equal((await s.rpc('tools/list', {}, { 'Content-Encoding': 'gzip' }))!.status, 415);
});

test('MCP malformed, batch and oversized bodies return bounded protocol errors', async () => {
  const s = fixture();
  for (const body of ['{', '[]', JSON.stringify({ jsonrpc: '2.0', id: {}, method: 'ping' }), 'x'.repeat(32 * 1024 + 1)]) {
    const response = await s.request('/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
    assert.equal(response!.status, 400); const value: any = await response!.json(); assert.equal(value.jsonrpc, '2.0'); assert.ok(value.error.code < 0);
  }
  assert.equal(s.calls.length, 0);
});

test('only successful eligible public reads and tool calls produce goal measurements', async () => {
  const s = fixture(); const measured: unknown[][] = [];
  const metrics = { ...env, METRICS_KEY: 'local-test-HMAC-key', METRICS_TEST_KEY: 'internal-test', METRICS: { prepare() { let values: unknown[] = []; return { bind(...args: unknown[]) { values = args; return this; }, async run() { measured.push(values); }, async all() { return { results: [] }; } }; } } };
  const read = (path: string, headers: Record<string, string> = {}, method = 'GET') => s.handler(new Request('https://api.superfastrobotics.com' + path, { method, headers: { 'User-Agent': 'Codex', ...headers } }), metrics);
  const rpc = (method: string, params: any = {}, id = true) => s.handler(new Request('https://api.superfastrobotics.com/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json', 'User-Agent': 'Codex' }, body: JSON.stringify({ jsonrpc: '2.0', ...(id ? { id: 1 } : {}), method, params }) }), metrics);
  await read('/v1/capabilities'); await read('/v1/metrics'); await read('/v1/search', {}, 'HEAD');
  await rpc('initialize', { protocolVersion: '2025-11-25', clientInfo: { name: 'Independent test client' } }); await rpc('notifications/initialized', {}, false); await rpc('tools/list'); await rpc('ping');
  await read('/v1/search?limit=0'); await rpc('tools/call', { name: 'execute_robot', arguments: {} });
  assert.equal(measured.length, 0);
  await read('/v1/search'); await read('/v1/skills/alpha-pick'); await rpc('tools/call', { name: 'find_robot_skills', arguments: { q: 'cube' } });
  assert.deepEqual(measured.map(values => values[1]), ['search', 'inspect', 'mcp']);
  await read('/v1/search', { DNT: '1' }); await read('/v1/search', { 'X-RSH-Telemetry': 'off' }); await read('/v1/search', { 'X-RSH-Test-Key': 'internal-test' });
  assert.equal(measured.length, 3);
});

test('catalog and reference proxies validate the same published resource hashes', async () => {
  const s = fixture(); assert.equal(await (await s.request('/v1/catalog'))!.text(), s.catalog); assert.equal(await (await s.request('/v1/references'))!.text(), s.references);
  let calls = 0;
  const handler = createPublicHandler(async input => {
    calls++; const path = new URL(String(input)).pathname;
    return Response.json(path.endsWith('version.json') ? { hub_commit: HUB, resources: { index: { sha256: '0'.repeat(64) }, references: { sha256: '0'.repeat(64) } } } : { records: [] });
  });
  for (const path of ['/v1/catalog', '/v1/references']) assert.equal((await handler(new Request('https://api.superfastrobotics.com' + path), env))!.status, 503);
  assert.ok(calls >= 4);
});
