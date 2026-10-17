# Launch measurement operations

The fixed launch window is **2026-10-17 15:47:38 UTC through 2026-10-18 15:47:38 UTC**, with a target of 100 eligible API accesses. Neither monitoring nor deployment resets this window.

Read the current counter at `https://api.superfastrobotics.com/v1/metrics`. It counts successful discovery/record reads from the Hub CLI or a recognized agent User-Agent, plus successful MCP tool calls. Health, metrics, protocol handshakes, crawlers, internal tests and telemetry opt-outs do not count. Client identity is self-reported: these counters cannot establish 100 distinct autonomous agents. Direct Pages, GitHub and offline use are outside this counter.

Preserve a local observation:

```sh
python tools/monitor_campaign.py --external
```

The monitor reads health, metrics and the publication version manifest. `--external` also reads the existing community PR and Commons post status. It sends `DNT: 1` and `X-RSH-Telemetry: off`; it never searches the catalog, calls MCP tools, executes robot code or creates visits. Missing or inconsistent measurements remain `null`.

Timestamped JSON snapshots and `latest.json` are written to `.local/campaign-monitor/`. Use `--output DIR` for another location. `--watch --interval 300` keeps observing until the fixed deadline and can be stopped with Ctrl-C.

The `Observe fixed launch campaign` GitHub Actions workflow runs hourly and can be dispatched manually from `main`. Observations are retained as artifacts for seven days. After the deadline, a separate job disables this workflow using its job-scoped Actions permission. It cannot write repository content. GitHub may delay scheduled runs, so the last observation can occur after the deadline; the API still counts only the fixed window.
