use std::time::SystemTime;

use rusqlite::{params, Connection};

use crate::vector::{bytes_to_embed, cosine_similarity, embed_to_bytes};

const SEMANTIC_SIM_THRESHOLD: f32 = 0.25;

/// Insert spaces around CJK ideographs so the unicode61 tokenizer treats
/// each character as a separate token.  ASCII words are left intact.
pub fn cjk_split(text: &str) -> String {
    let mut out = String::with_capacity(text.len() * 2);
    for ch in text.chars() {
        if is_cjk(ch) {
            out.push(' ');
            out.push(ch);
            out.push(' ');
        } else {
            out.push(ch);
        }
    }
    out
}

fn is_cjk(ch: char) -> bool {
    matches!(ch,
        '\u{4E00}'..='\u{9FFF}'   // CJK Unified Ideographs
        | '\u{3400}'..='\u{4DBF}' // CJK Unified Ideographs Extension A
        | '\u{F900}'..='\u{FAFF}' // CJK Compatibility Ideographs
    )
}
const SEMANTIC_TOP_K: usize = 5;

/// Fast-path: ingest a new event node, create temporal + semantic edges,
/// sync to FTS5, and enqueue for slow-path consolidation.  Returns the new
/// node id.
pub fn ingest_event(
    conn: &Connection,
    content: &str,
    summary: &str,
    timestamp: f64,
    embedding: &[f32],
    session_id: &str,
    metadata_json: &str,
) -> rusqlite::Result<String> {
    let node_id = uuid::Uuid::new_v4().to_string();
    let now = sys_now();

    conn.execute(
        "INSERT INTO nodes (id, content, summary, timestamp, session_id, metadata, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![node_id, content, summary, timestamp, session_id, metadata_json, now],
    )?;

    let blob = embed_to_bytes(embedding);
    conn.execute(
        "INSERT INTO node_embeddings (node_id, embedding, dimension)
         VALUES (?1, ?2, ?3)",
        params![node_id, blob, embedding.len() as i64],
    )?;

    // --- Temporal edges ---
    // Primary: link to previous node in the SAME session
    let prev_session: Option<String> = conn
        .query_row(
            "SELECT id FROM nodes WHERE session_id = ?2 AND id != ?1
             ORDER BY timestamp DESC, created_at DESC LIMIT 1",
            params![node_id, session_id],
            |row| row.get(0),
        )
        .ok();

    if let Some(ref prev_id) = prev_session {
        add_edge(conn, prev_id, &node_id, "temporal", 1.0, None)?;
    }

    // Secondary: weak cross-session temporal link to the globally most recent node
    let prev_global: Option<String> = conn
        .query_row(
            "SELECT id FROM nodes WHERE id != ?1 ORDER BY timestamp DESC, created_at DESC LIMIT 1",
            params![node_id],
            |row| row.get(0),
        )
        .ok();

    if let Some(ref gid) = prev_global {
        // Only add if it differs from the session-local link
        let dominated = prev_session.as_ref().map_or(false, |s| s == gid);
        if !dominated {
            add_edge(conn, gid, &node_id, "temporal", 0.3, Some("cross_session"))?;
        }
    }

    // --- Semantic edges ---
    let neighbors = brute_force_top_k(conn, embedding, SEMANTIC_TOP_K, &node_id)?;
    for (nid, sim) in &neighbors {
        if *sim >= SEMANTIC_SIM_THRESHOLD {
            add_edge(conn, &node_id, nid, "semantic", *sim as f64, None)?;
            add_edge(conn, nid, &node_id, "semantic", *sim as f64, None)?;
        }
    }

    // --- FTS5 sync (CJK character-splitting for unicode61 tokenizer) ---
    let fts_body = cjk_split(content);
    let fts_summary = cjk_split(summary);
    conn.execute(
        "INSERT INTO nodes_fts_map (node_id) VALUES (?1)",
        params![node_id],
    )?;
    let fts_rowid: i64 = conn.last_insert_rowid();
    conn.execute(
        "INSERT INTO nodes_fts (rowid, body, summary) VALUES (?1, ?2, ?3)",
        params![fts_rowid, fts_body, fts_summary],
    )?;

    // --- Enqueue for slow-path consolidation ---
    conn.execute(
        "INSERT INTO consolidation_queue (node_id, status, enqueued_at, retry_count)
         VALUES (?1, 'pending', ?2, 0)",
        params![node_id, now],
    )?;

    Ok(node_id)
}

/// Insert a single directed edge, ignoring duplicates.
pub fn add_edge(
    conn: &Connection,
    source: &str,
    target: &str,
    edge_type: &str,
    weight: f64,
    metadata: Option<&str>,
) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight, metadata, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![source, target, edge_type, weight, metadata, sys_now()],
    )?;
    Ok(())
}

/// Batch-insert edges from a JSON array.
pub fn add_edges_batch(conn: &Connection, edges_json: &str) -> rusqlite::Result<usize> {
    let edges: Vec<serde_json::Value> =
        serde_json::from_str(edges_json).unwrap_or_default();
    let mut count = 0usize;
    for e in &edges {
        let src = e["source_id"].as_str().unwrap_or_default();
        let tgt = e["target_id"].as_str().unwrap_or_default();
        let etype = e["edge_type"].as_str().unwrap_or_default();
        let w = e["weight"].as_f64().unwrap_or(1.0);
        let meta = e.get("metadata").and_then(|v| v.as_str());
        if !src.is_empty() && !tgt.is_empty() && !etype.is_empty() {
            add_edge(conn, src, tgt, etype, w, meta)?;
            count += 1;
        }
    }
    Ok(count)
}

/// Upsert an abstract entity node.
pub fn upsert_entity(
    conn: &Connection,
    id: &str,
    name: &str,
    entity_type: &str,
) -> rusqlite::Result<()> {
    let now = sys_now();
    conn.execute(
        "INSERT INTO entities (id, name, entity_type, first_seen, last_seen, mention_count)
         VALUES (?1, ?2, ?3, ?4, ?4, 1)
         ON CONFLICT(id) DO UPDATE SET
             last_seen = ?4,
             mention_count = mention_count + 1",
        params![id, name, entity_type, now],
    )?;
    Ok(())
}

/// Link an entity to a node.
pub fn link_entity_node(
    conn: &Connection,
    entity_id: &str,
    node_id: &str,
    relation: Option<&str>,
) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT OR IGNORE INTO entity_node_links (entity_id, node_id, relation)
         VALUES (?1, ?2, ?3)",
        params![entity_id, node_id, relation],
    )?;
    Ok(())
}

/// Return node IDs pending consolidation (retry_count < max_retries).
pub fn pending_consolidation(conn: &Connection, limit: usize) -> rusqlite::Result<Vec<String>> {
    let mut stmt = conn.prepare(
        "SELECT node_id FROM consolidation_queue
         WHERE status = 'pending' AND retry_count < 3
         ORDER BY enqueued_at ASC LIMIT ?1",
    )?;
    let rows = stmt.query_map(params![limit as i64], |row| row.get::<_, String>(0))?;
    let mut ids = Vec::new();
    for r in rows {
        ids.push(r?);
    }
    Ok(ids)
}

/// Mark a node as consolidated (done).
pub fn mark_consolidated(conn: &Connection, node_id: &str) -> rusqlite::Result<()> {
    conn.execute(
        "UPDATE consolidation_queue SET status = 'done' WHERE node_id = ?1",
        params![node_id],
    )?;
    Ok(())
}

/// Increment the retry counter for a node that failed consolidation.
/// If retry_count reaches 3, the status is automatically set to 'done'.
pub fn increment_retry(conn: &Connection, node_id: &str) -> rusqlite::Result<()> {
    conn.execute(
        "UPDATE consolidation_queue
         SET retry_count = retry_count + 1,
             status = CASE WHEN retry_count + 1 >= 3 THEN 'done' ELSE status END
         WHERE node_id = ?1",
        params![node_id],
    )?;
    Ok(())
}

// ---- Meta table helpers -------------------------------------------------------

pub fn get_meta(conn: &Connection, key: &str) -> rusqlite::Result<Option<String>> {
    conn.query_row(
        "SELECT value FROM meta WHERE key = ?1",
        params![key],
        |row| row.get(0),
    )
    .optional_result()
}

pub fn set_meta(conn: &Connection, key: &str, value: &str) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?1, ?2)
         ON CONFLICT(key) DO UPDATE SET value = ?2",
        params![key, value],
    )?;
    Ok(())
}

// ---- internal helpers -------------------------------------------------------

fn brute_force_top_k(
    conn: &Connection,
    query: &[f32],
    k: usize,
    exclude_id: &str,
) -> rusqlite::Result<Vec<(String, f32)>> {
    let mut stmt =
        conn.prepare("SELECT node_id, embedding FROM node_embeddings WHERE node_id != ?1")?;
    let rows = stmt.query_map(params![exclude_id], |row| {
        let nid: String = row.get(0)?;
        let blob: Vec<u8> = row.get(1)?;
        Ok((nid, blob))
    })?;

    let mut scored: Vec<(String, f32)> = Vec::new();
    for r in rows {
        let (nid, blob) = r?;
        let emb = bytes_to_embed(&blob);
        let sim = cosine_similarity(query, &emb);
        scored.push((nid, sim));
    }

    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    scored.truncate(k);
    Ok(scored)
}

fn sys_now() -> f64 {
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

trait OptionalResult<T> {
    fn optional_result(self) -> rusqlite::Result<Option<T>>;
}

impl<T> OptionalResult<T> for rusqlite::Result<T> {
    fn optional_result(self) -> rusqlite::Result<Option<T>> {
        match self {
            Ok(v) => Ok(Some(v)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e),
        }
    }
}
