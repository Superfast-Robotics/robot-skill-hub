/** Small discovery views. Full contracts and code remain separate pinned reads. */
type Row = Record<string, any>;
const API = 'https://api.superfastrobotics.com';
const pick = (value: Row, keys: string[]) => Object.fromEntries(keys.filter(key => value[key] !== undefined).map(key => [key, value[key]]));

export function executionContract(record: Row) {
  return pick(record, ['id', 'source', 'license', 'adapter_license', 'compatibility', 'observation',
    'requirements', 'interface', 'invocation', 'completion', 'evidence', 'maintenance']);
}

function recallSummary(page: Row, url: string) {
  return { ...pick(page, ['status', 'reason_code', 'total', 'coverage', 'complete', 'next', 'through', 'next_after']),
    interpretation: 'data_only', trust: 'contributor_reported', details_omitted: true, details_url: url,
    results: (page.results || []).map((entry: Row) => pick(entry, ['memory_id', 'id', 'kind', 'summary', 'entry_url',
      'detail_path', 'environment', 'reuse_reports'])),
    next_action: 'read_applicable_details_before_reuse' };
}

export function compactStart(value: Row, includeContract = false) {
  const selected = value.selected;
  const results = value.results.map((row: Row) => pick(row, ['id', 'name', 'summary', 'kind', 'record_version',
    'runtime', 'robots', 'runtime_verification', 'last_task_attempt', 'selection_reason', 'inspect_url', 'start_url']));
  if (!selected) return { ...value, detail: includeContract ? 'execute' : 'compact', results };
  const record = selected.record;
  const contractURL = API + '/v1/skills/' + selected.id + '?' + new URLSearchParams({
    hub_commit: value.hub_commit, record_version: results[0].record_version, format: 'contract' });
  const scope = { skill_id: selected.id, record_version: results[0].record_version,
    source_commit: value.results[0].source_commit, limit: '3' };
  const environment = selected.environment_check.supplied;
  const findingsURL = API + '/v1/findings?' + new URLSearchParams({ ...scope, hub_commit: value.hub_commit, ...environment });
  const communityURL = API + '/v1/community/items?' + new URLSearchParams({ ...scope, environment: JSON.stringify(environment) });
  // Only replace a duplicate schema when byte-equivalent. Retain differing schemas.
  const invocation = record.invocation?.outputs?.schema && record.interface?.output_schema
    && JSON.stringify(record.invocation.outputs.schema) === JSON.stringify(record.interface.output_schema)
    ? { ...record.invocation, outputs: { ...pick(record.invocation.outputs, Object.keys(record.invocation.outputs).filter(k => k !== 'schema')),
        schema_from: '#/selected/record/interface/output_schema' } } : record.invocation;
  return { ...pick(value, ['schema_version', 'interpretation', 'hub_commit', 'coverage', 'total', 'limit', 'offset',
    'next', 'next_url', 'scope', 'execution_performed', 'sharing_performed']), detail: includeContract ? 'execute' : 'compact', results,
    selected: { ...pick(selected, ['id', 'selection', 'record_files_omitted', 'full_record_url', 'environment_check', 'preparation']),
      preparation: { ...selected.preparation, execute: {
        ...pick(selected.preparation.execute, ['argv_from', 'cwd_from', 'timeout_seconds', 'result_check']),
        contract_from: 'selected.contract_url',
        input_override: 'Read the full contract, then replace --example with --input /ABSOLUTE_PATH/task.json when supported.' } },
      record: { ...pick(record, ['id', 'license', 'adapter_license', 'requirements', 'compatibility', 'maintenance']),
        source: pick(record.source || {}, ['repository', 'commit', 'revision', 'url', 'sha256', 'archive_url', 'archive_sha256']),
        evidence: record.evidence,
        ...(includeContract ? { ...pick(record, ['interface', 'observation', 'completion']), invocation } : {}) },
      source_file_list_omitted: true,
      ...(!includeContract ? { interface_summary: pick(record.interface || {}, ['version', 'kind', 'abstraction_level', 'execution_domain', 'language', 'conventions']) } : {}),
      contract_url: contractURL, contract_omitted: !includeContract,
      contract_tool: { name: 'inspect_robot_skill', arguments: { skill_id: selected.id,
        record_version: results[0].record_version, hub_commit: value.hub_commit, detail: 'contract' } },
      findings: recallSummary(selected.findings, findingsURL),
      community: recallSummary(selected.community, communityURL) },
    next_action: includeContract ? 'check_contract_environment_and_applicable_recall_then_run_plan_within_task_scope'
      : 'read_contract_url_before_execution; check_environment_and_applicable_recall_details',
    evidence_rule: 'A match does not establish compatibility. Read the full contract and evidence before execution.' };
}
