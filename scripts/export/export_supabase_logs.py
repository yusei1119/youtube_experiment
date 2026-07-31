"""Supabase の view_logs テーブルを JSONL に書き出すスクリプト。

analyze_youtube_logs.py がそのまま読める data/logs.jsonl 形式（1行1イベント）で
出力する。experiment_sessionsから実測開始・終了時刻も結合する。
PostgREST の REST API を直接叩く。

認証情報は .env.local（または環境変数）から読む:
  NEXT_PUBLIC_SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

使い方:
  python -m scripts.export.export_supabase_logs
  python -m scripts.export.export_supabase_logs 出力先.jsonl

既存データを保護するため、実際の出力名には
logs_YYYYMMDD_HHMMSS.jsonl のように実行日時を付ける。
"""

import json
import argparse
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.common.output_versioning import versioned_file

try:
    import requests
except ModuleNotFoundError:
    requests = None

LOG_TABLE = "view_logs"
SESSION_TABLE = "experiment_sessions"
PAGE_SIZE = 1000  # PostgREST の1リクエスト上限に合わせて分割取得
DEFAULT_OUT = "data/exports/youtube_logs.jsonl"

# Supabase の主キー列名 → ローカル JSONL の列名（既存ファイルに合わせる）
COLUMN_RENAME = {"id": "log_id"}


def load_env(path=".env.local"):
    """.env.local の KEY=VALUE を環境変数に取り込む（既存の環境変数は上書きしない）。"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_all(base_url, headers, order_column):
    """指定テーブルをページングしながら全件取得する。"""
    rows = []
    offset = 0
    while True:
        params = {
            "select": "*",
            "order": f"{order_column}.asc",
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        batch = fetch_page(base_url, headers, params)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def enrich_logs_with_session_timing(log_rows, session_rows):
    """ログへセッションの実測開始・終了時刻を付与する。"""
    sessions = {str(row.get("id")): row for row in session_rows if row.get("id")}
    enriched = []
    for source in log_rows:
        row = dict(source)
        session = sessions.get(str(row.get("session_id")), {})
        row["session_started_at"] = session.get("started_at")
        row["session_expires_at"] = session.get("expires_at")
        row["session_finished_at"] = session.get("finished_at")
        enriched.append(row)
    return enriched


def fetch_page(base_url, headers, params):
    """1ページ分を取得する。requests がなければ標準ライブラリで取得する。"""
    if requests is not None:
        resp = requests.get(base_url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{base_url}?{query}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase API error: {error.code} {detail}") from error


def parse_args():
    parser = argparse.ArgumentParser(description="Supabaseの視聴ログをJSONL出力")
    parser.add_argument("output", nargs="?", default=DEFAULT_OUT, help="基準出力名")
    parser.add_argument("--run-id", default=None, help=argparse.SUPPRESS)
    return parser.parse_args()


def main():
    args = parse_args()
    out_path = versioned_file(args.output, args.run_id)

    load_env()
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "Supabase環境変数が未設定です（NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）。"
        )

    rest_url = f"{url.rstrip('/')}/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    log_rows = fetch_all(f"{rest_url}/{LOG_TABLE}", headers, "server_time")
    session_rows = fetch_all(f"{rest_url}/{SESSION_TABLE}", headers, "id")
    rows = enrich_logs_with_session_timing(log_rows, session_rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            for src, dst in COLUMN_RENAME.items():
                if src in row and dst not in row:
                    row[dst] = row.pop(src)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    participants = sorted({r.get("participant_id") for r in rows if r.get("participant_id")})
    print(f"取得: {len(rows)} イベント → {out_path}")
    print(f"参加者: {len(participants)} 人 {participants}")


if __name__ == "__main__":
    main()
