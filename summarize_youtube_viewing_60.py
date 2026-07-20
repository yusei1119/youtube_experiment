#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""60分実験のB系参加者を、設定したショート動画視聴時間ごとに要約する。

入力:
  youtube_analysis_summary.csv  analyze_youtube_logs.py の参加者・セッション別出力
  nasa_task_60_results.csv       participant_id と viewing_duration の対応

出力:
  B系参加者を5/10/15/20/25/30分条件ごとに分けた記述統計、カテゴリ集計、図。
  仮説検定や有意差検定は行わない。

実行例:
  python analyze_youtube_logs.py data/logs.jsonl
  python export_nasa_60_responses.py
  python summarize_youtube_viewing_60.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from summarize_youtube_viewing import (
    METRICS,
    PLOT_METRICS,
    PLOT_UNITS,
    RATE_METRICS,
    aggregate_participant_sessions,
    category_summary,
    configure_plot_style,
    format_value,
    mean_confidence_interval,
    top_category_counts,
)


DURATION_ORDER = tuple(f"{minutes}min" for minutes in range(5, 31, 5))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="B系参加者のYouTube視聴指標を視聴時間条件ごとに要約します。"
    )
    parser.add_argument(
        "--youtube-input",
        type=Path,
        default=Path("youtube_analysis_summary.csv"),
    )
    parser.add_argument(
        "--duration-input",
        type=Path,
        default=Path("nasa_task_60_results.csv"),
        help="participant_idとviewing_durationを持つCSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("youtube_descriptive_analysis/b_participants_by_duration"),
    )
    parser.add_argument("--id-pattern", default=r"B\d+")
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


def load_duration_mapping(
    path: Path,
    id_pattern: str,
) -> tuple[pd.DataFrame, pd.DataFrame, set[str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} がありません。先に export_nasa_60_responses.py を実行してください。"
        )
    source = pd.read_csv(path, encoding="utf-8-sig")
    source.columns = source.columns.astype(str).str.strip()
    ensure_columns(source, {"participant_id", "viewing_duration"}, path)
    source = source.copy()
    source.insert(0, "source_row", np.arange(2, len(source) + 2))
    source["participant_id"] = source["participant_id"].astype("string").str.strip()
    source["viewing_duration"] = (
        source["viewing_duration"].astype("string").str.strip().str.lower()
    )
    valid_id = source["participant_id"].str.fullmatch(id_pattern, na=False)
    valid_duration = source["viewing_duration"].isin(DURATION_ORDER)

    report = source[["source_row", "participant_id", "viewing_duration"]].copy()
    report["valid_b_id"] = valid_id
    report["valid_duration"] = valid_duration
    report["reason"] = np.select(
        [~valid_id, valid_id & ~valid_duration],
        ["invalid_participant_id", "invalid_viewing_duration"],
        default="candidate",
    )

    valid = source.loc[valid_id & valid_duration, ["participant_id", "viewing_duration"]]
    duration_counts = valid.groupby("participant_id")["viewing_duration"].nunique()
    conflicting_ids = set(duration_counts[duration_counts > 1].index.astype(str))
    if conflicting_ids:
        report.loc[report["participant_id"].isin(conflicting_ids), "reason"] = (
            "conflicting_viewing_durations"
        )
    valid = valid[~valid["participant_id"].isin(conflicting_ids)]
    mapping = valid.drop_duplicates("participant_id", keep="last").copy()
    mapping["duration_minutes"] = (
        mapping["viewing_duration"].str.removesuffix("min").astype(int)
    )
    mapped_ids = set(mapping["participant_id"].astype(str))
    report.loc[
        report["participant_id"].isin(mapped_ids) & (report["reason"] == "candidate"),
        "reason",
    ] = "valid_mapping"
    return mapping, report, conflicting_ids


def load_youtube_participants(
    path: Path,
    id_pattern: str,
    duration_mapping: pd.DataFrame,
    conflicting_ids: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} がありません。先に analyze_youtube_logs.py を実行してください。"
        )
    source = pd.read_csv(path, encoding="utf-8-sig")
    source.columns = source.columns.astype(str).str.strip()
    ensure_columns(
        source,
        {
            "participant_id",
            "session_id",
            "session_minutes",
            "watched_categories",
            *METRICS,
        },
        path,
    )
    source = source.copy()
    source.insert(0, "source_row", np.arange(2, len(source) + 2))
    source["participant_id"] = source["participant_id"].astype("string").str.strip()
    valid_id = source["participant_id"].str.fullmatch(id_pattern, na=False)
    report = source[["source_row", "participant_id", "session_id", "session_minutes"]].copy()
    report["included"] = False
    report["reason"] = np.where(valid_id, "candidate", "invalid_participant_id")

    candidates = source.loc[valid_id].copy()
    for metric in METRICS:
        candidates[metric] = pd.to_numeric(candidates[metric], errors="coerce")
    candidates["session_minutes"] = pd.to_numeric(
        candidates["session_minutes"], errors="coerce"
    )
    invalid_numeric = candidates[[*METRICS]].isna().all(axis=1)
    invalid_rows = set(candidates.loc[invalid_numeric, "source_row"].astype(int))
    report.loc[report["source_row"].isin(invalid_rows), "reason"] = (
        "all_numeric_metrics_missing"
    )
    candidates = candidates.loc[~invalid_numeric].copy()

    mapping_ids = set(duration_mapping["participant_id"].astype(str))
    missing_mapping_ids = set(candidates["participant_id"].astype(str)) - mapping_ids
    report.loc[report["participant_id"].isin(missing_mapping_ids), "reason"] = (
        "viewing_duration_not_found"
    )
    report.loc[report["participant_id"].isin(conflicting_ids), "reason"] = (
        "conflicting_viewing_durations"
    )
    candidates = candidates[candidates["participant_id"].isin(mapping_ids)].copy()
    if candidates.empty:
        return pd.DataFrame(), report.sort_values("source_row")

    participant_data = aggregate_participant_sessions(candidates)
    participant_data = participant_data.merge(
        duration_mapping,
        on="participant_id",
        how="inner",
        validate="one_to_one",
    )
    participant_data = participant_data.sort_values(
        ["duration_minutes", "participant_id"]
    ).reset_index(drop=True)

    for participant_id, group in candidates.groupby("participant_id", sort=False):
        source_rows = set(group["source_row"].astype(int))
        mask = report["source_row"].isin(source_rows)
        reason = "included" if len(group) == 1 else f"included_combined_{len(group)}_sessions"
        report.loc[mask, ["included", "reason"]] = [True, reason]
    return participant_data, report.sort_values("source_row")


def grouped_descriptive_statistics(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for duration in DURATION_ORDER:
        group = data[data["viewing_duration"] == duration]
        if group.empty:
            continue
        for metric, (label, unit) in METRICS.items():
            values = pd.to_numeric(group[metric], errors="coerce")
            clean = values.dropna()
            ci_low, ci_high = mean_confidence_interval(values)
            rows.append(
                {
                    "viewing_duration": duration,
                    "duration_minutes": int(duration.removesuffix("min")),
                    "metric": metric,
                    "label_en": label,
                    "unit": unit,
                    "n": int(clean.size),
                    "missing": int(values.isna().sum()),
                    "mean": clean.mean(),
                    "sd": clean.std(ddof=1),
                    "sem": clean.sem(),
                    "ci95_low": ci_low,
                    "ci95_high": ci_high,
                    "median": clean.median(),
                    "q1": clean.quantile(0.25),
                    "q3": clean.quantile(0.75),
                    "minimum": clean.min(),
                    "maximum": clean.max(),
                    "sum": clean.sum(),
                }
            )
    return pd.DataFrame(rows)


def grouped_means(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for duration in DURATION_ORDER:
        group = data[data["viewing_duration"] == duration]
        if group.empty:
            continue
        row: dict[str, int | float | str] = {
            "viewing_duration": duration,
            "duration_minutes": int(duration.removesuffix("min")),
            "participant_count": len(group),
        }
        for metric in METRICS:
            mean = pd.to_numeric(group[metric], errors="coerce").mean()
            row[f"mean_{metric}"] = mean
            if metric in RATE_METRICS:
                row[f"mean_{metric}_percent"] = mean * 100
        rows.append(row)
    return pd.DataFrame(rows)


def grouped_category_summary(data: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for duration in DURATION_ORDER:
        group = data[data["viewing_duration"] == duration]
        if group.empty:
            continue
        summary = category_summary(group)
        summary.insert(0, "participant_count", len(group))
        summary.insert(0, "duration_minutes", int(duration.removesuffix("min")))
        summary.insert(0, "viewing_duration", duration)
        frames.append(summary)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def grouped_top_categories(data: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for duration in DURATION_ORDER:
        group = data[data["viewing_duration"] == duration]
        if group.empty:
            continue
        summary = top_category_counts(group)
        summary.insert(0, "duration_minutes", int(duration.removesuffix("min")))
        summary.insert(0, "viewing_duration", duration)
        frames.append(summary)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def plot_metrics_by_duration(
    data: pd.DataFrame,
    descriptive: pd.DataFrame,
    output: Path,
    dpi: int,
    seed: int,
) -> None:
    configure_plot_style()
    present = [duration for duration in DURATION_ORDER if duration in set(data["viewing_duration"])]
    x_positions = np.arange(len(present))
    rng = np.random.default_rng(seed)
    fig, axes = plt.subplots(3, 4, figsize=(17, 11))
    for ax, metric in zip(axes.flat, PLOT_METRICS):
        means, lower_errors, upper_errors = [], [], []
        metric_stats = descriptive[descriptive["metric"] == metric]
        for x_position, duration in enumerate(present):
            values = pd.to_numeric(
                data.loc[data["viewing_duration"] == duration, metric], errors="coerce"
            ).dropna().to_numpy(float)
            jitter = rng.uniform(-0.09, 0.09, values.size)
            ax.scatter(
                np.full(values.size, x_position) + jitter,
                values,
                color="0.55",
                alpha=0.65,
                s=24,
                zorder=2,
            )
            row = metric_stats[metric_stats["viewing_duration"] == duration]
            if row.empty:
                mean = ci_low = ci_high = np.nan
            else:
                mean = float(row.iloc[0]["mean"])
                ci_low = float(row.iloc[0]["ci95_low"])
                ci_high = float(row.iloc[0]["ci95_high"])
            means.append(mean)
            lower_errors.append(mean - ci_low if np.isfinite(ci_low) else np.nan)
            upper_errors.append(ci_high - mean if np.isfinite(ci_high) else np.nan)
        ax.plot(x_positions, means, color="#e41a1c", marker="o", linewidth=2, zorder=3)
        ax.errorbar(
            x_positions,
            means,
            yerr=np.array([lower_errors, upper_errors]),
            fmt="none",
            color="black",
            capsize=4,
            zorder=4,
        )
        label, unit = METRICS[metric]
        ax.set_title(label)
        ax.set_xlabel("Configured viewing duration")
        ax.set_ylabel(PLOT_UNITS.get(unit, unit))
        ax.set_xticks(x_positions, present)
        ax.grid(axis="y", linestyle="--", alpha=0.25)
    fig.suptitle(
        f"YouTube Shorts Metrics by Viewing Duration (B participants, n={len(data)})",
        fontsize=18,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def plot_category_heatmap(category_data: pd.DataFrame, output: Path, dpi: int) -> None:
    configure_plot_style()
    if category_data.empty:
        return
    overall_order = (
        category_data.groupby("category")["total_view_sec"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .index
    )
    pivot = category_data.pivot(
        index="viewing_duration",
        columns="category",
        values="overall_view_time_share",
    ).reindex(index=[value for value in DURATION_ORDER if value in set(category_data["viewing_duration"])], columns=overall_order)
    values = pivot.fillna(0).to_numpy(float) * 100
    fig, ax = plt.subplots(figsize=(13, max(4.2, 0.7 * len(pivot))))
    image = ax.imshow(values, cmap="YlGnBu", aspect="auto", vmin=0)
    ax.set_xticks(np.arange(len(pivot.columns)), pivot.columns, rotation=35, ha="right")
    ax.set_yticks(np.arange(len(pivot.index)), pivot.index)
    ax.set_xlabel("YouTube category")
    ax.set_ylabel("Configured viewing duration")
    ax.set_title("Category Share of Viewing Time by Duration (%)")
    threshold = values.max() * 0.55 if values.size else 0
    for row_index in range(values.shape[0]):
        for column_index in range(values.shape[1]):
            value = values[row_index, column_index]
            ax.text(
                column_index,
                row_index,
                f"{value:.1f}",
                ha="center",
                va="center",
                fontsize=8,
                color="white" if value > threshold else "black",
            )
    fig.colorbar(image, ax=ax, label="Share of group viewing time (%)")
    fig.tight_layout()
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def write_report(
    data: pd.DataFrame,
    descriptive: pd.DataFrame,
    categories: pd.DataFrame,
    output: Path,
) -> None:
    counts = (
        data["viewing_duration"].value_counts().reindex(DURATION_ORDER, fill_value=0)
    )
    lines = [
        "# 60分実験：YouTubeショート動画視聴データの時間条件別記述統計",
        "",
        f"- 解析対象: B系参加者 {len(data)}名",
        "- 分析: 記述統計（有意差検定なし）",
        "",
        "## 条件別参加者数",
        "",
        "| 視聴時間 | 人数 |",
        "|---|---:|",
    ]
    for duration, count in counts.items():
        lines.append(f"| {duration} | {count} |")
    lines.extend(
        [
            "",
            "## 条件別の主要平均値",
            "",
            "| 視聴時間 | n | 視聴本数 | 総再生秒数 | 1本平均秒数 | 完了率 | 早期スキップ率 | 切替/分 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    selected = (
        "total_videos",
        "total_view_sec",
        "mean_view_sec",
        "completion_rate",
        "early_skip_rate",
        "switch_per_min",
    )
    for duration in DURATION_ORDER:
        group = data[data["viewing_duration"] == duration]
        if group.empty:
            continue
        values = []
        for metric in selected:
            mean = pd.to_numeric(group[metric], errors="coerce").mean()
            values.append(format_value(metric, mean))
        lines.append(f"| {duration} | {len(group)} | " + " | ".join(values) + " |")

    lines.extend(["", "## 各条件で視聴時間割合が高いカテゴリ", ""])
    for duration in DURATION_ORDER:
        group_categories = categories[categories["viewing_duration"] == duration]
        if group_categories.empty:
            continue
        top = ", ".join(
            f"{row.category} {row.overall_view_time_share * 100:.1f}%"
            for row in group_categories.head(5).itertuples(index=False)
        )
        lines.append(f"- {duration}: {top}")
    lines.extend(
        [
            "",
            "注: 本レポートは記述統計であり、条件間の統計的有意差は検定していません。",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    mapping, mapping_report, conflicting_ids = load_duration_mapping(
        args.duration_input, args.id_pattern
    )
    data, youtube_report = load_youtube_participants(
        args.youtube_input,
        args.id_pattern,
        mapping,
        conflicting_ids,
    )
    save_csv(mapping_report, args.output_dir / "youtube_b_duration_mapping_report.csv")
    save_csv(youtube_report, args.output_dir / "youtube_b_filter_report.csv")
    if data.empty:
        print(
            "B系参加者と視聴時間の有効な組み合わせがまだないため、"
            "時間条件別の集計をスキップしました。"
        )
        return

    descriptive = grouped_descriptive_statistics(data)
    means = grouped_means(data)
    categories = grouped_category_summary(data)
    top_categories = grouped_top_categories(data)
    save_csv(data, args.output_dir / "youtube_b_participant_data.csv")
    save_csv(descriptive, args.output_dir / "youtube_b_descriptive_stats_by_duration.csv")
    save_csv(means, args.output_dir / "youtube_b_overall_means_by_duration.csv")
    save_csv(categories, args.output_dir / "youtube_b_category_summary_by_duration.csv")
    save_csv(top_categories, args.output_dir / "youtube_b_top_category_counts_by_duration.csv")

    metrics_plot = args.output_dir / "youtube_b_metrics_by_duration.png"
    category_plot = args.output_dir / "youtube_b_category_heatmap.png"
    plot_metrics_by_duration(data, descriptive, metrics_plot, args.dpi, args.seed)
    plot_category_heatmap(categories, category_plot, args.dpi)
    print(f"  saved: {metrics_plot}")
    print(f"  saved: {category_plot}")

    report = args.output_dir / "youtube_b_descriptive_report.md"
    write_report(data, descriptive, categories, report)
    print(f"  saved: {report}")
    counts = data["viewing_duration"].value_counts().reindex(DURATION_ORDER, fill_value=0)
    print(f"\nB系参加者 {len(data)}名を時間条件別に集計しました。")
    print(counts.to_string())


if __name__ == "__main__":
    main()
