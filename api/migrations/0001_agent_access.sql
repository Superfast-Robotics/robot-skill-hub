CREATE TABLE IF NOT EXISTS agent_access (
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  route TEXT NOT NULL CHECK (route IN ('search', 'inspect', 'catalog', 'references', 'mcp')),
  family TEXT NOT NULL CHECK (family IN ('rsh_cli', 'recognized_agent', 'mcp_tool', 'crawler', 'unclassified')),
  client_hash TEXT
);
CREATE INDEX IF NOT EXISTS agent_access_ts ON agent_access (ts);
