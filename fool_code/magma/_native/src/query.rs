use std::collections::{BinaryHeap, HashMap, HashSet};
use std::cmp::Ordering;

use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};

use crate::ingest::cjk_split;
use crate::vector::{bytes_to_embed, cosine_similarity};

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone)]
pub struct AnchorResult {
    pub node_id: String,
    pub score: f64,
    pub content: String,
    pub summary: String,
    pub timestamp: f64,
}

#[derive(Serialize, Clone)]
pub struct TraversalResult {
    pub node_id: String,
    pub score: f64,
    pub content: String,
    pub summary: String,
    pub timestamp: f64,
    pub depth: usize,
}

#[derive(Deserialize)]
pub struct IntentWeights {
    #[serde(default = "default_weight")]
    pub temporal: f64,
    #[serde(default = "default_weight")]
    pub causal: f64,
    #[serde(default = "default_weight")]
    pub semantic: f64,
    #[serde(default = "default_weight")]
    pub entity: f64,
}

fn default_weight() -> f64 {
    1.0
}

// ---------------------------------------------------------------------------
// Stage 2: Multi-signal anchor identification
// ---------------------------------------------------------------------------

/// Find anchor nodes via RRF fusion of vector, keyword, and temporal signals.
///
/// `vector_weight` controls the vector signal's contribution to RRF fusion:
///   - 1.0 = full weight (real embeddings configured)
///   - 0.0 = disabled   (hash pseudo-embeddings — avoids random noise in fusion)
/// Keyword and temporal signals are always at full weight.
pub fn find_anchors(
    conn: &Connection,
    query_embedding: &[f32],
    keywords: &[String],
    time_start: Option<f64>,
    time_end: Option<f64>,
    top_k: usize,
    rrf_k: u32,
    vector_weight: f64,
) -> rusqlite::Result<Vec<AnchorResult>> {
    let vec_ranked = vector_rank(conn, query_embedding, top_k * 3)?;
    let kw_ranked = keyword_rank_fts5(conn, keywords, top_k * 3)?;
    let time_ranked = temporal_rank(conn, time_start, time_end, top_k * 3)?;

    // RRF fusion — vector_weight scales the vector signal so it can be
    // disabled (0.0) when only hash pseudo-embeddings are available.
    let mut rrf_scores: HashMap<String, f64> = HashMap::new();
    let k = rrf_k as f64;

    for (rank, (nid, _)) in vec_ranked.iter().enumerate() {
        *rrf_scores.entry(nid.clone()).or_default() +=
            vector_weight * (1.0 / (k + rank as f64 + 1.0));
    }
    for (rank, (nid, _)) in kw_ranked.iter().enumerate() {
        *rrf_scores.entry(nid.clone()).or_default() += 1.0 / (k + rank as f64 + 1.0);
    }
    for (rank, (nid, _)) in time_ranked.iter().enumerate() {
        *rrf_scores.entry(nid.clone()).or_default() += 1.0 / (k + rank as f64 + 1.0);
    }

    let mut fused: Vec<(String, f64)> = rrf_scores.into_iter().collect();
    fused.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(Ordering::Equal));
    fused.truncate(top_k);

    let mut results = Vec::with_capacity(fused.len());
    for (nid, score) in fused {
        if let Some(r) = fetch_anchor_detail(conn, &nid, score)? {
            results.push(r);
        }
    }

    Ok(results)
}

// ---------------------------------------------------------------------------
// Stage 3: Adaptive traversal (beam search)
// ---------------------------------------------------------------------------

pub fn traverse(
    conn: &Connection,
    anchor_ids: &[String],
    weights: &IntentWeights,
    query_embedding: &[f32],
    lambda1: f64,
    lambda2: f64,
    max_depth: usize,
    beam_width: usize,
    budget: usize,
    decay: f64,
    drop_threshold: f64,
) -> rusqlite::Result<Vec<TraversalResult>> {
    let mut visited: HashSet<String> = HashSet::new();
    let mut all_results: Vec<TraversalResult> = Vec::new();

    let mut frontier: Vec<(String, f64, usize)> = Vec::new();
    for aid in anchor_ids {
        if visited.insert(aid.clone()) {
            frontier.push((aid.clone(), 1.0, 0));
            if let Some(r) = fetch_traversal_detail(conn, aid, 1.0, 0)? {
                all_results.push(r);
            }
        }
    }

    for _depth in 1..=max_depth {
        if all_results.len() >= budget {
            break;
        }

        let mut candidates: BinaryHeap<ScoredNode> = BinaryHeap::new();

        for (uid, u_score, u_depth) in &frontier {
            let neighbors = get_neighbors_with_type(conn, uid)?;
            for (vid, edge_type, _edge_weight) in &neighbors {
                if visited.contains(vid) {
                    continue;
                }

                let phi = structural_alignment(edge_type, weights);
                let sem = node_embedding_similarity(conn, vid, query_embedding);

                // Transition score (Eq. 5 in paper)
                let s_uv = (lambda1 * phi + lambda2 * sem as f64).exp();

                // Drop threshold: skip low-quality transitions
                if s_uv < drop_threshold {
                    continue;
                }

                let score_v = u_score * decay + s_uv;

                candidates.push(ScoredNode {
                    node_id: vid.clone(),
                    score: score_v,
                    depth: u_depth + 1,
                });
            }
        }

        let mut new_frontier: Vec<(String, f64, usize)> = Vec::new();
        while let Some(sn) = candidates.pop() {
            if new_frontier.len() >= beam_width {
                break;
            }
            if visited.insert(sn.node_id.clone()) {
                if let Some(r) =
                    fetch_traversal_detail(conn, &sn.node_id, sn.score, sn.depth)?
                {
                    all_results.push(r);
                }
                new_frontier.push((sn.node_id, sn.score, sn.depth));
            }
            if all_results.len() >= budget {
                break;
            }
        }

        if new_frontier.is_empty() {
            break;
        }
        frontier = new_frontier;
    }

    all_results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(Ordering::Equal));
    Ok(all_results)
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

#[derive(PartialEq)]
struct ScoredNode {
    node_id: String,
    score: f64,
    depth: usize,
}

impl Eq for ScoredNode {}

impl PartialOrd for ScoredNode {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for ScoredNode {
    fn cmp(&self, other: &Self) -> Ordering {
        self.score
            .partial_cmp(&other.score)
            .unwrap_or(Ordering::Equal)
    }
}

/// Map edge type to intent-specific weight (Eq. 6 in paper).
fn structural_alignment(edge_type: &str, w: &IntentWeights) -> f64 {
    match edge_type {
        "temporal" => w.temporal,
        "causal" => w.causal,
        "semantic" => w.semantic,
        "entity" => w.entity,
        _ => 1.0,
    }
}

fn node_embedding_similarity(conn: &Connection, node_id: &str, query: &[f32]) -> f32 {
    let blob: Option<Vec<u8>> = conn
        .query_row(
            "SELECT embedding FROM node_embeddings WHERE node_id = ?1",
            params![node_id],
            |row| row.get(0),
        )
        .ok();
    match blob {
        Some(b) => cosine_similarity(query, &bytes_to_embed(&b)),
        None => 0.0,
    }
}

fn vector_rank(
    conn: &Connection,
    query: &[f32],
    limit: usize,
) -> rusqlite::Result<Vec<(String, f64)>> {
    let mut stmt = conn.prepare("SELECT node_id, embedding FROM node_embeddings")?;
    let rows = stmt.query_map([], |row| {
        let nid: String = row.get(0)?;
        let blob: Vec<u8> = row.get(1)?;
        Ok((nid, blob))
    })?;

    let mut scored: Vec<(String, f64)> = Vec::new();
    for r in rows {
        let (nid, blob) = r?;
        let sim = cosine_similarity(query, &bytes_to_embed(&blob)) as f64;
        scored.push((nid, sim));
    }
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(Ordering::Equal));
    scored.truncate(limit);
    Ok(scored)
}

/// FTS5-based keyword ranking (replaces old LIKE-based approach).
fn keyword_rank_fts5(
    conn: &Connection,
    keywords: &[String],
    limit: usize,
) -> rusqlite::Result<Vec<(String, f64)>> {
    if keywords.is_empty() {
        return Ok(Vec::new());
    }

    // Each keyword is CJK-split (so "达梦" → "达 梦") then sanitized.
    // Multiple tokens within one keyword use implicit AND; keywords are OR'd.
    let fts_query = keywords
        .iter()
        .map(|kw| {
            let split = cjk_split(kw);
            let tokens: Vec<String> = split
                .split_whitespace()
                .map(|t| sanitize_fts5_token(t))
                .filter(|s| !s.is_empty())
                .collect();
            if tokens.is_empty() {
                String::new()
            } else if tokens.len() == 1 {
                tokens[0].clone()
            } else {
                // AND: all chars must appear (not phrase — too strict for CJK)
                tokens.join(" ")
            }
        })
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" OR ");

    if fts_query.is_empty() {
        return Ok(Vec::new());
    }

    let sql = format!(
        "SELECT m.node_id, f.rank
         FROM nodes_fts f
         JOIN nodes_fts_map m ON m.fts_rowid = f.rowid
         WHERE nodes_fts MATCH ?1
         ORDER BY f.rank
         LIMIT {limit}"
    );

    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map(params![fts_query], |row| {
        let nid: String = row.get(0)?;
        let rank: f64 = row.get(1)?;
        Ok((nid, -rank)) // FTS5 rank is negative; negate for positive score
    });

    match rows {
        Ok(r) => {
            let mut results = Vec::new();
            for item in r {
                if let Ok(v) = item {
                    results.push(v);
                }
            }
            Ok(results)
        }
        Err(_) => Ok(Vec::new()), // FTS query syntax error → empty results
    }
}

fn sanitize_fts5_token(token: &str) -> String {
    token
        .chars()
        .filter(|c| !matches!(c, '+' | '{' | '}' | '(' | ')' | '"' | '^' | '*' | ':'))
        .collect::<String>()
        .trim()
        .to_string()
}

fn temporal_rank(
    conn: &Connection,
    time_start: Option<f64>,
    time_end: Option<f64>,
    limit: usize,
) -> rusqlite::Result<Vec<(String, f64)>> {
    let (sql, needs_start, needs_end) = match (time_start, time_end) {
        (Some(_), Some(_)) => (
            "SELECT id, timestamp FROM nodes WHERE timestamp >= ?1 AND timestamp <= ?2
             ORDER BY timestamp DESC LIMIT ?3",
            true,
            true,
        ),
        (Some(_), None) => (
            "SELECT id, timestamp FROM nodes WHERE timestamp >= ?1
             ORDER BY timestamp DESC LIMIT ?2",
            true,
            false,
        ),
        (None, Some(_)) => (
            "SELECT id, timestamp FROM nodes WHERE timestamp <= ?1
             ORDER BY timestamp DESC LIMIT ?2",
            false,
            true,
        ),
        (None, None) => (
            "SELECT id, timestamp FROM nodes ORDER BY timestamp DESC LIMIT ?1",
            false,
            false,
        ),
    };

    let mut stmt = conn.prepare(sql)?;
    let rows: Vec<(String, f64)> = match (needs_start, needs_end) {
        (true, true) => {
            let r = stmt.query_map(
                params![time_start.unwrap(), time_end.unwrap(), limit as i64],
                |row| {
                    let nid: String = row.get(0)?;
                    let ts: f64 = row.get(1)?;
                    Ok((nid, ts))
                },
            )?;
            r.filter_map(|x| x.ok()).collect()
        }
        (true, false) => {
            let r = stmt.query_map(params![time_start.unwrap(), limit as i64], |row| {
                let nid: String = row.get(0)?;
                let ts: f64 = row.get(1)?;
                Ok((nid, ts))
            })?;
            r.filter_map(|x| x.ok()).collect()
        }
        (false, true) => {
            let r = stmt.query_map(params![time_end.unwrap(), limit as i64], |row| {
                let nid: String = row.get(0)?;
                let ts: f64 = row.get(1)?;
                Ok((nid, ts))
            })?;
            r.filter_map(|x| x.ok()).collect()
        }
        (false, false) => {
            let r = stmt.query_map(params![limit as i64], |row| {
                let nid: String = row.get(0)?;
                let ts: f64 = row.get(1)?;
                Ok((nid, ts))
            })?;
            r.filter_map(|x| x.ok()).collect()
        }
    };

    let results: Vec<(String, f64)> = rows
        .into_iter()
        .enumerate()
        .map(|(i, (nid, _ts))| (nid, 1.0 / (i as f64 + 1.0)))
        .collect();
    Ok(results)
}

fn fetch_anchor_detail(
    conn: &Connection,
    node_id: &str,
    score: f64,
) -> rusqlite::Result<Option<AnchorResult>> {
    conn.query_row(
        "SELECT id, content, summary, timestamp FROM nodes WHERE id = ?1",
        params![node_id],
        |row| {
            Ok(AnchorResult {
                node_id: row.get(0)?,
                score,
                content: row.get(1)?,
                summary: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                timestamp: row.get(3)?,
            })
        },
    )
    .optional()
}

fn fetch_traversal_detail(
    conn: &Connection,
    node_id: &str,
    score: f64,
    depth: usize,
) -> rusqlite::Result<Option<TraversalResult>> {
    conn.query_row(
        "SELECT id, content, summary, timestamp FROM nodes WHERE id = ?1",
        params![node_id],
        |row| {
            Ok(TraversalResult {
                node_id: row.get(0)?,
                score,
                content: row.get(1)?,
                summary: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                timestamp: row.get(3)?,
                depth,
            })
        },
    )
    .optional()
}

/// Get all neighbors of a node: direct edges PLUS entity_node_links co-occurrences.
fn get_neighbors_with_type(
    conn: &Connection,
    node_id: &str,
) -> rusqlite::Result<Vec<(String, String, f64)>> {
    // Direct edges (both directions)
    let mut stmt = conn.prepare(
        "SELECT target_id, edge_type, weight FROM edges WHERE source_id = ?1
         UNION ALL
         SELECT source_id, edge_type, weight FROM edges WHERE target_id = ?1",
    )?;
    let rows = stmt.query_map(params![node_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, f64>(2)?,
        ))
    })?;
    let mut result: Vec<(String, String, f64)> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for r in rows {
        let item = r?;
        seen.insert(item.0.clone());
        result.push(item);
    }

    // Entity co-occurrence: nodes sharing at least one entity (as "entity" edge type)
    let mut estmt = conn.prepare(
        "SELECT DISTINCT enl2.node_id
         FROM entity_node_links enl1
         JOIN entity_node_links enl2 ON enl1.entity_id = enl2.entity_id
         WHERE enl1.node_id = ?1 AND enl2.node_id != ?1",
    )?;
    let erows = estmt.query_map(params![node_id], |row| row.get::<_, String>(0))?;
    for r in erows {
        if let Ok(nid) = r {
            if !seen.contains(&nid) {
                seen.insert(nid.clone());
                result.push((nid, "entity".to_string(), 1.0));
            }
        }
    }

    Ok(result)
}

/// Return the maximum cosine similarity between the query embedding and
/// any stored node embedding.  Returns 0.0 if the store is empty.
pub fn query_max_similarity(conn: &Connection, query: &[f32]) -> rusqlite::Result<f64> {
    let mut stmt = conn.prepare("SELECT embedding FROM node_embeddings")?;
    let rows = stmt.query_map([], |row| {
        let blob: Vec<u8> = row.get(0)?;
        Ok(blob)
    })?;

    let mut max_sim: f64 = 0.0;
    for r in rows {
        let blob = r?;
        let sim = cosine_similarity(query, &bytes_to_embed(&blob)) as f64;
        if sim > max_sim {
            max_sim = sim;
        }
    }
    Ok(max_sim)
}

/// Return the number of FTS5 matches for the given keywords.
pub fn keyword_match_count(
    conn: &Connection,
    keywords: &[String],
) -> rusqlite::Result<usize> {
    if keywords.is_empty() {
        return Ok(0);
    }

    let fts_query = keywords
        .iter()
        .map(|kw| {
            let split = cjk_split(kw);
            let tokens: Vec<String> = split
                .split_whitespace()
                .map(|t| sanitize_fts5_token(t))
                .filter(|s| !s.is_empty())
                .collect();
            if tokens.is_empty() {
                String::new()
            } else if tokens.len() == 1 {
                tokens[0].clone()
            } else {
                tokens.join(" ")
            }
        })
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" OR ");

    if fts_query.is_empty() {
        return Ok(0);
    }

    let count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM nodes_fts WHERE nodes_fts MATCH ?1",
            params![fts_query],
            |row| row.get(0),
        )
        .unwrap_or(0);

    Ok(count as usize)
}

/// Count how many distinct entities have a name matching any of the keywords.
/// Used as a fallback relevance signal when vector similarity is unavailable
/// (hash-only mode).
///
/// Matching strategy (bidirectional):
///   1. `entity.name LIKE '%keyword%'`  — keyword is a substring of the entity name
///   2. Sub-token expansion: compound keywords like "Docker配置" are split at
///      CJK boundaries via `cjk_split`, producing tokens like "Docker".  Each
///      token with 2+ characters is also tested with `entity.name LIKE '%token%'`.
///
/// This allows "Docker配置" to match entity "Docker" and "PostgreSQL性能"
/// to match entity "PostgreSQL数据库".
pub fn entity_match_count(
    conn: &Connection,
    keywords: &[String],
) -> rusqlite::Result<usize> {
    if keywords.is_empty() {
        return Ok(0);
    }

    // Collect all search tokens: original keywords + sub-tokens from CJK split.
    let mut tokens: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    for kw in keywords {
        let trimmed = kw.trim().to_lowercase();
        if trimmed.is_empty() {
            continue;
        }
        if seen.insert(trimmed.clone()) {
            tokens.push(trimmed.clone());
        }

        // Split compound keywords at CJK boundaries and keep tokens with 2+ chars.
        // E.g. "Docker配置" → cjk_split → "Docker 配 置" → keep "Docker" (6 chars).
        let split = cjk_split(&trimmed);
        for sub in split.split_whitespace() {
            let s = sub.trim().to_lowercase();
            if s.chars().count() >= 2 && !seen.contains(&s) {
                seen.insert(s.clone());
                tokens.push(s);
            }
        }
    }

    if tokens.is_empty() {
        return Ok(0);
    }

    // Build OR-ed LIKE conditions for all tokens.
    let conditions: Vec<String> = tokens
        .iter()
        .enumerate()
        .map(|(i, _)| format!("LOWER(name) LIKE ?{}", i + 1))
        .collect();
    let sql = format!(
        "SELECT COUNT(DISTINCT id) FROM entities WHERE {}",
        conditions.join(" OR ")
    );

    let mut stmt = conn.prepare(&sql)?;
    let params: Vec<String> = tokens
        .iter()
        .map(|t| format!("%{}%", t))
        .collect();

    let count: i64 = stmt
        .query_row(
            rusqlite::params_from_iter(params.iter()),
            |row| row.get(0),
        )
        .unwrap_or(0);

    Ok(count as usize)
}

trait OptionalExt<T> {
    fn optional(self) -> rusqlite::Result<Option<T>>;
}

impl<T> OptionalExt<T> for rusqlite::Result<T> {
    fn optional(self) -> rusqlite::Result<Option<T>> {
        match self {
            Ok(v) => Ok(Some(v)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e),
        }
    }
}
