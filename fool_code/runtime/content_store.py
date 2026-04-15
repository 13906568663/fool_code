"""ContentStore — unified external content management.

Manages disk storage for:
  - Images: ~/.fool-code/image-cache/{session_id}/{image_id}.{ext}
  - Large tool results: ~/.fool-code/tool-results/{session_id}/{tool_use_id}.{txt|json}
  - Plan files: ~/.fool-code/plans/{slug}.md

Each content type is stored externally and referenced by path in ContentBlock.
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import shutil
from pathlib import Path

import yaml

from fool_code.runtime.config import config_dir as get_config_dir

logger = logging.getLogger(__name__)

PREVIEW_SIZE_BYTES = 2000
MAX_STORED_IMAGE_PATHS = 200
PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"

_WORD_POOL = [
    "amber", "arctic", "autumn", "azure", "bamboo", "birch", "bloom", "breeze",
    "bronze", "canyon", "cedar", "cherry", "citrus", "clover", "cobalt", "coral",
    "cotton", "crimson", "crystal", "cypress", "dahlia", "dawn", "delta", "desert",
    "dusk", "ebony", "echo", "ember", "fern", "flint", "flora", "forest",
    "frost", "garden", "glacier", "golden", "grove", "harbor", "hazel", "heron",
    "hollow", "horizon", "indigo", "iron", "island", "ivory", "jade", "jasper",
    "lapis", "lark", "laurel", "lavender", "lemon", "lilac", "linen", "lotus",
    "lunar", "maple", "marble", "meadow", "mist", "moss", "navy", "oasis",
    "obsidian", "olive", "onyx", "orchid", "pearl", "pebble", "pine", "plum",
    "prism", "quartz", "raven", "river", "robin", "ruby", "rustic", "sable",
    "sage", "sand", "scarlet", "shadow", "silver", "slate", "solar", "spruce",
    "stone", "storm", "summit", "teal", "thistle", "tide", "timber", "topaz",
    "tulip", "valley", "velvet", "violet", "walnut", "willow", "winter", "wren",
]


def generate_word_slug() -> str:
    return "-".join(random.choices(_WORD_POOL, k=3))


class ContentStore:
    """Session-scoped external content manager."""

    def __init__(self, session_id: str, config_dir: Path | None = None) -> None:
        self.session_id = session_id
        self._config_dir = config_dir or get_config_dir()
        self._image_path_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Directory helpers
    # ------------------------------------------------------------------

    @property
    def image_dir(self) -> Path:
        return self._config_dir / "image-cache" / self.session_id

    @property
    def tool_results_dir(self) -> Path:
        return self._config_dir / "tool-results" / self.session_id

    @property
    def plans_dir(self) -> Path:
        return self._config_dir / "plans"

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def store_image(self, image_id: str, data_b64: str, media_type: str = "image/png") -> str:
        """Decode base64 image data and write to disk. Returns the file path."""
        self._ensure_dir(self.image_dir)
        ext = media_type.split("/")[-1] if "/" in media_type else "png"
        path = self.image_dir / f"{image_id}.{ext}"
        path.write_bytes(base64.b64decode(data_b64))
        path_str = str(path)
        self._evict_image_cache()
        self._image_path_cache[image_id] = path_str
        logger.debug("Stored image %s to %s", image_id, path)
        return path_str

    def get_image_path(self, image_id: str) -> str | None:
        cached = self._image_path_cache.get(image_id)
        if cached:
            return cached
        for ext in ("png", "jpg", "jpeg", "gif", "webp"):
            candidate = self.image_dir / f"{image_id}.{ext}"
            if candidate.exists():
                path_str = str(candidate)
                self._image_path_cache[image_id] = path_str
                return path_str
        return None

    def read_image_base64(self, path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode("ascii")

    def cleanup_old_image_caches(self, max_age_days: int = 30) -> None:
        """Remove image cache dirs older than *max_age_days*.

        Unlike the previous implementation, this does NOT delete caches from
        other active sessions — only dirs whose modification time exceeds
        the threshold.  Intended to be called from a periodic maintenance
        task, NOT on every chat message.
        """
        import time

        base_dir = self._config_dir / "image-cache"
        if not base_dir.exists():
            return
        cutoff = time.time() - max_age_days * 86400
        for child in base_dir.iterdir():
            if child.is_dir() and child.name != self.session_id:
                try:
                    if child.stat().st_mtime < cutoff:
                        shutil.rmtree(child)
                        logger.debug("Cleaned up old image cache: %s", child)
                except Exception:
                    pass

    def _evict_image_cache(self) -> None:
        while len(self._image_path_cache) >= MAX_STORED_IMAGE_PATHS:
            oldest_key = next(iter(self._image_path_cache))
            del self._image_path_cache[oldest_key]

    # ------------------------------------------------------------------
    # Large tool results
    # ------------------------------------------------------------------

    def persist_tool_result(self, tool_use_id: str, content: str) -> tuple[str, str, bool]:
        """Write large tool result to disk.

        Returns (file_path, preview_text, has_more).
        """
        self._ensure_dir(self.tool_results_dir)
        is_json = content.lstrip().startswith(("{", "["))
        ext = "json" if is_json else "txt"
        path = self.tool_results_dir / f"{tool_use_id}.{ext}"
        path.write_text(content, encoding="utf-8")
        logger.debug(
            "Persisted tool result to %s (%s)",
            path, _format_size(len(content)),
        )
        preview, has_more = _generate_preview(content, PREVIEW_SIZE_BYTES)
        return str(path), preview, has_more

    def build_replacement_message(
        self, file_path: str, preview: str, original_size: int, has_more: bool,
    ) -> str:
        msg = f"{PERSISTED_OUTPUT_TAG}\n"
        msg += f"Output too large ({_format_size(original_size)}). Full output saved to: {file_path}\n\n"
        msg += f"Preview (first {_format_size(PREVIEW_SIZE_BYTES)}):\n"
        msg += preview
        msg += "\n...\n" if has_more else "\n"
        msg += PERSISTED_OUTPUT_CLOSING_TAG
        return msg

    def read_tool_result(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def is_replacement_message(self, content: str) -> bool:
        return content.startswith(PERSISTED_OUTPUT_TAG)

    # ------------------------------------------------------------------
    # Plan files
    # ------------------------------------------------------------------

    def get_or_create_plan_slug(self, existing_slug: str | None = None) -> str:
        if existing_slug:
            return existing_slug
        self._ensure_dir(self.plans_dir)
        for _ in range(10):
            slug = generate_word_slug()
            path = self.plans_dir / f"{slug}.md"
            if not path.exists():
                return slug
        return generate_word_slug()

    def plan_path(self, slug: str, agent_id: str | None = None) -> Path:
        if agent_id:
            return self.plans_dir / f"{slug}-agent-{agent_id}.md"
        return self.plans_dir / f"{slug}.md"

    def write_plan(self, slug: str, content: str, agent_id: str | None = None) -> str:
        self._ensure_dir(self.plans_dir)
        path = self.plan_path(slug, agent_id)
        path.write_text(content, encoding="utf-8")
        logger.info("Plan saved to %s", path)
        return str(path)

    def read_plan(self, slug: str, agent_id: str | None = None) -> str | None:
        path = self.plan_path(slug, agent_id)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def write_plan_with_frontmatter(self, slug: str, markdown: str) -> str:
        """Parse markdown headings, generate YAML frontmatter, write plan file."""
        title, headings = _parse_plan_headings(markdown)
        first_para = _extract_first_paragraph(markdown)
        fm: dict = {
            "name": title or slug,
            "overview": first_para,
            "status": "drafted",
            "todos": [
                {"id": f"step-{i + 1}", "content": h, "status": "pending"}
                for i, h in enumerate(headings)
            ],
        }
        fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
        content = f"---\n{fm_str}---\n\n{markdown}"
        return self.write_plan(slug, content)

    def read_plan_parsed(self, slug: str) -> dict | None:
        """Read plan file and return parsed {frontmatter, body, todos}."""
        raw = self.read_plan(slug)
        if raw is None:
            return None
        fm, body = _split_frontmatter(raw)
        return {"frontmatter": fm, "body": body, "todos": fm.get("todos", [])}

    def update_plan_todos(self, slug: str, todos: list[dict]) -> None:
        """Update the frontmatter todos in a plan file by matching content."""
        raw = self.read_plan(slug)
        if raw is None:
            return
        fm, body = _split_frontmatter(raw)
        fm_todos = fm.get("todos", [])
        if not fm_todos:
            return
        for incoming in todos:
            inc_content = (incoming.get("content") or "").strip().lower()
            inc_status = incoming.get("status", "pending")
            if not inc_content:
                continue
            best_match = _fuzzy_match_todo(inc_content, fm_todos)
            if best_match is not None:
                fm_todos[best_match]["status"] = inc_status
        all_done = all(t.get("status") == "completed" for t in fm_todos)
        if all_done and fm_todos:
            fm["status"] = "completed"
        elif any(t.get("status") == "in_progress" for t in fm_todos):
            fm["status"] = "executing"
        fm["todos"] = fm_todos
        fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
        content = f"---\n{fm_str}---\n\n{body}"
        self.write_plan(slug, content)

    def update_plan_status(self, slug: str, status: str) -> None:
        """Update only the status field in plan frontmatter."""
        raw = self.read_plan(slug)
        if raw is None:
            return
        fm, body = _split_frontmatter(raw)
        fm["status"] = status
        fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
        content = f"---\n{fm_str}---\n\n{body}"
        self.write_plan(slug, content)

    # ------------------------------------------------------------------
    # Generic read
    # ------------------------------------------------------------------

    def read_content(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def read_content_bytes(self, path: str) -> bytes:
        return Path(path).read_bytes()


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _generate_preview(content: str, max_bytes: int) -> tuple[str, bool]:
    if len(content) <= max_bytes:
        return content, False
    truncated = content[:max_bytes]
    last_nl = truncated.rfind("\n")
    cut = last_nl if last_nl > max_bytes * 0.5 else max_bytes
    return content[:cut], True


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def extract_plan_summary(plan_text: str) -> str:
    """Extract a compact summary from plan markdown: just the ## headings."""
    body = plan_text
    if body.startswith("---"):
        _, body = _split_frontmatter(body)
    lines = body.splitlines()
    headings: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped[3:].strip().rstrip(" —-")
            if title:
                headings.append(title)
    if not headings:
        first_line = body.strip().splitlines()[0] if body.strip() else "Plan"
        return first_line[:80]
    return "\n".join(f"- {h}" for h in headings)


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    """Split a plan file into (frontmatter_dict, markdown_body)."""
    if not raw.startswith("---"):
        return {}, raw
    match = re.match(r"^---\n(.*?\n)---\n*(.*)", raw, re.DOTALL)
    if not match:
        return {}, raw
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except Exception:
        fm = {}
    return fm, match.group(2)


def _parse_plan_headings(markdown: str) -> tuple[str, list[str]]:
    """Extract (title, list_of_h2_headings) from plan markdown."""
    title = ""
    headings: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## ") and not title:
            title = stripped[2:].strip()
        elif stripped.startswith("## "):
            h = stripped[3:].strip().rstrip(" —-")
            if h:
                headings.append(h)
    return title, headings


def _extract_first_paragraph(markdown: str) -> str:
    """Extract the first non-heading paragraph as overview."""
    lines = markdown.splitlines()
    buf: list[str] = []
    started = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if started and buf:
                break
            continue
        if stripped:
            started = True
            buf.append(stripped)
        elif started and buf:
            break
    return " ".join(buf)[:200] if buf else ""


def _fuzzy_match_todo(incoming_content: str, fm_todos: list[dict]) -> int | None:
    """Find the best matching frontmatter todo index for an incoming todo content."""
    best_idx = None
    best_score = 0
    for i, ft in enumerate(fm_todos):
        ft_content = (ft.get("content") or "").strip().lower()
        if not ft_content:
            continue
        if incoming_content == ft_content:
            return i
        if incoming_content in ft_content or ft_content in incoming_content:
            score = min(len(incoming_content), len(ft_content))
            if score > best_score:
                best_score = score
                best_idx = i
    return best_idx
