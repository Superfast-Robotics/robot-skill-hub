-- Fixed public distribution labels only; no referral URLs or personal data.
ALTER TABLE agent_access ADD COLUMN channel TEXT CHECK (channel IS NULL OR channel IN (
  'task-planning', 'task-kinematics', 'task-trajectory', 'ros-mcp-example',
  'rai-example', 'hf-space', 'problem-case', 'agent-pilot'
));
