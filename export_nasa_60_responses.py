"""SupabaseのNASA_task_60回答を分析用CSVへ出力する。

必要な環境変数（.env.localからも読み込み可）:
  NEXT_PUBLIC_SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

使用例:
  python export_nasa_60_responses.py
  python export_nasa_60_responses.py --format long
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
DEFAULT_OUTPUT = "nasa_task_60_results.csv"
DIMENSION_ORDER = (
    "mental", "physical", "temporal", "performance",
    "effort", "frustration", "overall",
)
DURATION_ORDER = {f"{minutes}min": minutes for minutes in range(5, 31, 5)}


def load_env(path: str = ".env.local") -> None:
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
        batch = fetch_page(url, headers, {**params, "limit": PAGE_SIZE, "offset": offset})
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def flatten_long(submissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for submission in submissions:
        common = {
            ("submission_id" if key == "id" else key): value
            for key, value in submission.items()
            if key != "nasa_60_responses"
        }
        for response in submission.get("nasa_60_responses", []):
            response = {key: value for key, value in response.items() if key != "id"}
            rows.append({**common, **response})
    return rows


def flatten_wide(submissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """1回の提出を1行にし、7尺度を横方向へ展開する。"""
    rows: list[dict[str, Any]] = []
    for submission in submissions:
        row = {
            ("submission_id" if key == "id" else key): value
            for key, value in submission.items()
            if key != "nasa_60_responses"
        }
        responses_by_key = {
            response["dimension_key"]: response
            for response in submission.get("nasa_60_responses", [])
        }
        for dimension in DIMENSION_ORDER:
            response = responses_by_key.get(dimension, {})
            for key in (
                "question_id", "dimension_label", "display_order", "question_text",
                "slider_value", "first_shown_sec", "latency_to_first_input_sec",
                "cumulative_duration_sec", "visits", "revision_count",
            ):
                row[f"{dimension}_{key}"] = response.get(key)
        rows.append(row)
    rows.sort(key=lambda row: (
        str(row.get("participant_id", "")),
        DURATION_ORDER.get(str(row.get("viewing_duration", "")), 999),
    ))
    return rows


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output.write_text("", encoding="utf-8-sig")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with output.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NASA_task_60の回答をCSV出力")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT)
    parser.add_argument("--format", choices=("wide", "long"), default="wide")
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

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
    }
    params = {
        "select": (
            "id,survey_id,participant_id,viewing_duration,questionnaire_number,page_session_id,"
            "started_at,completed_at,total_duration_sec,raw_tlx_sum,raw_tlx_mean,"
            "overall_workload,created_at,nasa_60_responses(*)"
        ),
        "order": "created_at.asc",
        "nasa_60_responses.order": "display_order.asc",
    }
    endpoint = f"{base_url.rstrip('/')}/rest/v1/nasa_60_submissions"
    submissions = fetch_all(endpoint, headers, params)
    rows = flatten_wide(submissions) if args.format == "wide" else flatten_long(submissions)
    output = Path(args.output)
    write_csv(rows, output)
    print(f"{len(submissions)}件の条件回答・{len(rows)}行を {output} に出力しました。")


if __name__ == "__main__":
    main()
