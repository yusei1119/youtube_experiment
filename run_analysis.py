#!/usr/bin/env python3
"""最新データの取得から全分析までを1回のコマンドで実行する。"""

from __future__ import annotations

import argparse
import csv
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
DEFAULT_YOUTUBE_CORRECTIONS = (
    ROOT / "data/corrections/youtube_participant_corrections.csv"
)
DEFAULT_YOUTUBE_SESSION_CORRECTIONS = (
    ROOT / "data/corrections/youtube_session_corrections.csv"
)
DEFAULT_PARTICIPANT_SELECTION = (
    ROOT / "data/corrections/analysis_participants.csv"
)


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
        "--youtube-corrections",
        type=Path,
        default=DEFAULT_YOUTUBE_CORRECTIONS,
        help="YouTube参加者IDの除外・訂正ルールCSV",
    )
    parser.add_argument(
        "--youtube-session-corrections",
        type=Path,
        default=DEFAULT_YOUTUBE_SESSION_CORRECTIONS,
        help="YouTubeセッションの除外・末尾トリムルールCSV",
    )
    parser.add_argument(
        "--participant-selection",
        type=Path,
        default=DEFAULT_PARTICIPANT_SELECTION,
        help="YouTube・NASA・記述課題・事後アンケートで共通利用するA系採用者CSV",
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


def participant_ids_from_file(path: Path) -> set[str]:
    """Supabase exportのCSV/JSONLから空でない参加者IDを抽出する。"""
    participant_ids: set[str] = set()
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"{path}:{line_number}: JSONLを読み取れません"
                    ) from error
                participant_id = str(row.get("participant_id") or "").strip()
                if participant_id:
                    participant_ids.add(participant_id)
        return participant_ids

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                return participant_ids
            if "participant_id" not in reader.fieldnames:
                raise ValueError(f"{path}: participant_id列がありません")
            for row in reader:
                participant_id = str(row.get("participant_id") or "").strip()
                if participant_id:
                    participant_ids.add(participant_id)
        return participant_ids

    raise ValueError(f"参加者ID抽出に未対応の形式です: {path}")


def supabase_export_files(raw_dir: Path) -> list[Path]:
    """一括分析run内のSupabase由来5ファイルを返す。"""
    patterns = (
        "youtube_logs*.jsonl",
        "nasa_90*.csv",
        "nasa_60*.csv",
        "writing_90*.csv",
        "writing_60*.csv",
    )
    files: list[Path] = []
    for pattern in patterns:
        matches = sorted(raw_dir.glob(pattern))
        if len(matches) != 1:
            raise ValueError(
                f"{raw_dir}: {pattern} が1ファイルではありません（{len(matches)}件）"
            )
        files.append(matches[0])
    return files


def participant_ids_from_exports(paths: list[Path]) -> set[str]:
    participant_ids: set[str] = set()
    for path in paths:
        participant_ids.update(participant_ids_from_file(path))
    return participant_ids


def new_participant_ids(
    current_paths: list[Path], previous_raw_dir: Path
) -> tuple[set[str], set[str], list[str]]:
    """現在・前回の参加者集合と、今回初出の参加者IDを返す。"""
    current = participant_ids_from_exports(current_paths)
    previous = participant_ids_from_exports(
        supabase_export_files(previous_raw_dir)
    )
    return current, previous, sorted(current - previous)


def latest_completed_supabase_run(
    output_root: Path, current_run: Path
) -> tuple[Path, dict[str, object]] | None:
    """現在のrunを除き、直近の正常完了Supabase runを返す。"""
    candidates: list[tuple[str, Path, dict[str, object]]] = []
    if not output_root.is_dir():
        return None
    for path in output_root.glob("run_*"):
        if path == current_run or not path.is_dir():
            continue
        manifest_path = path / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (
            manifest.get("status") != "complete"
            or manifest.get("mode") != "supabase_export"
        ):
            continue
        completed_at = str(manifest.get("completed_at") or "")
        candidates.append((completed_at, path, manifest))
    if not candidates:
        return None
    _, path, manifest = max(candidates, key=lambda item: (item[0], item[1].name))
    return path, manifest


def replace_run_directory(current_run: Path, previous_run: Path) -> Path:
    """前回runを今回runで安全に置き換え、前回のパスを維持する。"""
    backup = previous_run.with_name(f".{previous_run.name}.overwrite_backup")
    number = 2
    while backup.exists():
        backup = previous_run.with_name(
            f".{previous_run.name}.overwrite_backup_{number}"
        )
        number += 1

    previous_run.rename(backup)
    try:
        current_run.rename(previous_run)
    except Exception:
        backup.rename(previous_run)
        raise
    shutil.rmtree(backup)
    return previous_run


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
    overwrite_target: Path | None = None

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

                    current_participant_ids = participant_ids_from_exports(
                        [youtube_logs, nasa_90, nasa_60, writing_90, writing_60]
                    )
                    if not current_participant_ids:
                        raise ValueError(
                            "Supabase exportに参加者IDが1件もありません。"
                            "前回runの上書きを中止します。"
                        )
                    previous = latest_completed_supabase_run(
                        args.output_root, run_root
                    )
                    if previous is not None:
                        previous_run, _previous_manifest = previous
                        try:
                            previous_participant_ids = (
                                participant_ids_from_exports(
                                    supabase_export_files(previous_run / "raw")
                                )
                            )
                            new_participant_ids_list = sorted(
                                current_participant_ids
                                - previous_participant_ids
                            )
                        except (OSError, ValueError) as error:
                            manifest["participant_comparison"] = {
                                "previous_run": display_path(previous_run),
                                "current_participant_count": len(
                                    current_participant_ids
                                ),
                                "action": "keep_new_run",
                                "reason": f"previous_run_unreadable: {error}",
                            }
                            print(
                                "\n前回runの参加者IDを比較できないため、"
                                f"新規runとして保存します: {error}"
                            )
                        else:
                            overwrite_target = (
                                previous_run
                                if not new_participant_ids_list
                                else None
                            )
                            manifest["participant_comparison"] = {
                                "previous_run": display_path(previous_run),
                                "previous_participant_count": len(
                                    previous_participant_ids
                                ),
                                "current_participant_count": len(
                                    current_participant_ids
                                ),
                                "new_participant_ids": new_participant_ids_list,
                                "action": (
                                    "overwrite_previous_run"
                                    if overwrite_target is not None
                                    else "keep_new_run"
                                ),
                            }
                            if overwrite_target is not None:
                                print(
                                    "\n新しい参加者IDはありません。分析成功後に"
                                    f"前回runを上書きします: {overwrite_target}"
                                )
                            else:
                                print(
                                    "\n新しい参加者IDを検出しました。"
                                    "新規runとして保存します: "
                                    f"{new_participant_ids_list}"
                                )

            snapshots = {
                "sessions": (args.sessions, raw_dir / "sessions.json"),
                "youtube_category_cache": (
                    args.category_cache,
                    raw_dir / "youtube_video_category_cache.csv",
                ),
                "youtube_corrections": (
                    args.youtube_corrections,
                    raw_dir / "youtube_participant_corrections.csv",
                ),
                "youtube_session_corrections": (
                    args.youtube_session_corrections,
                    raw_dir / "youtube_session_corrections.csv",
                ),
                "participant_selection": (
                    args.participant_selection,
                    raw_dir / "analysis_participants.csv",
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
            youtube_corrections = raw_dir / "youtube_participant_corrections.csv"
            youtube_session_corrections = (
                raw_dir / "youtube_session_corrections.csv"
            )
            participant_selection = raw_dir / "analysis_participants.csv"
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
                    "--corrections",
                    youtube_corrections,
                    "--session-corrections",
                    youtube_session_corrections,
                    "--correction-report",
                    analysis_dir / "youtube/youtube_log_correction_report.csv",
                    "--session-correction-report",
                    analysis_dir / "youtube/youtube_session_correction_report.csv",
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
                    "--participant-selection",
                    participant_selection,
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
                    "--participant-selection",
                    participant_selection,
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
                    "--participant-selection",
                    participant_selection,
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
                    "--participant-selection",
                    participant_selection,
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
            if overwrite_target is not None:
                manifest["stored_as"] = display_path(overwrite_target)
            (run_root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            final_root = (
                replace_run_directory(run_root, overwrite_target)
                if overwrite_target is not None
                else run_root
            )
            print(f"\n完了: {final_root}")
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
