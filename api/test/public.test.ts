import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createPublicHandler } from '../src/public.ts';

const HUB = 'a'.repeat(40), ORIGIN = 'https://hub.superfastrobotics.com';
const hash = (bytes: string | Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const env = { PUBLICATION_URL: ORIGIN + '/catalog/v1/publication.json' };
function fixture(options: { badSearchHash?: boolean; badRecordHash?: boolean; redirect?: boolean; indexLimit?: boolean; rowOverrides?: Record<string, unknown>[]; recipeEvidence?: Record<string, any>; findingRows?: any[]; memoryCommit?: string; badMemoryHash?: boolean; memoryUnavailable?: boolean } = {}) {
  let instant = Date.parse('2026-10-18T00:00:00Z');
  const combo = (runtime: string, robot: string, controller = 'pd_joint_pos', observation = 'state', os = 'linux') => ({ runtime, runtime_version: '1', robot, controller, observation, os, status: 'source_reviewed' });
  const source = { repository: 'https://github.com/upstream/robot', commit: 'b'.repeat(40), sha256: 'c'.repeat(64), url: 'https://github.com/upstream/robot/blob/' + 'b'.repeat(40) + '/task.py' };
  const details = [
    { id: 'alpha-pick', name: 'Alpha pick', summary: 'Pick a cube', source, access: { mode: 'preparation_recipe', hub_prepare: true }, maintenance: { record_version: '1.0.0' }, evidence: options.recipeEvidence || { level: 'source_reviewed', runtime_verification: 'not_run' } },
    { id: 'beta-grasp', name: 'Beta grasp', summary: 'ROS grasp source', source, access: { mode: 'source_reference', hub_prepare: false }, evidence: { level: 'source_reviewed', runtime_verification: 'not_run' } },
    { id: 'gamma-policy', name: 'Gamma policy', summary: 'Pinned ONNX policy source', source: { revision: 'sha256:' + 'd'.repeat(64), sha256: 'd'.repeat(64) }, access: { mode: 'source_reference', hub_prepare: false }, evidence: { level: 'contributor_reported', runtime_verification: 'not_run' } }
  ];
  const text = details.map(d => JSON.stringify(d));
  const rows = details.map((d, index) => ({ id: d.id, name: d.name, summary: d.summary, kind: index === 0 ? 'preparation_recipe' : 'source_reference',
    hub_prepare: index === 0, record_version: index === 0 ? '1.0.0' : 'source-' + d.source.sha256, record_sha256: hash(text[index]),
    source_commit: 'commit' in d.source ? d.source.commit : d.source.revision, source_sha256: d.source.sha256,
    capabilities: [index === 0 ? 'pick' : 'grasp', ...(index === 2 ? ['locomotion'] : [])], aliases: index === 0 ? ['cube transfer'] : [], robots: [index === 1 ? 'ur5' : 'panda'], robot_types: index === 2 ? ['humanoid'] : [], runtime: index === 1 ? 'ros2' : 'maniskill', framework: index === 2 ? 'openpi' : 'maniskill',
    compatibility: index === 0 ? [combo('maniskill', 'panda'), combo('mujoco', 'ur5', 'torque', 'rgb', 'windows')] : index === 1 ? [combo('ros2', 'ur5')] : [],
    record_url: 'https://attacker.example.org/ignored-destination.json', evidence: d.evidence }));
  options.rowOverrides?.forEach((values, index) => Object.assign(rows[index], values));
  const search = JSON.stringify({ schema_version: '1', hub_commit: HUB, counts: { recipes: 1, references: 2, memories: 0 }, records: rows });
  const catalog = JSON.stringify({ schema_version: '1', hub_commit: HUB, records: [details[0]] });
  const references = JSON.stringify({ schema_version: '1', records: details.slice(1) });
  const memories = JSON.stringify({ schema_version: '1', hub_commit: options.memoryCommit || HUB, records: options.findingRows || [] });
  const version = JSON.stringify({ schema_version: '1', hub_commit: HUB, resources: { search: { sha256: options.badSearchHash ? '0'.repeat(64) : hash(search) }, index: { sha256: hash(catalog) }, references: { sha256: hash(references) }, memories: { sha256: options.badMemoryHash ? '0'.repeat(64) : hash(memories) } } });
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
    if (path === '/catalog/v1/memories.json') return options.memoryUnavailable ? new Response(null, { status: 503 }) : new Response(memories);
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

function selectedFinding(id = 1, changes: Record<string, any> = {}) {
  const memory_id = 'mem_' + String(id).padStart(64, '0');
  return { schema_version: '1', memory_id, skill_id: 'alpha-pick', base: { record_version: '1.0.0', source_commit: 'b'.repeat(40), hub_commit: HUB },
    environment: { runtime: 'maniskill', robot: 'panda', os: 'linux' }, fingerprint: 'd'.repeat(64), content_sha256: 'e'.repeat(64),
    entry_url: ORIGIN + '/memories/' + memory_id + '.json', curation: 'maintainer_merged', interpretation: 'data_only', trust: 'contributor_reported',
    summary: 'Observed dependency issue', observation: 'An observed task dependency needs separate review.', resolution: null,
    evidence: { level: 'contributor_reported', reported_by: 'submitter' }, ...changes };
}

test('one task start returns a pinned plan, real recall and an export usable as one-record catalog', async () => {
  const s = fixture({ findingRows: [selectedFinding()] });
  const r: any = await (await s.request('/v1/start?q=pick%20cube&runtime=maniskill&robot=panda&os=linux'))!.json();
  assert.equal(r.results.length, 1); assert.equal(r.selected.id, 'alpha-pick');
  assert.equal(r.scope.startsWith('preparation_recipes_only'), true);
  assert.equal(r.selected.findings.total, 1);
  assert.equal(r.selected.community.status, 'unknown');
  assert.equal(r.results[0].selection_reason.caller_compatibility_verified, false);
  assert.deepEqual(r.selected.environment_check.missing, ['python', 'architecture']);
  assert.equal(r.selected.record_files_omitted, true);
  const p = r.selected.preparation;
  assert.deepEqual(p.bootstrap_argv[2].slice(-2), ['--detach', HUB]);
  assert.ok(p.plan_argv.includes('--plan')); assert.ok(p.plan_argv.includes('b'.repeat(40)));
  assert.equal(p.prepare_argv.includes('--plan'), false); assert.ok(p.prepare_argv.includes('--install-deps'));
  assert.equal(p.execute.argv_from, 'prepare.next_command');
  const url = new URL(p.catalog.url);
  const catalog: any = await (await s.request(url.pathname + url.search))!.json();
  assert.equal(catalog.hub_commit, HUB); assert.deepEqual(catalog.records, [s.details[0]]);
  assert.equal(catalog.coverage.complete, false);
  assert.equal(r.execution_performed, false); assert.equal(r.sharing_performed, false);
});

test('task start preserves empty results and explicit incompatibility without guessing an environment', async () => {
  const s = fixture();
  for (const query of ['q=unrelated%20accounting', 'q=pick%20cube&runtime=maniskill&robot=ur5']) {
    const r: any = await (await s.request('/v1/start?' + query))!.json();
    assert.equal(r.selected, null); assert.equal(r.results.length, 0); assert.ok(r.recovery);
  }
  const r: any = await (await s.request('/v1/start?q=pick%20cube'))!.json();
  assert.deepEqual(r.selected.environment_check.supplied, {});
  assert.equal(r.selected.environment_check.missing.length, 5);
});

test('start bounds optional lookup and validates parameters, pins, hashes and catalog exports', async () => {
  for (const query of ['', 'q=', 'q=pick&limit=4', 'q=pick&limit=0', 'q=pick&offset=0',
    'q=pick&kind=source_reference', 'q=pick&execute=true']) {
    assert.equal((await fixture().request('/v1/start?' + query))!.status, 400);
  }
  assert.equal((await fixture().request('/v1/start?q=pick&hub_commit=' + 'f'.repeat(40)))!.status, 409);
  assert.equal((await fixture({ badRecordHash: true }).request('/v1/start?q=pick'))!.status, 503);
  const s = fixture({ memoryUnavailable: true });
  const r: any = await (await s.request('/v1/start?q=pick'))!.json();
  assert.equal(r.selected.findings.status, 'unknown'); assert.equal(r.selected.findings.total, null);
  assert.ok(r.selected.preparation.plan_argv);
  assert.equal(s.calls.filter(c => /\/skill.json/.test(c.url)).length, 1, 'Only the first candidate is hydrated');
  for (const suffix of ['format=unknown', 'format=catalog&include=experience', 'format=catalog&execute=true'])
    assert.equal((await s.request('/v1/skills/alpha-pick?' + suffix))!.status, 400);
  assert.equal((await s.request('/v1/skills/beta-grasp?format=catalog'))!.status, 400);
  assert.equal((await s.request('/v1/skills/alpha-pick?format=catalog&record_version=old'))!.status, 409);
});

test('MCP task start matches HTTP semantics and rejects nonnumeric limits', async () => {
  const s = fixture();
  const result: any = await (await s.rpc('tools/call', {name:'start_robot_task', arguments:{q:'pick cube'}}))!.json();
  assert.equal(result.result.isError, false);
  assert.equal(result.result.structuredContent.selected.id, 'alpha-pick');
  assert.equal(result.result.structuredContent.execution_performed, false);
  const bad: any = await (await s.rpc('tools/call', {name:'start_robot_task', arguments:{q:'pick',limit:'2'}}))!.json();
  assert.equal(bad.result.isError, true);
});

test('compact discovery retains pins and failures; full mode and pinned contract remain accessible', async () => {
  const evidence = { level: 'import_verified', hub_verification: { last_task_attempt: { status: 'failed', success: false } } };
  const s = fixture({ recipeEvidence: evidence, findingRows: [selectedFinding()] });
  const r: any = await (await s.request('/v1/start?q=pick&robot=panda'))!.json();
  assert.equal(r.detail, 'compact'); assert.equal(r.limit, 1);
  assert.equal(r.selected.contract_omitted, true);
  assert.deepEqual(r.selected.record.evidence, evidence);
  assert.equal(r.selected.findings.results[0].observation, undefined);
  assert.equal(r.selected.findings.results[0].summary, 'Observed dependency issue');
  assert.equal(r.selected.findings.details_omitted, true);
  const findingsURL = new URL(r.selected.findings.details_url);
  assert.equal(findingsURL.pathname, '/v1/findings');
  assert.equal(findingsURL.searchParams.get('source_commit'), 'b'.repeat(40));
  assert.equal(findingsURL.searchParams.get('robot'), 'panda');
  assert.equal(new URL(r.selected.community.details_url).pathname, '/v1/community/items');
  const detail = new URL(r.selected.full_record_url);
  assert.deepEqual(JSON.parse(detail.searchParams.get('environment')!), { robot: 'panda' });
  const full: any = await (await s.request('/v1/start?q=pick&detail=full'))!.json();
  assert.equal(full.limit, 3); assert.equal(full.detail, 'full');
  assert.equal(full.selected.findings.results[0].observation, selectedFinding().observation);
  const url = new URL(r.selected.contract_url);
  const contract: any = await (await s.request(url.pathname + url.search))!.json();
  assert.equal(contract.hub_commit, HUB); assert.equal(contract.record_version, '1.0.0');
  assert.deepEqual(contract.record.source, s.details[0].source);
  assert.deepEqual(contract.record.evidence, evidence);
  assert.equal(contract.record.preparation, undefined); assert.equal(contract.findings, undefined);
  const rpc: any = await (await s.rpc('tools/call', r.selected.contract_tool))!.json();
  assert.deepEqual(rpc.result.structuredContent, contract);
  assert.deepEqual(JSON.parse(rpc.result.content[0].text), contract);
  for (const suffix of ['detail=typo', 'detail=full&execute=true'])
    assert.equal((await s.request('/v1/start?q=pick&' + suffix))!.status, 400);
  assert.equal((await s.request('/v1/skills/alpha-pick?format=contract&record_version=old'))!.status, 409);
  assert.equal((await s.request('/v1/skills/alpha-pick?format=contract&hub_commit=' + 'f'.repeat(40)))!.status, 409);
  const bad: any = await (await s.rpc('tools/call', { name: 'inspect_robot_skill', arguments: {
    skill_id: 'alpha-pick', detail: 'contract', hub_commit: 'f'.repeat(40) } }))!.json();
  assert.equal(bad.result.isError, true);
});

test('empty first search returns a bounded actionable retry and pinned HTTP experience link', async () => {
  const s = fixture({ findingRows: [selectedFinding()] });
  const first: any = await (await s.request('/v1/search?q=Please%20find%20code%20to%20pick%20up%20a%20cube&limit=3'))!.json();
  assert.equal(first.total, 0);
  assert.equal(first.recovery.automatic_retry, false);
  const suggestion = first.recovery.suggested_requests[0];
  assert.equal(suggestion.arguments.kind, 'preparation_recipe');
  assert.match(suggestion.scope, /excludes_source_references/);
  assert.equal(suggestion.arguments.robot, undefined);
  assert.equal(suggestion.arguments.hub_commit, HUB);
  assert.equal(suggestion.arguments.limit, 3);
  const rpc: any = await (await s.rpc('tools/call', { name: 'find_robot_skills', arguments: suggestion.arguments }))!.json();
  assert.equal(rpc.result.isError, false, 'HTTP recovery arguments are directly usable by MCP');
  const retry = new URL(suggestion.url);
  const found: any = await (await s.request(retry.pathname + retry.search))!.json();
  assert.equal(found.results[0].id, 'alpha-pick');
  const detailURL = new URL(found.results[0].inspect_url);
  assert.equal(detailURL.origin, 'https://api.superfastrobotics.com');
  assert.equal(detailURL.searchParams.get('record_version'), '1.0.0');
  detailURL.searchParams.set('environment', JSON.stringify({ robot: 'panda', os: 'linux' }));
  const detail: any = await (await s.request(detailURL.pathname + detailURL.search))!.json();
  assert.equal(detail.findings.total, 1);
  assert.equal(detail.findings.base.source_commit, 'b'.repeat(40));
  assert.equal(detail.community.status, 'unknown', 'Missing community database is not empty success');
  assert.deepEqual(detail.record, s.details[0]);
  detailURL.searchParams.set('environment', JSON.stringify({ robot: 'ur5' }));
  const other: any = await (await s.request(detailURL.pathname + detailURL.search))!.json();
  assert.equal(other.findings.total, 0);
});

test('HTTP experience rejects drift and invalid filters and preserves records on optional recall failure', async () => {
  const s = fixture({ memoryUnavailable: true });
  for (const suffix of ['&environment=null', '&environment=false', '&environment=%7Bbad', '&environment=%7B%22robot%22%3Afalse%7D', '&robot=panda']) {
    assert.equal((await s.request('/v1/skills/alpha-pick?include=experience' + suffix))!.status, 400);
  }
  assert.equal((await s.request('/v1/skills/alpha-pick?include=unknown'))!.status, 400);
  assert.equal((await s.request('/v1/skills/alpha-pick?include=experience&hub_commit=' + 'f'.repeat(40)))!.status, 409);
  assert.equal((await s.request('/v1/skills/alpha-pick?include=experience&record_version=old'))!.status, 409);
  const detail: any = await (await s.request('/v1/skills/alpha-pick?include=experience'))!.json();
  assert.deepEqual(detail.record, s.details[0]);
  assert.equal(detail.findings.status, 'unknown');
  assert.equal(detail.findings.total, null);
  assert.equal(detail.findings.coverage.complete, false);
});

test('search recovery preserves caller filters and never changes a reference-only scope to recipes', async () => {
  const s = fixture();
  for (const kind of ['source_reference', 'preparation_recipe']) {
    const result: any = await (await s.request('/v1/search?q=find%20example%20code&kind=' + kind + '&runtime=ros2&robot=ur5&offset=2'))!.json();
    const retry = result.recovery.suggested_requests[0].arguments;
    assert.equal(retry.query_mode, 'task'); assert.equal(retry.kind, kind);
    assert.equal(retry.runtime, 'ros2'); assert.equal(retry.robot, 'ur5'); assert.equal(retry.offset, 0);
  }
  const unsupported: any = await (await s.request('/v1/search?q=' + encodeURIComponent('없는 스킬')))!.json();
  assert.deepEqual(unsupported.recovery.suggested_requests, []);
});

test('reference discovery and inspection link separate exact-pin executable adaptations without promoting the source', async () => {
  const s=fixture({rowOverrides:[{}, {prepared_adaptations:[{id:'alpha-pick',record_version:'1.0.0',source_commit:'b'.repeat(40),model:'panda',relationship:'adapted_from; model and contract may differ'}]}]});
  const found: any=await (await s.request('/v1/search?q=ROS'))!.json();
  assert.equal(found.results[0].kind,'source_reference'); assert.equal(found.results[0].hub_prepare,false);
  const link=new URL(found.results[0].prepared_adaptations[0].inspect_url);
  assert.equal(link.origin,'https://api.superfastrobotics.com'); assert.equal(link.searchParams.get('record_version'),'1.0.0');
  const reference: any=await (await s.request('/v1/skills/beta-grasp'))!.json();
  assert.deepEqual(reference.record,s.details[1]);
  assert.equal(reference.prepared_adaptations[0].id,'alpha-pick');
  const prepared: any=await (await s.request(link.pathname+link.search))!.json();
  assert.equal(prepared.record.id,'alpha-pick');assert.equal(prepared.record.access.hub_prepare,true);
});

test('MCP inspect automatically recalls bounded exact-version findings without changing records or search', async () => {
  const rows = [1, 2, 3, 4, 5].map(id => selectedFinding(id));
  rows.push(selectedFinding(6, { base: { ...rows[0].base, source_commit: 'f'.repeat(40) } }));
  rows.push(selectedFinding(7, { base: { ...rows[0].base, record_version: '2.0.0' } }));
  rows.push(selectedFinding(8, { environment: { runtime: 'maniskill', robot: 'ur5' } }));
  const s = fixture({ findingRows: rows });
  await s.rpc('tools/call', { name: 'find_robot_skills', arguments: { q: 'cube' } });
  assert.equal(s.calls.filter(c => c.url.includes('/memories.json')).length, 0, 'Search must not fan out memory lookups');
  const response: any = await (await s.rpc('tools/call', { name: 'inspect_robot_skill', arguments: { skill_id: 'alpha-pick', environment: { robot: 'panda' } } }))!.json();
  assert.equal(response.result.isError, false);
  const detail = response.result.structuredContent;
  assert.deepEqual(detail.record, s.details[0]);
  assert.equal(detail.findings.status, 'ready'); assert.equal(detail.findings.total, 5);
  assert.equal(detail.findings.results.length, 3); assert.equal(detail.findings.next.offset, 3);
  assert.equal(detail.findings.next.hub_commit, HUB); assert.deepEqual(detail.findings.coverage, { complete: true });
  assert.equal(detail.findings.interpretation, 'data_only'); assert.equal(detail.findings.applicability, 'needs_applicability_check');
  assert.deepEqual(detail.findings.environment_filter, { robot: 'panda' });
  assert.equal(s.calls.filter(c => c.url.includes('/memories.json')).length, 1);
  const before = s.calls.length;
  const restText = await (await s.request('/v1/skills/alpha-pick'))!.text();
  assert.equal(restText, JSON.stringify({ schema_version: '1', interpretation: 'data_only', hub_commit: HUB,
    backend: 'static_v1_fallback', record: s.details[0], execution_performed: false }), 'Existing REST envelope bytes remain unchanged');
  const rest: any = JSON.parse(restText);
  assert.deepEqual(rest.record, s.details[0]); assert.equal(rest.findings, undefined);
  assert.equal(s.calls.length, before, 'Existing REST record reads do not add recall');
});

test('optional MCP recall failure never breaks inspect or fabricates absence', async () => {
  for (const options of [{ badMemoryHash: true }, { memoryCommit: 'f'.repeat(40) }, { memoryUnavailable: true },
    { findingRows: [selectedFinding(1, { curation: 'draft' })] }, { findingRows: [selectedFinding(), selectedFinding()] }]) {
    const s = fixture(options);
    const rpc: any = await (await s.rpc('tools/call', { name: 'inspect_robot_skill', arguments: { skill_id: 'alpha-pick' } }))!.json();
    assert.equal(rpc.result.isError, false);
    const detail = rpc.result.structuredContent;
    assert.deepEqual(detail.record, s.details[0]); assert.equal(detail.findings.status, 'unknown');
    assert.equal(detail.findings.total, null); assert.deepEqual(detail.findings.coverage, { complete: false });
    assert.equal(detail.findings.applicability, 'needs_applicability_check'); assert.ok(detail.findings.reason_code);
  }
});

test('MCP reference recall uses source digest version and accepts only explicit bounded environment labels', async () => {
  const s = fixture({ findingRows: [selectedFinding(1, { skill_id: 'beta-grasp', base: { record_version: 'source-' + 'c'.repeat(64), source_commit: 'b'.repeat(40), hub_commit: HUB } })] });
  const result: any = await (await s.rpc('tools/call', { name: 'inspect_robot_skill', arguments: { skill_id: 'beta-grasp' } }))!.json();
  assert.equal(result.result.isError, false); const detail = result.result.structuredContent;
  assert.equal(detail.findings.total, 1); assert.deepEqual(detail.findings.environment_filter, {});
  assert.equal(detail.findings.applicability, 'needs_applicability_check');
  assert.equal(detail.record.evidence.runtime_verification, 'not_run');
  const beforeInvalid = s.calls.length;
  for (const environment of [{ private_path: '/private' }, { robot: 123 }, { robot: ' ' }, { robot: 'x'.repeat(241) }, []]) {
    const invalid: any = await (await s.rpc('tools/call', { name: 'inspect_robot_skill', arguments: { skill_id: 'beta-grasp', environment } }))!.json();
    assert.equal(invalid.result.isError, true);
  }
  assert.equal(s.calls.length, beforeInvalid, 'Invalid labels stop before any publication lookup');
  assert.ok(s.calls.every(c => !new Headers(c.init?.headers).has('Authorization')));
});

test('public search and inspect need no credentials and preserve recipe/reference evidence distinctions', async () => {
  const s = fixture(); const response = await s.request('/v1/search?q=cube'); assert.equal(response!.status, 200);
  const body: any = await response!.json(); assert.equal(body.results.length, 1); assert.equal(body.results[0].id, 'alpha-pick'); assert.equal(body.execution_performed, false);
  const reference: any = await (await s.request('/v1/skills/beta-grasp'))!.json(); assert.equal(reference.record.access.hub_prepare, false); assert.equal(reference.record.evidence.runtime_verification, 'not_run');
  const policy: any = await (await s.request('/v1/skills/gamma-policy'))!.json(); assert.equal(policy.record.source.commit, undefined); assert.match(policy.record.source.revision, /^sha256:/);
  assert.ok(s.calls.every(call => !call.url.startsWith('https://attacker.example.org')));
});

test('HTTP and MCP preserve an observed failed attempt separately from positive checks', async () => {
  const attempt = { status: 'failed', execution_performed: true, success: false, reason_code: 'task_objective_not_reached',
    seed: 0, elapsed_steps: 12, terminated: false, truncated: false, exit_code: 1, timed_out: false,
    workflow_run_id: '123', verified_hub_commit: HUB, source_commit: 'b'.repeat(40), record_version: '1.0.0',
    environment: { runtime: 'maniskill', runtime_version: '1', robot: 'panda', controller: 'pd_joint_pos', observation: 'state', os: 'linux' } };
  const evidence = { level: 'import_verified', runtime_verification: 'import_verified', artifacts: ['https://example.org/pinned/report.json'],
    hub_verification: { level: 'import_verified', runtime: 'import_verified', last_task_attempt: attempt } };
  const s = fixture({ recipeEvidence: evidence, rowOverrides: [{ evidence_level: evidence.level, runtime_verification: evidence.runtime_verification, last_task_attempt: attempt }] });
  const found: any = await (await s.request('/v1/search?q=cube'))!.json();
  assert.deepEqual(found.results[0].last_task_attempt, attempt);
  assert.equal(found.results[0].evidence_level, 'import_verified');
  assert.ok(found.results[0].compatibility.every((c: any) => c.status !== 'hub_verified'));
  assert.deepEqual(found.counts, { recipes: 1, references: 2, memories: 0 }, 'Inventory counts are not success counts');
  const inspected: any = await (await s.request('/v1/skills/alpha-pick'))!.json();
  assert.deepEqual(inspected.record.evidence, evidence);
  for (const [name, args] of [['find_robot_skills', { q: 'cube' }], ['inspect_robot_skill', { skill_id: 'alpha-pick' }]] as const) {
    const rpc: any = await (await s.rpc('tools/call', { name, arguments: args }))!.json();
    assert.equal(rpc.result.isError, false);
    const body = rpc.result.structuredContent;
    assert.deepEqual(name === 'find_robot_skills' ? body.results[0].last_task_attempt : body.record.evidence.hub_verification.last_task_attempt, attempt);
  }
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
  assert.equal(s.calls.length, 0, 'HTTP capability metadata does not fetch or install onboarding resources');
  const mcp: any = await (await s.rpc('tools/call', { name: 'get_hub_capabilities', arguments: {} }))!.json();
  assert.equal(mcp.result.isError, false);
  assert.deepEqual(mcp.result.structuredContent.onboarding, body.onboarding, 'HTTP and MCP clients receive the same local handoff');
  assert.equal(body.onboarding.source_acquisition.cli_command, 'fetch-source');
  assert.equal(body.onboarding.source_acquisition.source_manifest_grants_sharing_permission, false);
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

test('static word-prefix search separates acronyms from mid-word substrings and preserves declared aliases, Unicode words and filters', async () => {
  const overrides = [
    { name: 'Model predictive speed and steer control', summary: 'Path tracking control', aliases: ['MPC', 'steering control'] },
    { name: 'Dynamic window approach', summary: 'Navigation algorithm', aliases: ['DWA'], capabilities: ['navigation'] },
    { name: 'Hardware SDK', summary: '\uB85C\uBD07 SDK sample', aliases: [] }
  ];
  const s = fixture({ rowOverrides: overrides });
  const read = async (q: string, extra = '') => {
    const response = await s.request('/v1/search?q=' + encodeURIComponent(q) + extra);
    assert.equal(response!.status, 200); const value = await response!.json() as any;
    assert.equal(value.search_semantics, 'all_terms_word_prefix'); assert.equal(value.backend, 'static_v1_fallback');
    return value;
  };
  for (const q of ['DWA', '!!!DWA!!!', 'dynamic\u2013window/navigation', 'dyn nav']) {
    const found = await read(q); assert.deepEqual(found.results.map((row: any) => row.id), ['beta-grasp']);
    assert.equal(found.results[0].record_version, 'source-' + s.details[1].source.sha256);
    assert.equal(found.results[0].hub_prepare, false);
  }
  for (const q of ['model predictive speed steering', 'speed steering', 'MPC']) {
    assert.deepEqual((await read(q)).results.map((row: any) => row.id), ['alpha-pick']);
  }
  for (const q of ['ware', 'dwa missingterm', 'DWA OR hardware', '\uC5C6\uB294\uB2E8\uC5B4', '---', '!!!', '/_']) {
    const absent = await read(q, '&offset=5&limit=2'); assert.equal(absent.total, 0); assert.deepEqual(absent.results, []);
    assert.equal(absent.offset, 5); assert.equal(absent.limit, 2); assert.equal(absent.next, null);
  }
  assert.deepEqual((await read('\uB85C\uBD07 SDK')).results.map((row: any) => row.id), ['gamma-policy']);
  assert.equal((await read('DWA', '&runtime=ros2')).total, 1);
  assert.equal((await read('DWA', '&runtime=ros2&robot=ur5')).total, 1);
  assert.equal((await read('DWA', '&runtime=ros2&robot=panda')).total, 0);
  assert.equal((await read('DWA', '&kind=preparation_recipe')).total, 0);
  for (const q of ['', '  ']) assert.equal((await read(q)).total, 3, 'Only empty or whitespace query browses every record');
  const undeclared = fixture({ rowOverrides: [{ ...overrides[0], aliases: ['MPC'] }] });
  assert.equal((await (await undeclared.request('/v1/search?q=speed%20steering'))!.json() as any).total, 0, 'No inferred stemming or undeclared synonym');
});

test('static word-prefix search retains exact-ID priority, pinned pagination and its explicit accent limitation', async () => {
  const s = fixture({ rowOverrides: [{ name: 'Beta grasp recipe', summary: 'Caf\u00E9 manipulation' }] });
  const first = await (await s.request('/v1/search?q=beta-grasp&limit=1'))!.json() as any;
  assert.equal(first.total, 2); assert.deepEqual(first.results.map((row: any) => row.id), ['beta-grasp']);
  assert.deepEqual(first.next, { q: 'beta-grasp', limit: 1, offset: 1, hub_commit: HUB });
  const last = await (await s.request('/v1/search?' + new URLSearchParams(first.next)))!.json() as any;
  assert.deepEqual(last.results.map((row: any) => row.id), ['alpha-pick']); assert.equal(last.next, null);
  assert.equal(last.results[0].source_commit, s.rows[0].source_commit);
  assert.equal((await (await s.request('/v1/search?q=caf\u00E9'))!.json() as any).total, 1);
  assert.equal((await (await s.request('/v1/search?q=cafe'))!.json() as any).total, 0, 'Static tokenization does not claim native Latin accent folding');
});

test('static search recognizes standalone A*/D* queries without rewriting identifiers or document symbols', async () => {
  const s = fixture({ rowOverrides: [
    { name: 'AStar grid planner', summary: 'Grid route', aliases: ['AStar', 'A*'] },
    { name: 'DStarLite incremental planner', summary: 'Incremental route', aliases: ['DStarLite', 'D* Lite'] },
    { name: 'Algebra dynamics', summary: 'Ordinary algorithm terms and literal A* D* text',
      aliases: ['RA', 'A B', 'D B', 'A variable', '\u00e9A', '\uB85C\uBD07A', 'A*', 'D*'] }
  ] });
  const read = async (q: string) => {
    const response = await s.request('/v1/search?q=' + encodeURIComponent(q));
    assert.equal(response!.status, 200); const body = await response!.json() as any;
    assert.equal(body.backend, 'static_v1_fallback'); assert.equal(body.search_semantics, 'all_terms_word_prefix');
    return body.results.map((row: any) => row.id);
  };
  for (const q of ['A*', 'a*', '!!!A*!!!', '(A*)/grid', 'AStar grid']) {
    assert.deepEqual(await read(q), ['alpha-pick'], q);
  }
  for (const q of ['D*', 'd* lite', '(D*)/incremental', 'DStarLite']) {
    assert.deepEqual(await read(q), ['beta-grasp'], q);
  }
  assert.deepEqual(await read('A* impossible'), [], 'Every normalized query term is still required');
  assert.deepEqual(await read('A* OR dynamics'), [], 'Algorithm spelling does not add OR search');
  for (const q of ['RA*', 'A*B', 'a_variable*', '\u00e9A*', '\uB85C\uBD07A*']) {
    assert.deepEqual(await read(q), ['gamma-policy'], q + ' keeps ordinary word tokens');
  }
  assert.deepEqual(await read('D*B'), ['beta-grasp', 'gamma-policy'], 'Existing beta ID supplies the ordinary b prefix');
  for (const q of ['A**', '*A*', '_A*', 'A*_', '\u0301A*', 'A*\u0301', 'a']) {
    assert.deepEqual(await read(q), ['alpha-pick', 'gamma-policy'], q + ' does not become astar');
  }
  assert.deepEqual(await read('D**'), ['beta-grasp', 'gamma-policy']);
  assert.deepEqual(await read('algebra dynamics'), ['gamma-policy'], 'Ordinary words retain word-prefix matching');
  const hybrid = fixture({ rowOverrides: [
    { name: 'Hybrid AStar planner', summary: 'Curvature route', aliases: ['Hybrid AStar'] }
  ] });
  const found = await (await hybrid.request('/v1/search?q=Hybrid%20A*'))!.json() as any;
  assert.deepEqual(found.results.map((row: any) => row.id), ['alpha-pick']);
});

test('static discovery distinguishes canonical RRT* from ordinary RRT words and literal-only text', async () => {
  const s = fixture({ rowOverrides: [
    { name: 'RRT planner', summary: 'Sampling routes', aliases: ['RRT', 'Rapidlyexploring random tree'] },
    { name: 'RRTStar planner', summary: 'Optimal routes', aliases: ['RRTStar', 'RRT*', 'Rapidlyexploring random tree star'] },
    { name: 'Query syntax notes', summary: 'Literal RRT* notation', aliases: ['RRRT', 'RRT B', '2RRT', '\u00e9RRT', '\uB85C\uBD07RRT', 'RRT*'] }
  ] });
  const cases: [string, string[]][] = [
    ...['RRT*', 'rrt*', 'rRt*', '!!!RRT*!!!', '(RRT*)/planner', 'RRTStar', 'RRT Star'].map(q => [q, ['beta-grasp']] as [string, string[]]),
    ...['RRRT*', '2RRT*', '\u00e9RRT*', '\uB85C\uBD07RRT*'].map(q => [q, ['gamma-policy']] as [string, string[]]),
    ...['RRT', 'rr', 'RRT**', '*RRT*', '_RRT*', 'RRT*_', '\u0301RRT*', 'RRT*\u0301'].map(q => [q, ['alpha-pick', 'beta-grasp', 'gamma-policy']] as [string, string[]]),
    ['RRT*B', ['beta-grasp', 'gamma-policy']], ['RRT planner', ['alpha-pick', 'beta-grasp']],
    ['RRT* sampling', []], ['RRT* impossible', []], ['RRT* OR sampling', []]
  ];
  for (const [q, expected] of cases) {
    const response = await s.request('/v1/search?q=' + encodeURIComponent(q));
    assert.equal(response!.status, 200); const body = await response!.json() as any;
    assert.equal(body.backend, 'static_v1_fallback'); assert.equal(body.search_semantics, 'all_terms_word_prefix');
    assert.deepEqual(body.results.map((row: any) => row.id), expected, q); assert.equal(body.total, expected.length);
  }
  const tools: any = await (await s.rpc('tools/list'))!.json();
  assert.match(tools.result.tools.find((tool: any) => tool.name === 'find_robot_skills').inputSchema.properties.q.description, /RRT\*/);
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
  const tools: any = await (await s.rpc('tools/list'))!.json(); assert.equal(tools.result.tools.length, 4);
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

function coverageFixture(options: { change?: (value: any) => void; badHash?: boolean; missing?: boolean; wrongUrl?: boolean; oversized?: boolean } = {}) {
  const value: any = { schema_version: '1', hub_commit: HUB, totals: { preparation_recipes: 2, source_references: 3,
    completed: 1, failed: 1, not_executed: 0, evidence_unbound: 0, completed_computations: 1, completed_simulations: 0, completed_hardware: 0 },
    recipes: [{ id: 'alpha-pick', state: 'completed' }, { id: 'beta-task', state: 'failed' }], references: {
      by_framework: [{ label: 'fixture', references: 3 }], by_runtime_evidence: [{ label: 'not_run', references: 3 }],
      by_robot_type: [], by_capability: [], by_robot_label: [], by_runtime_label: [] } };
  options.change?.(value);
  const body = options.oversized ? 'x'.repeat(256 * 1024 + 1) : JSON.stringify(value);
  const calls: string[] = [];
  const handler = createPublicHandler(async (input, init) => {
    const url = String(input); calls.push(url);
    assert.equal(new Headers(init?.headers).get('DNT'), '1');
    assert.equal(new Headers(init?.headers).has('Authorization'), false);
    assert.equal(init?.redirect, 'manual');
    if (new URL(url).pathname === '/catalog/v1/version.json') return Response.json({ schema_version: '1', hub_commit: HUB,
      counts: { recipes: 2, references: 3 }, resources: options.missing ? {} : { coverage: {
        url: options.wrongUrl ? 'https://attacker.invalid/coverage.json' : ORIGIN + '/catalog/v1/coverage.json', sha256: options.badHash ? '0'.repeat(64) : hash(body) } } });
    assert.equal(url, ORIGIN + '/catalog/v1/coverage.json?v=' + HUB);
    return new Response(body);
  });
  return { value, calls, request: (path = '/v1/coverage', method = 'GET') => handler(new Request('https://api.superfastrobotics.com' + path, { method }), env) };
}

test('coverage is a bounded read-only complete generation with optional exact pin and HEAD', async () => {
  const s = coverageFixture();
  assert.deepEqual(await (await s.request('/v1/coverage?view=full&hub_commit=' + HUB))!.json(), s.value);
  const summary: any = await (await s.request('/v1/coverage?hub_commit=' + HUB))!.json();
  assert.deepEqual(summary.totals, s.value.totals); assert.equal(summary.view, 'summary'); assert.equal('recipes' in summary, false);
  assert.equal(summary.source_resource.sha256, hash(JSON.stringify(s.value)));
  assert.ok(summary.full_url.includes('view=full&hub_commit=' + HUB));
  const head = (await s.request('/v1/coverage', 'HEAD'))!; assert.equal(head.status, 200); assert.equal(await head.text(), '');
  assert.equal((await s.request('/v1/coverage', 'POST'))!.status, 405);
  assert.equal((await s.request('/v1/coverage?hub_commit=' + 'b'.repeat(40)))!.status, 409);
  assert.equal((await s.request('/v1/coverage?robot=panda'))!.status, 400);
  assert.equal((await s.request('/v1/coverage?view=unknown'))!.status, 400);
});

test('coverage rejects missing, foreign, oversized or checksum-mismatched resources', async () => {
  for (const options of [{ missing: true }, { wrongUrl: true }, { oversized: true }, { badHash: true }]) {
    const s = coverageFixture(options); assert.equal((await s.request())!.status, 503);
    assert.ok(s.calls.every(url => url.startsWith(ORIGIN + '/')));
  }
});

test('coverage summary bounds capability tags explicitly and preserves complete totals and full access', async () => {
  const s = coverageFixture({ change: value => { value.references.by_capability = Array.from({ length: 15 }, (_, n) => ({ label: 'tag-' + n, references: 1 })); } });
  const summary: any = await (await s.request())!.json();
  assert.equal(summary.references.by_capability.length, 10);
  assert.deepEqual(summary.references.capability_tag_coverage, { complete: false, shown: 10, total: 15 });
  assert.deepEqual(summary.totals, s.value.totals);
  assert.deepEqual(await (await s.request('/v1/coverage?view=full'))!.json(), s.value);
});

test('coverage never serves wrong-generation, inconsistent or duplicate recipe totals', async () => {
  for (const change of [(v: any) => v.hub_commit = 'b'.repeat(40),
    (v: any) => v.totals.completed = 2, (v: any) => v.totals.completed_hardware = -1,
    (v: any) => v.totals.source_references = 4, (v: any) => v.recipes[1].id = v.recipes[0].id,
    (v: any) => v.recipes[1].state = 'completed', (v: any) => v.references.by_framework[0].references = 4,
    (v: any) => v.references.by_capability = 'bad', (v: any) => v.references.by_framework.push(v.references.by_framework[0])]) {
    assert.equal((await coverageFixture({ change }).request())!.status, 503);
  }
});
