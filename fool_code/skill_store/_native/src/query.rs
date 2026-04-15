use std::collections::{BinaryHeap, HashMap, HashSet};
use std::cmp::Ordering;

use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};

use crate::vector::{bytes_to_embed, cosine_similarity};

#[derive(Serialize, Clone)]
pub struct AnchorResult {
    pub skill_id: String,
    pub score: f64,
    pub display_name: String,
    pub description: String,
    pub category: Option<String>,
}

#[derive(Serialize, Clone)]
pub struct TraversalResult {
    pub skill_id: String,
    pub score: f64,
    pub display_name: String,
    pub description: String,
    pub category: Option<String>,
    pub depth: usize,
}

#[derive(Deserialize)]
pub struct IntentWeights {
    #[serde(default = "default_weight")]
    pub prerequisite: f64,
    #[serde(default = "default_weight")]
    pub complementary: f64,
    #[serde(default = "default_weight")]
    pub alternative: f64,
    #[serde(default = "default_weight")]
    pub composes_with: f64,
    #[serde(default = "default_weight")]
    pub shared_domain: f64,
}

fn default_weight() -> f64 {
    1.0
}

/// Multi-signal anchor search with RRF fusion.
pub fn find_anchors(
    conn: &Connection,
    query_embedding: &[f32],
    keywords: &[String],
    top_k: usize,
    rrf_k: u32,
) -> rusqlite::Result<Vec<AnchorResult>> {
    let pool = top_k * 3;

    let vec_ranked = multi_vector_rank(conn, query_embedding, pool)?;
    let kw_ranked = keyword_rank(conn, keywords, pool)?;
    let heat_ranked = heat_rank(conn, pool)?;

    let mut rrf_scores: HashMap<String, f64> = HashMap::new();
    let k = rrf_k as f64;

    for (rank, (sid, _)) in vec_ranked.iter().enumerate() {
        *rrf_scores.entry(sid.clone()).or_default() += 1.0 / (k + rank as f64 + 1.0);
    }
    for (rank, (sid, _)) in kw_ranked.iter().enumerate() {
        *rrf_scores.entry(sid.clone()).or_default() += 1.0 / (k + rank as f64 + 1.0);
    }
    for (rank, (sid, _)) in heat_ranked.iter().enumerate() {
        *rrf_scores.entry(sid.clone()).or_default() += 1.0 / (k + rank as f64 + 1.0);
    }

    let mut fused: Vec<(String, f64)> = rrf_scores.into_iter().collect();
    fused.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(Ordering::Equal));
    fused.truncate(top_k);

    let mut results = Vec::with_capacity(fused.len());
    for (sid, score) in fused {
        if let Some(r) = fetch_anchor_detail(conn, &sid, score)? {
            results.push(r);
        }
    }
    Ok(results)
}

/// Beam-search graph traversal from anchor skills.
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
            for (vid, edge_type, _weight) in &neighbors {
                if visited.contains(vid) {
                    continue;
                }
                let phi = structural_alignment(edge_type, weights);
                let sem = skill_embedding_similarity(conn, vid, query_embedding);
                let s_uv = (lambda1 * phi + lambda2 * sem as f64).exp();
                let score_v = u_score * decay + s_uv;

                candidates.push(ScoredNode {
                    skill_id: vid.clone(),
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
            if visited.insert(sn.skill_id.clone()) {
                if let Some(r) = fetch_traversal_detail(conn, &sn.skill_id, sn.score, sn.depth)? {
                    all_results.push(r);
                }
                new_frontier.push((sn.skill_id, sn.score, sn.depth));
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

// --- Internal helpers ---

#[derive(PartialEq)]
struct ScoredNode {
    skill_id: String,
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

fn structural_alignment(edge_type: &str, w: &IntentWeights) -> f64 {
    match edge_type {
        "prerequisite" => w.prerequisite,
        "complementary" => w.complementary,
        "alternative" => w.alternative,
        "composes_with" => w.composes_with,
        "shared_domain" => w.shared_domain,
        _ => 1.0,
    }
}

fn skill_embedding_similarity(conn: &Connection, skill_id: &str, query: &[f32]) -> f32 {
    let blob: Option<Vec<u8>> = conn
        .query_row(
            "SELECT embedding FROM skill_embeddings WHERE skill_id = ?1 AND source_type = 'description'",
            params![skill_id],
            |row| row.get(0),
        )
        .ok();
    match blob {
        Some(b) => cosine_similarity(query, &bytes_to_embed(&b)),
        None => 0.0,
    }
}

/// Weighted multi-vector similarity: 0.5*desc + 0.3*trigger + 0.2*body
fn multi_vector_rank(
    conn: &Connection,
    query: &[f32],
    limit: usize,
) -> rusqlite::Result<Vec<(String, f64)>> {
    let mut stmt = conn.prepare(
        "SELECT se.skill_id, se.source_type, se.embedding
         FROM skill_embeddings se
         JOIN skills s ON s.id = se.skill_id
         WHERE s.enabled = 1",
    )?;
    let rows = stmt.query_map([], |row| {
        let sid: String = row.get(0)?;
        let stype: String = row.get(1)?;
        let blob: Vec<u8> = row.get(2)?;
        Ok((sid, stype, blob))
    })?;

    let mut scores: HashMap<String, f64> = HashMap::new();
    for r in rows {
        let (sid, stype, blob) = r?;
        let sim = cosine_similarity(query, &bytes_to_embed(&blob)) as f64;
        let w = match stype.as_str() {
            "description" => 0.5,
            "trigger_terms" => 0.3,
            "body_summary" => 0.2,
            _ => 0.1,
        };
        *scores.entry(sid).or_default() += w * sim;
    }

    let mut ranked: Vec<(String, f64)> = scores.into_iter().collect();
    ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(Ordering::Equal));
    ranked.truncate(limit);
    Ok(ranked)
}

fn keyword_rank(
    conn: &Connection,
    keywords: &[String],
    limit: usize,
) -> rusqlite::Result<Vec<(String, f64)>> {
    if keywords.is_empty() {
        return Ok(Vec::new());
    }

    // Try FTS5 BM25 first; fall back to LIKE-based scoring if the
    // virtual table is unavailable (e.g. SQLite compiled without FTS5).
    match keyword_rank_fts5(conn, keywords, limit) {
        Ok(results) if !results.is_empty() => return Ok(results),
        Ok(_) => { /* empty result, try LIKE fallback */ }
        Err(_) => { /* FTS5 not available, fall through */ }
    }

    keyword_rank_like(conn, keywords, limit)
}

/// BM25-based full-text search via the `skills_fts` FTS5 virtual table.
/// Column weights: id=0, display_name=1.0, description=2.0, trigger_terms=1.5
fn keyword_rank_fts5(
    conn: &Connection,
    keywords: &[String],
    limit: usize,
) -> rusqlite::Result<Vec<(String, f64)>> {
    let match_expr = keywords
        .iter()
        .map(|kw| {
            let escaped = kw.replace('"', "\"\"");
            format!("\"{escaped}\"")
        })
        .collect::<Vec<_>>()
        .join(" OR ");

    let sql = format!(
        "SELECT f.id, -bm25(skills_fts, 0, 1.0, 2.0, 1.5) AS score
         FROM skills_fts f
         JOIN skills s ON s.id = f.id
         WHERE skills_fts MATCH '{match_expr}' AND s.enabled = 1
         ORDER BY score DESC
         LIMIT {limit}"
    );

    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, f64>(1)?))
    })?;

    let mut results = Vec::new();
    for r in rows {
        results.push(r?);
    }
    Ok(results)
}

/// Legacy LIKE-based keyword scoring (fallback when FTS5 is unavailable).
fn keyword_rank_like(
    conn: &Connection,
    keywords: &[String],
    limit: usize,
) -> rusqlite::Result<Vec<(String, f64)>> {
    let conditions: Vec<String> = keywords
        .iter()
        .map(|kw| {
            let escaped = kw.replace('\'', "''");
            format!(
                "(trigger_terms LIKE '%{escaped}%' OR description LIKE '%{escaped}%')"
            )
        })
        .collect();
    let where_clause = conditions.join(" OR ");

    let match_exprs: Vec<String> = keywords
        .iter()
        .map(|kw| {
            let escaped = kw.replace('\'', "''");
            format!(
                "(CASE WHEN trigger_terms LIKE '%{escaped}%' OR description LIKE '%{escaped}%' THEN 1 ELSE 0 END)"
            )
        })
        .collect();
    let score_expr = match_exprs.join(" + ");

    let sql = format!(
        "SELECT id, ({score_expr}) as kw_score FROM skills
         WHERE enabled = 1 AND ({where_clause})
         ORDER BY kw_score DESC LIMIT {limit}"
    );

    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, f64>(1)?))
    })?;

    let mut results = Vec::new();
    for r in rows {
        results.push(r?);
    }
    Ok(results)
}

fn heat_rank(
    conn: &Connection,
    limit: usize,
) -> rusqlite::Result<Vec<(String, f64)>> {
    let thirty_days_ago = std::time::SystemTime::now()
        .duration_since(std::time::SystemTime::UNIX_EPOCH)
        .map(|d| d.as_secs_f64() - 30.0 * 86400.0)
        .unwrap_or(0.0);

    let mut stmt = conn.prepare(
        "SELECT skill_id,
                COUNT(*) + SUM(CASE WHEN was_helpful = 1 THEN 1 ELSE 0 END) as heat
         FROM skill_usage
         WHERE used_at > ?1
         GROUP BY skill_id
         ORDER BY heat DESC LIMIT ?2",
    )?;
    let rows = stmt.query_map(params![thirty_days_ago, limit as i64], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, f64>(1)?))
    })?;

    let mut results = Vec::new();
    for r in rows {
        results.push(r?);
    }
    Ok(results)
}

fn fetch_anchor_detail(
    conn: &Connection,
    skill_id: &str,
    score: f64,
) -> rusqlite::Result<Option<AnchorResult>> {
    match conn.query_row(
        "SELECT id, display_name, description, category FROM skills WHERE id = ?1",
        params![skill_id],
        |row| {
            Ok(AnchorResult {
                skill_id: row.get(0)?,
                score,
                display_name: row.get(1)?,
                description: row.get(2)?,
                category: row.get(3)?,
            })
        },
    ) {
        Ok(v) => Ok(Some(v)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(e),
    }
}

fn fetch_traversal_detail(
    conn: &Connection,
    skill_id: &str,
    score: f64,
    depth: usize,
) -> rusqlite::Result<Option<TraversalResult>> {
    match conn.query_row(
        "SELECT id, display_name, description, category FROM skills WHERE id = ?1",
        params![skill_id],
        |row| {
            Ok(TraversalResult {
                skill_id: row.get(0)?,
                score,
                display_name: row.get(1)?,
                description: row.get(2)?,
                category: row.get(3)?,
                depth,
            })
        },
    ) {
        Ok(v) => Ok(Some(v)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(e),
    }
}

fn get_neighbors_with_type(
    conn: &Connection,
    skill_id: &str,
) -> rusqlite::Result<Vec<(String, String, f64)>> {
    let mut stmt = conn.prepare(
        "SELECT target_id, edge_type, weight FROM skill_edges WHERE source_id = ?1
         UNION ALL
         SELECT source_id, edge_type, weight FROM skill_edges WHERE target_id = ?1",
    )?;
    let rows = stmt.query_map(params![skill_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, f64>(2)?,
        ))
    })?;
    let mut result = Vec::new();
    for r in rows {
        result.push(r?);
    }
    Ok(result)
}
