"""Fetch model IDs from OpenAI-compatible GET /v1/models."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from fool_code.types import ModelInfo

logger = logging.getLogger(__name__)


def _models_url(base_url: str) -> str:
    b = (base_url or "").strip().rstrip("/")
    if not b:
        b = "https://api.openai.com/v1"
    if b.endswith("/v1"):
        return f"{b}/models"
    return f"{b}/v1/models"


def fetch_openai_compatible_models(
    base_url: str,
    api_key: str,
    timeout: float = 45.0,
) -> tuple[list[ModelInfo], str | None]:
    """Return (models, error_message). error_message is None on success."""
    if not api_key.strip():
        return [], "缺少 API Key"

    url = _models_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
    except httpx.RequestError as exc:
        logger.warning("models list request failed: %s", exc)
        return [], f"网络错误: {exc}"

    if resp.status_code != 200:
        body = resp.text[:500] if resp.text else ""
        return [], f"HTTP {resp.status_code}: {body}"

    try:
        data: dict[str, Any] = resp.json()
    except Exception:
        return [], "响应不是合法 JSON"

    raw_list = data.get("data")
    if not isinstance(raw_list, list):
        raw_list = data.get("models") if isinstance(data.get("models"), list) else []

    out: list[ModelInfo] = []
    seen: set[str] = set()
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        mid = item.get("id") or item.get("name") or item.get("model")
        if not mid or not isinstance(mid, str):
            continue
        mid = mid.strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        name = item.get("name") or item.get("title") or mid
        if not isinstance(name, str):
            name = mid
        out.append(ModelInfo(id=mid, name=name))

    out.sort(key=lambda m: m.id.lower())
    if not out:
        return [], "接口未返回模型列表（可能不支持 /v1/models）"

    return out, None
