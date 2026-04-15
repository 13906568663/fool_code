use rusqlite::Connection;

pub fn initialize_schema(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch("PRAGMA journal_mode=WAL;")?;
    conn.execute_batch("PRAGMA foreign_keys=ON;")?;

    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS skills (
            id              TEXT PRIMARY KEY,
            display_name    TEXT NOT NULL,
            description     TEXT NOT NULL,
            category        TEXT,
            body_path       TEXT,
            body_hash       TEXT,
            pinned          INTEGER DEFAULT 0,
            enabled         INTEGER DEFAULT 1,
            trigger_terms   TEXT,
            metadata        TEXT,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS skill_embeddings (
            skill_id        TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            source_type     TEXT NOT NULL,
            embedding       BLOB NOT NULL,
            dimension       INTEGER NOT NULL,
            PRIMARY KEY (skill_id, source_type)
        );

        CREATE TABLE IF NOT EXISTS skill_edges (
            source_id       TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            target_id       TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            edge_type       TEXT NOT NULL,
            weight          REAL DEFAULT 1.0,
            metadata        TEXT,
            created_at      REAL NOT NULL,
            UNIQUE(source_id, target_id, edge_type)
        );

        CREATE TABLE IF NOT EXISTS skill_entities (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            entity_type     TEXT NOT NULL,
            skill_count     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS skill_entity_links (
            entity_id       TEXT NOT NULL REFERENCES skill_entities(id) ON DELETE CASCADE,
            skill_id        TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            relation        TEXT,
            PRIMARY KEY (entity_id, skill_id)
        );

        CREATE TABLE IF NOT EXISTS skill_usage (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id        TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            session_id      TEXT,
            query_text      TEXT,
            was_helpful     INTEGER DEFAULT -1,
            used_at         REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS skill_consolidation_queue (
            skill_id        TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            status          TEXT DEFAULT 'pending',
            enqueued_at     REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_skills_category     ON skills(category);
        CREATE INDEX IF NOT EXISTS idx_skills_pinned       ON skills(pinned);
        CREATE INDEX IF NOT EXISTS idx_skills_enabled      ON skills(enabled);
        CREATE INDEX IF NOT EXISTS idx_skill_edges_src     ON skill_edges(source_id, edge_type);
        CREATE INDEX IF NOT EXISTS idx_skill_edges_tgt     ON skill_edges(target_id, edge_type);
        CREATE INDEX IF NOT EXISTS idx_usage_skill         ON skill_usage(skill_id, used_at);
        CREATE INDEX IF NOT EXISTS idx_usage_time          ON skill_usage(used_at);
        CREATE INDEX IF NOT EXISTS idx_entity_links_skill  ON skill_entity_links(skill_id);
        CREATE INDEX IF NOT EXISTS idx_consolidation_st    ON skill_consolidation_queue(status);
        ",
    )?;

    // FTS5 virtual table for full-text keyword search (BM25 ranking).
    // content-sync mode keeps it in lockstep with the `skills` table.
    // unicode61 tokenizer handles Latin + CJK reasonably; Python-side
    // pre-tokenization with jieba can be added later for better CJK recall.
    initialize_fts5(conn)?;

    Ok(())
}

fn initialize_fts5(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch(
        "
        CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
            id,
            display_name,
            description,
            trigger_terms,
            content='skills',
            content_rowid='rowid',
            tokenize='unicode61'
        );
        ",
    )?;

    // Sync triggers: INSERT / UPDATE / DELETE on `skills` → mirror to `skills_fts`
    conn.execute_batch(
        "
        CREATE TRIGGER IF NOT EXISTS skills_fts_insert AFTER INSERT ON skills BEGIN
            INSERT INTO skills_fts(rowid, id, display_name, description, trigger_terms)
            VALUES (new.rowid, new.id, new.display_name, new.description, new.trigger_terms);
        END;

        CREATE TRIGGER IF NOT EXISTS skills_fts_delete AFTER DELETE ON skills BEGIN
            INSERT INTO skills_fts(skills_fts, rowid, id, display_name, description, trigger_terms)
            VALUES ('delete', old.rowid, old.id, old.display_name, old.description, old.trigger_terms);
        END;

        CREATE TRIGGER IF NOT EXISTS skills_fts_update AFTER UPDATE ON skills BEGIN
            INSERT INTO skills_fts(skills_fts, rowid, id, display_name, description, trigger_terms)
            VALUES ('delete', old.rowid, old.id, old.display_name, old.description, old.trigger_terms);
            INSERT INTO skills_fts(rowid, id, display_name, description, trigger_terms)
            VALUES (new.rowid, new.id, new.display_name, new.description, new.trigger_terms);
        END;
        ",
    )?;

    // Back-fill FTS index for any existing skills that aren't indexed yet.
    // `INSERT OR IGNORE` on FTS5 doesn't exist, so we rebuild on first run.
    let count: i64 = conn.query_row(
        "SELECT count(*) FROM skills_fts",
        [],
        |row| row.get(0),
    ).unwrap_or(0);

    let skill_count: i64 = conn.query_row(
        "SELECT count(*) FROM skills",
        [],
        |row| row.get(0),
    ).unwrap_or(0);

    if count == 0 && skill_count > 0 {
        conn.execute_batch(
            "INSERT INTO skills_fts(rowid, id, display_name, description, trigger_terms)
             SELECT rowid, id, display_name, description, trigger_terms FROM skills;",
        )?;
    }

    Ok(())
}
