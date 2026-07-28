"""A系実験の共通採用者リストを読み込み、分析対象を絞り込む。"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd


TRUE_VALUES = {"1", "true", "yes", "y", "include", "included", "採用"}
FALSE_VALUES = {"0", "false", "no", "n", "exclude", "excluded", "除外"}
REQUIRED_COLUMNS = {"participant_id", "included", "note"}


def canonicalize_participant_id(value: object) -> str:
    """全半角・大小文字・ゼロ埋めの表記ずれを吸収する。"""
    text = unicodedata.normalize("NFKC", str(value)).strip().upper()
    match = re.fullmatch(r"A0*(\d+)", text)
    return f"A{int(match.group(1)):03d}" if match else text


def normalize_participant_id(value: object) -> str:
    """採用者CSVのA系IDを検証して標準化する。"""
    text = canonicalize_participant_id(value)
    if not re.fullmatch(r"A\d{3}", text):
        raise ValueError(f"採用者CSVに不正な参加者IDがあります: {value!r}")
    return text


def parse_included(value: object) -> bool:
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise ValueError(
        f"included は true/false（または 採用/除外）で指定してください: {value!r}"
    )


def load_participant_selection(path: Path) -> tuple[pd.DataFrame, set[str]]:
    """編集用CSVを検証し、標準化済み一覧と採用ID集合を返す。"""
    if not path.is_file():
        raise FileNotFoundError(f"採用者CSVが見つかりません: {path}")
    selection = pd.read_csv(
        path, dtype=str, keep_default_na=False, encoding="utf-8-sig"
    )
    selection.columns = selection.columns.astype(str).str.strip()
    missing = sorted(REQUIRED_COLUMNS - set(selection.columns))
    if missing:
        raise ValueError(f"{path}: 必須列がありません: {missing}")
    selection = selection[["participant_id", "included", "note"]].copy()
    selection["participant_id"] = selection["participant_id"].map(
        normalize_participant_id
    )
    selection["included"] = selection["included"].map(parse_included)
    duplicates = selection.loc[
        selection["participant_id"].duplicated(keep=False), "participant_id"
    ].unique()
    if len(duplicates):
        raise ValueError(f"{path}: 参加者IDが重複しています: {duplicates.tolist()}")
    selection = selection.sort_values("participant_id").reset_index(drop=True)
    included_ids = set(
        selection.loc[selection["included"], "participant_id"].astype(str)
    )
    if not included_ids:
        raise ValueError(f"{path}: included=true の参加者がいません。")
    return selection, included_ids


def filter_selected_participants(
    data: pd.DataFrame,
    report: pd.DataFrame,
    included_ids: set[str],
    reason: str = "excluded_by_participant_selection",
) -> pd.DataFrame:
    """候補行を採用者集合との積に限定し、除外を既存レポートへ記録する。"""
    selected = data["participant_id"].isin(included_ids)
    excluded_rows = set(data.loc[~selected, "source_row"].astype(int))
    if excluded_rows:
        mask = report["source_row"].isin(excluded_rows)
        report.loc[mask, "included"] = False
        report.loc[mask, "reason"] = reason
    return data.loc[selected].copy()
