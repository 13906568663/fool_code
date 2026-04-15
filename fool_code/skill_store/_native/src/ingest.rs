use std::time::SystemTime;

use rusqlite::{params, Connection};

use crate::vector::embed_to_bytes;

pub fn upsert_skill(
    conn: &Connection,
    id: &str,
    display_name: &str,
    description: &str,
    category: Option<&str>,
    body_path: Option<&str>,
    body_hash: Option<&str>,
    trigger_terms_json: Option<&str>,
    metadata_json: Option<&str>,
) -> rusqlite::Result<()> {
    let now = sys_now();

    conn.execute(
        "INSERT INTO skills (id, display_name, description, category, body_path, body_hash,
                            trigger_terms, metadata, created_at, updated_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?9)
         ON CONFLICT(id) DO UPDATE SET
             display_name = excluded.display_name,
             description = excluded.description,
             category = excluded.category,
             body_path = excluded.body_path,
             body_hash = excluded.body_hash,
             trigger_terms = excluded.trigger_terms,
             metadata = excluded.metadata,
             updated_at = excluded.updated_at",
        params![
            id,
            display_name,
            description,
            category,
            body_path,
            body_hash,
            trigger_terms_json,
            metadata_json,
            now,
        ],
    )?;
    Ok(())
}

pub fn upsert_embedding(
    conn: &Connection,
    skill_id: &str,
    source_type: &str,
    embedding: &[f32],
) -> rusqlite::Result<()> {
    let blob = embed_to_bytes(embedding);
    conn.execute(
        "INSERT INTO skill_embeddings (skill_id, source_type, embedding, dimension)
         VALUES (?1, ?2, ?3, ?4)
         ON CONFLICT(skill_id, source_type) DO UPDATE SET
             embedding = excluded.embedding,
             dimension = excluded.dimension",
        params![skill_id, source_type, blob, embedding.len() as i64],
    )?;
    Ok(())
}

pub fn upsert_entity(
    conn: &Connection,
    id: &str,
    name: &str,
    entity_type: &str,
) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT INTO skill_entities (id, name, entity_type, skill_count)
         VALUES (?1, ?2, ?3, 1)
         ON CONFLICT(id) DO UPDATE SET
             skill_count = skill_count + 1",
        params![id, name, entity_type],
    )?;
    Ok(())
}

pub fn link_skill_entity(
    conn: &Connection,
    entity_id: &str,
    skill_id: &str,
    relation: Option<&str>,
) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT OR IGNORE INTO skill_entity_links (entity_id, skill_id, relation)
         VALUES (?1, ?2, ?3)",
        params![entity_id, skill_id, relation],
    )?;
    Ok(())
}

pub fn add_edge(
    conn: &Connection,
    source_id: &str,
    target_id: &str,
    edge_type: &str,
    weight: f64,
    metadata: Option<&str>,
) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT OR IGNORE INTO skill_edges (source_id, target_id, edge_type, weight, metadata, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![source_id, target_id, edge_type, weight, metadata, sys_now()],
    )?;
    Ok(())
}

pub fn add_edges_batch(conn: &Connection, edges_json: &str) -> rusqlite::Result<usize> {
    let edges: Vec<serde_json::Value> = serde_json::from_str(edges_json).unwrap_or_default();
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

pub fn enqueue_consolidation(conn: &Connection, skill_id: &str) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT INTO skill_consolidation_queue (skill_id, status, enqueued_at)
         VALUES (?1, 'pending', ?2)",
        params![skill_id, sys_now()],
    )?;
    Ok(())
}

pub fn pending_consolidation(conn: &Connection, limit: usize) -> rusqlite::Result<Vec<String>> {
    let mut stmt = conn.prepare(
        "SELECT skill_id FROM skill_consolidation_queue WHERE status = 'pending'
         ORDER BY enqueued_at ASC LIMIT ?1",
    )?;
    let rows = stmt.query_map(params![limit as i64], |row| row.get::<_, String>(0))?;
    let mut ids = Vec::new();
    for r in rows {
        ids.push(r?);
    }
    Ok(ids)
}

pub fn mark_consolidated(conn: &Connection, skill_id: &str) -> rusqlite::Result<()> {
    conn.execute(
        "UPDATE skill_consolidation_queue SET status = 'done' WHERE skill_id = ?1",
        params![skill_id],
    )?;
    Ok(())
}

pub fn delete_skill(conn: &Connection, skill_id: &str) -> rusqlite::Result<bool> {
    let changed = conn.execute("DELETE FROM skills WHERE id = ?1", params![skill_id])?;
    Ok(changed > 0)
}

pub fn clear_entity_links_for_skill(conn: &Connection, skill_id: &str) -> rusqlite::Result<()> {
    conn.execute(
        "DELETE FROM skill_entity_links WHERE skill_id = ?1",
        params![skill_id],
    )?;
    Ok(())
}

fn sys_now() -> f64 {
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}
