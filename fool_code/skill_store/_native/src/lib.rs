use std::sync::Mutex;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use rusqlite::{params, Connection};

mod ingest;
mod query;
mod schema;
mod vector;

/// Skill Store backed by SQLite — manages skill metadata, embeddings, and relationships.
#[pyclass]
struct SkillStore {
    conn: Mutex<Connection>,
}

fn to_pyerr(e: rusqlite::Error) -> PyErr {
    PyRuntimeError::new_err(format!("skill store db error: {e}"))
}

#[pymethods]
impl SkillStore {
    #[new]
    fn new(db_path: &str) -> PyResult<Self> {
        if let Some(parent) = std::path::Path::new(db_path).parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                PyRuntimeError::new_err(format!("cannot create data dir: {e}"))
            })?;
        }

        let conn = Connection::open(db_path).map_err(to_pyerr)?;
        schema::initialize_schema(&conn).map_err(to_pyerr)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    fn close(&self) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")
            .map_err(to_pyerr)?;
        Ok(())
    }

    // ===== Ingest =====

    #[pyo3(signature = (id, display_name, description, category=None, body_path=None, body_hash=None, trigger_terms_json=None, metadata_json=None))]
    fn upsert_skill(
        &self,
        id: &str,
        display_name: &str,
        description: &str,
        category: Option<&str>,
        body_path: Option<&str>,
        body_hash: Option<&str>,
        trigger_terms_json: Option<&str>,
        metadata_json: Option<&str>,
    ) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::upsert_skill(
            &conn,
            id,
            display_name,
            description,
            category,
            body_path,
            body_hash,
            trigger_terms_json,
            metadata_json,
        )
        .map_err(to_pyerr)
    }

    fn upsert_embedding(
        &self,
        skill_id: &str,
        source_type: &str,
        embedding: Vec<f32>,
    ) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::upsert_embedding(&conn, skill_id, source_type, &embedding).map_err(to_pyerr)
    }

    fn upsert_entity(&self, id: &str, name: &str, entity_type: &str) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::upsert_entity(&conn, id, name, entity_type).map_err(to_pyerr)
    }

    #[pyo3(signature = (entity_id, skill_id, relation=None))]
    fn link_skill_entity(
        &self,
        entity_id: &str,
        skill_id: &str,
        relation: Option<&str>,
    ) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::link_skill_entity(&conn, entity_id, skill_id, relation).map_err(to_pyerr)
    }

    fn add_edges(&self, edges_json: &str) -> PyResult<usize> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::add_edges_batch(&conn, edges_json).map_err(to_pyerr)
    }

    fn enqueue_consolidation(&self, skill_id: &str) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::enqueue_consolidation(&conn, skill_id).map_err(to_pyerr)
    }

    #[pyo3(signature = (limit=5))]
    fn pending_consolidation(&self, limit: usize) -> PyResult<Vec<String>> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::pending_consolidation(&conn, limit).map_err(to_pyerr)
    }

    fn mark_consolidated(&self, skill_id: &str) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::mark_consolidated(&conn, skill_id).map_err(to_pyerr)
    }

    fn delete_skill(&self, skill_id: &str) -> PyResult<bool> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::delete_skill(&conn, skill_id).map_err(to_pyerr)
    }

    fn clear_entity_links_for_skill(&self, skill_id: &str) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::clear_entity_links_for_skill(&conn, skill_id).map_err(to_pyerr)
    }

    // ===== Query =====

    #[pyo3(signature = (query_embedding, keywords=vec![], top_k=8, rrf_k=60))]
    fn find_anchors(
        &self,
        query_embedding: Vec<f32>,
        keywords: Vec<String>,
        top_k: usize,
        rrf_k: u32,
    ) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let results =
            query::find_anchors(&conn, &query_embedding, &keywords, top_k, rrf_k)
                .map_err(to_pyerr)?;
        serde_json::to_string(&results)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    #[pyo3(signature = (anchor_ids, intent_weights_json, query_embedding, lambda1=1.0, lambda2=0.5, max_depth=2, beam_width=5, budget=15, decay=0.85))]
    fn traverse(
        &self,
        anchor_ids: Vec<String>,
        intent_weights_json: &str,
        query_embedding: Vec<f32>,
        lambda1: f64,
        lambda2: f64,
        max_depth: usize,
        beam_width: usize,
        budget: usize,
        decay: f64,
    ) -> PyResult<String> {
        let weights: query::IntentWeights =
            serde_json::from_str(intent_weights_json).map_err(|e| {
                PyRuntimeError::new_err(format!("invalid intent_weights JSON: {e}"))
            })?;
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let results = query::traverse(
            &conn,
            &anchor_ids,
            &weights,
            &query_embedding,
            lambda1,
            lambda2,
            max_depth,
            beam_width,
            budget,
            decay,
        )
        .map_err(to_pyerr)?;
        serde_json::to_string(&results)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    // ===== CRUD helpers =====

    fn set_enabled(&self, skill_id: &str, enabled: bool) -> PyResult<bool> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let val: i64 = if enabled { 1 } else { 0 };
        let changed = conn
            .execute(
                "UPDATE skills SET enabled = ?1 WHERE id = ?2",
                params![val, skill_id],
            )
            .map_err(to_pyerr)?;
        Ok(changed > 0)
    }

    fn set_pinned(&self, skill_id: &str, pinned: bool) -> PyResult<bool> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let val: i64 = if pinned { 1 } else { 0 };
        let changed = conn
            .execute(
                "UPDATE skills SET pinned = ?1 WHERE id = ?2",
                params![val, skill_id],
            )
            .map_err(to_pyerr)?;
        Ok(changed > 0)
    }

    #[pyo3(signature = (skill_id, display_name=None, description=None, category=None, trigger_terms_json=None))]
    fn update_metadata(
        &self,
        skill_id: &str,
        display_name: Option<&str>,
        description: Option<&str>,
        category: Option<&str>,
        trigger_terms_json: Option<&str>,
    ) -> PyResult<bool> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::SystemTime::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);

        let mut sets: Vec<String> = vec!["updated_at = ?1".to_string()];
        let mut idx = 2u32;

        macro_rules! maybe_set {
            ($field:expr, $col:expr) => {
                if $field.is_some() {
                    sets.push(format!("{} = ?{}", $col, idx));
                    idx += 1;
                }
            };
        }
        maybe_set!(display_name, "display_name");
        maybe_set!(description, "description");
        maybe_set!(category, "category");
        maybe_set!(trigger_terms_json, "trigger_terms");

        let sql = format!(
            "UPDATE skills SET {} WHERE id = ?{}",
            sets.join(", "),
            idx
        );
        let mut stmt = conn.prepare(&sql).map_err(to_pyerr)?;

        let mut param_idx = 1;
        stmt.raw_bind_parameter(param_idx, now).map_err(to_pyerr)?;
        param_idx += 1;

        if let Some(v) = display_name {
            stmt.raw_bind_parameter(param_idx, v).map_err(to_pyerr)?;
            param_idx += 1;
        }
        if let Some(v) = description {
            stmt.raw_bind_parameter(param_idx, v).map_err(to_pyerr)?;
            param_idx += 1;
        }
        if let Some(v) = category {
            stmt.raw_bind_parameter(param_idx, v).map_err(to_pyerr)?;
            param_idx += 1;
        }
        if let Some(v) = trigger_terms_json {
            stmt.raw_bind_parameter(param_idx, v).map_err(to_pyerr)?;
            param_idx += 1;
        }
        stmt.raw_bind_parameter(param_idx, skill_id).map_err(to_pyerr)?;

        let changed = stmt.raw_execute().map_err(to_pyerr)?;
        Ok(changed > 0)
    }

    fn get_skill(&self, skill_id: &str) -> PyResult<Option<String>> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let result = conn.query_row(
            "SELECT id, display_name, description, category, body_path, body_hash,
                    pinned, enabled, trigger_terms, metadata, created_at, updated_at
             FROM skills WHERE id = ?1",
            params![skill_id],
            |row| {
                Ok(serde_json::json!({
                    "id": row.get::<_, String>(0)?,
                    "display_name": row.get::<_, String>(1)?,
                    "description": row.get::<_, String>(2)?,
                    "category": row.get::<_, Option<String>>(3)?,
                    "body_path": row.get::<_, Option<String>>(4)?,
                    "body_hash": row.get::<_, Option<String>>(5)?,
                    "pinned": row.get::<_, i64>(6)? != 0,
                    "enabled": row.get::<_, i64>(7)? != 0,
                    "trigger_terms": row.get::<_, Option<String>>(8)?,
                    "metadata": row.get::<_, Option<String>>(9)?,
                    "created_at": row.get::<_, f64>(10)?,
                    "updated_at": row.get::<_, f64>(11)?,
                }))
            },
        );
        match result {
            Ok(v) => Ok(Some(v.to_string())),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(to_pyerr(e)),
        }
    }

    #[pyo3(signature = (category=None, enabled=None, pinned=None))]
    fn list_skills(
        &self,
        category: Option<&str>,
        enabled: Option<bool>,
        pinned: Option<bool>,
    ) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;

        let mut conditions: Vec<String> = Vec::new();
        if let Some(c) = category {
            conditions.push(format!("category = '{}'", c.replace('\'', "''")));
        }
        if let Some(e) = enabled {
            conditions.push(format!("enabled = {}", if e { 1 } else { 0 }));
        }
        if let Some(p) = pinned {
            conditions.push(format!("pinned = {}", if p { 1 } else { 0 }));
        }

        let where_clause = if conditions.is_empty() {
            String::new()
        } else {
            format!("WHERE {}", conditions.join(" AND "))
        };

        let sql = format!(
            "SELECT id, display_name, description, category, body_path, body_hash,
                    pinned, enabled, trigger_terms, metadata, created_at, updated_at
             FROM skills {where_clause} ORDER BY pinned DESC, updated_at DESC"
        );

        let mut stmt = conn.prepare(&sql).map_err(to_pyerr)?;
        let rows = stmt
            .query_map([], |row| {
                Ok(serde_json::json!({
                    "id": row.get::<_, String>(0)?,
                    "display_name": row.get::<_, String>(1)?,
                    "description": row.get::<_, String>(2)?,
                    "category": row.get::<_, Option<String>>(3)?,
                    "body_path": row.get::<_, Option<String>>(4)?,
                    "body_hash": row.get::<_, Option<String>>(5)?,
                    "pinned": row.get::<_, i64>(6)? != 0,
                    "enabled": row.get::<_, i64>(7)? != 0,
                    "trigger_terms": row.get::<_, Option<String>>(8)?,
                    "metadata": row.get::<_, Option<String>>(9)?,
                    "created_at": row.get::<_, f64>(10)?,
                    "updated_at": row.get::<_, f64>(11)?,
                }))
            })
            .map_err(to_pyerr)?;

        let mut arr = Vec::new();
        for r in rows {
            arr.push(r.map_err(to_pyerr)?);
        }
        Ok(serde_json::Value::Array(arr).to_string())
    }

    fn get_skill_edges(&self, skill_id: &str) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let mut stmt = conn
            .prepare(
                "SELECT source_id, target_id, edge_type, weight, metadata FROM skill_edges
                 WHERE source_id = ?1 OR target_id = ?1",
            )
            .map_err(to_pyerr)?;
        let rows: Vec<serde_json::Value> = stmt
            .query_map(params![skill_id], |row| {
                Ok(serde_json::json!({
                    "source_id": row.get::<_, String>(0)?,
                    "target_id": row.get::<_, String>(1)?,
                    "edge_type": row.get::<_, String>(2)?,
                    "weight": row.get::<_, f64>(3)?,
                    "metadata": row.get::<_, Option<String>>(4)?,
                }))
            })
            .map_err(to_pyerr)?
            .filter_map(|x| x.ok())
            .collect();
        serde_json::to_string(&rows)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    fn get_all_edges(&self) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let mut stmt = conn
            .prepare("SELECT source_id, target_id, edge_type, weight FROM skill_edges")
            .map_err(to_pyerr)?;
        let rows: Vec<serde_json::Value> = stmt
            .query_map([], |row| {
                Ok(serde_json::json!({
                    "source_id": row.get::<_, String>(0)?,
                    "target_id": row.get::<_, String>(1)?,
                    "edge_type": row.get::<_, String>(2)?,
                    "weight": row.get::<_, f64>(3)?,
                }))
            })
            .map_err(to_pyerr)?
            .filter_map(|x| x.ok())
            .collect();
        serde_json::to_string(&rows)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    fn get_skill_entities(&self, skill_id: &str) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let mut stmt = conn
            .prepare(
                "SELECT e.id, e.name, e.entity_type, l.relation
                 FROM skill_entity_links l
                 JOIN skill_entities e ON e.id = l.entity_id
                 WHERE l.skill_id = ?1",
            )
            .map_err(to_pyerr)?;
        let rows: Vec<serde_json::Value> = stmt
            .query_map(params![skill_id], |row| {
                Ok(serde_json::json!({
                    "id": row.get::<_, String>(0)?,
                    "name": row.get::<_, String>(1)?,
                    "entity_type": row.get::<_, String>(2)?,
                    "relation": row.get::<_, Option<String>>(3)?,
                }))
            })
            .map_err(to_pyerr)?
            .filter_map(|x| x.ok())
            .collect();
        serde_json::to_string(&rows)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    fn stats(&self) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;

        let total: i64 = conn
            .query_row("SELECT COUNT(*) FROM skills", [], |r| r.get(0))
            .map_err(to_pyerr)?;
        let enabled: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM skills WHERE enabled = 1",
                [],
                |r| r.get(0),
            )
            .map_err(to_pyerr)?;
        let pinned: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM skills WHERE pinned = 1",
                [],
                |r| r.get(0),
            )
            .map_err(to_pyerr)?;
        let edge_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM skill_edges", [], |r| r.get(0))
            .map_err(to_pyerr)?;
        let entity_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM skill_entities", [], |r| r.get(0))
            .map_err(to_pyerr)?;
        let has_embeddings: i64 = conn
            .query_row(
                "SELECT COUNT(DISTINCT skill_id) FROM skill_embeddings",
                [],
                |r| r.get(0),
            )
            .map_err(to_pyerr)?;

        let mut stmt = conn
            .prepare("SELECT category, COUNT(*) FROM skills GROUP BY category")
            .map_err(to_pyerr)?;
        let cats: Vec<(Option<String>, i64)> = stmt
            .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
            .map_err(to_pyerr)?
            .filter_map(|x| x.ok())
            .collect();

        let mut cat_map = serde_json::Map::new();
        for (c, n) in cats {
            cat_map.insert(
                c.unwrap_or_else(|| "uncategorized".to_string()),
                serde_json::Value::Number(n.into()),
            );
        }

        let obj = serde_json::json!({
            "total": total,
            "enabled": enabled,
            "pinned": pinned,
            "edge_count": edge_count,
            "entity_count": entity_count,
            "has_embeddings": has_embeddings,
            "categories": cat_map,
        });

        Ok(obj.to_string())
    }

    fn record_usage(
        &self,
        skill_id: &str,
        session_id: &str,
        query_text: &str,
    ) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::SystemTime::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        conn.execute(
            "INSERT INTO skill_usage (skill_id, session_id, query_text, used_at)
             VALUES (?1, ?2, ?3, ?4)",
            params![skill_id, session_id, query_text, now],
        )
        .map_err(to_pyerr)?;
        Ok(())
    }

    fn get_pinned_skills(&self) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let mut stmt = conn
            .prepare(
                "SELECT id, display_name, description, category, body_path
                 FROM skills WHERE pinned = 1 AND enabled = 1",
            )
            .map_err(to_pyerr)?;
        let rows: Vec<serde_json::Value> = stmt
            .query_map([], |row| {
                Ok(serde_json::json!({
                    "id": row.get::<_, String>(0)?,
                    "display_name": row.get::<_, String>(1)?,
                    "description": row.get::<_, String>(2)?,
                    "category": row.get::<_, Option<String>>(3)?,
                    "body_path": row.get::<_, Option<String>>(4)?,
                }))
            })
            .map_err(to_pyerr)?
            .filter_map(|x| x.ok())
            .collect();
        serde_json::to_string(&rows)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    fn has_embedding(&self, skill_id: &str) -> PyResult<bool> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM skill_embeddings WHERE skill_id = ?1",
                params![skill_id],
                |r| r.get(0),
            )
            .map_err(to_pyerr)?;
        Ok(count > 0)
    }
}

#[pymodule]
fn skill_store(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<SkillStore>()?;
    Ok(())
}
