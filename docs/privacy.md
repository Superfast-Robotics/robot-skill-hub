# Access measurement and privacy

The public API measures successful discovery and record reads from the Hub CLI or recognized agent User-Agent, and successful read-only MCP tool calls. It reports aggregate counts at https://api.superfastrobotics.com/v1/metrics . Client identities are self-reported: these counts do not prove distinct autonomous agents, and a person can initiate CLI requests.

Health checks, metrics reads, MCP initialization/tool-list handshakes, crawlers, internal verification and opted-out traffic do not count toward the 100-access campaign target. Direct GitHub Pages reads and offline usage are not measured. The campaign window is fixed; it is not reset to hide an unmet target.

The CLI may send a random installation ID to the owned API. Metrics retain only a daily HMAC of that ID, a timestamp, a bounded route name and a client-family label. Raw IPs, raw installation IDs, query strings, user tasks, project files, conversations and credentials are not stored in the metrics database. Aggregate identified client-days are not a unique-agent count. Rows older than 30 days are pruned in bounded hourly batches. The public rate limiter uses a hashed address key separately from measurement data.

Set `RSH_TELEMETRY=off` for CLI opt-out. HTTP clients can send `DNT: 1` or `X-RSH-Telemetry: off`. Reads and offline discovery still work. Measurement failure never blocks discovery or the original task.

Public contributions are separate from access measurements. A supplied finding or new-skill manifest is shared only under its explicit project scope and an allowed-agent token. Do not include private data in a public finding. Local outbox entries and project locks remain in the caller's project.
