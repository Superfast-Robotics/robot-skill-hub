-- An outer INSERT OR IGNORE can suppress CHECK failures in AFTER triggers.
-- Explicit RAISE(ABORT) guards keep the content and accounting transaction atomic.
CREATE TRIGGER community_item_capacity BEFORE INSERT ON community_items
WHEN NOT EXISTS(SELECT 1 FROM community_items WHERE id=NEW.id)
BEGIN
  SELECT CASE WHEN (SELECT bytes+length(CAST(NEW.content_json AS BLOB))>67108864 OR items>=20000 FROM community_storage_budget WHERE singleton=1)
    THEN RAISE(ABORT, 'community_capacity') END;
END;
CREATE TRIGGER community_principal_capacity BEFORE INSERT ON community_principals
WHEN NOT EXISTS(SELECT 1 FROM community_principals WHERE id=NEW.id)
BEGIN
  SELECT CASE WHEN (SELECT principals>=10000 FROM community_storage_budget WHERE singleton=1)
    THEN RAISE(ABORT, 'community_capacity') END;
END;
CREATE TRIGGER community_attestation_capacity BEFORE INSERT ON community_attestations
WHEN NOT EXISTS(SELECT 1 FROM community_attestations WHERE item_id=NEW.item_id AND principal_id=NEW.principal_id)
BEGIN
  SELECT CASE WHEN (SELECT attestations>=100000 FROM community_storage_budget WHERE singleton=1)
    THEN RAISE(ABORT, 'community_capacity') END;
END;
