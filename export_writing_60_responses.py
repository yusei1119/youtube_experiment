"""SupabaseのWriting_task_60回答をCSVへ出力する。

必要な環境変数（.env.localからも読み込み可）:
  NEXT_PUBLIC_SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

使用例:
  python export_writing_60_responses.py
  python export_writing_60_responses.py --output writing_60_responses.csv
  python export_writing_60_responses.py --format long
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PAGE_SIZE = 1000
DEFAULT_OUTPUT = "writing_60_responses.csv"


def load_env(path: str = ".env.local") -> None:
    """簡易的に.env.localを読み込む（既存環境変数を優先）。"""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_page(url: str, headers: dict[str, str], params: dict[str, Any]) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase API error {error.code}: {detail}") from error


def fetch_all(url: str, headers: dict[str, str], params: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page_params = {**params, "limit": PAGE_SIZE, "offset": offset}
        batch = fetch_page(url, headers, page_params)
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def flatten_long(submissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    submission_fields = [
        "id", "survey_id", "participant_id", "viewing_duration", "questionnaire_number",
        "total_questionnaires", "assignment_seed",
        "page_randomization_id", "started_at", "completed_at", "total_duration_sec",
        "total_answer_duration_sec", "total_char_count", "created_at",
    ]
    for submission in submissions:
        common = {
            ("submission_id" if key == "id" else key): submission.get(key)
            for key in submission_fields
        }
        for response in submission.get("writing_60_responses", []):
            response = {key: value for key, value in response.items() if key != "id"}
            rows.append({**common, **response})
    return rows


def flatten_wide(submissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """参加者ごとに1行とし、5カテゴリの回答を横方向へ展開する。"""
    rows: list[dict[str, Any]] = []
    for submission in submissions:
        row = {
            ("submission_id" if key == "id" else key): value
            for key, value in submission.items()
            if key != "writing_60_responses"
        }
        for response in submission.get("writing_60_responses", []):
            prefix = response["category_key"]
            for key in ("question_id", "display_order", "category_label", "variant_number",
                        "question_text", "answer_text", "answer_char_count", "first_shown_sec",
                        "latency_sec", "writing_duration_sec", "visits",
                        "revision_count"):
                row[f"{prefix}_{key}"] = response.get(key)
        rows.append(row)
    duration_order = {f"{minutes}min": minutes for minutes in range(5, 31, 5)}
    rows.sort(key=lambda row: (
        str(row.get("participant_id", "")),
        duration_order.get(str(row.get("viewing_duration", "")), 999),
    ))
    return rows


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output.write_text("", encoding="utf-8-sig")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with output.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Writing_task_60の回答をCSV出力")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--format", choices=("long", "wide"), default="wide",
        help="wide: 参加者ごとに1行（既定）、long: 1回答で1行",
    )
    parser.add_argument("--survey-id", default=None, help="指定したsurvey_idだけを出力")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env()
    base_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not base_url or not service_key:
        raise SystemExit(
            "NEXT_PUBLIC_SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を設定してください。"
        )

    params: dict[str, Any] = {
        "select": (
            "id,survey_id,participant_id,viewing_duration,questionnaire_number,total_questionnaires,"
            "assignment_seed,page_randomization_id,started_at,completed_at,total_duration_sec,"
            "total_answer_duration_sec,total_char_count,created_at,writing_60_responses(*)"
        ),
        "order": "created_at.asc",
        "writing_60_responses.order": "display_order.asc",
    }
    if args.survey_id:
        params["survey_id"] = f"eq.{args.survey_id}"

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
    }
    endpoint = f"{base_url.rstrip('/')}/rest/v1/writing_60_submissions"
    submissions = fetch_all(endpoint, headers, params)
    rows = flatten_long(submissions) if args.format == "long" else flatten_wide(submissions)
    output = Path(args.output)
    write_csv(rows, output)
    print(f"{len(submissions)}件の提出・{len(rows)}行を {output} に出力しました。")


if __name__ == "__main__":
    main()
