from __future__ import annotations

import json
import re
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from i18n import english


STAGE_LABELS = {
    "screen": "全市场筛选",
    "quick": "快速提炼",
    "deep": "深度点评",
}


def safe_account(account: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", (account or "").strip().lower())
    return cleaned or "unknown"


def user_dir(root: Path, account: str) -> Path:
    path = Path(root) / "data" / "users" / safe_account(account)
    path.mkdir(parents=True, exist_ok=True)
    (path / "researches").mkdir(exist_ok=True)
    return path


def _index_path(root: Path, account: str) -> Path:
    return user_dir(root, account) / "index.json"


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def list_researches(root: Path, account: str) -> list[dict[str, Any]]:
    items = _read_json(_index_path(root, account), [])
    if not isinstance(items, list):
        return []
    return sorted(items, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)


def _save_index(root: Path, account: str, items: list[dict[str, Any]]) -> None:
    _write_json(_index_path(root, account), items)


def research_dir(root: Path, account: str, research_id: str) -> Path:
    path = user_dir(root, account) / "researches" / research_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "comments").mkdir(exist_ok=True)
    (path / "screenings").mkdir(exist_ok=True)
    return path


def create_research(root: Path, account: str, title: str = "未命名研究") -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    research_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    existing = {item.get("id") for item in list_researches(root, account)}
    suffix = 1
    while research_id in existing:
        suffix += 1
        research_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{suffix}"
    meta = {
        "id": research_id,
        "title": (title or "").strip() or "未命名研究",
        "named_by_user": bool((title or "").strip() and (title or "").strip() != "未命名研究"),
        "created_at": now,
        "updated_at": now,
        "stage": "screen",
        "source": "",
        "company_count": 0,
        "quick_count": 0,
        "deep_count": 0,
        "screening_count": 0,
    }
    folder = research_dir(root, account, research_id)
    _write_json(folder / "meta.json", meta)
    _write_json(
        folder / "screen.json",
        {"worklist": [], "announcements": {}, "source_mode": "巨潮资讯自动下载", "market_mode": "A股"},
    )
    _write_json(folder / ("summaries.en.json" if english() else "summaries.json"), [])
    _write_json(folder / ("comments.en.json" if english() else "comments.json"), [])
    _write_json(folder / ("screenings.en.json" if english() else "screenings.json"), [])
    items = list_researches(root, account)
    items.insert(0, meta)
    _save_index(root, account, items)
    return meta


def load_meta(root: Path, account: str, research_id: str) -> dict[str, Any]:
    payload = _read_json(research_dir(root, account, research_id) / "meta.json", {})
    if not isinstance(payload, dict): return {}
    folder = research_dir(root, account, research_id)
    suffix = '.en.json' if english() else '.json'
    summaries = _read_json(folder / ('summaries' + suffix), [])
    comments = _read_json(folder / ('comments' + suffix), [])
    payload['stage'] = 'deep' if comments else ('quick' if summaries else 'screen')
    payload['quick_count'] = len(summaries)
    payload['deep_count'] = len(comments)
    return payload


def update_meta(root: Path, account: str, research_id: str, **changes: Any) -> dict[str, Any]:
    meta = load_meta(root, account, research_id)
    if not meta:
        meta = {"id": research_id, "title": "未命名研究", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    meta.update(changes)
    meta["id"] = research_id
    meta["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(research_dir(root, account, research_id) / "meta.json", meta)
    items = list_researches(root, account)
    replaced = False
    for index, item in enumerate(items):
        if item.get("id") == research_id:
            items[index] = meta
            replaced = True
            break
    if not replaced:
        items.insert(0, meta)
    _save_index(root, account, items)
    return meta


def save_screen(
    root: Path,
    account: str,
    research_id: str,
    worklist: list[dict[str, Any]],
    announcements: dict[str, Any],
    source_mode: str,
    market_mode: str = "A股",
    source: str = "",
    title: str | None = None,
) -> None:
    _write_json(
        research_dir(root, account, research_id) / "screen.json",
        {
            "worklist": worklist,
            "announcements": announcements or {},
            "source_mode": source_mode,
            "market_mode": market_mode,
        },
    )
    meta = load_meta(root, account, research_id)
    changes: dict[str, Any] = {
        "company_count": len(worklist),
        "source": source or meta.get("source") or source_mode,
    }
    if (meta.get("stage") or "screen") == "screen":
        changes["stage"] = "screen"
    if title and not meta.get("named_by_user"):
        changes["title"] = title
    update_meta(root, account, research_id, **changes)


def load_screen(root: Path, account: str, research_id: str) -> dict[str, Any]:
    payload = _read_json(
        research_dir(root, account, research_id) / "screen.json",
        {"worklist": [], "announcements": {}, "source_mode": "巨潮资讯自动下载", "market_mode": "A股"},
    )
    if not isinstance(payload, dict):
        return {"worklist": [], "announcements": {}, "source_mode": "巨潮资讯自动下载", "market_mode": "A股"}
    payload.setdefault("worklist", [])
    payload.setdefault("announcements", {})
    payload.setdefault("source_mode", "巨潮资讯自动下载")
    payload.setdefault("market_mode", "港股" if any(str(row.get("证券代码") or "").upper().endswith(".HK") for row in payload["worklist"] if isinstance(row, dict)) else "A股")
    return payload


def save_summaries(root: Path, account: str, research_id: str, summaries: list[dict[str, Any]]) -> None:
    _write_json(research_dir(root, account, research_id) / ("summaries.en.json" if english() else "summaries.json"), summaries)
    selected = sum(1 for item in summaries if item.get("selected"))
    update_meta(root, account, research_id, stage="quick", quick_count=len(summaries), selected_count=selected)


def load_summaries(root: Path, account: str, research_id: str) -> list[dict[str, Any]]:
    payload = _read_json(research_dir(root, account, research_id) / ("summaries.en.json" if english() else "summaries.json"), [])
    return payload if isinstance(payload, list) else []


def save_comments(root: Path, account: str, research_id: str, comments: list[dict[str, Any]]) -> None:
    _write_json(research_dir(root, account, research_id) / ("comments.en.json" if english() else "comments.json"), comments)
    update_meta(root, account, research_id, stage="deep", deep_count=len(comments))


def load_comments(root: Path, account: str, research_id: str) -> list[dict[str, Any]]:
    payload = _read_json(research_dir(root, account, research_id) / ("comments.en.json" if english() else "comments.json"), [])
    return payload if isinstance(payload, list) else []


def save_screenings(root: Path, account: str, research_id: str, screenings: list[dict[str, Any]]) -> None:
    _write_json(research_dir(root, account, research_id) / ("screenings.en.json" if english() else "screenings.json"), screenings)
    update_meta(root, account, research_id, stage="deep", screening_count=len(screenings))


def load_screenings(root: Path, account: str, research_id: str) -> list[dict[str, Any]]:
    payload = _read_json(research_dir(root, account, research_id) / ("screenings.en.json" if english() else "screenings.json"), [])
    return payload if isinstance(payload, list) else []


def comments_dir(root: Path, account: str, research_id: str) -> Path:
    path = research_dir(root, account, research_id) / ("comments_en" if english() else "comments")
    path.mkdir(parents=True, exist_ok=True)
    return path


def screenings_dir(root: Path, account: str, research_id: str) -> Path:
    path = research_dir(root, account, research_id) / ("screenings_en" if english() else "screenings")
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_comment_filename(stock_code: str, company_name: str, report_year: int, report_type: str) -> str:
    raw = f"{stock_code}_{company_name}_{report_year}年{report_type}点评.md"
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", raw)
    return cleaned[:120]
