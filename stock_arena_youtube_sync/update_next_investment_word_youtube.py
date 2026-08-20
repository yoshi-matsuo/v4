#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NEXT投資ワード YouTube data auto-updater

STOCK ARENA用の update_stock_arena_youtube.py とは完全に独立したスクリプト。
同じYouTubeチャンネル・同じOAuth認証情報を読み取り専用で共有するが、
STOCK ARENAの履歴・PerformanceCSV・reachキャッシュには一切書き込まない。

What it does
------------
1. 認証済みチャンネルのアップロード一覧を取得する（STOCK ARENAと同じチャンネル）。
2. タイトル末尾が「｜NEXT投資ワード」の動画だけを対象に抽出する。
3. next_investment_word_history.csv / next_investment_word_youtube_performance.csv
   に保存する（STOCK ARENA側のファイルとは別系統）。
4. YouTube Analytics APIで再生数・視聴時間などを取得する。
5. YouTube Reporting API（channel_reach_basic_a1）は既存のSTOCK ARENA側のジョブを
   そのまま参照し、NEXT動画に該当する行だけを next_investment_word_reach_daily.csv
   に抽出保存する（新規ジョブは作成しない）。
6. NEXT専用CSVをCloud Run APIの /admin/sync/next へ送信する
   （STOCK ARENAの /admin/sync とは別エンドポイント・別Cloud Storageオブジェクト）。
   Cloud同期に失敗してもローカルCSVの生成自体は失敗させない。

テーマ分類・フック分類などの独自分析ロジックは今回実装しない。
まずはYouTubeから取得できる客観的な実績データの蓄積のみを行う。
"""

from __future__ import annotations

import csv
import json
import re
import sys
import requests
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parent

CONFIG_PATH = ROOT / "next_investment_word_sync_config.json"

# OAuth認証情報はSTOCK ARENAと同じ1チャンネル・同じ認証済みトークンを読み取り専用で共有する。
# （別トークンを新規発行すると同一チャンネルへの二重同意を招くだけなので、あえて共有する）
CLIENT_SECRET_PATH = ROOT / "client_secret.json"
TOKEN_PATH = ROOT / "youtube_token.json"

HISTORY_PATH = ROOT / "next_investment_word_history.csv"
PERF_PATH = ROOT / "next_investment_word_youtube_performance.csv"
REACH_CACHE_PATH = ROOT / "next_investment_word_reach_daily.csv"

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
                "STOCK ARENA側と同じフォルダの client_secret.json を使用してください。"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds


def parse_iso8601_duration(value: str) -> int:
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
    for row in rows:
        if "動画ID" in row and row["動画ID"] is not None:
            row["動画ID"] = row["動画ID"].strip()
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


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
        chunk = video_ids[i:i + 50]
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


def is_next_investment_word_video(v: dict, config: dict) -> bool:
    """
    タイトル末尾が「｜NEXT投資ワード」の動画だけを対象とする。
    STOCK ARENAや他番組の動画を混入させないよう、判定はこの1条件のみに絞る。
    """
    if v["privacy_status"] != "public":
        return False
    if v["duration_seconds"] < int(config.get("min_duration_seconds", 180)):
        return False

    suffix = config.get("title_suffix", "｜NEXT投資ワード")
    return v["title"].strip().endswith(suffix)


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


def normalize_report_date(d: str) -> str:
    # YouTube Reporting APIのCSVは日付を"YYYYMMDD"（ハイフンなし）で返す場合がある。
    # STOCK ARENA側と同じ正規化をNEXT側でも行い、日付形式を統一しておく。
    d = (d or "").strip()
    if d and "-" not in d and len(d) == 8 and d.isdigit():
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return d


def find_existing_reach_job(reporting) -> str | None:
    """
    STOCK ARENA側が作成済みのchannel_reach_basic_a1ジョブ（チャンネル単位）を
    そのまま参照する。NEXT側では新規ジョブを作成しない。
    """
    target_type = "channel_reach_basic_a1"
    resp = reporting.jobs().list().execute()
    for job in resp.get("jobs", []):
        if job.get("reportTypeId") == target_type:
            return job["id"]
    return None


def update_next_reach_cache(
    reporting, creds: Credentials, job_id: str, next_video_ids: set[str]
) -> dict:
    """
    既存のchannel_reach_basic_a1ジョブのレポート（チャンネル全体分）を読み取り、
    NEXT対象動画のIDに該当する行だけをNEXT専用キャッシュに保存する。
    STOCK ARENA側の stock_arena_reach_daily.csv には一切書き込まない。
    """
    cache: dict[tuple[str, str], dict] = {}
    for r in read_csv_dict(REACH_CACHE_PATH):
        r["date"] = normalize_report_date(r.get("date", ""))
        cache[(r["date"], r["video_id"])] = r

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
            if vid not in next_video_ids:
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
        print(f"[OK] NEXT Reach日次データを更新: {imported}行読み込み")
    return cache


def aggregate_next_reach(video_id: str, reach_cache: dict) -> tuple[str, str, str]:
    new_imp = 0
    new_click_est = 0.0

    for (_d_str, vid), r in reach_cache.items():
        if vid != video_id:
            continue
        imp = as_int(r.get("video_thumbnail_impressions"))
        ctr_raw = as_float(r.get("video_thumbnail_impressions_ctr"))
        ctr_pct = ctr_raw * 100.0 if 0 <= ctr_raw <= 1 else ctr_raw

        new_imp += imp
        new_click_est += imp * ctr_pct / 100.0

    if new_imp > 0:
        total_ctr = new_click_est / new_imp * 100.0
        return str(new_imp), f"{total_ctr:.2f}", "更新済み"

    return "", "", "取得待ち"


def push_next_data(config: dict) -> None:
    """
    NEXT専用CSVをCloud Run APIの /admin/sync/next へ送信する。
    STOCK ARENAの /admin/sync とは別エンドポイント・別Cloud Storageオブジェクトなので、
    ここでの送信がSTOCK ARENA側のCloudデータに影響することはない。
    ここでの例外は握りつぶして警告のみ表示する。NEXT同期の失敗が
    NEXTローカルCSVの生成やSTOCK ARENA側の処理を巻き込むことがないようにするため。
    """
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
            f"{api_url}/admin/sync/next",
            headers={"Authorization": f"Bearer {write_key}"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"[OK] NEXT投資ワード Cloud同期: history={result.get('history_count')} / performance={result.get('performance_count')}")
    except Exception as e:
        print(f"[WARN] NEXT投資ワード Cloud同期失敗: {e}")


def main():
    config = load_config()

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    reporting = build("youtubereporting", "v1", credentials=creds, cache_discovery=False)

    ch = get_authenticated_channel(youtube)
    print(f"[OK] 認証チャンネル: {ch['channel_title']}")

    upload_ids = list_upload_ids(youtube, ch["uploads_playlist"])
    metadata = get_video_metadata(youtube, upload_ids)

    videos = [v for v in metadata if is_next_investment_word_video(v, config)]
    videos.sort(key=lambda v: v["published_at"], reverse=True)

    print(f"[OK] NEXT投資ワード動画: {len(videos)}本")
    for v in videos:
        print(f"  - {v['published_date_jst']} / {v['title']}")

    latest_day = analytics_latest_complete_day(analytics)
    print(f"[OK] Analytics最新確定日: {latest_day}")

    reach_status_note = ""
    job_id = find_existing_reach_job(reporting)
    if job_id is None:
        # STOCK ARENA側のジョブが未作成の場合のみ発生。NEXT側では新規作成しない。
        print("[WARN] channel_reach_basic_a1 ジョブが見つかりません。"
              "先にSTOCK ARENA側のupdate_stock_arena_youtube.pyを一度実行してください。")
        reach_cache = {}
        reach_status_note = "ジョブ未作成"
    else:
        next_video_ids = {v["video_id"] for v in videos}
        try:
            reach_cache = update_next_reach_cache(reporting, creds, job_id, next_video_ids)
        except HttpError as e:
            print(f"[WARN] Reachレポート取得待ち: {e}")
            reach_cache = {}
            for r in read_csv_dict(REACH_CACHE_PATH):
                r["date"] = normalize_report_date(r.get("date", ""))
                reach_cache[(r["date"], r["video_id"])] = r

    history_rows = []
    perf_rows = []

    for v in videos:
        history_rows.append({
            "公開日": v["published_date_jst"].isoformat(),
            "動画ID": v["video_id"],
            "動画タイトル": v["title"],
        })

        try:
            overall = query_video_overall(analytics, v, latest_day)
            early = query_first_days_views(analytics, v, latest_day)
        except HttpError as e:
            print(f"[WARN] Analytics取得失敗 {v['video_id']}: {e}")
            overall, early = {}, {"day1": "", "day3": "", "day7": ""}

        if job_id is None:
            imp, ctr, reach_status = "", "", reach_status_note
        else:
            imp, ctr, reach_status = aggregate_next_reach(v["video_id"], reach_cache)

        avg_dur = overall.get("average_view_duration")
        avg_pct = overall.get("average_view_percentage")

        perf_rows.append({
            "公開日": v["published_date_jst"].isoformat(),
            "動画ID": v["video_id"],
            "動画タイトル": v["title"],
            "長さ秒": v["duration_seconds"],
            "視聴回数": overall.get("views", ""),
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
            "Analytics最終日": latest_day.isoformat(),
        })

    history_fields = ["公開日", "動画ID", "動画タイトル"]
    perf_fields = [
        "公開日", "動画ID", "動画タイトル", "長さ秒",
        "視聴回数", "公開日視聴回数", "公開後3日視聴回数", "公開後7日視聴回数",
        "総再生時間_時間", "平均視聴時間", "平均視聴率_%",
        "インプレッション数", "CTR_%", "Reachデータ状態",
        "チャンネル登録者増減", "Analytics最終日",
    ]

    write_csv(HISTORY_PATH, history_rows, history_fields)
    write_csv(PERF_PATH, perf_rows, perf_fields)

    push_next_data(config)

    print()
    print(f"[完了] {HISTORY_PATH.name}: {len(history_rows)}本")
    print(f"[完了] {PERF_PATH.name}: {len(perf_rows)}本")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        raise
