#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""NASA-TLX CSV の統計解析と可視化。

90版:
  A+数字の参加者だけを対象に、short / control / med の対応あり3条件を解析する。
60版:
  B+数字の参加者だけを対象に、5min～30min の独立した時間条件を解析する。

主な実行例:
  python analyze_nasa_tlx.py
  python analyze_nasa_tlx.py --study all
  python analyze_nasa_tlx.py --study 60 --input-60 nasa_task_60_results.csv

必要パッケージ:
  numpy, pandas, scipy, matplotlib

注意:
  現在のアンケートの performance_slider_value は、質問文ですでに
  「低い値ほど良い、高い値ほど悪い」と定義されている。そのため 100-value の
  再反転は行わず、その値を Performance_rev（負荷方向）として使用する。
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


METRIC_SOURCE = {
    "Mental": "mental_slider_value",
    "Physical": "physical_slider_value",
    "Temporal": "temporal_slider_value",
    "Performance_rev": "performance_slider_value",
    "Effort": "effort_slider_value",
    "Frustration": "frustration_slider_value",
    "Overall": "overall_slider_value",
}
CORE6 = (
    "Mental",
    "Physical",
    "Temporal",
    "Performance_rev",
    "Effort",
    "Frustration",
)
METRICS = (*CORE6, "Overall", "Raw_TLX")
LABELS = {
    "Mental": "Mental Demand",
    "Physical": "Physical Demand",
    "Temporal": "Temporal Demand",
    "Performance_rev": "Performance (reversed)",
    "Effort": "Effort",
    "Frustration": "Frustration",
    "Overall": "Overall Workload",
    "Raw_TLX": "Raw TLX (mean of 6)",
}
CONDITION_ORDER_90 = ("short", "control", "med")
CONDITION_LABELS_90 = {
    "short": "Short",
    "control": "Control",
    "med": "Meditation",
}
DURATION_ORDER_60 = tuple(f"{minutes}min" for minutes in range(5, 31, 5))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NASA-TLXを有効IDだけに限定して統計解析・可視化します。"
    )
    parser.add_argument("--study", choices=("90", "60", "all"), default="90")
    parser.add_argument("--input-90", type=Path, default=Path("nasa_task_90_results.csv"))
    parser.add_argument("--input-60", type=Path, default=Path("nasa_task_60_results.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("nasa_tlx_analysis"))
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--duplicate-policy",
        choices=("latest", "first", "error"),
        default="latest",
        help="同一参加者・同一条件の重複回答の扱い（既定: latest）",
    )
    return parser.parse_args()


def ensure_columns(df: pd.DataFrame, required: set[str], path: Path) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{path}: 必須列がありません: {missing}")


def p_stars(p_value: float) -> str:
    if not np.isfinite(p_value):
        return ""
    if p_value < 0.001:
        return "***"
    if p_value < 0.01:
        return "**"
    if p_value < 0.05:
        return "*"
    return "NS"


def holm_adjust(p_values: list[float]) -> list[float]:
    """NaNを保ったHolm法の調整済みp値。"""
    values = np.asarray(p_values, dtype=float)
    adjusted = np.full(values.size, np.nan)
    valid = np.flatnonzero(np.isfinite(values))
    if valid.size == 0:
        return adjusted.tolist()
    ordered = valid[np.argsort(values[valid])]
    running_max = 0.0
    count = ordered.size
    for rank, index in enumerate(ordered):
        candidate = min(1.0, values[index] * (count - rank))
        running_max = max(running_max, candidate)
        adjusted[index] = running_max
    return adjusted.tolist()


def safe_shapiro(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 3 or np.ptp(values) == 0:
        return np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(stats.shapiro(values).pvalue)


def load_base(path: Path, id_pattern: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(f"入力CSVが見つかりません: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = df.columns.astype(str).str.strip()
    ensure_columns(df, {"participant_id", *METRIC_SOURCE.values()}, path)
    df = df.copy()
    df.insert(0, "source_row", np.arange(2, len(df) + 2))
    df["participant_id"] = df["participant_id"].astype("string").str.strip()
    valid_id = df["participant_id"].str.fullmatch(id_pattern, na=False)

    report = df[["source_row", "participant_id"]].copy()
    report["included"] = valid_id.to_numpy()
    report["reason"] = np.where(valid_id, "candidate", "invalid_participant_id")
    return df.loc[valid_id].copy(), report


def add_metrics(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    converted = pd.DataFrame(index=df.index)
    for metric, source in METRIC_SOURCE.items():
        converted[metric] = pd.to_numeric(df[source], errors="coerce")
    in_range = converted.ge(0) & converted.le(100)
    invalid = converted.isna().any(axis=1) | (~in_range).any(axis=1)
    for metric in METRIC_SOURCE:
        df[metric] = converted[metric]
    df["Raw_TLX"] = df[list(CORE6)].mean(axis=1)
    return df, invalid


def resolve_duplicates(
    df: pd.DataFrame,
    keys: list[str],
    policy: str,
) -> tuple[pd.DataFrame, set[int]]:
    duplicate_mask = df.duplicated(keys, keep=False)
    if not duplicate_mask.any():
        return df, set()
    examples = df.loc[duplicate_mask, keys].drop_duplicates().head(8).to_dict("records")
    if policy == "error":
        raise ValueError(f"同一参加者・条件の重複回答があります: {examples}")
    ordered = df.copy()
    if "created_at" in ordered:
        ordered["_created_sort"] = pd.to_datetime(ordered["created_at"], errors="coerce", utc=True)
        ordered = ordered.sort_values([*keys, "_created_sort", "source_row"])
    keep = "last" if policy == "latest" else "first"
    discarded = ordered.duplicated(keys, keep=keep)
    removed_rows = set(ordered.loc[discarded, "source_row"].astype(int))
    return ordered.loc[~discarded].drop(columns="_created_sort", errors="ignore"), removed_rows


def update_report(
    report: pd.DataFrame,
    source_rows: set[int] | pd.Series | np.ndarray,
    reason: str,
) -> None:
    rows = set(int(value) for value in source_rows)
    if not rows:
        return
    mask = report["source_row"].isin(rows)
    report.loc[mask, "included"] = False
    report.loc[mask, "reason"] = reason


def descriptives(long_df: pd.DataFrame, condition_order: tuple[str, ...]) -> pd.DataFrame:
    grouped = long_df.groupby(["metric", "condition"], observed=True)["value"]
    result = grouped.agg(
        n="count",
        mean="mean",
        sd="std",
        median="median",
        q1=lambda x: x.quantile(0.25),
        q3=lambda x: x.quantile(0.75),
        sem=lambda x: x.sem(),
        minimum="min",
        maximum="max",
    ).reset_index()
    metric_rank = {value: index for index, value in enumerate(METRICS)}
    condition_rank = {value: index for index, value in enumerate(condition_order)}
    result["label_en"] = result["metric"].map(LABELS)
    result["_metric_order"] = result["metric"].map(metric_rank)
    result["_condition_order"] = result["condition"].map(condition_rank)
    return result.sort_values(["_metric_order", "_condition_order"]).drop(
        columns=["_metric_order", "_condition_order"]
    )


def repeated_measures_anova(values: np.ndarray) -> tuple[float, float, float]:
    """1要因の反復測定ANOVA: F, p, partial eta squared。"""
    n_subjects, n_conditions = values.shape
    grand = values.mean()
    subject_means = values.mean(axis=1)
    condition_means = values.mean(axis=0)
    ss_total = np.square(values - grand).sum()
    ss_subject = n_conditions * np.square(subject_means - grand).sum()
    ss_condition = n_subjects * np.square(condition_means - grand).sum()
    ss_error = max(0.0, ss_total - ss_subject - ss_condition)
    df_condition = n_conditions - 1
    df_error = (n_subjects - 1) * df_condition
    if df_error <= 0:
        return np.nan, np.nan, np.nan
    if ss_error == 0:
        f_value = np.inf if ss_condition > 0 else 0.0
    else:
        f_value = (ss_condition / df_condition) / (ss_error / df_error)
    p_value = float(stats.f.sf(f_value, df_condition, df_error))
    denominator = ss_condition + ss_error
    eta_partial = ss_condition / denominator if denominator else 0.0
    return float(f_value), p_value, float(eta_partial)


def rank_biserial_paired(difference: np.ndarray) -> float:
    nonzero = difference[difference != 0]
    if nonzero.size == 0:
        return 0.0
    ranks = stats.rankdata(np.abs(nonzero))
    positive = ranks[nonzero > 0].sum()
    negative = ranks[nonzero < 0].sum()
    return float((positive - negative) / (positive + negative))


def paired_comparison(x: np.ndarray, y: np.ndarray) -> dict[str, float | str]:
    """effectの向きはcondition_1 - condition_2。"""
    difference = np.asarray(x, float) - np.asarray(y, float)
    n = difference.size
    normality_p = safe_shapiro(difference)
    if n < 2:
        return {
            "test": "NA", "statistic": np.nan, "p_raw": np.nan,
            "normality_p_difference": normality_p, "effect": np.nan,
            "effect_name": "", "mean_difference": np.nan,
        }
    if np.ptp(difference) == 0 and difference[0] == 0:
        return {
            "test": "all paired differences are zero", "statistic": 0.0,
            "p_raw": 1.0, "normality_p_difference": normality_p,
            "effect": 0.0, "effect_name": "rank-biserial r",
            "mean_difference": 0.0,
        }
    if np.isfinite(normality_p) and normality_p >= 0.05:
        result = stats.ttest_rel(x, y)
        sd = difference.std(ddof=1)
        effect = difference.mean() / sd if sd > 0 else np.sign(difference.mean()) * np.inf
        return {
            "test": "paired t-test", "statistic": float(result.statistic),
            "p_raw": float(result.pvalue), "normality_p_difference": normality_p,
            "effect": float(effect), "effect_name": "Cohen's dz",
            "mean_difference": float(difference.mean()),
        }
    result = stats.wilcoxon(x, y, zero_method="wilcox", alternative="two-sided")
    return {
        "test": "Wilcoxon signed-rank", "statistic": float(result.statistic),
        "p_raw": float(result.pvalue), "normality_p_difference": normality_p,
        "effect": rank_biserial_paired(difference),
        "effect_name": "rank-biserial r",
        "mean_difference": float(difference.mean()),
    }


def analyze_paired(wide: pd.DataFrame, condition_order: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    omnibus_rows: list[dict[str, float | str | int]] = []
    pairwise_rows: list[dict[str, float | str | int]] = []
    for metric in METRICS:
        values = wide.loc[:, [(metric, condition) for condition in condition_order]].to_numpy(float)
        subject_means = values.mean(axis=1, keepdims=True)
        condition_means = values.mean(axis=0, keepdims=True)
        residuals = values - subject_means - condition_means + values.mean()
        normality_p = safe_shapiro(residuals.ravel())
        n = values.shape[0]
        if n >= 2 and np.allclose(values, values[:, [0]]):
            statistic, p_raw, effect = 0.0, 1.0, 0.0
            test = "all within-participant condition differences are zero"
            effect_name = "Kendall's W"
        elif n >= 3 and np.isfinite(normality_p) and normality_p >= 0.05:
            statistic, p_raw, effect = repeated_measures_anova(values)
            test = "one-way repeated-measures ANOVA"
            effect_name = "partial eta squared"
        elif n >= 2:
            result = stats.friedmanchisquare(*(values[:, index] for index in range(values.shape[1])))
            statistic = float(result.statistic)
            p_raw = float(result.pvalue)
            effect = statistic / (n * (values.shape[1] - 1))
            test = "Friedman test"
            effect_name = "Kendall's W"
        else:
            statistic = p_raw = effect = np.nan
            test = "NA"
            effect_name = ""
        omnibus_rows.append({
            "metric": metric, "label_en": LABELS[metric], "n": n,
            "test": test, "statistic": statistic, "p_raw": p_raw,
            "residual_shapiro_p": normality_p, "effect": effect,
            "effect_name": effect_name,
        })

        metric_pair_rows = []
        for condition_1, condition_2 in combinations(condition_order, 2):
            result = paired_comparison(
                wide[(metric, condition_1)].to_numpy(float),
                wide[(metric, condition_2)].to_numpy(float),
            )
            metric_pair_rows.append({
                "metric": metric, "label_en": LABELS[metric], "n": n,
                "condition_1": condition_1, "condition_2": condition_2,
                **result,
            })
        adjusted = holm_adjust([float(row["p_raw"]) for row in metric_pair_rows])
        for row, p_holm in zip(metric_pair_rows, adjusted):
            row["p_holm_within_metric"] = p_holm
            row["significance_holm"] = p_stars(p_holm)
        pairwise_rows.extend(metric_pair_rows)

    omnibus = pd.DataFrame(omnibus_rows)
    omnibus["p_holm_across_metrics"] = holm_adjust(omnibus["p_raw"].tolist())
    omnibus["significance_holm"] = omnibus["p_holm_across_metrics"].map(p_stars)
    return omnibus, pd.DataFrame(pairwise_rows)


def independent_comparison(x: np.ndarray, y: np.ndarray) -> dict[str, float | str]:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if min(x.size, y.size) < 2:
        return {"test": "NA", "statistic": np.nan, "p_raw": np.nan, "effect": np.nan, "effect_name": ""}
    normal = safe_shapiro(x) >= 0.05 and safe_shapiro(y) >= 0.05
    if normal:
        result = stats.ttest_ind(x, y, equal_var=False)
        pooled = math.sqrt(((x.size - 1) * x.var(ddof=1) + (y.size - 1) * y.var(ddof=1)) / (x.size + y.size - 2))
        effect = (x.mean() - y.mean()) / pooled if pooled else 0.0
        return {"test": "Welch t-test", "statistic": float(result.statistic), "p_raw": float(result.pvalue), "effect": float(effect), "effect_name": "Cohen's d"}
    result = stats.mannwhitneyu(x, y, alternative="two-sided")
    effect = 2 * float(result.statistic) / (x.size * y.size) - 1
    return {"test": "Mann-Whitney U", "statistic": float(result.statistic), "p_raw": float(result.pvalue), "effect": effect, "effect_name": "rank-biserial r"}


def analyze_independent(long_df: pd.DataFrame, condition_order: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    omnibus_rows = []
    pairwise_rows = []
    for metric in METRICS:
        metric_df = long_df[long_df["metric"] == metric]
        groups = [metric_df.loc[metric_df["condition"] == condition, "value"].to_numpy(float) for condition in condition_order]
        groups = [group for group in groups if group.size]
        if len(groups) < 2:
            omnibus_rows.append({"metric": metric, "label_en": LABELS[metric], "test": "NA", "statistic": np.nan, "p_raw": np.nan, "effect": np.nan, "effect_name": ""})
            continue
        residuals = np.concatenate([group - group.mean() for group in groups])
        normality_p = safe_shapiro(residuals)
        levene_p = float(stats.levene(*groups, center="median").pvalue) if all(group.size >= 2 for group in groups) else np.nan
        if np.ptp(np.concatenate(groups)) == 0:
            result_statistic, result_pvalue = 0.0, 1.0
            effect = 0.0
            test, effect_name = "all group values are identical", "epsilon squared"
        elif np.isfinite(normality_p) and normality_p >= 0.05 and np.isfinite(levene_p) and levene_p >= 0.05:
            result = stats.f_oneway(*groups)
            result_statistic, result_pvalue = float(result.statistic), float(result.pvalue)
            grand = np.concatenate(groups).mean()
            ss_between = sum(group.size * (group.mean() - grand) ** 2 for group in groups)
            ss_total = np.square(np.concatenate(groups) - grand).sum()
            effect = ss_between / ss_total if ss_total else 0.0
            test, effect_name = "one-way ANOVA", "eta squared"
        else:
            result = stats.kruskal(*groups)
            result_statistic, result_pvalue = float(result.statistic), float(result.pvalue)
            total_n = sum(group.size for group in groups)
            effect = max(0.0, (float(result.statistic) - len(groups) + 1) / (total_n - len(groups))) if total_n > len(groups) else np.nan
            test, effect_name = "Kruskal-Wallis", "epsilon squared"
        omnibus_rows.append({
            "metric": metric, "label_en": LABELS[metric], "test": test,
            "statistic": result_statistic, "p_raw": result_pvalue,
            "residual_shapiro_p": normality_p, "levene_p": levene_p,
            "effect": effect, "effect_name": effect_name,
        })
        current = []
        for condition_1, condition_2 in combinations(condition_order, 2):
            x = metric_df.loc[metric_df["condition"] == condition_1, "value"].to_numpy(float)
            y = metric_df.loc[metric_df["condition"] == condition_2, "value"].to_numpy(float)
            current.append({
                "metric": metric, "label_en": LABELS[metric],
                "condition_1": condition_1, "condition_2": condition_2,
                "n_1": x.size, "n_2": y.size, **independent_comparison(x, y),
            })
        adjusted = holm_adjust([float(row["p_raw"]) for row in current])
        for row, p_holm in zip(current, adjusted):
            row["p_holm_within_metric"] = p_holm
            row["significance_holm"] = p_stars(p_holm)
        pairwise_rows.extend(current)
    omnibus = pd.DataFrame(omnibus_rows)
    omnibus["p_holm_across_metrics"] = holm_adjust(omnibus["p_raw"].tolist())
    omnibus["significance_holm"] = omnibus["p_holm_across_metrics"].map(p_stars)
    return omnibus, pd.DataFrame(pairwise_rows)


def configure_plot_style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Serif",
        "axes.linewidth": 1.3,
        "axes.titlesize": 15,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "xtick.direction": "in",
        "ytick.direction": "in",
    })


def plot_scatter_mean(
    long_df: pd.DataFrame,
    condition_order: tuple[str, ...],
    labels: dict[str, str],
    omnibus: pd.DataFrame,
    output: Path,
    dpi: int,
    seed: int,
) -> None:
    configure_plot_style()
    fig, axes = plt.subplots(2, 4, figsize=(18, 8.2), sharey=True)
    rng = np.random.default_rng(seed)
    p_map = dict(zip(omnibus["metric"], omnibus["p_holm_across_metrics"]))
    x_positions = np.arange(len(condition_order))
    for ax, metric in zip(axes.flat, METRICS):
        means, sems = [], []
        metric_df = long_df[long_df["metric"] == metric]
        for x_position, condition in enumerate(condition_order):
            values = metric_df.loc[metric_df["condition"] == condition, "value"].to_numpy(float)
            jitter = rng.uniform(-0.11, 0.11, values.size)
            ax.scatter(x_position + jitter, values, color="gray", alpha=0.58, s=25, zorder=2)
            means.append(values.mean() if values.size else np.nan)
            sems.append(stats.sem(values) if values.size >= 2 else np.nan)
        ax.plot(x_positions, means, color="#e41a1c", linewidth=2.2, zorder=3)
        ax.errorbar(x_positions, means, yerr=sems, fmt="o", color="black", ecolor="black", capsize=5, markersize=6, zorder=4)
        ax.set_title(LABELS[metric])
        ax.set_xticks(x_positions, [labels.get(value, value) for value in condition_order])
        ax.set_ylim(-4, 110)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.grid(axis="y", linestyle="--", alpha=0.28)
        p_value = p_map.get(metric, np.nan)
        ax.text(0.98, 0.96, f"Holm p={p_value:.3g} {p_stars(p_value)}" if np.isfinite(p_value) else "", transform=ax.transAxes, ha="right", va="top", fontsize=9)
    fig.suptitle("NASA-TLX Scatter + Mean ± SEM", fontsize=20)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {output}")


def plot_pairlines(
    wide: pd.DataFrame,
    condition_order: tuple[str, ...],
    labels: dict[str, str],
    output: Path,
    dpi: int,
) -> None:
    configure_plot_style()
    fig, axes = plt.subplots(2, 4, figsize=(18, 8.2), sharey=True)
    x_positions = np.arange(len(condition_order))
    for ax, metric in zip(axes.flat, METRICS):
        values = wide.loc[:, [(metric, condition) for condition in condition_order]].to_numpy(float)
        for participant_values in values:
            ax.plot(x_positions, participant_values, color="0.68", alpha=0.48, linewidth=0.9, marker="o", markersize=3)
        means = values.mean(axis=0)
        sems = stats.sem(values, axis=0) if values.shape[0] >= 2 else np.full(values.shape[1], np.nan)
        ax.plot(x_positions, means, color="#e41a1c", linewidth=2.4, marker="o", markersize=6, zorder=4)
        ax.errorbar(x_positions, means, yerr=sems, fmt="none", color="black", capsize=5, zorder=5)
        ax.set_title(LABELS[metric])
        ax.set_xticks(x_positions, [labels.get(value, value) for value in condition_order])
        ax.set_ylim(-4, 110)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.grid(axis="y", linestyle="--", alpha=0.28)
    fig.suptitle("NASA-TLX Paired Participant Lines + Mean ± SEM", fontsize=20)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {output}")


def save_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  saved: {path}")


def make_pairwise_pvalue_table(pairwise: pd.DataFrame) -> pd.DataFrame:
    """90版の3比較を、尺度ごとに横並びにした発表用p値表にする。"""
    comparisons = (
        ("short", "control"),
        ("short", "med"),
        ("control", "med"),
    )
    rows: list[dict[str, float | str]] = []
    for metric in METRICS:
        row: dict[str, float | str] = {
            "metric": metric,
            "label_en": LABELS[metric],
        }
        metric_rows = pairwise[pairwise["metric"] == metric]
        for condition_1, condition_2 in comparisons:
            match = metric_rows[
                (metric_rows["condition_1"] == condition_1)
                & (metric_rows["condition_2"] == condition_2)
            ]
            prefix = f"{condition_1}_vs_{condition_2}"
            if match.empty:
                p_raw = p_holm = np.nan
                significance = ""
            else:
                result = match.iloc[0]
                p_raw = float(result["p_raw"])
                p_holm = float(result["p_holm_within_metric"])
                significance = str(result["significance_holm"])
            row[f"{prefix}_p_raw"] = p_raw
            row[f"{prefix}_p_holm"] = p_holm
            row[f"{prefix}_significance"] = significance
            row[f"{prefix}_display"] = (
                f"{p_holm:.4g} {significance}" if np.isfinite(p_holm) else ""
            )
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_90(path: Path, root: Path, duplicate_policy: str, dpi: int, seed: int) -> None:
    output = root / "nasa_90"
    output.mkdir(parents=True, exist_ok=True)
    df, report = load_base(path, r"A\d+")
    ensure_columns(df, {"video_condition"}, path)
    df["video_condition"] = df["video_condition"].astype("string").str.strip().str.lower()
    valid_condition = df["video_condition"].isin(CONDITION_ORDER_90)
    update_report(report, df.loc[~valid_condition, "source_row"], "invalid_condition")
    df = df.loc[valid_condition].copy()
    df, invalid_values = add_metrics(df)
    update_report(report, df.loc[invalid_values, "source_row"], "missing_or_out_of_range_score")
    df = df.loc[~invalid_values].copy()
    df, duplicates = resolve_duplicates(df, ["participant_id", "video_condition"], duplicate_policy)
    update_report(report, duplicates, f"duplicate_discarded_by_{duplicate_policy}")

    condition_sets = df.groupby("participant_id")["video_condition"].agg(set)
    complete_ids = condition_sets[condition_sets.map(lambda value: set(CONDITION_ORDER_90) <= value)].index
    incomplete_rows = df.loc[~df["participant_id"].isin(complete_ids), "source_row"]
    update_report(report, incomplete_rows, "incomplete_three_conditions")
    df = df[df["participant_id"].isin(complete_ids)].copy()
    if df.empty:
        save_csv(report, output / "nasa_90_filter_report.csv")
        raise ValueError("90版に3条件が揃ったA系参加者がいません。")

    used_rows = set(df["source_row"].astype(int))
    report.loc[report["source_row"].isin(used_rows), ["included", "reason"]] = [True, "included"]
    wide = df.pivot(index="participant_id", columns="video_condition", values=list(METRICS))
    wide = wide.loc[:, pd.MultiIndex.from_product([METRICS, CONDITION_ORDER_90])].sort_index()
    long_df = df.melt(
        id_vars=["participant_id", "video_condition"], value_vars=list(METRICS),
        var_name="metric", value_name="value",
    ).rename(columns={"video_condition": "condition"})
    long_df["condition_label"] = long_df["condition"].map(CONDITION_LABELS_90)
    long_df["label_en"] = long_df["metric"].map(LABELS)
    omnibus, pairwise = analyze_paired(wide, CONDITION_ORDER_90)
    pairwise_table = make_pairwise_pvalue_table(pairwise)
    description = descriptives(long_df, CONDITION_ORDER_90)

    wide_export = wide.copy()
    wide_export.columns = [f"{metric}_{condition}" for metric, condition in wide_export.columns]
    save_csv(report.sort_values("source_row"), output / "nasa_90_filter_report.csv")
    save_csv(wide_export.reset_index(), output / "nasa_90_analysis_data_wide.csv")
    save_csv(long_df, output / "nasa_90_plot_data_long.csv")
    save_csv(description, output / "nasa_90_descriptive_stats.csv")
    save_csv(omnibus, output / "nasa_90_omnibus_results.csv")
    save_csv(pairwise, output / "nasa_90_pairwise_results.csv")
    save_csv(pairwise_table, output / "nasa_90_pairwise_pvalue_table.csv")
    plot_pairlines(wide, CONDITION_ORDER_90, CONDITION_LABELS_90, output / "nasa_90_pairlines.png", dpi)
    plot_scatter_mean(long_df, CONDITION_ORDER_90, CONDITION_LABELS_90, omnibus, output / "nasa_90_scatter_mean_sem.png", dpi, seed)
    print(f"90版: A系完全ケース {len(wide)}名（入力 {len(report)}行）")
    print(omnibus[["metric", "test", "p_raw", "p_holm_across_metrics", "significance_holm"]].to_string(index=False))
    display_columns = [
        "label_en",
        "short_vs_control_display",
        "short_vs_med_display",
        "control_vs_med_display",
    ]
    print("\n3条件の全ペア比較（各尺度内の3比較をHolm補正）")
    print(pairwise_table[display_columns].to_string(index=False))


def analyze_60(path: Path, root: Path, duplicate_policy: str, dpi: int, seed: int) -> None:
    output = root / "nasa_60"
    output.mkdir(parents=True, exist_ok=True)
    df, report = load_base(path, r"B\d+")
    ensure_columns(df, {"viewing_duration"}, path)
    df["viewing_duration"] = df["viewing_duration"].astype("string").str.strip().str.lower()
    valid_condition = df["viewing_duration"].isin(DURATION_ORDER_60)
    update_report(report, df.loc[~valid_condition, "source_row"], "invalid_viewing_duration")
    df = df.loc[valid_condition].copy()
    df, invalid_values = add_metrics(df)
    update_report(report, df.loc[invalid_values, "source_row"], "missing_or_out_of_range_score")
    df = df.loc[~invalid_values].copy()
    # 60版は参加者間計画（1名につき1つの視聴時間）なので、ID単位で重複を解消する。
    df, duplicates = resolve_duplicates(df, ["participant_id"], duplicate_policy)
    update_report(report, duplicates, f"duplicate_discarded_by_{duplicate_policy}")
    if df.empty:
        save_csv(report.sort_values("source_row"), output / "nasa_60_filter_report.csv")
        print("60版: B系の有効回答がないため、統計解析をスキップしました。")
        return
    used_rows = set(df["source_row"].astype(int))
    report.loc[report["source_row"].isin(used_rows), ["included", "reason"]] = [True, "included"]
    long_df = df.melt(
        id_vars=["participant_id", "viewing_duration"], value_vars=list(METRICS),
        var_name="metric", value_name="value",
    ).rename(columns={"viewing_duration": "condition"})
    long_df["condition_label"] = long_df["condition"]
    long_df["label_en"] = long_df["metric"].map(LABELS)
    present_order = tuple(condition for condition in DURATION_ORDER_60 if condition in set(long_df["condition"]))
    omnibus, pairwise = analyze_independent(long_df, present_order)
    description = descriptives(long_df, present_order)
    metric_columns = ["participant_id", "viewing_duration", *METRICS]
    save_csv(report.sort_values("source_row"), output / "nasa_60_filter_report.csv")
    save_csv(df[metric_columns], output / "nasa_60_analysis_data_wide.csv")
    save_csv(long_df, output / "nasa_60_plot_data_long.csv")
    save_csv(description, output / "nasa_60_descriptive_stats.csv")
    save_csv(omnibus, output / "nasa_60_omnibus_results.csv")
    save_csv(pairwise, output / "nasa_60_pairwise_results.csv")
    plot_scatter_mean(long_df, present_order, {value: value for value in present_order}, omnibus, output / "nasa_60_scatter_mean_sem.png", dpi, seed)
    print(f"60版: B系有効回答 {len(df)}件（入力 {len(report)}行）")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.study in ("90", "all"):
        analyze_90(args.input_90, args.output_dir, args.duplicate_policy, args.dpi, args.seed)
    if args.study in ("60", "all"):
        analyze_60(args.input_60, args.output_dir, args.duplicate_policy, args.dpi, args.seed)


if __name__ == "__main__":
    main()
