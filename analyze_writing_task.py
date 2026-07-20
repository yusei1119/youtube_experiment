#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Writing task 90/60 の時間・質問・文字数を分析する。

90版:
  A+数字の参加者だけを対象に、short / med / control の対応あり3条件を比較。
  各指標の3ペア比較をHolm補正する。

60版:
  B+数字の参加者だけを対象に、5/10/15/20/25/30分の参加者間比較。
  各指標の全時間ペア比較をHolm補正する。

時間指標:
  Total_task_sec   ページ開始から送信までの総所要時間
  Total_answer_sec 5問分のLatency + Writing（確認・送信時間を除く）
  Latency_sec      質問表示から最初の入力までの時間の5問合計
  Writing_sec      実際に入力・修正していた時間の5問合計
  Total_chars      5問分の回答文字数合計

実行例:
  python analyze_writing_task.py
  python analyze_writing_task.py --study all
"""

from __future__ import annotations

import argparse
import math
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
    p_stars,
    paired_comparison,
    repeated_measures_anova,
    safe_shapiro,
)


CATEGORIES = ("general", "content", "inquiry", "emotion", "summary")
CATEGORY_LABELS = {
    "general": "General",
    "content": "Content",
    "inquiry": "Inquiry",
    "emotion": "Emotion",
    "summary": "Summary",
}
CONDITIONS_90 = ("short", "med", "control")
CONDITION_LABELS = {"short": "Short", "med": "Meditation", "control": "Control"}
DURATIONS_60 = tuple(f"{minutes}min" for minutes in range(5, 31, 5))

OVERALL_METRICS = (
    "Total_task_sec",
    "Total_answer_sec",
    "Latency_sec",
    "Writing_sec",
    "Total_chars",
)
MEASURES = ("Latency", "Writing", "Chars")
ALL_METRICS = OVERALL_METRICS + tuple(
    f"{category}_{measure}" for category in CATEGORIES for measure in MEASURES
)
METRIC_LABELS = {
    "Total_task_sec": "Total task time",
    "Total_answer_sec": "Total answer time",
    "Latency_sec": "Time to first input (sum)",
    "Writing_sec": "Writing time (sum)",
    "Total_chars": "Total character count",
}
for _category in CATEGORIES:
    for _measure in MEASURES:
        _unit_label = {
            "Latency": "time to first input",
            "Writing": "writing time",
            "Chars": "character count",
        }[_measure]
        METRIC_LABELS[f"{_category}_{_measure}"] = (
            f"{CATEGORY_LABELS[_category]}: {_unit_label}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Writing taskの時間・質問・文字数を条件比較します。"
    )
    parser.add_argument("--study", choices=("90", "60", "all"), default="all")
    parser.add_argument("--input-90", type=Path, default=Path("writing_responses.csv"))
    parser.add_argument("--input-60", type=Path, default=Path("writing_60_responses.csv"))
    parser.add_argument(
        "--nasa-90-input",
        type=Path,
        default=Path("nasa_task_90_results.csv"),
        help="90版の条件ラベルを時系列照合するNASA CSV",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("writing_task_analysis"))
    parser.add_argument("--duplicate-policy", choices=("latest", "first", "error"), default="latest")
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def ensure_columns(df: pd.DataFrame, required: set[str], path: Path) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{path}: 必須列がありません: {missing}")


def save_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  saved: {path}")


def numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def extract_writing_metrics(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """新旧両CSV形式から全体指標と質問別longデータを作る。"""
    result = df.copy()
    latency_columns = []
    writing_columns = []
    char_columns = []
    question_frames = []

    for category in CATEGORIES:
        modern_latency = numeric_series(result, f"{category}_latency_sec")
        legacy_latency = numeric_series(result, f"{category}_latency_to_first_input_sec")
        latency = modern_latency.combine_first(legacy_latency)

        modern_writing = numeric_series(result, f"{category}_writing_duration_sec")
        legacy_cumulative = numeric_series(result, f"{category}_cumulative_duration_sec")
        legacy_writing = (legacy_cumulative - latency).clip(lower=0)
        writing = modern_writing.combine_first(legacy_writing)
        chars = numeric_series(result, f"{category}_answer_char_count")

        latency_name = f"{category}_Latency"
        writing_name = f"{category}_Writing"
        char_name = f"{category}_Chars"
        result[latency_name] = latency
        result[writing_name] = writing
        result[char_name] = chars
        latency_columns.append(latency_name)
        writing_columns.append(writing_name)
        char_columns.append(char_name)

        metadata = {
            "participant_id": result["participant_id"],
            "source_row": result["source_row"],
            "category": category,
            "category_label": CATEGORY_LABELS[category],
            "question_id": result.get(f"{category}_question_id", pd.Series("", index=result.index)),
            "variant_number": result.get(f"{category}_variant_number", pd.Series(np.nan, index=result.index)),
            "display_order": result.get(f"{category}_display_order", pd.Series(np.nan, index=result.index)),
            "question_text": result.get(f"{category}_question_text", pd.Series("", index=result.index)),
            "answer_text": result.get(f"{category}_answer_text", pd.Series("", index=result.index)),
            "Latency": latency,
            "Writing": writing,
            "Chars": chars,
        }
        for grouping_column in ("video_condition", "viewing_duration"):
            if grouping_column in result:
                metadata[grouping_column] = result[grouping_column]
        question_frames.append(pd.DataFrame(metadata))

    result["Total_task_sec"] = numeric_series(result, "total_duration_sec")
    result["Latency_sec"] = result[latency_columns].sum(axis=1, min_count=len(CATEGORIES))
    result["Writing_sec"] = result[writing_columns].sum(axis=1, min_count=len(CATEGORIES))
    derived_answer = result["Latency_sec"] + result["Writing_sec"]
    result["Total_answer_sec"] = numeric_series(
        result, "total_answer_duration_sec"
    ).combine_first(derived_answer)
    derived_chars = result[char_columns].sum(axis=1, min_count=len(CATEGORIES))
    result["Total_chars"] = numeric_series(result, "total_char_count").combine_first(
        derived_chars
    )
    return result, pd.concat(question_frames, ignore_index=True)


def load_source(path: Path, id_pattern: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(f"入力CSVがありません: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = df.columns.astype(str).str.strip()
    ensure_columns(df, {"participant_id", "total_duration_sec"}, path)
    df = df.copy()
    df.insert(0, "source_row", np.arange(2, len(df) + 2))
    df["participant_id"] = df["participant_id"].astype("string").str.strip()
    valid_id = df["participant_id"].str.fullmatch(id_pattern, na=False)
    report_columns = ["source_row", "participant_id"]
    for column in ("submission_id", "video_condition", "viewing_duration", "created_at"):
        if column in df:
            report_columns.append(column)
    report = df[report_columns].copy()
    report["included"] = False
    report["reason"] = np.where(valid_id, "candidate", "invalid_participant_id")
    return df.loc[valid_id].copy(), report


def repair_90_conditions(
    writing: pd.DataFrame,
    nasa_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """同一参加者の実施時刻順をNASAと照合してWriting条件ラベルを検証する。"""
    repair_rows = []
    result = writing.copy()
    result["original_video_condition"] = result["video_condition"]
    result["condition_source"] = "writing_csv"
    if not nasa_path.exists():
        return result, pd.DataFrame(columns=[
            "participant_id", "source_row", "original_condition", "assigned_condition",
            "corrected", "reason",
        ])
    nasa = pd.read_csv(nasa_path, encoding="utf-8-sig")
    nasa.columns = nasa.columns.astype(str).str.strip()
    required = {"participant_id", "video_condition", "completed_at"}
    if not required <= set(nasa.columns):
        warnings.warn(f"{nasa_path} に時系列照合用列がないため条件修復を省略します。")
        return result, pd.DataFrame()
    nasa["participant_id"] = nasa["participant_id"].astype("string").str.strip()
    nasa["video_condition"] = nasa["video_condition"].astype("string").str.strip().str.lower()
    nasa["completed_at"] = pd.to_datetime(
        nasa["completed_at"], errors="coerce", utc=True, format="mixed"
    )
    result["_writing_time"] = pd.to_datetime(
        result["started_at"], errors="coerce", utc=True, format="mixed"
    )

    for participant_id, indices in result.groupby("participant_id").groups.items():
        writing_group = result.loc[indices].sort_values("_writing_time")
        nasa_group = nasa[
            (nasa["participant_id"] == participant_id)
            & nasa["video_condition"].isin(CONDITIONS_90)
        ].dropna(subset=["completed_at"]).sort_values("completed_at")
        can_assign = (
            len(writing_group) == 3
            and len(nasa_group) == 3
            and set(nasa_group["video_condition"]) == set(CONDITIONS_90)
        )
        if can_assign:
            assigned = nasa_group["video_condition"].tolist()
            for row_index, condition in zip(writing_group.index, assigned):
                original = str(result.at[row_index, "video_condition"])
                corrected = original != condition
                result.at[row_index, "video_condition"] = condition
                result.at[row_index, "condition_source"] = "nasa_time_order"
                repair_rows.append({
                    "participant_id": participant_id,
                    "source_row": int(result.at[row_index, "source_row"]),
                    "original_condition": original,
                    "assigned_condition": condition,
                    "corrected": corrected,
                    "reason": "matched_by_within_participant_time_order",
                })
        else:
            for row_index in writing_group.index:
                repair_rows.append({
                    "participant_id": participant_id,
                    "source_row": int(result.at[row_index, "source_row"]),
                    "original_condition": str(result.at[row_index, "video_condition"]),
                    "assigned_condition": str(result.at[row_index, "video_condition"]),
                    "corrected": False,
                    "reason": "nasa_complete_order_not_available",
                })
    return result.drop(columns="_writing_time"), pd.DataFrame(repair_rows)


def resolve_duplicates(
    df: pd.DataFrame,
    keys: list[str],
    policy: str,
) -> tuple[pd.DataFrame, set[int]]:
    duplicated = df.duplicated(keys, keep=False)
    if not duplicated.any():
        return df, set()
    examples = df.loc[duplicated, keys].drop_duplicates().head(8).to_dict("records")
    if policy == "error":
        raise ValueError(f"重複回答があります: {examples}")
    ordered = df.copy()
    if "created_at" in ordered:
        ordered["_created_sort"] = pd.to_datetime(
            ordered["created_at"], errors="coerce", utc=True, format="mixed"
        )
        ordered = ordered.sort_values([*keys, "_created_sort", "source_row"])
    keep = "last" if policy == "latest" else "first"
    discarded = ordered.duplicated(keys, keep=keep)
    removed = set(ordered.loc[discarded, "source_row"].astype(int))
    return ordered.loc[~discarded].drop(columns="_created_sort", errors="ignore"), removed


def mark_report(report: pd.DataFrame, source_rows: set[int], reason: str) -> None:
    if not source_rows:
        return
    mask = report["source_row"].isin(source_rows)
    report.loc[mask, ["included", "reason"]] = [False, reason]


def descriptive_statistics(
    data: pd.DataFrame,
    group_column: str,
    group_order: tuple[str, ...],
) -> pd.DataFrame:
    rows = []
    for group_name in group_order:
        group = data[data[group_column] == group_name]
        if group.empty:
            continue
        for metric in ALL_METRICS:
            values = pd.to_numeric(group[metric], errors="coerce")
            clean = values.dropna()
            if clean.size >= 2:
                sem = clean.sem()
                margin = stats.t.ppf(0.975, clean.size - 1) * sem
                ci_low, ci_high = clean.mean() - margin, clean.mean() + margin
            else:
                sem = ci_low = ci_high = np.nan
            rows.append({
                group_column: group_name,
                "metric": metric,
                "label_en": METRIC_LABELS[metric],
                "n": int(clean.size),
                "missing": int(values.isna().sum()),
                "mean": clean.mean(),
                "sd": clean.std(ddof=1),
                "sem": sem,
                "ci95_low": ci_low,
                "ci95_high": ci_high,
                "median": clean.median(),
                "q1": clean.quantile(0.25),
                "q3": clean.quantile(0.75),
                "minimum": clean.min(),
                "maximum": clean.max(),
            })
    return pd.DataFrame(rows)


def question_variant_descriptives(
    question_data: pd.DataFrame,
    group_column: str,
) -> pd.DataFrame:
    long = question_data.melt(
        id_vars=[
            group_column, "category", "category_label", "question_id",
            "variant_number", "question_text",
        ],
        value_vars=list(MEASURES),
        var_name="measure",
        value_name="value",
    )
    result = (
        long.groupby(
            [group_column, "category", "category_label", "question_id", "variant_number", "question_text", "measure"],
            dropna=False,
            observed=True,
        )["value"]
        .agg(n="count", mean="mean", sd="std", median="median", minimum="min", maximum="max")
        .reset_index()
    )
    return result


def paired_analysis(
    data: pd.DataFrame,
    conditions: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    wide = data.pivot(index="participant_id", columns="video_condition", values=list(ALL_METRICS))
    wide = wide.loc[:, pd.MultiIndex.from_product([ALL_METRICS, conditions])]
    omnibus_rows = []
    pairwise_rows = []
    for metric in ALL_METRICS:
        values = wide.loc[:, [(metric, condition) for condition in conditions]].to_numpy(float)
        n = len(values)
        residuals = values - values.mean(axis=1, keepdims=True) - values.mean(axis=0, keepdims=True) + values.mean()
        normality_p = safe_shapiro(residuals.ravel())
        if n >= 2 and np.allclose(values, values[:, [0]]):
            statistic, p_raw, effect = 0.0, 1.0, 0.0
            test, effect_name = "all within-participant differences are zero", "Kendall's W"
        elif n >= 3 and np.isfinite(normality_p) and normality_p >= 0.05:
            statistic, p_raw, effect = repeated_measures_anova(values)
            test, effect_name = "one-way repeated-measures ANOVA", "partial eta squared"
        elif n >= 2:
            test_result = stats.friedmanchisquare(*(values[:, i] for i in range(values.shape[1])))
            statistic, p_raw = float(test_result.statistic), float(test_result.pvalue)
            effect = statistic / (n * (values.shape[1] - 1))
            test, effect_name = "Friedman test", "Kendall's W"
        else:
            statistic = p_raw = effect = np.nan
            test = effect_name = "NA"
        omnibus_rows.append({
            "metric": metric, "label_en": METRIC_LABELS[metric], "n": n,
            "test": test, "statistic": statistic, "p_raw": p_raw,
            "residual_shapiro_p": normality_p, "effect": effect,
            "effect_name": effect_name,
        })
        current_rows = []
        for condition_1, condition_2 in combinations(conditions, 2):
            result = paired_comparison(
                wide[(metric, condition_1)].to_numpy(float),
                wide[(metric, condition_2)].to_numpy(float),
            )
            current_rows.append({
                "metric": metric, "label_en": METRIC_LABELS[metric], "n": n,
                "condition_1": condition_1, "condition_2": condition_2,
                **result,
            })
        adjusted = holm_adjust([float(row["p_raw"]) for row in current_rows])
        for row, p_holm in zip(current_rows, adjusted):
            row["p_holm_within_metric"] = p_holm
            row["significance_holm"] = p_stars(p_holm)
        pairwise_rows.extend(current_rows)
    omnibus = pd.DataFrame(omnibus_rows)
    omnibus["p_holm_across_metrics"] = holm_adjust(omnibus["p_raw"].tolist())
    omnibus["significance_holm"] = omnibus["p_holm_across_metrics"].map(p_stars)
    return omnibus, pd.DataFrame(pairwise_rows), wide


def independent_analysis(
    data: pd.DataFrame,
    group_column: str,
    group_order: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    present = tuple(group for group in group_order if group in set(data[group_column]))
    omnibus_rows = []
    pairwise_rows = []
    for metric in ALL_METRICS:
        groups = [
            pd.to_numeric(data.loc[data[group_column] == group, metric], errors="coerce").dropna().to_numpy(float)
            for group in present
        ]
        nonempty = [group for group in groups if group.size]
        if len(nonempty) < 2:
            omnibus_rows.append({
                "metric": metric, "label_en": METRIC_LABELS[metric], "test": "NA",
                "statistic": np.nan, "p_raw": np.nan, "effect": np.nan,
                "effect_name": "", "residual_shapiro_p": np.nan, "levene_p": np.nan,
            })
        else:
            residuals = np.concatenate([group - group.mean() for group in nonempty])
            normality_p = safe_shapiro(residuals)
            if all(group.size >= 2 for group in nonempty):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    levene_p = float(stats.levene(*nonempty, center="median").pvalue)
            else:
                levene_p = np.nan
            all_values = np.concatenate(nonempty)
            if np.ptp(all_values) == 0:
                statistic, p_raw, effect = 0.0, 1.0, 0.0
                test, effect_name = "all group values are identical", "epsilon squared"
            elif np.isfinite(normality_p) and normality_p >= 0.05 and np.isfinite(levene_p) and levene_p >= 0.05:
                result = stats.f_oneway(*nonempty)
                statistic, p_raw = float(result.statistic), float(result.pvalue)
                grand = all_values.mean()
                ss_between = sum(group.size * (group.mean() - grand) ** 2 for group in nonempty)
                ss_total = np.square(all_values - grand).sum()
                effect = ss_between / ss_total if ss_total else 0.0
                test, effect_name = "one-way ANOVA", "eta squared"
            else:
                result = stats.kruskal(*nonempty)
                statistic, p_raw = float(result.statistic), float(result.pvalue)
                total_n = sum(group.size for group in nonempty)
                effect = max(0.0, (statistic - len(nonempty) + 1) / (total_n - len(nonempty))) if total_n > len(nonempty) else np.nan
                test, effect_name = "Kruskal-Wallis", "epsilon squared"
            omnibus_rows.append({
                "metric": metric, "label_en": METRIC_LABELS[metric], "test": test,
                "statistic": statistic, "p_raw": p_raw, "effect": effect,
                "effect_name": effect_name, "residual_shapiro_p": normality_p,
                "levene_p": levene_p,
            })

        current_rows = []
        for group_1, group_2 in combinations(present, 2):
            x = pd.to_numeric(data.loc[data[group_column] == group_1, metric], errors="coerce").dropna().to_numpy(float)
            y = pd.to_numeric(data.loc[data[group_column] == group_2, metric], errors="coerce").dropna().to_numpy(float)
            result = independent_comparison(x, y)
            current_rows.append({
                "metric": metric, "label_en": METRIC_LABELS[metric],
                "condition_1": group_1, "condition_2": group_2,
                "n_1": len(x), "n_2": len(y), **result,
            })
        adjusted = holm_adjust([float(row["p_raw"]) for row in current_rows])
        for row, p_holm in zip(current_rows, adjusted):
            row["p_holm_within_metric"] = p_holm
            row["significance_holm"] = p_stars(p_holm)
        pairwise_rows.extend(current_rows)
    omnibus = pd.DataFrame(omnibus_rows)
    omnibus["p_holm_across_metrics"] = holm_adjust(omnibus["p_raw"].tolist())
    omnibus["significance_holm"] = omnibus["p_holm_across_metrics"].map(p_stars)
    return omnibus, pd.DataFrame(pairwise_rows)


def pairwise_wide_table(pairwise: pd.DataFrame, conditions: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for metric in ALL_METRICS:
        row: dict[str, str | float] = {"metric": metric, "label_en": METRIC_LABELS[metric]}
        metric_rows = pairwise[pairwise["metric"] == metric]
        for condition_1, condition_2 in combinations(conditions, 2):
            prefix = f"{condition_1}_vs_{condition_2}"
            match = metric_rows[
                (metric_rows["condition_1"] == condition_1)
                & (metric_rows["condition_2"] == condition_2)
            ]
            if match.empty:
                p_raw = p_holm = np.nan
                significance = ""
            else:
                p_raw = float(match.iloc[0]["p_raw"])
                p_holm = float(match.iloc[0]["p_holm_within_metric"])
                significance = str(match.iloc[0]["significance_holm"])
            row[f"{prefix}_p_raw"] = p_raw
            row[f"{prefix}_p_holm"] = p_holm
            row[f"{prefix}_significance"] = significance
            row[f"{prefix}_display"] = f"{p_holm:.4g} {significance}" if np.isfinite(p_holm) else ""
        rows.append(row)
    return pd.DataFrame(rows)


def configure_plot_style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "axes.linewidth": 1.2,
        "xtick.direction": "in", "ytick.direction": "in",
    })


def plot_metric_panels(
    data: pd.DataFrame,
    metrics: tuple[str, ...],
    group_column: str,
    group_order: tuple[str, ...],
    output: Path,
    dpi: int,
    seed: int,
    title: str,
) -> None:
    configure_plot_style()
    present = tuple(group for group in group_order if group in set(data[group_column]))
    ncols = 3
    nrows = math.ceil(len(metrics) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(15, 4.8 * nrows), squeeze=False)
    rng = np.random.default_rng(seed)
    x_positions = np.arange(len(present))
    for ax, metric in zip(axes.flat, metrics):
        means, sems = [], []
        for x_position, group_name in enumerate(present):
            values = pd.to_numeric(
                data.loc[data[group_column] == group_name, metric], errors="coerce"
            ).dropna().to_numpy(float)
            ax.scatter(
                x_position + rng.uniform(-0.10, 0.10, len(values)), values,
                color="0.55", alpha=0.6, s=24,
            )
            means.append(values.mean() if len(values) else np.nan)
            sems.append(stats.sem(values) if len(values) >= 2 else np.nan)
        ax.plot(x_positions, means, color="#e41a1c", marker="o", linewidth=2)
        ax.errorbar(x_positions, means, yerr=sems, fmt="none", color="black", capsize=4)
        ax.set_xticks(x_positions, [CONDITION_LABELS.get(value, value) for value in present])
        ax.set_title(METRIC_LABELS[metric])
        ax.grid(axis="y", linestyle="--", alpha=0.25)
    for ax in axes.flat[len(metrics):]:
        ax.axis("off")
    fig.suptitle(title, fontsize=18)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.subplots_adjust(hspace=0.38)
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def write_report_90(
    data: pd.DataFrame,
    descriptives: pd.DataFrame,
    pairwise_table: pd.DataFrame,
    output: Path,
) -> None:
    lines = [
        "# Writing task 90：3条件分析",
        "",
        f"- 解析対象: A系完全ケース {data['participant_id'].nunique()}名",
        "- 条件: short / med / control",
        "- ペア比較: 各指標内の3比較をHolm補正",
        "",
        "## 全体指標の平均",
        "",
        "| 指標 | Short | Meditation | Control |",
        "|---|---:|---:|---:|",
    ]
    for metric in OVERALL_METRICS:
        values = []
        for condition in CONDITIONS_90:
            match = descriptives[
                (descriptives["metric"] == metric)
                & (descriptives["video_condition"] == condition)
            ]
            values.append(f"{float(match.iloc[0]['mean']):.2f}" if not match.empty else "NA")
        lines.append(f"| {METRIC_LABELS[metric]} | " + " | ".join(values) + " |")
    lines.extend([
        "", "## 全体指標のHolm補正後p値", "",
        "| 指標 | short vs med | short vs control | med vs control |",
        "|---|---:|---:|---:|",
    ])
    for metric in OVERALL_METRICS:
        row = pairwise_table[pairwise_table["metric"] == metric].iloc[0]
        lines.append(
            f"| {METRIC_LABELS[metric]} | {row['short_vs_med_display']} "
            f"| {row['short_vs_control_display']} | {row['med_vs_control_display']} |"
        )
    lines.extend([
        "", "有意記号: * p<.05, ** p<.01, *** p<.001, NS p≥.05。",
        "質問カテゴリ別の時間・文字数と検定結果はCSVに収録しています。", "",
    ])
    output.write_text("\n".join(lines), encoding="utf-8")


def write_report_60(
    data: pd.DataFrame,
    descriptives: pd.DataFrame,
    pairwise: pd.DataFrame,
    output: Path,
) -> None:
    lines = [
        "# Writing task 60：視聴時間条件別分析",
        "",
        f"- 解析対象: B系参加者 {data['participant_id'].nunique()}名",
        "- 条件: 5 / 10 / 15 / 20 / 25 / 30 min",
        "- ペア比較: 各指標内の全時間ペアをHolm補正",
        "",
        "## 条件別の全体指標平均",
        "",
        "| 視聴時間 | n | 総所要時間 | 総回答時間 | 入力まで | 回答中 | 総文字数 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for duration in DURATIONS_60:
        group = data[data["viewing_duration"] == duration]
        if group.empty:
            continue
        means = []
        for metric in OVERALL_METRICS:
            match = descriptives[
                (descriptives["viewing_duration"] == duration)
                & (descriptives["metric"] == metric)
            ]
            means.append(f"{float(match.iloc[0]['mean']):.2f}" if not match.empty else "NA")
        lines.append(f"| {duration} | {len(group)} | " + " | ".join(means) + " |")
    significant = pairwise[
        pd.to_numeric(pairwise["p_holm_within_metric"], errors="coerce") < 0.05
    ]
    lines.extend(["", "## Holm補正後に有意なペア比較", ""])
    if significant.empty:
        lines.append("有意なペア比較はありませんでした。")
    else:
        lines.extend([
            "| 指標 | 条件1 | 条件2 | 補正p値 | 有意記号 |",
            "|---|---|---|---:|---:|",
        ])
        for row in significant.itertuples(index=False):
            lines.append(
                f"| {row.label_en} | {row.condition_1} | {row.condition_2} "
                f"| {row.p_holm_within_metric:.4g} | {row.significance_holm} |"
            )
    lines.extend(["", "有意記号: * p<.05, ** p<.01, *** p<.001。", ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def analyze_90(args: argparse.Namespace) -> None:
    output = args.output_dir / "writing_90"
    output.mkdir(parents=True, exist_ok=True)
    data, report = load_source(args.input_90, r"A\d+")
    ensure_columns(data, {"video_condition", "started_at"}, args.input_90)
    data["video_condition"] = data["video_condition"].astype("string").str.strip().str.lower()
    data, repairs = repair_90_conditions(data, args.nasa_90_input)
    valid_condition = data["video_condition"].isin(CONDITIONS_90)
    invalid_rows = set(data.loc[~valid_condition, "source_row"].astype(int))
    mark_report(report, invalid_rows, "invalid_condition")
    data = data.loc[valid_condition].copy()
    data, question_data = extract_writing_metrics(data)
    invalid_values = data[list(ALL_METRICS)].isna().any(axis=1) | (data[list(ALL_METRICS)] < 0).any(axis=1)
    invalid_rows = set(data.loc[invalid_values, "source_row"].astype(int))
    mark_report(report, invalid_rows, "missing_or_negative_metric")
    data = data.loc[~invalid_values].copy()
    data, duplicates = resolve_duplicates(
        data, ["participant_id", "video_condition"], args.duplicate_policy
    )
    mark_report(report, duplicates, f"duplicate_discarded_by_{args.duplicate_policy}")
    condition_sets = data.groupby("participant_id")["video_condition"].agg(set)
    complete_ids = condition_sets[
        condition_sets.map(lambda value: set(CONDITIONS_90) <= value)
    ].index
    incomplete_rows = set(
        data.loc[~data["participant_id"].isin(complete_ids), "source_row"].astype(int)
    )
    mark_report(report, incomplete_rows, "incomplete_three_conditions")
    data = data[data["participant_id"].isin(complete_ids)].copy()
    if data.empty:
        save_csv(report, output / "writing_90_filter_report.csv")
        raise ValueError("90版に3条件が揃ったA系参加者がいません。")
    included_rows = set(data["source_row"].astype(int))
    report.loc[report["source_row"].isin(included_rows), ["included", "reason"]] = [True, "included"]
    question_data = question_data[question_data["source_row"].isin(included_rows)].copy()
    question_data["video_condition"] = question_data["source_row"].map(
        data.set_index("source_row")["video_condition"]
    )

    descriptives = descriptive_statistics(data, "video_condition", CONDITIONS_90)
    variant_descriptives = question_variant_descriptives(question_data, "video_condition")
    omnibus, pairwise, wide = paired_analysis(data, CONDITIONS_90)
    pairwise_table = pairwise_wide_table(pairwise, CONDITIONS_90)
    analysis_columns = ["participant_id", "video_condition", *ALL_METRICS]
    save_csv(report.sort_values("source_row"), output / "writing_90_filter_report.csv")
    save_csv(repairs, output / "writing_90_condition_repair_report.csv")
    save_csv(data[analysis_columns], output / "writing_90_analysis_data.csv")
    save_csv(question_data, output / "writing_90_question_data_long.csv")
    save_csv(descriptives, output / "writing_90_descriptive_stats.csv")
    save_csv(variant_descriptives, output / "writing_90_question_variant_descriptive_stats.csv")
    save_csv(omnibus, output / "writing_90_omnibus_results.csv")
    save_csv(pairwise, output / "writing_90_pairwise_results.csv")
    save_csv(pairwise_table, output / "writing_90_pairwise_pvalue_table.csv")

    plot_metric_panels(
        data, OVERALL_METRICS, "video_condition", CONDITIONS_90,
        output / "writing_90_overall_metrics.png", args.dpi, args.seed,
        "Writing Task 90: Overall Metrics",
    )
    for measure in MEASURES:
        metrics = tuple(f"{category}_{measure}" for category in CATEGORIES)
        plot_metric_panels(
            data, metrics, "video_condition", CONDITIONS_90,
            output / f"writing_90_questions_{measure.lower()}.png",
            args.dpi, args.seed, f"Writing Task 90: Question-level {measure}",
        )
    report_path = output / "writing_90_report.md"
    write_report_90(data, descriptives, pairwise_table, report_path)
    print(f"  saved: {report_path}")
    print(f"90版: A系完全ケース {data['participant_id'].nunique()}名")


def analyze_60(args: argparse.Namespace) -> None:
    output = args.output_dir / "writing_60"
    output.mkdir(parents=True, exist_ok=True)
    data, report = load_source(args.input_60, r"B\d+")
    ensure_columns(data, {"viewing_duration"}, args.input_60)
    data["viewing_duration"] = data["viewing_duration"].astype("string").str.strip().str.lower()
    valid_duration = data["viewing_duration"].isin(DURATIONS_60)
    invalid_rows = set(data.loc[~valid_duration, "source_row"].astype(int))
    mark_report(report, invalid_rows, "invalid_viewing_duration")
    data = data.loc[valid_duration].copy()
    if data.empty:
        save_csv(report.sort_values("source_row"), output / "writing_60_filter_report.csv")
        print("60版: B系回答がないため分析をスキップしました。")
        return
    data, question_data = extract_writing_metrics(data)
    invalid_values = data[list(ALL_METRICS)].isna().any(axis=1) | (data[list(ALL_METRICS)] < 0).any(axis=1)
    invalid_rows = set(data.loc[invalid_values, "source_row"].astype(int))
    mark_report(report, invalid_rows, "missing_or_negative_metric")
    data = data.loc[~invalid_values].copy()
    data, duplicates = resolve_duplicates(data, ["participant_id"], args.duplicate_policy)
    mark_report(report, duplicates, f"duplicate_discarded_by_{args.duplicate_policy}")
    if data.empty:
        save_csv(report.sort_values("source_row"), output / "writing_60_filter_report.csv")
        print("60版: 有効なB系回答がないため分析をスキップしました。")
        return
    included_rows = set(data["source_row"].astype(int))
    report.loc[report["source_row"].isin(included_rows), ["included", "reason"]] = [True, "included"]
    question_data = question_data[question_data["source_row"].isin(included_rows)].copy()
    descriptives = descriptive_statistics(data, "viewing_duration", DURATIONS_60)
    variant_descriptives = question_variant_descriptives(question_data, "viewing_duration")
    omnibus, pairwise = independent_analysis(data, "viewing_duration", DURATIONS_60)
    pairwise_table = pairwise_wide_table(pairwise, DURATIONS_60)
    analysis_columns = ["participant_id", "viewing_duration", *ALL_METRICS]
    save_csv(report.sort_values("source_row"), output / "writing_60_filter_report.csv")
    save_csv(data[analysis_columns], output / "writing_60_analysis_data.csv")
    save_csv(question_data, output / "writing_60_question_data_long.csv")
    save_csv(descriptives, output / "writing_60_descriptive_stats.csv")
    save_csv(variant_descriptives, output / "writing_60_question_variant_descriptive_stats.csv")
    save_csv(omnibus, output / "writing_60_omnibus_results.csv")
    save_csv(pairwise, output / "writing_60_pairwise_results.csv")
    save_csv(pairwise_table, output / "writing_60_pairwise_pvalue_table.csv")
    plot_metric_panels(
        data, OVERALL_METRICS, "viewing_duration", DURATIONS_60,
        output / "writing_60_overall_metrics.png", args.dpi, args.seed,
        "Writing Task 60: Overall Metrics by Viewing Duration",
    )
    for measure in MEASURES:
        metrics = tuple(f"{category}_{measure}" for category in CATEGORIES)
        plot_metric_panels(
            data, metrics, "viewing_duration", DURATIONS_60,
            output / f"writing_60_questions_{measure.lower()}.png",
            args.dpi, args.seed, f"Writing Task 60: Question-level {measure}",
        )
    report_path = output / "writing_60_report.md"
    write_report_60(data, descriptives, pairwise, report_path)
    print(f"  saved: {report_path}")
    print(f"60版: B系有効回答 {len(data)}名")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.study in ("90", "all"):
        analyze_90(args)
    if args.study in ("60", "all"):
        analyze_60(args)


if __name__ == "__main__":
    main()
