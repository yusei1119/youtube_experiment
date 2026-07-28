"""分析・export結果を既存ファイルと衝突しない出力先へ振り分ける。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def make_run_id() -> str:
    """人が並び順を読み取りやすいローカル時刻の実行IDを返す。"""
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def versioned_file(path: str | Path, run_id: str | None = None) -> Path:
    """元の拡張子を保ち、日時付きの未使用ファイル名を返す。"""
    source = Path(path)
    identifier = run_id or make_run_id()
    candidate = source.with_name(f"{source.stem}_{identifier}{source.suffix}")
    number = 2
    while candidate.exists():
        candidate = source.with_name(
            f"{source.stem}_{identifier}_{number}{source.suffix}"
        )
        number += 1
    return candidate


def create_run_output_dir(base_dir: str | Path, run_id: str | None = None) -> Path:
    """分析1回分を格納する未使用の run_日時 ディレクトリを作る。"""
    base = Path(base_dir)
    identifier = run_id or make_run_id()
    candidate = base / f"run_{identifier}"
    number = 2
    while candidate.exists():
        candidate = base / f"run_{identifier}_{number}"
        number += 1
    candidate.mkdir(parents=True)
    return candidate
