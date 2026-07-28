#!/usr/bin/env python3
"""最新データの取得から全分析までを1回のコマンドで実行する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from scripts.common.output_versioning import create_run_output_dir, make_run_id


ROOT = Path(__file__).resolve().parent
DEFAULT_POST_SURVEY_90 = ROOT / (
    "data/post_survey/実験後アンケート_ex1_2026_07（回答） - "
    "フォームの回答 1.csv"
)
DEFAULT_POST_SURVEY_60 = ROOT / (
    "data/post_survey/実験後アンケート_ex2_time_05_2026_07（回答） - "
    "フォームの回答 1.csv"
)
LOCAL_EXPORTS = ROOT / "data/local_exports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Supabaseの最新結果を取得し、YouTube・NASA・記述課題・事後アンケートを一括分析"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Supabaseから取得せず、指定したローカルCSV/JSONLを分析",
    )
    parser.add_argument("--run-id", default=None, help="実行ID（既定: 現在日時）")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "analysis_runs",
        help="実行結果の保存先",
    )
    parser.add_argument("--youtube-logs", type=Path, default=ROOT / "data/logs.jsonl")
    parser.add_argument("--sessions", type=Path, default=ROOT / "data/sessions.json")
    parser.add_argument(
        "--category-cache",
        type=Path,
        default=ROOT / "data/reference/youtube_video_category_cache.csv",
    )
    parser.add_argument(
        "--nasa-90", type=Path, default=LOCAL_EXPORTS / "nasa_task_90_results.csv"
    )
    parser.add_argument(
        "--nasa-60", type=Path, default=LOCAL_EXPORTS / "nasa_task_60_results.csv"
    )
    parser.add_argument(
        "--writing-90", type=Path, default=LOCAL_EXPORTS / "writing_responses.csv"
    )
    parser.add_argument(
        "--writing-60", type=Path, default=LOCAL_EXPORTS / "writing_60_responses.csv"
    )
    parser.add_argument(
        "--post-survey-90", type=Path, default=DEFAULT_POST_SURVEY_90
    )
    parser.add_argument(
        "--post-survey-60", type=Path, default=DEFAULT_POST_SURVEY_60
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイル作成やコマンド実行をせず、処理内容だけ表示",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def file_record(path: Path, source: str) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"出力ファイルがありません: {path}")
    return {
        "source": source,
        "snapshot": display_path(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def snapshot(source: Path, destination: Path) -> dict[str, object]:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"入力ファイルがありません: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return file_record(destination, str(source))


def run(command: list[str], env: dict[str, str], dry_run: bool) -> None:
    printable = " ".join(command)
    print(f"\n$ {printable}")
    if not dry_run:
        subprocess.run(command, cwd=ROOT, env=env, check=True)


def module_command(module: str, *args: object) -> list[str]:
    return [sys.executable, "-m", module, *(str(value) for value in args)]


def main() -> None:
    args = parse_args()
    run_id = args.run_id or make_run_id()
    planned_root = args.output_root / f"run_{run_id}"

    if args.dry_run:
        run_root = planned_root
        print(f"DRY RUN: 出力予定 {run_root}")
    else:
        run_root = create_run_output_dir(args.output_root, run_id)
        print(f"実行結果: {run_root}")

    raw_dir = run_root / "raw"
    analysis_dir = run_root / "analysis"
    manifest: dict[str, object] = {
        "run_id": run_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "mode": "local" if args.local else "supabase_export",
        "status": "running",
        "inputs": {},
    }

    if args.dry_run:
        raw_dir = planned_root / "raw"
        analysis_dir = planned_root / "analysis"
    else:
        raw_dir.mkdir(parents=True)
        analysis_dir.mkdir(parents=True)

    env = os.environ.copy()
    try:
        with tempfile.TemporaryDirectory(prefix="youtube-experiment-mpl-") as mpl_cache:
            env["MPLCONFIGDIR"] = mpl_cache
            env["XDG_CACHE_HOME"] = mpl_cache

            if args.local:
                local_inputs = {
                    "youtube_logs": (args.youtube_logs, raw_dir / "youtube_logs.jsonl"),
                    "nasa_90": (args.nasa_90, raw_dir / "nasa_90.csv"),
                    "nasa_60": (args.nasa_60, raw_dir / "nasa_60.csv"),
                    "writing_90": (args.writing_90, raw_dir / "writing_90.csv"),
                    "writing_60": (args.writing_60, raw_dir / "writing_60.csv"),
                }
                if args.dry_run:
                    for label, (source, destination) in local_inputs.items():
                        print(f"snapshot: {source} -> {destination}")
                else:
                    manifest["inputs"].update(
                        {
                            label: snapshot(source, destination)
                            for label, (source, destination) in local_inputs.items()
                        }
                    )
                youtube_logs = raw_dir / "youtube_logs.jsonl"
                nasa_90 = raw_dir / "nasa_90.csv"
                nasa_60 = raw_dir / "nasa_60.csv"
                writing_90 = raw_dir / "writing_90.csv"
                writing_60 = raw_dir / "writing_60.csv"
            else:
                export_specs = [
                    (
                        "scripts.export.export_supabase_logs",
                        raw_dir / "youtube_logs.jsonl",
                    ),
                    (
                        "scripts.export.export_nasa_90_responses",
                        raw_dir / "nasa_90.csv",
                    ),
                    (
                        "scripts.export.export_nasa_60_responses",
                        raw_dir / "nasa_60.csv",
                    ),
                    (
                        "scripts.export.export_writing_responses",
                        raw_dir / "writing_90.csv",
                    ),
                    (
                        "scripts.export.export_writing_60_responses",
                        raw_dir / "writing_60.csv",
                    ),
                ]
                for module, output in export_specs:
                    run(
                        module_command(module, "--output", output, "--run-id", run_id)
                        if module != "scripts.export.export_supabase_logs"
                        else module_command(module, output, "--run-id", run_id),
                        env,
                        args.dry_run,
                    )
                youtube_logs = raw_dir / f"youtube_logs_{run_id}.jsonl"
                nasa_90 = raw_dir / f"nasa_90_{run_id}.csv"
                nasa_60 = raw_dir / f"nasa_60_{run_id}.csv"
                writing_90 = raw_dir / f"writing_90_{run_id}.csv"
                writing_60 = raw_dir / f"writing_60_{run_id}.csv"
                if not args.dry_run:
                    manifest["inputs"].update(
                        {
                            label: file_record(path, "Supabase")
                            for label, path in {
                                "youtube_logs": youtube_logs,
                                "nasa_90": nasa_90,
                                "nasa_60": nasa_60,
                                "writing_90": writing_90,
                                "writing_60": writing_60,
                            }.items()
                        }
                    )

            snapshots = {
                "sessions": (args.sessions, raw_dir / "sessions.json"),
                "youtube_category_cache": (
                    args.category_cache,
                    raw_dir / "youtube_video_category_cache.csv",
                ),
                "post_survey_90": (args.post_survey_90, raw_dir / "post_survey_90.csv"),
                "post_survey_60": (args.post_survey_60, raw_dir / "post_survey_60.csv"),
            }
            if args.dry_run:
                for label, (source, destination) in snapshots.items():
                    print(f"snapshot: {source} -> {destination}")
            else:
                manifest["inputs"].update(
                    {
                        label: snapshot(source, destination)
                        for label, (source, destination) in snapshots.items()
                    }
                )

            sessions = raw_dir / "sessions.json"
            category_cache = raw_dir / "youtube_video_category_cache.csv"
            post_survey_90 = raw_dir / "post_survey_90.csv"
            post_survey_60 = raw_dir / "post_survey_60.csv"
            youtube_summary_base = analysis_dir / "youtube/youtube_analysis_summary.csv"
            youtube_summary = youtube_summary_base.with_name(
                f"{youtube_summary_base.stem}_{run_id}{youtube_summary_base.suffix}"
            )

            commands = [
                module_command(
                    "scripts.analysis.analyze_youtube_logs",
                    youtube_logs,
                    "--sessions",
                    sessions,
                    "--category-cache",
                    category_cache,
                    "--output",
                    youtube_summary_base,
                    "--run-id",
                    run_id,
                ),
                module_command(
                    "scripts.analysis.summarize_youtube_viewing",
                    "--input",
                    youtube_summary,
                    "--output-dir",
                    analysis_dir / "youtube/a_participants",
                    "--exact-output-dir",
                    "--run-id",
                    run_id,
                ),
                module_command(
                    "scripts.analysis.summarize_youtube_viewing_60",
                    "--youtube-input",
                    youtube_summary,
                    "--duration-input",
                    nasa_60,
                    "--output-dir",
                    analysis_dir / "youtube/b_participants",
                    "--exact-output-dir",
                    "--run-id",
                    run_id,
                ),
                module_command(
                    "scripts.analysis.analyze_nasa_tlx",
                    "--study",
                    "all",
                    "--input-90",
                    nasa_90,
                    "--input-60",
                    nasa_60,
                    "--output-dir",
                    analysis_dir / "nasa_tlx",
                    "--exact-output-dir",
                    "--run-id",
                    run_id,
                ),
                module_command(
                    "scripts.analysis.analyze_writing_task",
                    "--study",
                    "all",
                    "--input-90",
                    writing_90,
                    "--input-60",
                    writing_60,
                    "--nasa-90-input",
                    nasa_90,
                    "--output-dir",
                    analysis_dir / "writing",
                    "--exact-output-dir",
                    "--run-id",
                    run_id,
                ),
                module_command(
                    "scripts.analysis.analyze_post_survey",
                    "--study",
                    "all",
                    "--input-90",
                    post_survey_90,
                    "--input-60",
                    post_survey_60,
                    "--output-dir",
                    analysis_dir / "post_survey",
                    "--exact-output-dir",
                    "--run-id",
                    run_id,
                ),
            ]
            for command in commands:
                run(command, env, args.dry_run)

        if not args.dry_run:
            manifest["status"] = "complete"
            manifest["completed_at"] = datetime.now().astimezone().isoformat()
            (run_root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"\n完了: {run_root}")
    except Exception as error:
        if not args.dry_run:
            manifest["status"] = "failed"
            manifest["failed_at"] = datetime.now().astimezone().isoformat()
            manifest["error"] = str(error)
            (run_root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        raise


if __name__ == "__main__":
    main()
