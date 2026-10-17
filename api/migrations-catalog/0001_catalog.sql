-- Separate from access metrics. Documents/FTS are content addressed and reused.
CREATE TABLE catalog_generations (
  hub_commit TEXT PRIMARY KEY,
  manifest_sha256 TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  total_pages INTEGER NOT NULL,
  total_records INTEGER NOT NULL,
  next_page INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE catalog_active (singleton INTEGER PRIMARY KEY CHECK(singleton=1), hub_commit TEXT NOT NULL);
CREATE TABLE catalog_pages (
  hub_commit TEXT NOT NULL REFERENCES catalog_generations(hub_commit) ON DELETE CASCADE,
  page_index INTEGER NOT NULL, sha256 TEXT NOT NULL, records INTEGER NOT NULL,
  PRIMARY KEY(hub_commit,page_index)
);
CREATE TABLE catalog_documents (
  doc_hash TEXT PRIMARY KEY, id TEXT NOT NULL, kind TEXT NOT NULL,
  row_json TEXT NOT NULL, search_text TEXT NOT NULL
);
CREATE TABLE catalog_members (
  hub_commit TEXT NOT NULL REFERENCES catalog_generations(hub_commit) ON DELETE CASCADE,
  id TEXT NOT NULL, doc_hash TEXT NOT NULL REFERENCES catalog_documents(doc_hash),
  PRIMARY KEY(hub_commit,id)
);
CREATE INDEX catalog_members_document ON catalog_members(doc_hash);
CREATE TABLE catalog_combinations (
  doc_hash TEXT NOT NULL REFERENCES catalog_documents(doc_hash) ON DELETE CASCADE,
  runtime TEXT, runtime_version TEXT, robot TEXT, controller TEXT, observation TEXT, os TEXT, python TEXT, architecture TEXT
);
CREATE INDEX catalog_combinations_runtime ON catalog_combinations(runtime,doc_hash);
CREATE INDEX catalog_combinations_runtime_version ON catalog_combinations(runtime_version,doc_hash);
CREATE INDEX catalog_combinations_robot ON catalog_combinations(robot,doc_hash);
CREATE INDEX catalog_combinations_controller ON catalog_combinations(controller,doc_hash);
CREATE INDEX catalog_combinations_observation ON catalog_combinations(observation,doc_hash);
CREATE INDEX catalog_combinations_os ON catalog_combinations(os,doc_hash);
CREATE INDEX catalog_combinations_python ON catalog_combinations(python,doc_hash);
CREATE INDEX catalog_combinations_architecture ON catalog_combinations(architecture,doc_hash);
CREATE INDEX catalog_combinations_document ON catalog_combinations(doc_hash);
CREATE TABLE catalog_labels (doc_hash TEXT NOT NULL REFERENCES catalog_documents(doc_hash) ON DELETE CASCADE, field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(field,value,doc_hash));
CREATE INDEX catalog_labels_document ON catalog_labels(doc_hash);
CREATE TABLE catalog_memory_documents (doc_hash TEXT PRIMARY KEY, memory_id TEXT NOT NULL, skill_id TEXT NOT NULL, record_version TEXT NOT NULL, source_commit TEXT NOT NULL, row_json TEXT NOT NULL);
CREATE INDEX catalog_memory_pins ON catalog_memory_documents(skill_id,record_version,source_commit);
CREATE TABLE catalog_memory_members (
  hub_commit TEXT NOT NULL REFERENCES catalog_generations(hub_commit) ON DELETE CASCADE,
  memory_id TEXT NOT NULL, doc_hash TEXT NOT NULL REFERENCES catalog_memory_documents(doc_hash),
  PRIMARY KEY(hub_commit,memory_id)
);
CREATE INDEX catalog_memory_members_document ON catalog_memory_members(doc_hash);
CREATE VIRTUAL TABLE catalog_fts USING fts5(search_text, content='catalog_documents', content_rowid='rowid', tokenize='unicode61', prefix='2 3 4');
CREATE TRIGGER catalog_document_insert AFTER INSERT ON catalog_documents BEGIN
  INSERT INTO catalog_fts(rowid,search_text) VALUES(new.rowid,new.search_text);
  INSERT INTO catalog_combinations(doc_hash,runtime,runtime_version,robot,controller,observation,os,python,architecture)
    SELECT new.doc_hash,lower(json_extract(value,'$.runtime')),lower(json_extract(value,'$.runtime_version')),lower(json_extract(value,'$.robot')),lower(json_extract(value,'$.controller')),lower(json_extract(value,'$.observation')),lower(json_extract(value,'$.os')),lower(json_extract(value,'$.python')),lower(json_extract(value,'$.architecture')) FROM json_each(new.row_json,'$.compatibility');
  INSERT OR IGNORE INTO catalog_labels(doc_hash,field,value) SELECT new.doc_hash,'robot',lower(value) FROM json_each(new.row_json,'$.robots') WHERE type='text';
  INSERT OR IGNORE INTO catalog_labels(doc_hash,field,value) SELECT new.doc_hash,'runtime',lower(json_extract(new.row_json,'$.runtime')) WHERE json_type(new.row_json,'$.runtime')='text';
  INSERT OR IGNORE INTO catalog_labels(doc_hash,field,value) SELECT new.doc_hash,'runtime',lower(json_extract(new.row_json,'$.framework')) WHERE json_type(new.row_json,'$.framework')='text';
END;
CREATE TRIGGER catalog_document_delete AFTER DELETE ON catalog_documents BEGIN
  INSERT INTO catalog_fts(catalog_fts,rowid,search_text) VALUES('delete',old.rowid,old.search_text);
END;
