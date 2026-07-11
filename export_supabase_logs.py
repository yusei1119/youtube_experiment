"""Supabase の view_logs テーブルを JSONL に書き出すスクリプト。

analyze_youtube_logs.py がそのまま読める data/logs.jsonl 形式（1行1イベント）で
出力する。PostgREST の REST API を直接叩く。

認証情報は .env.local（または環境変数）から読む:
  NEXT_PUBLIC_SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

使い方:
  python export_supabase_logs.py                 # data/logs.jsonl に出力
  python export_supabase_logs.py 出力先.jsonl     # 出力先を指定
"""

import os
import sys
import json
import urllib.error
import urllib.parse
import urllib.request

try:
    import requests
except ModuleNotFoundError:
    requests = None

TABLE = "view_logs"
PAGE_SIZE = 1000  # PostgREST の1リクエスト上限に合わせて分割取得
DEFAULT_OUT = "data/logs.jsonl"

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


def fetch_all(base_url, headers):
    """view_logs を server_time 昇順でページングしながら全件取得する。"""
    rows = []
    offset = 0
    while True:
        params = {
            "select": "*",
            "order": "server_time.asc",
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


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT

    load_env()
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "Supabase環境変数が未設定です（NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）。"
        )

    base_url = f"{url.rstrip('/')}/rest/v1/{TABLE}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    rows = fetch_all(base_url, headers)

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

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
