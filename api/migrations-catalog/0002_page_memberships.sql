-- Additive rollout: the old Worker can still read/write legacy memberships
-- before the new Worker is deployed. Existing receipts remain legacy (NULL).
CREATE TABLE catalog_page_groups (
  group_hash TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('search','memory')),
  records INTEGER NOT NULL CHECK(records BETWEEN 1 AND 100)
);
CREATE TABLE catalog_page_members (
  group_hash TEXT NOT NULL REFERENCES catalog_page_groups(group_hash) ON DELETE CASCADE,
  id TEXT NOT NULL,
  doc_hash TEXT NOT NULL REFERENCES catalog_documents(doc_hash),
  PRIMARY KEY(group_hash,id)
);
CREATE INDEX catalog_page_members_document ON catalog_page_members(doc_hash);
CREATE TABLE catalog_memory_page_members (
  group_hash TEXT NOT NULL REFERENCES catalog_page_groups(group_hash) ON DELETE CASCADE,
  memory_id TEXT NOT NULL,
  doc_hash TEXT NOT NULL REFERENCES catalog_memory_documents(doc_hash),
  PRIMARY KEY(group_hash,memory_id)
);
CREATE INDEX catalog_memory_page_members_document ON catalog_memory_page_members(doc_hash);
ALTER TABLE catalog_pages ADD COLUMN group_hash TEXT REFERENCES catalog_page_groups(group_hash);
CREATE INDEX catalog_pages_group ON catalog_pages(group_hash);
-- ALL is deliberate: duplicate identities across pages must remain visible to
-- validation rather than being hidden by SQL set deduplication.
CREATE VIEW catalog_all_members AS
  SELECT hub_commit,id,doc_hash FROM catalog_members
  UNION ALL
  SELECT p.hub_commit,m.id,m.doc_hash FROM catalog_pages p
    JOIN catalog_page_members m ON m.group_hash=p.group_hash;
CREATE VIEW catalog_all_memory_members AS
  SELECT hub_commit,memory_id,doc_hash FROM catalog_memory_members
  UNION ALL
  SELECT p.hub_commit,m.memory_id,m.doc_hash FROM catalog_pages p
    JOIN catalog_memory_page_members m ON m.group_hash=p.group_hash;
