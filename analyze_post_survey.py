#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""実験後アンケート（90版・60版）の主観評価を分析する。

90版
  A+数字の参加者のみを対象とする。med（瞑想）/ short（ショート）/
  control（日常）の各条件について、前半3問の平均を Reading、後半3問の
  平均を Output として対応あり比較を行う。

60版
  B+数字の参加者のみを対象とする。5～30分（5分刻み）のショート動画
  視聴時間ごとに Reading / Output と6つの個別質問を参加者間比較する。

参加者IDは照合キーとしてのみ保持し、既視聴確認Q2は分析項目に含めない。
「この質問の回答は4を記入してください」のようなダミー設問は、質問文から
自動検出して得点・参加者除外の両方から完全に無視する。同じ条件内に同一文面の
質問が重複している場合は、最初の列だけを採用する。

実行例:
  python analyze_post_survey.py
  python analyze_post_survey.py --study 90
  python analyze_post_survey.py --study 60 --input-60 path/to/form.csv

必要パッケージ: numpy, pandas, scipy, matplotlib
"""

from __future__ import annotations

import argparse
import math
import re
import warnings
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from analyze_nasa_tlx import (
    holm_adjust,
    independent_comparison,
    paired_comparison,
    p_stars,
    repeated_measures_anova,
    safe_shapiro,
)


DEFAULT_INPUT_90 = Path(
    "ex_after_survey/実験後アンケート_ex1_2026_07（回答） - フォームの回答 1.csv"
)
DEFAULT_INPUT_60 = Path(
    "ex_after_survey/実験後アンケート_ex2_time_05_2026_07（回答） - フォームの回答 1.csv"
)
CONDITIONS_90 = ("short", "control", "med")
CONDITION_LABELS_90 = {
    "short": "Short",
    "control": "Control",
    "med": "Meditation",
}
DURATIONS_60 = tuple(f"{minutes}min" for minutes in range(5, 31, 5))
METRICS = (
    "Reading",
    "Output",
    "Reading_Q1",
    "Reading_Q2",
    "Reading_Q3",
    "Output_Q1",
    "Output_Q2",
    "Output_Q3",
)
METRIC_LABELS = {
    "Reading": "Reading ability (mean of 3)",
    "Output": "Writing output ability (mean of 3)",
    "Reading_Q1": "Reading question 1",
    "Reading_Q2": "Reading question 2",
    "Reading_Q3": "Reading question 3",
    "Output_Q1": "Output question 1",
    "Output_Q2": "Output question 2",
    "Output_Q3": "Output question 3",
}
PAIR_ORDER_90 = (
    ("short", "control"),
    ("short", "med"),
    ("control", "med"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="実験後アンケートを条件別／視聴時間別に分析します。"
    )
    parser.add_argument("--study", choices=("90", "60", "all"), default="all")
    parser.add_argument("--input-90", type=Path, default=DEFAULT_INPUT_90)
    parser.add_argument("--input-60", type=Path, default=DEFAULT_INPUT_60)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("post_survey_analysis")
    )
    parser.add_argument(
        "--duplicate-policy",
        choices=("latest", "first", "error"),
        default="latest",
        help="同じ参加者IDの重複回答の扱い（既定: latest）",
    )
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  saved: {path}")


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def find_column(columns: list[str], pattern: str, label: str) -> str:
    matches = [column for column in columns if re.search(pattern, column)]
    if len(matches) != 1:
        raise ValueError(
            f"{label}列を一意に特定できません（候補数={len(matches)}）: {matches}"
        )
    return matches[0]


def question_number(header: str) -> int | None:
    match = re.search(r"Q\s*[.．]?\s*(\d+)", header, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def question_text(header: str) -> str:
    match = re.search(
        r"Q\s*[.．]?\s*\d+\s*[.．]?\s*(.*)$",
        header,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return normalize_space(match.group(1) if match else header)


def canonical_question_text(header: str) -> str:
    text = question_text(header).lower()
    text = text.translate(str.maketrans({
        "．": ".", "，": ",", "：": ":", "「": "", "」": "",
        "『": "", "』": "", "“": "", "”": "", "？": "?",
    }))
    return re.sub(r"[\s。.,、!?！？:：]", "", text)


def dummy_expected_value(header: str) -> int | None:
    compact = normalize_space(header)
    if "この質問" not in compact or "回答" not in compact:
        return None
    match = re.search(r"回答は\s*([1-7])", compact)
    if not match:
        match = re.search(r"([1-7])\s*を(?:記入|回答)", compact)
    return int(match.group(1)) if match else None


def domain_from_header(header: str) -> str | None:
    if "記述タスク" in header:
        return "Output"
    if "映画予告映像" in header or "2分間の映像" in header:
        return "Reading"
    return None


def condition_from_header(header: str) -> str | None:
    if "瞑想" in header:
        return "med"
    if "ショート" in header:
        return "short"
    if "日常" in header:
        return "control"
    return None


def non_analysis_reason(header: str) -> str | None:
    """主観評価の分析項目として使わない列を明示的に分類する。"""
    compact = normalize_space(header)
    if "参加者ID" in compact:
        return "participant_id_key_only"
    if "見たこと" in compact and "含まれて" in compact:
        return "prior_exposure_question_ignored"
    if "タイムスタンプ" in compact:
        return "timestamp_metadata"
    if compact == "スコア":
        return "form_score_metadata"
    if "視聴時間を選択" in compact:
        return "grouping_variable_only"
    if "コメント" in compact:
        return "free_text_comment_ignored"
    return None


def build_question_map(
    raw: pd.DataFrame,
    study: str,
) -> pd.DataFrame:
    """質問列を抽出し、ダミー・重複を除いて各領域3問へ割り当てる。"""
    records: list[dict[str, object]] = []
    source_columns = [column for column in raw.columns if column != "source_row"]
    for column_index, header in enumerate(source_columns, start=1):
        # ID、既視聴確認Q2、メタデータは主観評価項目に含めない。
        if non_analysis_reason(header) is not None:
            continue
        domain = domain_from_header(header)
        expected = dummy_expected_value(header)
        if domain is None and expected is None:
            continue
        condition = condition_from_header(header) if study == "90" else "duration_group"
        if study == "90" and condition is None:
            continue
        values = pd.to_numeric(raw[header], errors="coerce")
        record: dict[str, object] = {
            "source_column_index": column_index,
            "source_column": header,
            "question_number": question_number(header),
            "question_text": question_text(header),
            "condition": condition,
            "domain": domain,
            "position": np.nan,
            "included_in_score": expected is None,
            "exclusion_reason": "" if expected is None else "dummy_attention_check_ignored",
            "expected_attention_value": expected,
            "nonempty_response_count": int(raw[header].astype(str).str.strip().ne("").sum()),
            "numeric_response_count": int(values.notna().sum()),
            "attention_correct_count": np.nan,
            "attention_incorrect_count": np.nan,
            "attention_missing_count": np.nan,
            "duplicate_kept_question_number": np.nan,
            "_canonical": canonical_question_text(header),
        }
        if expected is not None:
            nonmissing = values.notna()
            record["attention_correct_count"] = int((values[nonmissing] == expected).sum())
            record["attention_incorrect_count"] = int((values[nonmissing] != expected).sum())
            record["attention_missing_count"] = int((~nonmissing).sum())
        records.append(record)

    mapping = pd.DataFrame(records)
    if mapping.empty:
        raise ValueError("1～7評価の質問列を質問文から検出できませんでした。")

    # 同一文面が複数ある場合は質問番号が小さい列を優先する。
    # 現行90版のQ21/Q22重複では、これによりQ21だけが採用される。
    score_candidates = mapping[mapping["included_in_score"].astype(bool)]
    duplicate_keys = ["condition", "domain", "_canonical"]
    for _, group in score_candidates.groupby(duplicate_keys, sort=False, dropna=False):
        if len(group) < 2:
            continue
        ordered = group.assign(
            _question_sort=pd.to_numeric(group["question_number"], errors="coerce").fillna(np.inf)
        ).sort_values(["_question_sort", "source_column_index"])
        keep_index = ordered.index[0]
        keep_number = mapping.at[keep_index, "question_number"]
        mapping.loc[group.index, "duplicate_kept_question_number"] = keep_number
        discard_indices = group.index.difference([keep_index])
        mapping.loc[discard_indices, "included_in_score"] = False
        mapping.loc[discard_indices, "exclusion_reason"] = "duplicate_question_text_ignored"

    expected_conditions = CONDITIONS_90 if study == "90" else ("duration_group",)
    for condition in expected_conditions:
        for domain in ("Reading", "Output"):
            selected = mapping.index[
                (mapping["condition"] == condition)
                & (mapping["domain"] == domain)
                & mapping["included_in_score"].astype(bool)
            ].tolist()
            if len(selected) != 3:
                headers = mapping.loc[selected, "source_column"].tolist()
                raise ValueError(
                    f"{study}版の {condition}/{domain} が3問ではありません"
                    f"（検出={len(selected)}）: {headers}"
                )
            for position, index in enumerate(selected, start=1):
                mapping.at[index, "position"] = position

    return mapping.drop(columns="_canonical")


def build_column_audit(raw: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """全入力列が分析でどの役割になったかを監査可能な表にする。"""
    mapping_by_column = mapping.set_index("source_column", drop=False)
    records: list[dict[str, object]] = []
    source_columns = [column for column in raw.columns if column != "source_row"]
    for column_index, header in enumerate(source_columns, start=1):
        explicit_reason = non_analysis_reason(header)
        if explicit_reason is not None:
            role = explicit_reason
            used_as_score = False
        elif header in mapping_by_column.index:
            item = mapping_by_column.loc[header]
            if isinstance(item, pd.DataFrame):
                item = item.iloc[0]
            used_as_score = bool(item["included_in_score"])
            role = "score_item" if used_as_score else str(item["exclusion_reason"])
        else:
            used_as_score = False
            role = "unclassified_not_used"
        records.append({
            "source_column_index": column_index,
            "source_column": header,
            "analysis_role": role,
            "used_as_score": used_as_score,
        })
    return pd.DataFrame(records)


def read_form(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"入力CSVが見つかりません: {path}")
    raw = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    raw.columns = [str(column).strip() for column in raw.columns]
    raw.insert(0, "source_row", np.arange(2, len(raw) + 2))
    return raw


def normalize_participant_id(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.upper()


def normalize_duration(value: object) -> str | None:
    text = normalize_space(value).lower()
    match = re.search(r"(?<!\d)(5|10|15|20|25|30)\s*(?:min|分)?", text)
    if not match:
        return None
    return f"{int(match.group(1))}min"


def make_filter_report(raw: pd.DataFrame, id_column: str, pattern: str) -> pd.DataFrame:
    ids = normalize_participant_id(raw[id_column])
    valid = ids.str.fullmatch(pattern, na=False)
    return pd.DataFrame({
        "source_row": raw["source_row"],
        "participant_id": ids,
        "included": valid,
        "reason": np.where(valid, "candidate", "invalid_participant_id"),
    })


def mark_report(report: pd.DataFrame, rows: set[int], reason: str) -> None:
    if not rows:
        return
    mask = report["source_row"].isin(rows)
    report.loc[mask, "included"] = False
    report.loc[mask, "reason"] = reason


def resolve_duplicate_rows(
    data: pd.DataFrame,
    timestamp_column: str | None,
    policy: str,
) -> tuple[pd.DataFrame, set[int]]:
    duplicate = data.duplicated("participant_id", keep=False)
    if not duplicate.any():
        return data, set()
    examples = data.loc[duplicate, "participant_id"].drop_duplicates().head(8).tolist()
    if policy == "error":
        raise ValueError(f"同一参加者IDの重複回答があります: {examples}")
    ordered = data.copy()
    sort_columns = ["participant_id"]
    if timestamp_column and timestamp_column in ordered:
        ordered["_timestamp_sort"] = pd.to_datetime(
            ordered[timestamp_column], errors="coerce"
        )
        sort_columns.append("_timestamp_sort")
    sort_columns.append("source_row")
    ordered = ordered.sort_values(sort_columns)
    keep = "last" if policy == "latest" else "first"
    discarded = ordered.duplicated("participant_id", keep=keep)
    rows = set(ordered.loc[discarded, "source_row"].astype(int))
    return ordered.loc[~discarded].drop(columns="_timestamp_sort", errors="ignore"), rows


def score_rows(
    raw: pd.DataFrame,
    mapping: pd.DataFrame,
    id_column: str,
    study: str,
    group_values: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """参加者×条件の得点表、項目long表、元行ごとの無効得点maskを作る。"""
    included = mapping[mapping["included_in_score"].astype(bool)].copy()
    numeric = {
        str(row.source_column): pd.to_numeric(raw[str(row.source_column)], errors="coerce")
        for row in included.itertuples()
    }
    invalid = pd.Series(False, index=raw.index)
    for values in numeric.values():
        invalid |= values.isna() | ~values.between(1, 7)

    participant_ids = normalize_participant_id(raw[id_column])
    frames: list[pd.DataFrame] = []
    item_frames: list[pd.DataFrame] = []
    condition_values = CONDITIONS_90 if study == "90" else ("duration_group",)
    for condition in condition_values:
        condition_map = included[included["condition"] == condition]
        base = pd.DataFrame({
            "source_row": raw["source_row"],
            "participant_id": participant_ids,
        })
        if study == "90":
            base["condition"] = condition
        else:
            if group_values is None:
                raise ValueError("60版の視聴時間列がありません。")
            base["viewing_duration"] = group_values
        for item in condition_map.itertuples():
            metric = f"{item.domain}_Q{int(item.position)}"
            base[metric] = numeric[str(item.source_column)]
            item_frames.append(pd.DataFrame({
                "source_row": raw["source_row"],
                "participant_id": participant_ids,
                "condition": condition if study == "90" else group_values,
                "domain": item.domain,
                "position": int(item.position),
                "metric": metric,
                "question_number": item.question_number,
                "question_text": item.question_text,
                "score": numeric[str(item.source_column)],
            }))
        base["Reading"] = base[[f"Reading_Q{i}" for i in range(1, 4)]].mean(axis=1)
        base["Output"] = base[[f"Output_Q{i}" for i in range(1, 4)]].mean(axis=1)
        frames.append(base)

    scores = pd.concat(frames, ignore_index=True)
    items = pd.concat(item_frames, ignore_index=True)
    return scores, items, invalid


def descriptive_statistics(
    data: pd.DataFrame,
    group_column: str,
    group_order: tuple[str, ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric in METRICS:
        for group in group_order:
            values = pd.to_numeric(
                data.loc[data[group_column] == group, metric], errors="coerce"
            ).dropna()
            n = len(values)
            mean = float(values.mean()) if n else np.nan
            sd = float(values.std(ddof=1)) if n >= 2 else np.nan
            sem = sd / math.sqrt(n) if n >= 2 else np.nan
            t_critical = float(stats.t.ppf(0.975, n - 1)) if n >= 2 else np.nan
            margin = t_critical * sem if n >= 2 else np.nan
            rows.append({
                "metric": metric,
                "metric_label": METRIC_LABELS[metric],
                group_column: group,
                "n": n,
                "mean": mean,
                "sd": sd,
                "median": float(values.median()) if n else np.nan,
                "q1": float(values.quantile(0.25)) if n else np.nan,
                "q3": float(values.quantile(0.75)) if n else np.nan,
                "sem": sem,
                "ci95_low": mean - margin if n >= 2 else np.nan,
                "ci95_high": mean + margin if n >= 2 else np.nan,
                "minimum": float(values.min()) if n else np.nan,
                "maximum": float(values.max()) if n else np.nan,
            })
    return pd.DataFrame(rows)


def paired_analysis(
    data: pd.DataFrame,
    conditions: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    omnibus_rows: list[dict[str, object]] = []
    pairwise_rows: list[dict[str, object]] = []
    for metric in METRICS:
        wide = data.pivot(index="participant_id", columns="condition", values=metric)
        wide = wide.reindex(columns=conditions).dropna()
        values = wide.to_numpy(float)
        n = len(wide)
        if n >= 2:
            subject_means = values.mean(axis=1, keepdims=True)
            condition_means = values.mean(axis=0, keepdims=True)
            residuals = values - subject_means - condition_means + values.mean()
            normality_p = safe_shapiro(residuals.ravel())
        else:
            normality_p = np.nan
        if n >= 2 and np.allclose(values, values[:, [0]]):
            statistic, p_raw, effect = 0.0, 1.0, 0.0
            test, effect_name = "all within-participant differences are zero", "Kendall's W"
        elif n >= 3 and np.isfinite(normality_p) and normality_p >= 0.05:
            statistic, p_raw, effect = repeated_measures_anova(values)
            test, effect_name = "one-way repeated-measures ANOVA", "partial eta squared"
        elif n >= 2:
            result = stats.friedmanchisquare(
                *(values[:, index] for index in range(values.shape[1]))
            )
            statistic, p_raw = float(result.statistic), float(result.pvalue)
            effect = statistic / (n * (len(conditions) - 1))
            test, effect_name = "Friedman test", "Kendall's W"
        else:
            statistic = p_raw = effect = np.nan
            test = effect_name = "NA"
        omnibus_rows.append({
            "metric": metric,
            "metric_label": METRIC_LABELS[metric],
            "n": n,
            "test": test,
            "statistic": statistic,
            "p_raw": p_raw,
            "residual_shapiro_p": normality_p,
            "effect": effect,
            "effect_name": effect_name,
        })

        current: list[dict[str, object]] = []
        for condition_1, condition_2 in PAIR_ORDER_90:
            result = paired_comparison(
                wide[condition_1].to_numpy(float),
                wide[condition_2].to_numpy(float),
            )
            current.append({
                "metric": metric,
                "metric_label": METRIC_LABELS[metric],
                "condition_1": condition_1,
                "condition_2": condition_2,
                "n": n,
                **result,
            })
        adjusted = holm_adjust([float(row["p_raw"]) for row in current])
        for row, adjusted_p in zip(current, adjusted):
            row["p_holm_within_metric"] = adjusted_p
            row["significance_holm"] = p_stars(adjusted_p)
        pairwise_rows.extend(current)

    omnibus = pd.DataFrame(omnibus_rows)
    omnibus["p_holm_across_metrics"] = holm_adjust(omnibus["p_raw"].tolist())
    omnibus["significance_holm"] = omnibus["p_holm_across_metrics"].map(p_stars)
    return omnibus, pd.DataFrame(pairwise_rows)


def independent_analysis(
    data: pd.DataFrame,
    group_column: str,
    group_order: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    present = tuple(group for group in group_order if (data[group_column] == group).any())
    omnibus_rows: list[dict[str, object]] = []
    pairwise_rows: list[dict[str, object]] = []
    for metric in METRICS:
        groups = [
            pd.to_numeric(
                data.loc[data[group_column] == group, metric], errors="coerce"
            ).dropna().to_numpy(float)
            for group in present
        ]
        nonempty = [values for values in groups if values.size]
        if len(nonempty) < 2:
            statistic = p_raw = effect = normality_p = levene_p = np.nan
            test = effect_name = "NA"
        else:
            residuals = np.concatenate([values - values.mean() for values in nonempty])
            normality_p = safe_shapiro(residuals)
            levene_p = (
                float(stats.levene(*nonempty, center="median").pvalue)
                if all(values.size >= 2 for values in nonempty)
                else np.nan
            )
            all_values = np.concatenate(nonempty)
            if np.ptp(all_values) == 0:
                statistic, p_raw, effect = 0.0, 1.0, 0.0
                test, effect_name = "all group values are identical", "epsilon squared"
            elif (
                np.isfinite(normality_p)
                and normality_p >= 0.05
                and np.isfinite(levene_p)
                and levene_p >= 0.05
            ):
                result = stats.f_oneway(*nonempty)
                statistic, p_raw = float(result.statistic), float(result.pvalue)
                grand = all_values.mean()
                ss_between = sum(
                    values.size * (values.mean() - grand) ** 2 for values in nonempty
                )
                ss_total = np.square(all_values - grand).sum()
                effect = ss_between / ss_total if ss_total else 0.0
                test, effect_name = "one-way ANOVA", "eta squared"
            else:
                result = stats.kruskal(*nonempty)
                statistic, p_raw = float(result.statistic), float(result.pvalue)
                total_n = sum(values.size for values in nonempty)
                effect = (
                    max(0.0, (statistic - len(nonempty) + 1) / (total_n - len(nonempty)))
                    if total_n > len(nonempty)
                    else np.nan
                )
                test, effect_name = "Kruskal-Wallis", "epsilon squared"
        omnibus_rows.append({
            "metric": metric,
            "metric_label": METRIC_LABELS[metric],
            "groups_present": len(present),
            "test": test,
            "statistic": statistic,
            "p_raw": p_raw,
            "residual_shapiro_p": normality_p,
            "levene_p": levene_p,
            "effect": effect,
            "effect_name": effect_name,
        })

        current: list[dict[str, object]] = []
        for condition_1, condition_2 in combinations(present, 2):
            x = pd.to_numeric(
                data.loc[data[group_column] == condition_1, metric], errors="coerce"
            ).dropna().to_numpy(float)
            y = pd.to_numeric(
                data.loc[data[group_column] == condition_2, metric], errors="coerce"
            ).dropna().to_numpy(float)
            result = independent_comparison(x, y)
            current.append({
                "metric": metric,
                "metric_label": METRIC_LABELS[metric],
                "condition_1": condition_1,
                "condition_2": condition_2,
                "n_1": len(x),
                "n_2": len(y),
                "mean_difference": float(x.mean() - y.mean()) if len(x) and len(y) else np.nan,
                **result,
            })
        adjusted = holm_adjust([float(row["p_raw"]) for row in current])
        for row, adjusted_p in zip(current, adjusted):
            row["p_holm_within_metric"] = adjusted_p
            row["significance_holm"] = p_stars(adjusted_p)
        pairwise_rows.extend(current)

    omnibus = pd.DataFrame(omnibus_rows)
    if not omnibus.empty:
        omnibus["p_holm_across_metrics"] = holm_adjust(omnibus["p_raw"].tolist())
        omnibus["significance_holm"] = omnibus["p_holm_across_metrics"].map(p_stars)
    return omnibus, pd.DataFrame(pairwise_rows)


def pairwise_pvalue_table(
    pairwise: pd.DataFrame,
    pairs: tuple[tuple[str, str], ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric in METRICS:
        row: dict[str, object] = {
            "metric": metric,
            "metric_label": METRIC_LABELS[metric],
        }
        metric_rows = pairwise[pairwise.get("metric", pd.Series(dtype=str)) == metric]
        for condition_1, condition_2 in pairs:
            prefix = f"{condition_1}_vs_{condition_2}"
            match = metric_rows[
                (metric_rows["condition_1"] == condition_1)
                & (metric_rows["condition_2"] == condition_2)
            ] if not metric_rows.empty else pd.DataFrame()
            if match.empty:
                p_raw = p_holm = np.nan
                significance = display = ""
            else:
                result = match.iloc[0]
                p_raw = float(result["p_raw"])
                p_holm = float(result["p_holm_within_metric"])
                significance = str(result["significance_holm"])
                display = f"{p_holm:.4g} {significance}"
            row[f"{prefix}_p_raw"] = p_raw
            row[f"{prefix}_p_holm"] = p_holm
            row[f"{prefix}_significance"] = significance
            row[f"{prefix}_display"] = display
        rows.append(row)
    return pd.DataFrame(rows)


def configure_plot_style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.linewidth": 1.2,
        "axes.titlesize": 13,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "xtick.direction": "in",
        "ytick.direction": "in",
    })


def ci95(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    if values.size < 2:
        return 0.0
    return float(stats.t.ppf(0.975, values.size - 1) * stats.sem(values))


def plot_metric_panels(
    data: pd.DataFrame,
    metrics: tuple[str, ...],
    group_column: str,
    group_order: tuple[str, ...],
    labels: dict[str, str],
    output: Path,
    dpi: int,
    seed: int,
    title: str,
    paired: bool,
) -> None:
    if data.empty:
        return
    present = tuple(group for group in group_order if (data[group_column] == group).any())
    if not present:
        return
    configure_plot_style()
    columns = min(3, len(metrics))
    rows = math.ceil(len(metrics) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(4.6 * columns, 3.8 * rows), squeeze=False)
    rng = np.random.default_rng(seed)
    x_positions = np.arange(len(present))
    for ax, metric in zip(axes.flat, metrics):
        if paired:
            wide = data.pivot(index="participant_id", columns=group_column, values=metric)
            wide = wide.reindex(columns=present)
            for values in wide.to_numpy(float):
                ax.plot(x_positions, values, color="0.75", alpha=0.42, linewidth=0.8, zorder=1)
        means, errors = [], []
        for x_position, group in enumerate(present):
            values = pd.to_numeric(
                data.loc[data[group_column] == group, metric], errors="coerce"
            ).dropna().to_numpy(float)
            jitter = rng.normal(0, 0.055, len(values))
            ax.scatter(
                np.full(len(values), x_position) + jitter,
                values,
                s=25,
                color="0.45",
                alpha=0.52,
                edgecolors="none",
                zorder=2,
            )
            means.append(float(np.mean(values)) if len(values) else np.nan)
            errors.append(ci95(values))
        ax.errorbar(
            x_positions,
            means,
            yerr=errors,
            color="#d62728",
            marker="o",
            markerfacecolor="black",
            markeredgecolor="black",
            linewidth=2.0,
            capsize=4,
            zorder=3,
        )
        ax.set_title(METRIC_LABELS[metric])
        ax.set_xticks(x_positions, [labels.get(group, group) for group in present])
        ax.set_ylim(0.8, 7.2)
        ax.set_yticks(range(1, 8))
        ax.set_ylabel("Score (1–7)")
        ax.grid(axis="y", linestyle="--", color="0.88", linewidth=0.7)
    for ax in axes.flat[len(metrics):]:
        ax.axis("off")
    fig.suptitle(title, fontsize=16)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {output}")


def format_mean_sd(descriptives: pd.DataFrame, metric: str, group_column: str, group: str) -> str:
    match = descriptives[
        (descriptives["metric"] == metric) & (descriptives[group_column] == group)
    ]
    if match.empty or int(match.iloc[0]["n"]) == 0:
        return "—"
    row = match.iloc[0]
    sd = float(row["sd"])
    return f"{float(row['mean']):.2f} ± {sd:.2f}" if np.isfinite(sd) else f"{float(row['mean']):.2f}"


def attention_summary(mapping: pd.DataFrame) -> tuple[int, int]:
    dummy = mapping[mapping["exclusion_reason"] == "dummy_attention_check_ignored"]
    return len(dummy), int(pd.to_numeric(dummy["attention_incorrect_count"], errors="coerce").fillna(0).sum())


def write_report_90(
    data: pd.DataFrame,
    mapping: pd.DataFrame,
    descriptives: pd.DataFrame,
    pairwise_table: pd.DataFrame,
    output: Path,
) -> None:
    dummy_count, incorrect_count = attention_summary(mapping)
    duplicate_count = int((mapping["exclusion_reason"] == "duplicate_question_text_ignored").sum())
    duplicate_kept = sorted(
        pd.to_numeric(mapping["duplicate_kept_question_number"], errors="coerce")
        .dropna().astype(int).unique().tolist()
    )
    duplicate_note = (
        f"（Q{', Q'.join(map(str, duplicate_kept))}を採用）" if duplicate_kept else ""
    )
    lines = [
        "# 実験後アンケート 90：条件別分析",
        "",
        f"- 対象: A系参加者 {data['participant_id'].nunique()}名",
        "- 条件: short / control（日常動画）/ med（瞑想動画）",
        "- 参加者ID: 照合キーとしてのみ使用し、分析指標には含めない",
        "- 既視聴確認Q2: 分析項目から除外",
        "- 読み取り能力: 各条件の映像に関する3問の平均（1–7）",
        "- 出力能力: 各条件のWriting taskに関する3問の平均（1–7）",
        f"- ダミー設問: {dummy_count}列を得点・参加者除外の両方から無視",
        f"- ダミーの指定値と異なる回答: {incorrect_count}件（分析対象には影響なし）",
        f"- 同一文面の重複質問: {duplicate_count}列を除外{duplicate_note}",
        "- ペア比較: 対応あり検定。各指標の3比較内でHolm補正",
        "- 有意記号: * p<.05, ** p<.01, *** p<.001, NS p≥.05",
        "",
        "## 主得点の平均 ± SD",
        "",
        "| 指標 | Short | Control | Meditation |",
        "|---|---:|---:|---:|",
    ]
    for metric in ("Reading", "Output"):
        values = [format_mean_sd(descriptives, metric, "condition", group) for group in CONDITIONS_90]
        lines.append(f"| {METRIC_LABELS[metric]} | " + " | ".join(values) + " |")
    lines.extend([
        "",
        "## 主得点の条件間比較（Holm補正済みp値）",
        "",
        "| 指標 | short vs control | short vs med | control vs med |",
        "|---|---:|---:|---:|",
    ])
    for metric in ("Reading", "Output"):
        match = pairwise_table[pairwise_table["metric"] == metric].iloc[0]
        values = [match[f"{left}_vs_{right}_display"] for left, right in PAIR_ORDER_90]
        lines.append(f"| {METRIC_LABELS[metric]} | " + " | ".join(values) + " |")
    lines.extend([
        "",
        "個別6問の記述統計・検定結果はCSVにも出力しています。ダミー設問の回答は、"
        "正誤にかかわらずReading/Outputの平均には含まれません。",
        "",
    ])
    output.write_text("\n".join(lines), encoding="utf-8")


def write_report_60(
    data: pd.DataFrame,
    mapping: pd.DataFrame,
    descriptives: pd.DataFrame,
    pairwise: pd.DataFrame,
    output: Path,
) -> None:
    dummy_count, incorrect_count = attention_summary(mapping)
    lines = [
        "# 実験後アンケート 60：ショート動画視聴時間別分析",
        "",
        f"- 対象: B系参加者 {data['participant_id'].nunique() if not data.empty else 0}名",
        "- 視聴時間: 5 / 10 / 15 / 20 / 25 / 30分",
        "- 参加者ID: 照合キーとしてのみ使用し、分析指標には含めない",
        "- 既視聴確認Q2: 分析項目から除外",
        "- 読み取り能力: 映像に関する3問の平均（1–7）",
        "- 出力能力: Writing taskに関する3問の平均（1–7）",
        f"- ダミー設問: {dummy_count}列を得点・参加者除外の両方から無視",
        f"- ダミーの指定値と異なる回答: {incorrect_count}件（分析対象には影響なし）",
        "- ペア比較: 独立群検定。各指標の全視聴時間ペア内でHolm補正",
        "",
    ]
    if data.empty:
        lines.extend([
            "現在のCSVにはB系回答がないため、質問構造の検証と監査表の出力のみ行いました。",
            "回答行を追加して再実行すると、表・統計・プロットが自動生成されます。",
            "",
        ])
        output.write_text("\n".join(lines), encoding="utf-8")
        return
    counts = data["viewing_duration"].value_counts().reindex(DURATIONS_60, fill_value=0)
    lines.extend(["## 視聴時間別人数", "", "| 視聴時間 | n |", "|---|---:|"])
    for group, count in counts.items():
        lines.append(f"| {group} | {int(count)} |")
    lines.extend([
        "",
        "## 主得点の平均 ± SD",
        "",
        "| 視聴時間 | 読み取り能力 | 出力能力 |",
        "|---|---:|---:|",
    ])
    for group in DURATIONS_60:
        reading = format_mean_sd(descriptives, "Reading", "viewing_duration", group)
        output_score = format_mean_sd(descriptives, "Output", "viewing_duration", group)
        lines.append(f"| {group} | {reading} | {output_score} |")
    significant = pairwise[
        pd.to_numeric(pairwise.get("p_holm_within_metric"), errors="coerce") < 0.05
    ] if not pairwise.empty else pairwise
    lines.extend(["", "## Holm補正後に有意な主得点のペア", ""])
    significant = significant[significant["metric"].isin(("Reading", "Output"))]
    if significant.empty:
        lines.append("該当なし。")
    else:
        lines.extend(["| 指標 | 比較 | p (Holm) | 記号 |", "|---|---|---:|:---:|"])
        for row in significant.itertuples():
            lines.append(
                f"| {METRIC_LABELS[row.metric]} | {row.condition_1} vs {row.condition_2} "
                f"| {row.p_holm_within_metric:.4g} | {row.significance_holm} |"
            )
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def analyze_90(args: argparse.Namespace) -> None:
    output = args.output_dir / "post_survey_90"
    output.mkdir(parents=True, exist_ok=True)
    raw = read_form(args.input_90)
    id_column = find_column(list(raw.columns), r"参加者ID", "参加者ID")
    timestamp_matches = [column for column in raw.columns if "タイムスタンプ" in column]
    timestamp_column = timestamp_matches[0] if timestamp_matches else None
    mapping = build_question_map(raw, "90")
    column_audit = build_column_audit(raw, mapping)
    report = make_filter_report(raw, id_column, r"A\d+")
    valid_ids = report.loc[report["included"], "source_row"]
    candidates = raw[raw["source_row"].isin(valid_ids)].copy()
    scores, items, invalid_scores = score_rows(candidates, mapping, id_column, "90")
    invalid_source_rows = set(candidates.loc[invalid_scores, "source_row"].astype(int))
    mark_report(report, invalid_source_rows, "missing_or_out_of_range_score")
    candidates = candidates.loc[~invalid_scores].copy()
    candidates["participant_id"] = normalize_participant_id(candidates[id_column])
    candidates, duplicate_rows = resolve_duplicate_rows(
        candidates, timestamp_column, args.duplicate_policy
    )
    mark_report(report, duplicate_rows, f"duplicate_discarded_by_{args.duplicate_policy}")
    included_rows = set(candidates["source_row"].astype(int))
    report.loc[report["source_row"].isin(included_rows), ["included", "reason"]] = [True, "included"]
    scores = scores[scores["source_row"].isin(included_rows)].copy()
    items = items[items["source_row"].isin(included_rows)].copy()
    if scores.empty:
        save_csv(mapping, output / "post_survey_90_question_mapping.csv")
        save_csv(column_audit, output / "post_survey_90_column_audit.csv")
        save_csv(report, output / "post_survey_90_filter_report.csv")
        raise ValueError("90版に有効なA系回答がありません。")

    descriptives = descriptive_statistics(scores, "condition", CONDITIONS_90)
    omnibus, pairwise = paired_analysis(scores, CONDITIONS_90)
    pvalue_table = pairwise_pvalue_table(pairwise, PAIR_ORDER_90)
    save_csv(mapping, output / "post_survey_90_question_mapping.csv")
    save_csv(column_audit, output / "post_survey_90_column_audit.csv")
    save_csv(report.sort_values("source_row"), output / "post_survey_90_filter_report.csv")
    save_csv(scores[["participant_id", "condition", *METRICS]], output / "post_survey_90_analysis_data.csv")
    save_csv(items, output / "post_survey_90_question_data_long.csv")
    save_csv(descriptives, output / "post_survey_90_descriptive_stats.csv")
    save_csv(omnibus, output / "post_survey_90_omnibus_results.csv")
    save_csv(pairwise, output / "post_survey_90_pairwise_results.csv")
    save_csv(pvalue_table, output / "post_survey_90_pairwise_pvalue_table.csv")
    plot_metric_panels(
        scores, ("Reading", "Output"), "condition", CONDITIONS_90,
        CONDITION_LABELS_90, output / "post_survey_90_composite_scores.png",
        args.dpi, args.seed, "Post-survey 90: Composite Scores", paired=True,
    )
    plot_metric_panels(
        scores, METRICS[2:], "condition", CONDITIONS_90,
        CONDITION_LABELS_90, output / "post_survey_90_question_scores.png",
        args.dpi, args.seed, "Post-survey 90: Question Scores", paired=True,
    )
    report_path = output / "post_survey_90_report.md"
    write_report_90(scores, mapping, descriptives, pvalue_table, report_path)
    print(f"  saved: {report_path}")
    print(f"90版: A系有効参加者 {scores['participant_id'].nunique()}名")


def analyze_60(args: argparse.Namespace) -> None:
    output = args.output_dir / "post_survey_60"
    output.mkdir(parents=True, exist_ok=True)
    raw = read_form(args.input_60)
    id_column = find_column(list(raw.columns), r"参加者ID", "参加者ID")
    duration_column = find_column(list(raw.columns), r"ショート動画視聴時間", "視聴時間")
    timestamp_matches = [column for column in raw.columns if "タイムスタンプ" in column]
    timestamp_column = timestamp_matches[0] if timestamp_matches else None
    mapping = build_question_map(raw, "60")
    column_audit = build_column_audit(raw, mapping)
    report = make_filter_report(raw, id_column, r"B\d+")
    durations = raw[duration_column].map(normalize_duration).astype("string")
    invalid_duration_rows = set(
        raw.loc[report["included"] & ~durations.isin(DURATIONS_60), "source_row"].astype(int)
    )
    mark_report(report, invalid_duration_rows, "invalid_viewing_duration")
    candidate_rows = report.loc[report["included"], "source_row"]
    candidates = raw[raw["source_row"].isin(candidate_rows)].copy()
    candidate_durations = durations.loc[candidates.index]
    scores, items, invalid_scores = score_rows(
        candidates, mapping, id_column, "60", candidate_durations
    )
    invalid_source_rows = set(candidates.loc[invalid_scores, "source_row"].astype(int))
    mark_report(report, invalid_source_rows, "missing_or_out_of_range_score")
    candidates = candidates.loc[~invalid_scores].copy()
    candidates["participant_id"] = normalize_participant_id(candidates[id_column])
    candidates, duplicate_rows = resolve_duplicate_rows(
        candidates, timestamp_column, args.duplicate_policy
    )
    mark_report(report, duplicate_rows, f"duplicate_discarded_by_{args.duplicate_policy}")
    included_rows = set(candidates["source_row"].astype(int))
    report.loc[report["source_row"].isin(included_rows), ["included", "reason"]] = [True, "included"]
    scores = scores[scores["source_row"].isin(included_rows)].copy()
    items = items[items["source_row"].isin(included_rows)].copy()

    save_csv(mapping, output / "post_survey_60_question_mapping.csv")
    save_csv(column_audit, output / "post_survey_60_column_audit.csv")
    save_csv(report.sort_values("source_row"), output / "post_survey_60_filter_report.csv")
    if scores.empty:
        empty_scores = pd.DataFrame(columns=["participant_id", "viewing_duration", *METRICS])
        empty_pairwise = pd.DataFrame(columns=[
            "metric", "metric_label", "condition_1", "condition_2",
            "n_1", "n_2", "p_raw", "p_holm_within_metric", "significance_holm",
        ])
        save_csv(empty_scores, output / "post_survey_60_analysis_data.csv")
        save_csv(items, output / "post_survey_60_question_data_long.csv")
        save_csv(descriptive_statistics(empty_scores, "viewing_duration", DURATIONS_60), output / "post_survey_60_descriptive_stats.csv")
        empty_omnibus = pd.DataFrame(columns=[
            "metric", "metric_label", "groups_present", "test", "statistic",
            "p_raw", "residual_shapiro_p", "levene_p", "effect", "effect_name",
            "p_holm_across_metrics", "significance_holm",
        ])
        save_csv(empty_omnibus, output / "post_survey_60_omnibus_results.csv")
        save_csv(empty_pairwise, output / "post_survey_60_pairwise_results.csv")
        save_csv(pairwise_pvalue_table(empty_pairwise, tuple(combinations(DURATIONS_60, 2))), output / "post_survey_60_pairwise_pvalue_table.csv")
        report_path = output / "post_survey_60_report.md"
        write_report_60(empty_scores, mapping, pd.DataFrame(), empty_pairwise, report_path)
        print(f"  saved: {report_path}")
        print("60版: B系回答がないため、構造検証のみ完了しました。")
        return

    descriptives = descriptive_statistics(scores, "viewing_duration", DURATIONS_60)
    omnibus, pairwise = independent_analysis(scores, "viewing_duration", DURATIONS_60)
    all_pairs = tuple(combinations(DURATIONS_60, 2))
    pvalue_table = pairwise_pvalue_table(pairwise, all_pairs)
    save_csv(scores[["participant_id", "viewing_duration", *METRICS]], output / "post_survey_60_analysis_data.csv")
    save_csv(items, output / "post_survey_60_question_data_long.csv")
    save_csv(descriptives, output / "post_survey_60_descriptive_stats.csv")
    save_csv(omnibus, output / "post_survey_60_omnibus_results.csv")
    save_csv(pairwise, output / "post_survey_60_pairwise_results.csv")
    save_csv(pvalue_table, output / "post_survey_60_pairwise_pvalue_table.csv")
    duration_labels = {duration: duration for duration in DURATIONS_60}
    plot_metric_panels(
        scores, ("Reading", "Output"), "viewing_duration", DURATIONS_60,
        duration_labels, output / "post_survey_60_composite_scores.png",
        args.dpi, args.seed, "Post-survey 60: Composite Scores by Viewing Duration", paired=False,
    )
    plot_metric_panels(
        scores, METRICS[2:], "viewing_duration", DURATIONS_60,
        duration_labels, output / "post_survey_60_question_scores.png",
        args.dpi, args.seed, "Post-survey 60: Question Scores by Viewing Duration", paired=False,
    )
    report_path = output / "post_survey_60_report.md"
    write_report_60(scores, mapping, descriptives, pairwise, report_path)
    print(f"  saved: {report_path}")
    print(f"60版: B系有効参加者 {scores['participant_id'].nunique()}名")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        if args.study in ("90", "all"):
            analyze_90(args)
        if args.study in ("60", "all"):
            analyze_60(args)


if __name__ == "__main__":
    main()
