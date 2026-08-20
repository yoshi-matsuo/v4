#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STOCK ARENA YouTube data auto-updater

What it does
------------
1. Reads the authenticated channel's upload list from YouTube Data API.
2. Updates stock_arena_history.csv with newly published STOCK ARENA videos.
3. Updates views/watch metrics from YouTube Analytics API.
4. Creates a YouTube Reporting API reach job once, then automatically imports
   thumbnail impressions / CTR reports as they become available.
5. Preserves the initial CSV as the baseline for older impression/CTR data and
   adds newer reach data on top of it.

One-time setup
--------------
- Put client_secret.json in the same folder as this script.
- Enable:
  * YouTube Data API v3
  * YouTube Analytics API
  * YouTube Reporting API
- First run opens a browser for Google OAuth, then saves token.json.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
import requests
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parent

CONFIG_PATH = ROOT / "stock_arena_sync_config.json"
CLIENT_SECRET_PATH = ROOT / "client_secret.json"
TOKEN_PATH = ROOT / "youtube_token.json"

HISTORY_PATH = ROOT / "stock_arena_history.csv"
PERF_PATH = ROOT / "stock_arena_youtube_performance.csv"
BASELINE_PERF_PATH = ROOT / "stock_arena_baseline_performance.csv"
REACH_CACHE_PATH = ROOT / "stock_arena_reach_daily.csv"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

JST = ZoneInfo("Asia/Tokyo")
PT = ZoneInfo("America/Los_Angeles")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"設定ファイルがありません: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def get_credentials() -> Credentials:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    if not creds or not creds.valid:
        if not CLIENT_SECRET_PATH.exists():
            raise FileNotFoundError(
                "client_secret.json がありません。\n"
                "Google CloudでOAuthデスクトップアプリを作成し、このスクリプトと同じフォルダに置いてください。"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds


def parse_iso8601_duration(value: str) -> int:
    # YouTube duration example: PT8M16S / PT1H2M3S
    m = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        value or "",
    )
    if not m:
        return 0
    return (
        int(m.group("days") or 0) * 86400
        + int(m.group("hours") or 0) * 3600
        + int(m.group("minutes") or 0) * 60
        + int(m.group("seconds") or 0)
    )


def seconds_to_hms(seconds: float | int | None) -> str:
    if seconds is None:
        return ""
    seconds = int(round(float(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def as_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def as_int(v, default=0):
    try:
        return int(round(float(v)))
    except Exception:
        return default


def read_csv_dict(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # YouTube video IDの前後空白を常に除去して同一動画の重複判定を安定させる。
    for row in rows:
        if "動画ID" in row and row["動画ID"] is not None:
            row["動画ID"] = row["動画ID"].strip()
        if "video_id" in row and row["video_id"] is not None:
            row["video_id"] = row["video_id"].strip()
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def snapshot_baseline_if_needed():
    # Preserve the first performance CSV permanently as the pre-API baseline.
    if PERF_PATH.exists() and not BASELINE_PERF_PATH.exists():
        shutil.copy2(PERF_PATH, BASELINE_PERF_PATH)
        print(f"[OK] 初期ベースライン保存: {BASELINE_PERF_PATH.name}")


def get_authenticated_channel(youtube):
    resp = youtube.channels().list(part="snippet,contentDetails", mine=True).execute()
    if not resp.get("items"):
        raise RuntimeError("認証したGoogleアカウントにYouTubeチャンネルが見つかりません。")
    ch = resp["items"][0]
    return {
        "channel_id": ch["id"],
        "channel_title": ch["snippet"]["title"],
        "uploads_playlist": ch["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def list_upload_ids(youtube, uploads_playlist: str) -> list[str]:
    ids = []
    token = None
    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=token,
        ).execute()
        for item in resp.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                vid = vid.strip()
                if vid:
                    ids.append(vid)
        token = resp.get("nextPageToken")
        if not token:
            break
    return ids


def get_video_metadata(youtube, video_ids: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        resp = youtube.videos().list(
            part="snippet,contentDetails,statistics,status",
            id=",".join(chunk),
            maxResults=50,
        ).execute()
        for item in resp.get("items", []):
            published = datetime.fromisoformat(
                item["snippet"]["publishedAt"].replace("Z", "+00:00")
            )
            duration = parse_iso8601_duration(item["contentDetails"].get("duration", ""))
            out.append({
                "video_id": item["id"].strip(),
                "title": item["snippet"]["title"],
                "published_at": published,
                "published_date_jst": published.astimezone(JST).date(),
                "published_date_pt": published.astimezone(PT).date(),
                "duration_seconds": duration,
                "privacy_status": item.get("status", {}).get("privacyStatus", ""),
                "public_view_count": as_int(item.get("statistics", {}).get("viewCount")),
            })
    return out


def is_stock_arena_video(v: dict, config: dict, baseline_video_ids: set[str]) -> bool:
    """
    STOCK ARENAの個別企業動画だけを採用する。

    - 初期ベースラインに含まれていた動画はそのまま維持。
    - 新方式: タイトル末尾の番組タグ（｜STOCK ARENA / ｜NEXT投資ワード / ｜COMPANY ARCHIVE）で
      明示的に採用・除外を判定する。
    - 旧方式（移行期間の互換処理）: 末尾タグがない動画は、従来どおり
      exclude_title_keywords と先頭【企業名】形式の判定を使う。
    """
    if v["privacy_status"] != "public":
        return False
    if v["duration_seconds"] < int(config.get("min_duration_seconds", 180)):
        return False

    title = v["title"]

    # 初期100本など、すでにSTOCK ARENAとして確定した動画は維持。
    if v["video_id"] in baseline_video_ids:
        return True

    # 新方式: タイトル末尾の番組タグによる明示判定（最優先）。
    stripped_title = title.strip()
    if stripped_title.endswith("｜NEXT投資ワード") or stripped_title.endswith("｜COMPANY ARCHIVE"):
        return False
    if stripped_title.endswith("｜STOCK ARENA"):
        return True

    # 旧方式（互換処理）: 末尾タグがまだ付いていない動画向けのフォールバック。
    for kw in config.get("exclude_title_keywords", []):
        if kw and kw.lower() in title.lower():
            return False

    # 【企業名】で始まる個別企業動画だけを採用。
    m = re.match(r"^【([^】]+)】", title)
    if not m:
        return False

    bracket = m.group(1).strip()
    generic_labels = {
        "日本株", "米国株", "NEXT投資ワード",
        "今日の日本株速報", "今日の米国株速報",
        "朝イチマーケット情報", "COMPANY ARCHIVE",
        "AI", "半導体", "データセンター", "防衛", "宇宙",
    }
    if bracket in generic_labels:
        return False

    return True


def extract_company(title: str) -> str:
    # Most STOCK ARENA titles begin with 【会社名】.
    m = re.match(r"^【([^】]+)】", title)
    if m:
        company = m.group(1).strip()
        generic = (
            "日本株", "決算", "上方修正", "S高", "暴落", "半導体", "AI",
            "防衛", "宇宙", "ストップ高", "最高益", "テンバガー"
        )
        if not any(g in company for g in generic):
            return re.sub(r"[/／]\s*(\d{4}|\d{3}[A-Z])$", "", company).strip()

    m = re.search(r"([一-龥ぁ-んァ-ヶA-Za-z0-9・＆&.]+)(?:\s*[/／]\s*(?:\d{4}|\d{3}[A-Z]))", title)
    if m:
        return m.group(1).strip()
    return ""


def extract_code(title: str) -> str:
    for p in (
        r"[/／]\s*(\d{4}|\d{3}[A-Z])(?:】|\s|$)",
        r"[（(](\d{4}|\d{3}[A-Z])[）)]",
    ):
        m = re.search(p, title)
        if m:
            return m.group(1)
    return ""


def infer_theme_and_hook(title: str) -> tuple[str, str]:
    # Lightweight only. Candidate Scout should still reason from the raw title.
    t = title.lower()

    themes = [
        ("AI・半導体・データセンター", ["ai", "半導体", "nvidia", "gpu", "hbm", "データセンター", "光電融合", "フィジカルai"]),
        ("防衛・宇宙・ドローン", ["防衛", "宇宙", "ドローン", "衛星", "ispace", "acsl"]),
        ("金融・金利", ["銀行", "金融", "日銀", "金利"]),
        ("原発・エネルギー", ["原発", "核融合", "蓄電", "電力", "エネルギー"]),
        ("消費・IP", ["任天堂", "サンリオ", "小売", "外食", "ゲーム"]),
        ("IT・DX・SaaS", ["saas", "dx", "aws", "クラウド", "ソフト"]),
    ]
    theme = "未分類"
    for label, kws in themes:
        if any(k in t for k in kws):
            theme = label
            break

    hooks = []
    if any(k in t for k in ["でも", "なのに", "リスク", "罠", "減益", "赤字", "急落", "重い", "死角", "依存"]):
        hooks.append("矛盾・逆説")
    if any(k in t for k in ["上方修正", "最高益", "利益", "決算", "増配", "v字"]):
        hooks.append("業績サプライズ")
    if any(k in t for k in ["協業", "提携", "採択", "受注", "量産", "参入", "特需"]):
        hooks.append("提携・需要変化")
    if any(k in t for k in ["急騰", "ストップ高", "s高", "爆上げ", "出来高"]):
        hooks.append("急騰・需給")
    hook = " × ".join(hooks) if hooks else "企業変化・深掘り"
    return theme, hook


def analytics_latest_complete_day(analytics) -> date:
    today_pt = datetime.now(PT).date()
    start = today_pt - timedelta(days=10)
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=start.isoformat(),
        endDate=today_pt.isoformat(),
        metrics="views",
        dimensions="day",
        sort="day",
    ).execute()
    rows = resp.get("rows", [])
    if rows:
        return date.fromisoformat(rows[-1][0])
    return today_pt - timedelta(days=2)


def query_video_overall(analytics, v: dict, end_day: date) -> dict:
    if v["published_date_pt"] > end_day:
        return {}
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=v["published_date_pt"].isoformat(),
        endDate=end_day.isoformat(),
        metrics=(
            "views,estimatedMinutesWatched,averageViewDuration,"
            "averageViewPercentage,subscribersGained,subscribersLost"
        ),
        filters=f"video=={v['video_id']}",
    ).execute()
    rows = resp.get("rows", [])
    if not rows:
        return {}
    row = rows[0]
    return {
        "views": as_int(row[0]),
        "estimated_minutes_watched": as_float(row[1]),
        "average_view_duration": as_float(row[2]),
        "average_view_percentage": as_float(row[3]),
        "subscribers_gained": as_int(row[4]),
        "subscribers_lost": as_int(row[5]),
    }


def query_first_days_views(analytics, v: dict, latest_day: date) -> dict:
    pub = v["published_date_pt"]
    if pub > latest_day:
        return {"day1": "", "day3": "", "day7": ""}

    end = min(pub + timedelta(days=6), latest_day)
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=pub.isoformat(),
        endDate=end.isoformat(),
        metrics="views",
        dimensions="day",
        filters=f"video=={v['video_id']}",
        sort="day",
    ).execute()

    by_day = {date.fromisoformat(r[0]): as_int(r[1]) for r in resp.get("rows", [])}

    def total(n: int):
        required_last = pub + timedelta(days=n - 1)
        if latest_day < required_last:
            return ""
        return sum(by_day.get(pub + timedelta(days=i), 0) for i in range(n))

    return {"day1": total(1), "day3": total(3), "day7": total(7)}


def ensure_reach_job(reporting) -> tuple[str, bool]:
    target_type = "channel_reach_basic_a1"
    resp = reporting.jobs().list().execute()
    for job in resp.get("jobs", []):
        if job.get("reportTypeId") == target_type:
            return job["id"], False

    job = reporting.jobs().create(
        body={"reportTypeId": target_type, "name": "STOCK ARENA reach auto sync"}
    ).execute()
    return job["id"], True


def normalize_report_date(d: str) -> str:
    # YouTube Reporting APIのCSVは日付を"YYYYMMDD"（ハイフンなし）で返す場合がある。
    # date.fromisoformat()はハイフン区切りしか受け付けないため、ここで正規化する。
    d = (d or "").strip()
    if d and "-" not in d and len(d) == 8 and d.isdigit():
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return d


def load_reach_cache() -> dict[tuple[str, str], dict]:
    cache = {}
    for r in read_csv_dict(REACH_CACHE_PATH):
        r["date"] = normalize_report_date(r.get("date", ""))
        cache[(r["date"], r["video_id"])] = r
    return cache


def update_reach_cache(reporting, creds: Credentials, job_id: str) -> dict:
    cache = load_reach_cache()
    session = AuthorizedSession(creds)

    reports = []
    token = None
    while True:
        resp = reporting.jobs().reports().list(
            jobId=job_id,
            pageSize=100,
            pageToken=token,
        ).execute()
        reports.extend(resp.get("reports", []))
        token = resp.get("nextPageToken")
        if not token:
            break

    # Older first, newer backfill versions overwrite the same date/video later.
    reports.sort(key=lambda x: x.get("createTime", ""))

    imported = 0
    for rep in reports:
        url = rep.get("downloadUrl")
        if not url:
            continue
        response = session.get(url, timeout=60)
        if response.status_code != 200:
            continue
        text = response.text
        reader = csv.DictReader(text.splitlines())
        for row in reader:
            d = normalize_report_date(row.get("date", ""))
            vid = row.get("video_id", "")
            if not d or not vid:
                continue
            cache[(d, vid)] = {
                "date": d,
                "channel_id": row.get("channel_id", ""),
                "video_id": vid,
                "video_thumbnail_impressions": row.get("video_thumbnail_impressions", ""),
                "video_thumbnail_impressions_ctr": row.get("video_thumbnail_impressions_ctr", ""),
            }
            imported += 1

    fields = [
        "date", "channel_id", "video_id",
        "video_thumbnail_impressions", "video_thumbnail_impressions_ctr"
    ]
    rows = sorted(cache.values(), key=lambda r: (r["date"], r["video_id"]))
    write_csv(REACH_CACHE_PATH, rows, fields)

    if imported:
        print(f"[OK] Reach日次データを更新: {imported}行読み込み")
    return cache


def aggregate_reach(
    video_id: str,
    baseline_row: dict | None,
    reach_cache: dict,
    baseline_cutoff: date,
) -> tuple[str, str, str]:

    baseline_imp = 0
    baseline_click_est = 0.0
    has_baseline = bool(baseline_row)

    if baseline_row:
        baseline_imp = as_int(baseline_row.get("インプレッション数"))
        baseline_ctr_pct = as_float(baseline_row.get("CTR_%"))
        baseline_click_est = baseline_imp * baseline_ctr_pct / 100.0

    new_imp = 0
    new_click_est = 0.0
    have_reach = False

    for (d_str, vid), r in reach_cache.items():
        if vid != video_id:
            continue
        d = date.fromisoformat(d_str)

        # For baseline videos, the original export already contains data through cutoff.
        if has_baseline and d <= baseline_cutoff:
            continue

        imp = as_int(r.get("video_thumbnail_impressions"))
        ctr_raw = as_float(r.get("video_thumbnail_impressions_ctr"))
        # Reporting API CTR is a ratio in many bulk reports; normalize if <=1.
        ctr_pct = ctr_raw * 100.0 if 0 <= ctr_raw <= 1 else ctr_raw

        new_imp += imp
        new_click_est += imp * ctr_pct / 100.0
        have_reach = True

    total_imp = baseline_imp + new_imp
    if total_imp > 0:
        total_ctr = (baseline_click_est + new_click_est) / total_imp * 100.0
        status = "更新済み" if have_reach else ("初期値" if has_baseline else "取得待ち")
        return str(total_imp), f"{total_ctr:.2f}", status

    return "", "", "取得待ち"


def push_candidate_scout_data(config: dict) -> None:
    api_url = (config.get("cloud_api_url") or "").rstrip("/")
    write_key = config.get("cloud_write_key") or ""
    if not api_url or not write_key:
        return

    payload = {
        "history": read_csv_dict(HISTORY_PATH),
        "performance": read_csv_dict(PERF_PATH),
        "source_updated_at": datetime.now(JST).isoformat(),
    }

    try:
        resp = requests.post(
            f"{api_url}/admin/sync",
            headers={"Authorization": f"Bearer {write_key}"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"[OK] Candidate Scout Cloud同期: history={result.get('history_count')} / performance={result.get('performance_count')}")
    except Exception as e:
        print(f"[WARN] Candidate Scout Cloud同期失敗: {e}")


def main():
    config = load_config()
    baseline_cutoff = date.fromisoformat(config["baseline_cutoff"])

    snapshot_baseline_if_needed()
    baseline_perf_rows = read_csv_dict(BASELINE_PERF_PATH)
    baseline_perf_by_id = {
        (r.get("動画ID", "") or "").strip(): r
        for r in baseline_perf_rows
        if (r.get("動画ID", "") or "").strip()
    }
    baseline_video_ids = set(baseline_perf_by_id)

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    reporting = build("youtubereporting", "v1", credentials=creds, cache_discovery=False)

    ch = get_authenticated_channel(youtube)
    print(f"[OK] 認証チャンネル: {ch['channel_title']}")

    upload_ids = list_upload_ids(youtube, ch["uploads_playlist"])

    # uploadsプレイリストだけに依存しない。
    # 初期ベースラインに含まれる既知のSTOCK ARENA動画IDも必ず直接照会する。
    # これにより、公開中なのにuploads一覧から何らかの理由で取りこぼした動画も拾える。
    lookup_ids = list(dict.fromkeys(upload_ids + list(baseline_video_ids)))

    metadata = get_video_metadata(youtube, lookup_ids)

    # YouTube Data API側で既知の動画IDがmetadataに返らない場合でも、
    # 初期ベースラインにあるSTOCK ARENA動画は落とさない。
    # baselineの公開日・タイトル・長さを使って最小metadataを補完し、
    # Analyticsは動画IDで引き続き更新する。
    returned_ids = {v["video_id"] for v in metadata}
    missing_baseline_ids = baseline_video_ids - returned_ids

    if missing_baseline_ids:
        print(f"[WARN] Data API metadata未返却の既知動画: {len(missing_baseline_ids)}本")
        for vid in sorted(missing_baseline_ids):
            row = baseline_perf_by_id.get(vid, {})
            pub_str = row.get("公開日", "")
            title = row.get("動画タイトル", "")
            duration = as_int(row.get("長さ秒"))

            if not pub_str or not title:
                print(f"[WARN] baseline補完不可: {vid}")
                continue

            pub_jst = datetime.fromisoformat(pub_str).replace(tzinfo=JST)
            metadata.append({
                "video_id": vid,
                "title": title,
                "published_at": pub_jst.astimezone(timezone.utc),
                "published_date_jst": pub_jst.date(),
                "published_date_pt": pub_jst.astimezone(PT).date(),
                "duration_seconds": duration,
                # baseline収録済み＝STOCK ARENA既知動画として保持。
                "privacy_status": "public",
                "public_view_count": as_int(row.get("視聴回数")),
            })
            print(f"[INFO] baselineから補完: {vid} | {title}")

    videos = [
        v for v in metadata
        if is_stock_arena_video(v, config, baseline_video_ids)
    ]
    videos.sort(key=lambda v: v["published_at"], reverse=True)

    print(f"[OK] STOCK ARENA長尺動画: {len(videos)}本")
    if videos:
        print(f"[OK] 最新動画: {videos[0]['published_date_jst']} / {videos[0]['title']}")

    latest_day = analytics_latest_complete_day(analytics)
    print(f"[OK] Analytics最新確定日: {latest_day}")

    job_id, created = ensure_reach_job(reporting)
    if created:
        print("[INFO] Reachレポートジョブを作成しました。")
        print("[INFO] インプレッション/CTRは通常24〜48時間後から自動反映され、過去30日もバックフィルされます。")

    try:
        reach_cache = update_reach_cache(reporting, creds, job_id)
    except HttpError as e:
        print(f"[WARN] Reachレポート取得待ち: {e}")
        reach_cache = load_reach_cache()

    old_history = {
        (r.get("動画ID", "") or "").strip(): r
        for r in read_csv_dict(HISTORY_PATH)
        if (r.get("動画ID", "") or "").strip()
    }

    history_rows = []
    perf_rows = []

    for idx, v in enumerate(videos, 1):
        old = old_history.get(v["video_id"], {})
        company = old.get("企業名") or extract_company(v["title"])
        code = old.get("証券コード") or extract_code(v["title"])
        theme = old.get("主テーマ")
        hook = old.get("フック型")
        if not theme or not hook:
            inferred_theme, inferred_hook = infer_theme_and_hook(v["title"])
            theme = theme or inferred_theme
            hook = hook or inferred_hook

        history_rows.append({
            "公開日": v["published_date_jst"].isoformat(),
            "動画ID": v["video_id"],
            "企業名": company,
            "証券コード": code,
            "動画タイトル": v["title"],
            "主テーマ": theme,
            "フック型": hook,
        })

        try:
            overall = query_video_overall(analytics, v, latest_day)
            early = query_first_days_views(analytics, v, latest_day)
        except HttpError as e:
            print(f"[WARN] Analytics取得失敗 {v['video_id']}: {e}")
            overall, early = {}, {"day1": "", "day3": "", "day7": ""}

        imp, ctr, reach_status = aggregate_reach(
            v["video_id"],
            baseline_perf_by_id.get(v["video_id"]),
            reach_cache,
            baseline_cutoff,
        )

        avg_dur = overall.get("average_view_duration")
        avg_pct = overall.get("average_view_percentage")

        perf_rows.append({
            "公開日": v["published_date_jst"].isoformat(),
            "動画ID": v["video_id"],
            "企業名": company,
            "証券コード": code,
            "動画タイトル": v["title"],
            "長さ秒": v["duration_seconds"],
            "視聴回数": overall.get("views", ""),
            "YouTube公開視聴回数": v["public_view_count"],
            "公開日視聴回数": early["day1"],
            "公開後3日視聴回数": early["day3"],
            "公開後7日視聴回数": early["day7"],
            "総再生時間_時間": (
                round(overall["estimated_minutes_watched"] / 60.0, 4)
                if "estimated_minutes_watched" in overall else ""
            ),
            "平均視聴時間": seconds_to_hms(avg_dur) if avg_dur is not None else "",
            "平均視聴率_%": round(avg_pct, 2) if avg_pct is not None else "",
            "インプレッション数": imp,
            "CTR_%": ctr,
            "Reachデータ状態": reach_status,
            "チャンネル登録者増減": (
                overall.get("subscribers_gained", 0) - overall.get("subscribers_lost", 0)
                if overall else ""
            ),
            "主テーマ": theme,
            "フック型": hook,
            "Analytics最終日": latest_day.isoformat(),
        })

        if idx % 20 == 0:
            print(f"[INFO] Analytics処理: {idx}/{len(videos)}")

    history_fields = [
        "公開日", "動画ID", "企業名", "証券コード",
        "動画タイトル", "主テーマ", "フック型"
    ]
    perf_fields = [
        "公開日", "動画ID", "企業名", "証券コード", "動画タイトル",
        "長さ秒", "視聴回数", "YouTube公開視聴回数",
        "公開日視聴回数", "公開後3日視聴回数", "公開後7日視聴回数",
        "総再生時間_時間", "平均視聴時間", "平均視聴率_%",
        "インプレッション数", "CTR_%", "Reachデータ状態",
        "チャンネル登録者増減", "主テーマ", "フック型", "Analytics最終日"
    ]

    write_csv(HISTORY_PATH, history_rows, history_fields)
    write_csv(PERF_PATH, perf_rows, perf_fields)
    push_candidate_scout_data(config)

    print()
    print(f"[完了] {HISTORY_PATH.name}: {len(history_rows)}本")
    print(f"[完了] {PERF_PATH.name}: {len(perf_rows)}本")
    print("[完了] 新しい公開動画は次回以降も自動追加されます。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        raise
