use std::sync::Mutex;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use rusqlite::{params, Connection};

mod ingest;
mod query;
mod schema;
mod vector;

/// Multi-graph agentic memory store backed by SQLite.
///
/// All data lives in a single `.db` file.  The store is thread-safe via an
/// internal mutex — Python can call methods from any thread.
#[pyclass]
struct MagmaStore {
    conn: Mutex<Connection>,
}

fn to_pyerr(e: rusqlite::Error) -> PyErr {
    PyRuntimeError::new_err(format!("magma db error: {e}"))
}

#[pymethods]
impl MagmaStore {
    #[new]
    fn new(db_path: &str) -> PyResult<Self> {
        // Ensure parent directory exists
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
        // wal_checkpoint returns a result row (busy, log, checkpointed)
        let _: (i32, i32, i32) = conn
            .query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?))
            })
            .unwrap_or((0, 0, 0));
        Ok(())
    }

    // ===== Fast Path =====

    /// Ingest a new event and return its node ID.
    #[pyo3(signature = (content, summary, timestamp, embedding, session_id, metadata_json="{}".to_string()))]
    fn ingest_event(
        &self,
        content: &str,
        summary: &str,
        timestamp: f64,
        embedding: Vec<f32>,
        session_id: &str,
        metadata_json: String,
    ) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::ingest_event(
            &conn,
            content,
            summary,
            timestamp,
            &embedding,
            session_id,
            &metadata_json,
        )
        .map_err(to_pyerr)
    }

    // ===== Slow Path =====

    #[pyo3(signature = (limit=10))]
    fn pending_consolidation(&self, limit: usize) -> PyResult<Vec<String>> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::pending_consolidation(&conn, limit).map_err(to_pyerr)
    }

    fn add_edges(&self, edges_json: &str) -> PyResult<usize> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::add_edges_batch(&conn, edges_json).map_err(to_pyerr)
    }

    fn upsert_entity(&self, id: &str, name: &str, entity_type: &str) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::upsert_entity(&conn, id, name, entity_type).map_err(to_pyerr)
    }

    #[pyo3(signature = (entity_id, node_id, relation=None))]
    fn link_entity_node(
        &self,
        entity_id: &str,
        node_id: &str,
        relation: Option<&str>,
    ) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::link_entity_node(&conn, entity_id, node_id, relation).map_err(to_pyerr)
    }

    fn mark_consolidated(&self, node_id: &str) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::mark_consolidated(&conn, node_id).map_err(to_pyerr)
    }

    fn increment_retry(&self, node_id: &str) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::increment_retry(&conn, node_id).map_err(to_pyerr)
    }

    // ===== Meta key-value =====

    fn get_meta(&self, key: &str) -> PyResult<Option<String>> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::get_meta(&conn, key).map_err(to_pyerr)
    }

    fn set_meta(&self, key: &str, value: &str) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        ingest::set_meta(&conn, key, value).map_err(to_pyerr)
    }

    // ===== Relevance gate =====

    fn max_query_similarity(&self, query_embedding: Vec<f32>) -> PyResult<f64> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        query::query_max_similarity(&conn, &query_embedding).map_err(to_pyerr)
    }

    fn keyword_match_count(&self, keywords: Vec<String>) -> PyResult<usize> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        query::keyword_match_count(&conn, &keywords).map_err(to_pyerr)
    }

    /// Count entities whose name matches any keyword (LIKE '%kw%').
    /// Complements FTS keyword matching with structured entity lookups.
    fn entity_match_count(&self, keywords: Vec<String>) -> PyResult<usize> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        query::entity_match_count(&conn, &keywords).map_err(to_pyerr)
    }

    // ===== Query: anchors =====

    /// vector_weight: scales vector signal in RRF (1.0 = normal, 0.0 = disabled for hash mode)
    #[pyo3(signature = (query_embedding, keywords=vec![], time_start=None, time_end=None, top_k=20, rrf_k=60, vector_weight=1.0))]
    fn find_anchors(
        &self,
        query_embedding: Vec<f32>,
        keywords: Vec<String>,
        time_start: Option<f64>,
        time_end: Option<f64>,
        top_k: usize,
        rrf_k: u32,
        vector_weight: f64,
    ) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let results = query::find_anchors(
            &conn,
            &query_embedding,
            &keywords,
            time_start,
            time_end,
            top_k,
            rrf_k,
            vector_weight,
        )
        .map_err(to_pyerr)?;
        serde_json::to_string(&results)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    // ===== Query: graph traversal =====

    #[pyo3(signature = (anchor_ids, intent_weights_json, query_embedding, lambda1=1.0, lambda2=0.5, max_depth=4, beam_width=10, budget=100, decay=0.9, drop_threshold=0.15))]
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
        drop_threshold: f64,
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
            drop_threshold,
        )
        .map_err(to_pyerr)?;
        serde_json::to_string(&results)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    // ===== Utility =====

    fn get_node(&self, node_id: &str) -> PyResult<Option<String>> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let result: Option<(String, String, Option<String>, f64, Option<String>, Option<String>)> =
            conn.query_row(
                "SELECT id, content, summary, timestamp, session_id, metadata
                 FROM nodes WHERE id = ?1",
                params![node_id],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                    ))
                },
            )
            .optional_row();

        match result {
            Some((id, content, summary, ts, sid, meta)) => {
                let obj = serde_json::json!({
                    "id": id,
                    "content": content,
                    "summary": summary,
                    "timestamp": ts,
                    "session_id": sid,
                    "metadata": meta,
                });
                Ok(Some(obj.to_string()))
            }
            None => Ok(None),
        }
    }

    #[pyo3(signature = (limit=20, offset=0))]
    fn get_recent_nodes(&self, limit: usize, offset: usize) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let mut stmt = conn
            .prepare(
                "SELECT id, content, summary, timestamp, session_id, metadata
                 FROM nodes ORDER BY timestamp DESC LIMIT ?1 OFFSET ?2",
            )
            .map_err(to_pyerr)?;
        let rows = stmt
            .query_map(params![limit as i64, offset as i64], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, Option<String>>(2)?,
                    row.get::<_, f64>(3)?,
                    row.get::<_, Option<String>>(4)?,
                    row.get::<_, Option<String>>(5)?,
                ))
            })
            .map_err(to_pyerr)?;
        let mut arr = Vec::new();
        for r in rows {
            let (id, content, summary, ts, sid, meta) = r.map_err(to_pyerr)?;
            arr.push(serde_json::json!({
                "id": id,
                "content": content,
                "summary": summary,
                "timestamp": ts,
                "session_id": sid,
                "metadata": meta,
            }));
        }
        Ok(serde_json::Value::Array(arr).to_string())
    }

    #[pyo3(signature = (node_id, edge_type=None))]
    fn get_neighbors(&self, node_id: &str, edge_type: Option<&str>) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;

        let sql = match edge_type {
            Some(_) => {
                "SELECT target_id, edge_type, weight, metadata FROM edges
                 WHERE source_id = ?1 AND edge_type = ?2
                 UNION ALL
                 SELECT source_id, edge_type, weight, metadata FROM edges
                 WHERE target_id = ?1 AND edge_type = ?2"
            }
            None => {
                "SELECT target_id, edge_type, weight, metadata FROM edges
                 WHERE source_id = ?1
                 UNION ALL
                 SELECT source_id, edge_type, weight, metadata FROM edges
                 WHERE target_id = ?1"
            }
        };

        let mut stmt = conn.prepare(sql).map_err(to_pyerr)?;
        let rows: Vec<serde_json::Value> = if let Some(et) = edge_type {
            let r = stmt
                .query_map(params![node_id, et], |row| {
                    Ok(serde_json::json!({
                        "node_id": row.get::<_, String>(0)?,
                        "edge_type": row.get::<_, String>(1)?,
                        "weight": row.get::<_, f64>(2)?,
                        "metadata": row.get::<_, Option<String>>(3)?,
                    }))
                })
                .map_err(to_pyerr)?;
            r.filter_map(|x| x.ok()).collect()
        } else {
            let r = stmt
                .query_map(params![node_id], |row| {
                    Ok(serde_json::json!({
                        "node_id": row.get::<_, String>(0)?,
                        "edge_type": row.get::<_, String>(1)?,
                        "weight": row.get::<_, f64>(2)?,
                        "metadata": row.get::<_, Option<String>>(3)?,
                    }))
                })
                .map_err(to_pyerr)?;
            r.filter_map(|x| x.ok()).collect()
        };

        serde_json::to_string(&rows)
            .map_err(|e| PyRuntimeError::new_err(format!("json serialize: {e}")))
    }

    #[pyo3(signature = (name, limit=10))]
    fn search_entities(&self, name: &str, limit: usize) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;
        let pattern = format!("%{name}%");
        let mut stmt = conn
            .prepare(
                "SELECT id, name, entity_type, mention_count, first_seen, last_seen
                 FROM entities WHERE name LIKE ?1
                 ORDER BY mention_count DESC LIMIT ?2",
            )
            .map_err(to_pyerr)?;
        let rows: Vec<serde_json::Value> = stmt
            .query_map(params![pattern, limit as i64], |row| {
                Ok(serde_json::json!({
                    "id": row.get::<_, String>(0)?,
                    "name": row.get::<_, String>(1)?,
                    "entity_type": row.get::<_, Option<String>>(2)?,
                    "mention_count": row.get::<_, i64>(3)?,
                    "first_seen": row.get::<_, Option<f64>>(4)?,
                    "last_seen": row.get::<_, Option<f64>>(5)?,
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

        let node_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM nodes", [], |r| r.get(0))
            .map_err(to_pyerr)?;
        let edge_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM edges", [], |r| r.get(0))
            .map_err(to_pyerr)?;
        let entity_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM entities", [], |r| r.get(0))
            .map_err(to_pyerr)?;
        let pending: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM consolidation_queue WHERE status = 'pending'",
                [],
                |r| r.get(0),
            )
            .map_err(to_pyerr)?;

        // Edge type breakdown
        let mut stmt = conn
            .prepare("SELECT edge_type, COUNT(*) FROM edges GROUP BY edge_type")
            .map_err(to_pyerr)?;
        let edge_types: Vec<(String, i64)> = stmt
            .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
            .map_err(to_pyerr)?
            .filter_map(|x| x.ok())
            .collect();

        let mut et_map = serde_json::Map::new();
        for (t, c) in edge_types {
            et_map.insert(t, serde_json::Value::Number(c.into()));
        }

        let fts_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM nodes_fts", [], |r| r.get(0))
            .unwrap_or(-1);
        let fts_map_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM nodes_fts_map", [], |r| r.get(0))
            .unwrap_or(-1);

        let obj = serde_json::json!({
            "node_count": node_count,
            "edge_count": edge_count,
            "entity_count": entity_count,
            "pending_consolidation": pending,
            "edge_types": et_map,
            "fts_count": fts_count,
            "fts_map_count": fts_map_count,
        });

        Ok(obj.to_string())
    }

    fn debug_fts_query(&self, query: String) -> PyResult<String> {
        let conn = self.conn.lock().map_err(|e| {
            PyRuntimeError::new_err(format!("lock poisoned: {e}"))
        })?;

        // Try raw MATCH query
        let match_result: Result<Vec<(i64, f64)>, _> = (|| {
            let mut stmt = conn.prepare(
                "SELECT rowid, rank FROM nodes_fts WHERE nodes_fts MATCH ?1 LIMIT 10"
            )?;
            let rows = stmt.query_map(rusqlite::params![query], |row| {
                Ok((row.get::<_, i64>(0)?, row.get::<_, f64>(1)?))
            })?;
            rows.collect::<Result<Vec<_>, _>>()
        })();

        let match_info = match match_result {
            Ok(rows) => format!("match_rows: {:?}", rows),
            Err(e) => format!("match_error: {}", e),
        };

        // Get sample FTS content
        let sample: Result<Vec<(i64, String)>, _> = (|| {
            let mut stmt = conn.prepare(
                "SELECT rowid, body FROM nodes_fts LIMIT 3"
            )?;
            let rows = stmt.query_map([], |row| {
                let rid: i64 = row.get(0)?;
                let content: String = row.get(1)?;
                Ok((rid, content))
            })?;
            rows.collect::<Result<Vec<_>, _>>()
        })();

        let sample_info = match sample {
            Ok(rows) => {
                let trimmed: Vec<(i64, String)> = rows.iter().map(|(r, c)| {
                    let s: String = c.chars().take(40).collect();
                    (*r, s)
                }).collect();
                format!("samples: {:?}", trimmed)
            }
            Err(e) => format!("sample_error: {}", e),
        };

        Ok(format!("{}\n{}", match_info, sample_info))
    }
}

// Helper trait — avoid clashing with rusqlite's own optional
trait OptionalRow<T> {
    fn optional_row(self) -> Option<T>;
}

impl<T> OptionalRow<T> for rusqlite::Result<T> {
    fn optional_row(self) -> Option<T> {
        match self {
            Ok(v) => Some(v),
            Err(rusqlite::Error::QueryReturnedNoRows) => None,
            Err(_) => None,
        }
    }
}

#[pymodule]
fn magma_memory(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<MagmaStore>()?;
    Ok(())
}
