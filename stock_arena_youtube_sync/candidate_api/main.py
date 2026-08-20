from __future__ import annotations

import json, os, statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from google.cloud import storage
from pydantic import BaseModel

app = FastAPI(title="STOCK ARENA Candidate Scout Data API", version="1.0.0")

BUCKET_NAME = os.environ["DATA_BUCKET"]
OBJECT_NAME = os.getenv("DATA_OBJECT", "stock_arena/latest.json")
# NEXT投資ワードはSTOCK ARENAと同じバケット内の別オブジェクトに保存し、データを完全に分離する。
NEXT_OBJECT_NAME = os.getenv("NEXT_DATA_OBJECT", "next_investment_word/latest.json")
READ_API_KEY = os.environ["READ_API_KEY"]
WRITE_API_KEY = os.environ["WRITE_API_KEY"]
storage_client = storage.Client()

def check_key(value: str | None, expected: str):
    if value != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")

def load_object(object_name: str) -> dict[str, Any]:
    blob = storage_client.bucket(BUCKET_NAME).blob(object_name)
    if not blob.exists():
        return {"updated_at": None, "history": [], "performance": []}
    return json.loads(blob.download_as_text(encoding="utf-8"))

def save_object(object_name: str, data: dict[str, Any]):
    storage_client.bucket(BUCKET_NAME).blob(object_name).upload_from_string(
        json.dumps(data, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )

def load_data() -> dict[str, Any]:
    return load_object(OBJECT_NAME)

def save_data(data: dict[str, Any]):
    save_object(OBJECT_NAME, data)

def load_next_data() -> dict[str, Any]:
    return load_object(NEXT_OBJECT_NAME)

def save_next_data(data: dict[str, Any]):
    save_object(NEXT_OBJECT_NAME, data)

def fnum(v):
    try:
        return float(v) if v not in ("", None) else None
    except Exception:
        return None

def med(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 2) if vals else None

def recent_enough(row: dict, days: int) -> bool:
    try:
        d = date.fromisoformat(row.get("公開日", ""))
    except Exception:
        return False
    return d >= date.today() - timedelta(days=days)

class SyncPayload(BaseModel):
    history: list[dict[str, Any]]
    performance: list[dict[str, Any]]
    source_updated_at: str | None = None

@app.get("/")
def root():
    return {"status": "ok", "service": "STOCK ARENA Candidate Scout Data API"}

@app.get("/health")
def health():
    data = load_data()
    return {
        "status": "ok",
        "updated_at": data.get("updated_at"),
        "history_count": len(data.get("history", [])),
        "performance_count": len(data.get("performance", [])),
    }

@app.post("/admin/sync")
def sync(payload: SyncPayload, authorization: str | None = Header(default=None)):
    check_key(authorization, WRITE_API_KEY)
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_updated_at": payload.source_updated_at,
        "history": payload.history,
        "performance": payload.performance,
    }
    save_data(data)
    return {"ok": True, "history_count": len(payload.history), "performance_count": len(payload.performance)}

@app.get("/snapshot")
def snapshot(recent_limit: int = Query(default=20, ge=1, le=50), authorization: str | None = Header(default=None)):
    check_key(authorization, READ_API_KEY)
    data = load_data()
    perf_by_id = {(r.get("動画ID") or "").strip(): r for r in data.get("performance", [])}
    recent = []
    for h in data.get("history", [])[:recent_limit]:
        item = dict(h)
        item["performance"] = perf_by_id.get((h.get("動画ID") or "").strip(), {})
        recent.append(item)
    return {
        "updated_at": data.get("updated_at"),
        "history_count": len(data.get("history", [])),
        "performance_count": len(data.get("performance", [])),
        "recent": recent,
    }

@app.get("/company")
def company(query: str = Query(min_length=1, max_length=100), authorization: str | None = Header(default=None)):
    check_key(authorization, READ_API_KEY)
    data = load_data()
    perf_by_id = {(r.get("動画ID") or "").strip(): r for r in data.get("performance", [])}
    q = query.casefold()
    matches = []
    for h in data.get("history", []):
        hay = " ".join(str(h.get(k, "")) for k in ("企業名", "証券コード", "動画タイトル")).casefold()
        if q in hay:
            item = dict(h)
            item["performance"] = perf_by_id.get((h.get("動画ID") or "").strip(), {})
            matches.append(item)
    return {"query": query, "count": len(matches), "matches": matches[:20]}

@app.get("/recent")
def recent(days: int = Query(default=60, ge=1, le=365), limit: int = Query(default=50, ge=1, le=100), authorization: str | None = Header(default=None)):
    check_key(authorization, READ_API_KEY)
    data = load_data()
    perf_by_id = {(r.get("動画ID") or "").strip(): r for r in data.get("performance", [])}
    out = []
    for h in data.get("history", []):
        if recent_enough(h, days):
            item = dict(h)
            item["performance"] = perf_by_id.get((h.get("動画ID") or "").strip(), {})
            out.append(item)
            if len(out) >= limit:
                break
    return {"days": days, "count": len(out), "videos": out}

@app.get("/benchmarks")
def benchmarks(days: int = Query(default=120, ge=14, le=365), authorization: str | None = Header(default=None)):
    check_key(authorization, READ_API_KEY)
    data = load_data()
    perf = [r for r in data.get("performance", []) if recent_enough(r, days)]

    def aggregate(key):
        groups = {}
        for r in perf:
            label = (r.get(key) or "未分類").strip() or "未分類"
            groups.setdefault(label, []).append(r)
        out = []
        for label, rows in groups.items():
            out.append({
                key: label,
                "videos": len(rows),
                "median_views_total": med([fnum(r.get("視聴回数")) for r in rows]),
                "median_views_7d": med([fnum(r.get("公開後7日視聴回数")) for r in rows]),
                "median_impressions": med([fnum(r.get("インプレッション数")) for r in rows]),
                "median_ctr_pct": med([fnum(r.get("CTR_%")) for r in rows]),
                "median_avg_view_pct": med([fnum(r.get("平均視聴率_%")) for r in rows]),
            })
        return sorted(out, key=lambda x: (x["videos"], x.get("median_views_7d") or 0), reverse=True)

    return {
        "updated_at": data.get("updated_at"),
        "days": days,
        "video_count": len(perf),
        "by_theme": aggregate("主テーマ"),
        "by_hook": aggregate("フック型"),
    }

# ─────────────────────────────────────────────
# NEXT投資ワード（STOCK ARENAとはCloud Storage上で別オブジェクトに完全分離）
# ─────────────────────────────────────────────

@app.post("/admin/sync/next")
def sync_next(payload: SyncPayload, authorization: str | None = Header(default=None)):
    check_key(authorization, WRITE_API_KEY)
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_updated_at": payload.source_updated_at,
        "history": payload.history,
        "performance": payload.performance,
    }
    save_next_data(data)
    return {"ok": True, "history_count": len(payload.history), "performance_count": len(payload.performance)}

@app.get("/next/snapshot")
def next_snapshot(recent_limit: int = Query(default=20, ge=1, le=50), authorization: str | None = Header(default=None)):
    check_key(authorization, READ_API_KEY)
    data = load_next_data()
    perf_by_id = {(r.get("動画ID") or "").strip(): r for r in data.get("performance", [])}
    recent = []
    for h in data.get("history", [])[:recent_limit]:
        item = dict(h)
        item["performance"] = perf_by_id.get((h.get("動画ID") or "").strip(), {})
        recent.append(item)
    return {
        "updated_at": data.get("updated_at"),
        "history_count": len(data.get("history", [])),
        "performance_count": len(data.get("performance", [])),
        "recent": recent,
    }

@app.get("/next/benchmarks")
def next_benchmarks(days: int = Query(default=120, ge=14, le=365), authorization: str | None = Header(default=None)):
    check_key(authorization, READ_API_KEY)
    data = load_next_data()
    perf = [r for r in data.get("performance", []) if recent_enough(r, days)]

    # NEXTはまだ動画数が少ないため、テーマ別集計などは行わず全体集計のみ返す。
    # データが増えた段階で by_theme / by_hook 相当を追加できるよう、
    # STOCK ARENA側と同じ集計ヘルパー（fnum/med/recent_enough）をそのまま使う設計にしてある。
    overall = {
        "videos": len(perf),
        "median_views_total": med([fnum(r.get("視聴回数")) for r in perf]),
        "median_views_7d": med([fnum(r.get("公開後7日視聴回数")) for r in perf]),
        "median_impressions": med([fnum(r.get("インプレッション数")) for r in perf]),
        "median_ctr_pct": med([fnum(r.get("CTR_%")) for r in perf]),
        "median_avg_view_pct": med([fnum(r.get("平均視聴率_%")) for r in perf]),
    }

    return {
        "updated_at": data.get("updated_at"),
        "days": days,
        "video_count": len(perf),
        "overall": overall,
    }
