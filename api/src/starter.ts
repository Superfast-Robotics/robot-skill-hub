/** Inert, pinned preparation instructions. Never executes a returned command. */
type Row = Record<string, any>;
const REPO = 'https://github.com/Superfast-Robotics/robot-skill-hub.git';
const API = 'https://api.superfastrobotics.com';
const HUB = 'https://hub.superfastrobotics.com';
export function preparationHandoff(record: Row, row: Row, commit: string) {
  const catalogURL = API + '/v1/skills/' + row.id + '?' + new URLSearchParams({
    hub_commit: commit, record_version: row.record_version, format: 'catalog'
  });
  const prefix = ['python', './robot-skill-hub-cli/skills/find-robot-skills/scripts/rsh.py',
    '--catalog', './pinned-catalog.json', '--offline', 'prepare', row.id,
    '--project', './experiment', '--expected-source-commit', row.source_commit,
    '--expected-record-version', row.record_version];
  return {
    interpretation: 'data_only', automatic_execution: false,
    working_directory: 'One caller-selected workspace; choose fresh cli and experiment directories.',
    prerequisites: ['Git', 'Python matching the selected recipe requirements'],
    catalog: { url: catalogURL, save_as: './pinned-catalog.json', method: 'GET',
      expected_hub_commit: commit, expected_record_version: row.record_version,
      expected_source_commit: row.source_commit },
    bootstrap_argv: [
      ['git', 'clone', '--filter=blob:none', '--sparse', '--no-checkout', REPO, './robot-skill-hub-cli'],
      ['git', '-C', './robot-skill-hub-cli', 'sparse-checkout', 'set', '--no-cone', '/skills/find-robot-skills/'],
      ['git', '-C', './robot-skill-hub-cli', 'checkout', '--detach', commit]
    ],
    plan_argv: [...prefix, '--plan', '--json'],
    prepare_argv: [...prefix, '--install-deps', '--json'],
    prepare_effects: 'Downloads pinned source and creates a project environment; dependency installation may execute package build hooks. Use within the authorized task.',
    execute: { argv_from: 'prepare.next_command', cwd_from: 'prepare.next_command_cwd',
      timeout_seconds: record.completion?.timeout_seconds ?? null,
      success_condition: record.completion?.success_condition ?? null,
      input: record.invocation?.inputs ?? null,
      input_override: record.interface ? 'Replace --example with --input /ABSOLUTE_PATH/task.json after validating record.interface.' : 'Use the invocation contract.',
      result_check: 'Read the returned JSON and named checks; a prepared environment is not task completion.' },
    reuse: { recall_argv: ['python', './robot-skill-hub-cli/skills/find-robot-skills/scripts/rsh.py', 'recall', row.id, '--project', './experiment', '--json'],
      save_scope: 'Save a useful finding actually observed during the task. Existing project sharing permission is required for public delivery.',
      guide_url: HUB + '/community.md' }
  };
}
