use rusqlite::Connection;

pub fn initialize_schema(conn: &Connection) -> rusqlite::Result<()> {
    let _: String = conn.query_row("PRAGMA journal_mode=WAL", [], |r| r.get(0))?;
    conn.execute("PRAGMA foreign_keys=ON", [])?;

    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS nodes (
            id          TEXT PRIMARY KEY,
            content     TEXT NOT NULL,
            summary     TEXT,
            timestamp   REAL NOT NULL,
            session_id  TEXT,
            metadata    TEXT,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS node_embeddings (
            node_id     TEXT PRIMARY KEY REFERENCES nodes(id),
            embedding   BLOB NOT NULL,
            dimension   INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS edges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id   TEXT NOT NULL REFERENCES nodes(id),
            target_id   TEXT NOT NULL REFERENCES nodes(id),
            edge_type   TEXT NOT NULL,
            weight      REAL DEFAULT 1.0,
            metadata    TEXT,
            created_at  REAL NOT NULL,
            UNIQUE(source_id, target_id, edge_type)
        );

        CREATE TABLE IF NOT EXISTS entities (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            entity_type     TEXT,
            first_seen      REAL,
            last_seen       REAL,
            mention_count   INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS entity_node_links (
            entity_id   TEXT NOT NULL REFERENCES entities(id),
            node_id     TEXT NOT NULL REFERENCES nodes(id),
            relation    TEXT,
            PRIMARY KEY (entity_id, node_id)
        );

        CREATE TABLE IF NOT EXISTS consolidation_queue (
            node_id     TEXT NOT NULL REFERENCES nodes(id),
            status      TEXT DEFAULT 'pending',
            enqueued_at REAL NOT NULL,
            retry_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS nodes_fts_map (
            fts_rowid  INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id    TEXT NOT NULL UNIQUE REFERENCES nodes(id)
        );

        CREATE INDEX IF NOT EXISTS idx_edges_source  ON edges(source_id, edge_type);
        CREATE INDEX IF NOT EXISTS idx_edges_target  ON edges(target_id, edge_type);
        CREATE INDEX IF NOT EXISTS idx_edges_type    ON edges(edge_type);
        CREATE INDEX IF NOT EXISTS idx_nodes_ts      ON nodes(timestamp);
        CREATE INDEX IF NOT EXISTS idx_nodes_session ON nodes(session_id);
        CREATE INDEX IF NOT EXISTS idx_queue_status  ON consolidation_queue(status);
        CREATE INDEX IF NOT EXISTS idx_entity_links  ON entity_node_links(node_id);
        ",
    )?;

    // FTS5 virtual table.  Column is named "body" (not "content") because
    // "content" is a reserved FTS5 option keyword.  CJK text is pre-split
    // at insert time so the default unicode61 tokenizer treats each character
    // as a separate token.
    // execute_batch may error with "Execute returned results" on some
    // bundled SQLite builds for virtual tables; use execute instead.
    let _ = conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(body, summary)",
        [],
    );
    // Verify the table exists (in case execute was silently ignored)
    let fts_exists: bool = conn
        .query_row(
            "SELECT COUNT(*) > 0 FROM sqlite_master WHERE type='table' AND name='nodes_fts'",
            [],
            |r| r.get(0),
        )
        .unwrap_or(false);
    if !fts_exists {
        conn.execute_batch(
            "CREATE VIRTUAL TABLE nodes_fts USING fts5(body, summary);",
        )?;
    }

    // --- Migration for existing databases ---
    migrate(conn)?;

    Ok(())
}

fn migrate(conn: &Connection) -> rusqlite::Result<()> {
    // Add retry_count column to consolidation_queue if missing (v0 → v1)
    let _ = conn.execute_batch(
        "ALTER TABLE consolidation_queue ADD COLUMN retry_count INTEGER DEFAULT 0;",
    );

    // Backfill FTS index for nodes that were ingested before FTS was added
    conn.execute_batch(
        "INSERT OR IGNORE INTO nodes_fts_map (node_id)
         SELECT id FROM nodes
         WHERE id NOT IN (SELECT node_id FROM nodes_fts_map);",
    )?;

    // Backfill FTS: find nodes_fts_map entries that have no corresponding FTS row
    let fts_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM nodes_fts", [], |row| row.get(0))
        .unwrap_or(0);
    let map_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM nodes_fts_map", [], |row| row.get(0))
        .unwrap_or(0);

    if map_count > fts_count {
        // Backfill: need CJK-split content.  Since we can't call Rust functions
        // from SQL, we do it row by row.
        let mut sel = conn.prepare(
            "SELECT m.fts_rowid, n.content, COALESCE(n.summary, '')
             FROM nodes_fts_map m
             JOIN nodes n ON n.id = m.node_id
             WHERE m.fts_rowid NOT IN (SELECT rowid FROM nodes_fts)",
        )?;
        let rows: Vec<(i64, String, String)> = sel
            .query_map([], |row| {
                Ok((row.get(0)?, row.get(1)?, row.get(2)?))
            })?
            .filter_map(|r| r.ok())
            .collect();
        drop(sel);

        for (rowid, content, summary) in rows {
            let body = crate::ingest::cjk_split(&content);
            let sum = crate::ingest::cjk_split(&summary);
            conn.execute(
                "INSERT OR IGNORE INTO nodes_fts (rowid, body, summary) VALUES (?1, ?2, ?3)",
                rusqlite::params![rowid, body, sum],
            )?;
        }
    }

    Ok(())
}
