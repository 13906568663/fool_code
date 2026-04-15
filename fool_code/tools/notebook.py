"""NotebookEdit tool — replace, insert, or delete cells in Jupyter notebooks.

Enhanced with protections:
  - mtime check before write (race-condition guard)
  - nbformat ≥ 4.5 check for cell id generation
  - cell-N index syntax support
  - read-state update after write
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from fool_code.runtime.config import active_workspace_root

logger = logging.getLogger(__name__)


def notebook_edit(args: dict[str, Any]) -> str:
    notebook_path = args.get("notebook_path", "")
    if not notebook_path:
        raise ValueError("notebook_path is required")

    path = Path(notebook_path)
    if not path.is_absolute():
        path = active_workspace_root() / path
    path = path.resolve()
    if path.suffix != ".ipynb":
        raise ValueError("File must be a Jupyter notebook (.ipynb file).")

    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {path}")

    # --- mtime check ---
    from fool_code.tools.file_ops import _get_read_record, _safe_mtime, _update_read_after_write

    prev = _get_read_record(path)
    current_mtime = _safe_mtime(path)
    if prev is not None and current_mtime - prev.mtime > 0.5:
        raise ValueError(
            f"Notebook {path.name} was modified after your last read "
            f"(read mtime={prev.mtime:.3f}, current={current_mtime:.3f}). "
            "Re-read the file before editing."
        )

    original_file = path.read_text(encoding="utf-8")
    # use fresh json.loads (not memo) to avoid mutable shared references
    notebook = json.loads(original_file)

    language = (
        notebook.get("metadata", {})
        .get("kernelspec", {})
        .get("language", "python")
    )

    # --- nbformat version detection (nbformat ≥ 4.5 for cell ids) ---
    nbformat_major = notebook.get("nbformat", 4)
    nbformat_minor = notebook.get("nbformat_minor", 0)
    supports_cell_id = (nbformat_major > 4) or (nbformat_major == 4 and nbformat_minor >= 5)

    cells = notebook.get("cells")
    if cells is None:
        raise ValueError("Notebook cells array not found")

    edit_mode = args.get("edit_mode", "replace")
    cell_id = args.get("cell_id")
    cell_type = args.get("cell_type")
    new_source = args.get("new_source")

    if edit_mode in ("replace", "delete") and not cells:
        raise ValueError("Notebook has no cells to edit")

    target_index: int | None = None
    if cell_id:
        target_index = _resolve_cell_index(cells, cell_id)
    elif edit_mode in ("replace", "delete"):
        target_index = max(0, len(cells) - 1)

    if edit_mode != "delete" and new_source is None:
        raise ValueError("new_source is required for insert and replace edits")

    resolved_cell_type: str | None = None
    if edit_mode == "delete":
        resolved_cell_type = None
    elif cell_type:
        resolved_cell_type = cell_type
    elif edit_mode == "replace" and target_index is not None:
        resolved_cell_type = cells[target_index].get("cell_type", "code")
    else:
        resolved_cell_type = "code"

    result_cell_id: str | None = None

    if edit_mode == "insert":
        new_id = f"cell-{len(cells) + 1}" if supports_cell_id else None
        new_cell = _build_cell(
            new_id, resolved_cell_type or "code", new_source or "",
            supports_cell_id=supports_cell_id,
        )
        insert_at = (target_index + 1) if target_index is not None else len(cells)
        cells.insert(insert_at, new_cell)
        result_cell_id = new_id

    elif edit_mode == "delete":
        assert target_index is not None
        removed = cells.pop(target_index)
        result_cell_id = removed.get("id")

    elif edit_mode == "replace":
        assert target_index is not None
        cell = cells[target_index]
        cell["source"] = _source_lines(new_source or "")
        cell["cell_type"] = resolved_cell_type or "code"
        if resolved_cell_type == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        elif resolved_cell_type == "markdown":
            cell.pop("outputs", None)
            cell.pop("execution_count", None)
        result_cell_id = cell.get("id")
    else:
        raise ValueError(f"Unknown edit_mode: {edit_mode}")

    updated_file = json.dumps(notebook, indent=1, ensure_ascii=False)
    path.write_text(updated_file, encoding="utf-8")

    # Update read state so subsequent reads don't return stale data
    _update_read_after_write(path)

    return json.dumps({
        "new_source": new_source or "",
        "cell_id": result_cell_id,
        "cell_type": resolved_cell_type,
        "language": language,
        "edit_mode": edit_mode,
        "notebook_path": str(path),
    }, indent=2, ensure_ascii=False)


def _resolve_cell_index(cells: list[dict], cell_id: str) -> int:
    # support "cell-N" numeric index syntax
    if cell_id.startswith("cell-"):
        try:
            idx = int(cell_id[5:]) - 1
            if 0 <= idx < len(cells):
                return idx
        except ValueError:
            pass

    for i, cell in enumerate(cells):
        if cell.get("id") == cell_id:
            return i
    raise ValueError(f"Cell id not found: {cell_id}")


def _source_lines(source: str) -> list[str]:
    if not source:
        return [""]
    parts: list[str] = []
    remaining = source
    while "\n" in remaining:
        idx = remaining.index("\n")
        parts.append(remaining[: idx + 1])
        remaining = remaining[idx + 1 :]
    if remaining:
        parts.append(remaining)
    return parts


def _build_cell(cell_id: str | None, cell_type: str, source: str,
                 *, supports_cell_id: bool = True) -> dict:
    cell: dict[str, Any] = {
        "cell_type": cell_type,
        "metadata": {},
        "source": _source_lines(source),
    }
    if supports_cell_id and cell_id is not None:
        cell["id"] = cell_id
    if cell_type == "code":
        cell["outputs"] = []
        cell["execution_count"] = None
    return cell
