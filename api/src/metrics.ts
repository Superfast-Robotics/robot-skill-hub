/** Aggregate access measurements. No query text, IP address or raw client ID is stored. */
export interface Statement {
  bind(...values: unknown[]): Statement;
  run(): Promise<unknown>;
  all<T = Record<string, unknown>>(): Promise<{ results: T[] }>;
}
export interface MetricsEnv {
  METRICS?: { prepare(sql: string): Statement };
  METRICS_KEY?: string;
  METRICS_TEST_KEY?: string;
  CAMPAIGN_STARTED_AT?: string;
}
export interface Background { waitUntil(promise: Promise<unknown>): void }
const TARGET_AGENT_ACCESSES = 10000;
const CHANNELS = new Set(['task-planning', 'task-kinematics', 'task-trajectory', 'ros-mcp-example', 'rai-example', 'hf-space', 'problem-case', 'agent-pilot']);
export type MeasurementWindow = 'launch' | '7d' | 'retained';

export function accessFamily(request: Request, mcpTool = false): string | null {
  if (request.headers.get('DNT') === '1' || request.headers.get('X-RSH-Telemetry') === 'off') return null;
  const ua = request.headers.get('User-Agent') || '';
  if (/bot|crawler|spider|slurp/i.test(ua) && !/robot-skill-hub/i.test(ua)) return 'crawler';
  if (mcpTool) return 'mcp_tool';
  if (/^robot-skill-hub\//i.test(ua)) return 'rsh_cli';
  if (/\b(codex|claude-code|claudecode|chatgpt|openai-agents|cursor|aider|opencode)\b/i.test(ua)) return 'recognized_agent';
  return 'unclassified';
}

export async function recordAccess(request: Request, env: MetricsEnv, route: string, mcpTool = false, now = Date.now()): Promise<void> {
  const family = accessFamily(request, mcpTool);
  if (!family || !env.METRICS || !env.METRICS_KEY) return;
  if (env.METRICS_TEST_KEY && request.headers.get('X-RSH-Test-Key') === env.METRICS_TEST_KEY) return;
  // IDs are optional random installation IDs. Never fall back to an IP fingerprint.
  const client = request.headers.get('X-RSH-Client');
  let clientHash: string | null = null;
  if (client && /^[A-Za-z0-9_-]{8,80}$/.test(client)) {
    const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(env.METRICS_KEY), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const bytes = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(new Date(now).toISOString().slice(0, 10) + '\0' + client));
    clientHash = Array.from(new Uint8Array(bytes), x => x.toString(16).padStart(2, '0')).join('');
  }
  const proposedChannel = request.headers.get('X-RSH-Channel') || '';
  const channel = CHANNELS.has(proposedChannel) ? proposedChannel : null;
  await env.METRICS.prepare('INSERT INTO agent_access (ts, route, family, client_hash, channel) VALUES (?, ?, ?, ?, ?)')
    .bind(Math.floor(now / 1000), route, family, clientHash, channel).run();
}

export function measure(request: Request, env: MetricsEnv, route: string, ctx?: Background, mcpTool = false): Promise<void> {
  // Analytics failures never fail discovery or change a returned robot-code record.
  const pending = recordAccess(request, env, route, mcpTool).catch(() => undefined);
  if (ctx) { ctx.waitUntil(pending); return Promise.resolve(); }
  return pending;
}

export async function measurementReport(env: MetricsEnv, now = Date.now(), window: MeasurementWindow = 'launch') {
  const configured = Boolean(env.METRICS && env.METRICS_KEY);
  const parsed = Date.parse(env.CAMPAIGN_STARTED_AT || '');
  const launch = Number.isFinite(parsed) ? parsed : now - 86400000;
  const start = window === 'launch' ? launch : Math.max(launch, now - (window === '7d' ? 7 : 30) * 86400000);
  const deadline = window === 'launch' ? start + 86400000 : now;
  const end = Math.min(now, deadline);
  const groups = configured ? (await env.METRICS!.prepare(
    'SELECT family, COUNT(*) AS requests, COUNT(DISTINCT client_hash) AS identified_client_days FROM agent_access WHERE ts >= ? AND ts < ? GROUP BY family')
    .bind(Math.floor(start / 1000), Math.ceil(end / 1000)).all<{ family: string; requests: number; identified_client_days: number }>()).results : [];
  const eligible = new Set(['rsh_cli', 'recognized_agent', 'mcp_tool']);
  const count = groups.filter(row => eligible.has(row.family)).reduce((n, row) => n + Number(row.requests), 0);
  if (window !== 'launch') {
    const channels = configured ? (await env.METRICS!.prepare(
      'SELECT channel, route, family, COUNT(*) AS requests FROM agent_access WHERE ts >= ? AND ts < ? GROUP BY channel, route, family')
      .bind(Math.floor(start / 1000), Math.ceil(end / 1000)).all()).results : [];
    return {
      schema_version: '1', interpretation: 'data_only', measurement_configured: configured,
      observed_at: new Date(now).toISOString(), window_kind: window,
      window_start: new Date(start).toISOString(), window_end: new Date(end).toISOString(),
      retention_days: 30, lifetime_total_available: false,
      observed_agent_accesses: configured ? count : null, groups, channels,
      counting_rule: 'Successful observed API discovery/record reads and MCP tool calls; family and channel are self-reported classifications.',
      limitations: ['Requests are not people, autonomous agents, completed tasks or a same-user conversion funnel.',
        'Direct Pages visits and offline/local preparation or execution are not observed.',
        'Retained totals cover at most 30 days; best-effort recording can drop events.',
        'Historical events have no channel and are never backfilled. Daily client pseudonyms cannot identify returning users across days.'],
      privacy: { raw_ip_stored: false, raw_client_id_stored: false, query_or_conversation_stored: false,
        referral_url_stored: false, channel: 'fixed_allowlist_only', opt_out: 'DNT: 1 or X-RSH-Telemetry: off' }
    };
  }
  return {
    schema_version: '1', interpretation: 'data_only', measurement_configured: configured,
    observed_at: new Date(now).toISOString(), window_start: new Date(start).toISOString(), window_end: new Date(deadline).toISOString(),
    window_closed: now >= deadline, target_agent_accesses: TARGET_AGENT_ACCESSES, observed_agent_accesses: configured ? count : null,
    target_reached: configured && count >= TARGET_AGENT_ACCESSES, groups,
    counting_rule: 'Successful public discovery/record reads from the Hub CLI or recognized agent User-Agent, plus successful MCP tool calls. Health, metrics, protocol handshakes, crawlers, internal tests and telemetry opt-outs do not count toward the target.',
    limitations: ['Client identity is self-reported; CLI use can be initiated by a person. Counts do not prove distinct autonomous agents.',
      'Direct GitHub Pages reads and offline uses are not measured. Anonymous clients have no installation identifier.',
      'Recording is best-effort. Storage failures, including free-tier write limits, can drop accesses; missing events are not estimated or backfilled.',
      'Optional installation IDs are HMAC hashed per UTC day; identified_client_days is not a unique-agent count.'],
    privacy: { raw_ip_stored: false, raw_client_id_stored: false, query_or_conversation_stored: false, retention_days: 30, opt_out: 'DNT: 1 or X-RSH-Telemetry: off' }
  };
}

export async function pruneMeasurements(env: MetricsEnv, now = Date.now()): Promise<void> {
  if (env.METRICS) await env.METRICS.prepare('DELETE FROM agent_access WHERE id IN (SELECT id FROM agent_access WHERE ts < ? ORDER BY ts LIMIT 1000)')
    .bind(Math.floor(now / 1000) - 30 * 86400).run();
}
