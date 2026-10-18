-- Immutable, contributor-reported experience. Never part of the trusted code catalog.
CREATE TABLE community_principals (
  id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, day TEXT NOT NULL,
  ip_day_hash TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX community_principals_day ON community_principals(day, ip_day_hash);
CREATE TABLE community_items (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
  skill_id TEXT NOT NULL, record_version TEXT NOT NULL, source_commit TEXT NOT NULL,
  kind TEXT NOT NULL, parent_id TEXT REFERENCES community_items(id),
  environment_json TEXT NOT NULL, content_json TEXT NOT NULL, content_sha256 TEXT NOT NULL,
  created_at INTEGER NOT NULL, hidden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX community_items_scope ON community_items(skill_id, record_version, source_commit, seq);
CREATE INDEX community_items_parent ON community_items(parent_id, seq);
CREATE TABLE community_attestations (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL REFERENCES community_items(id),
  principal_id TEXT NOT NULL REFERENCES community_principals(id), day TEXT NOT NULL,
  created_at INTEGER NOT NULL, UNIQUE(item_id, principal_id)
);
CREATE INDEX community_attestations_day ON community_attestations(day, principal_id);
CREATE TABLE community_storage_budget (singleton INTEGER PRIMARY KEY CHECK(singleton=1), bytes INTEGER NOT NULL CHECK(bytes<=67108864), items INTEGER NOT NULL CHECK(items<=20000), principals INTEGER NOT NULL CHECK(principals<=10000), attestations INTEGER NOT NULL CHECK(attestations<=100000));
INSERT INTO community_storage_budget VALUES(1,0,0,0,0);
CREATE TRIGGER community_storage_account AFTER INSERT ON community_items
BEGIN
  UPDATE community_storage_budget SET bytes=bytes+length(CAST(NEW.content_json AS BLOB)),items=items+1 WHERE singleton=1;
END;
CREATE TRIGGER community_principal_account AFTER INSERT ON community_principals
BEGIN
  UPDATE community_storage_budget SET principals=principals+1 WHERE singleton=1;
END;
CREATE TRIGGER community_attestation_account AFTER INSERT ON community_attestations
BEGIN
  UPDATE community_storage_budget SET attestations=attestations+1 WHERE singleton=1;
END;
CREATE TRIGGER community_registration_budget BEFORE INSERT ON community_principals
WHEN NOT EXISTS(SELECT 1 FROM community_principals WHERE id=NEW.id)
BEGIN
  SELECT CASE WHEN (SELECT count(*) FROM community_principals WHERE day=NEW.day)>=100
    OR (SELECT count(*) FROM community_principals WHERE day=NEW.day AND ip_day_hash=NEW.ip_day_hash)>=5
    THEN RAISE(ABORT, 'community_registration_quota') END;
END;
CREATE TRIGGER community_write_budget BEFORE INSERT ON community_attestations
WHEN NOT EXISTS(SELECT 1 FROM community_attestations WHERE item_id=NEW.item_id AND principal_id=NEW.principal_id)
BEGIN
  SELECT CASE WHEN (SELECT count(*) FROM community_attestations WHERE day=NEW.day)>=1000
    OR (SELECT count(*) FROM community_attestations WHERE day=NEW.day AND principal_id=NEW.principal_id)>=20
    THEN RAISE(ABORT, 'community_write_quota') END;
END;
