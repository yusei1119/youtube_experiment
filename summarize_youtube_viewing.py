#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""A系参加者のYouTubeショート動画視聴データを記述統計で要約する。

入力は analyze_youtube_logs.py が出力する youtube_analysis_summary.csv。
統計的仮説検定は行わず、参加者全体の平均、標準偏差、中央値、四分位範囲、
95%信頼区間、カテゴリ別視聴時間などをCSV・Markdown・PNGへ出力する。

実行例:
  python analyze_youtube_logs.py data/logs.jsonl
  python summarize_youtube_viewing.py

同一IDに複数セッションがある場合は、視聴本数・視聴時間・カテゴリ別時間を
合算し、率指標を重み付きで再計算して1名分にまとめる。既定では短時間の
セッションも含めるが、A014は解析対象から除外する。除外・統合内容は
filter_report.csv に記録する。
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


METRICS = {
    "total_videos": ("Videos watched", "本"),
    "total_view_sec": ("Total viewing time", "秒"),
    "mean_view_sec": ("Mean viewing time per video", "秒/本"),
    "completion_rate": ("Completion rate", "割合"),
    "early_skip_rate": ("Early-skip rate", "割合"),
    "switch_per_min": ("Switches per minute", "回/分"),
    "view_sec_var": ("Viewing-time variance", "秒²"),
    "max_consecutive_skip": ("Maximum consecutive skips", "本"),
    "late_skip_increase": ("Late minus early skip rate", "割合"),
    "session_minutes": ("Session duration", "分"),
    "unique_category_count": ("Unique categories", "種類"),
    "top_category_rate": ("Most frequent category share", "割合"),
    "top_view_time_category_rate": ("Top viewing-time category share", "割合"),
}
RATE_METRICS = {
    "completion_rate",
    "early_skip_rate",
    "late_skip_increase",
    "top_category_rate",
    "top_view_time_category_rate",
}
PLOT_METRICS = (
    "total_videos",
    "total_view_sec",
    "mean_view_sec",
    "completion_rate",
    "early_skip_rate",
    "switch_per_min",
    "view_sec_var",
    "max_consecutive_skip",
    "late_skip_increase",
    "session_minutes",
    "unique_category_count",
    "top_view_time_category_rate",
)
PLOT_UNITS = {
    "本": "videos",
    "秒": "seconds",
    "秒/本": "seconds/video",
    "割合": "proportion",
    "回/分": "switches/minute",
    "秒²": "seconds squared",
    "分": "minutes",
    "種類": "categories",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A系参加者のYouTube視聴指標を記述統計で要約します。"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("youtube_analysis_summary.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("youtube_descriptive_analysis/a_participants"),
    )
    parser.add_argument(
        "--id-pattern",
        default=r"A\d+",
        help=r"対象参加者IDの正規表現（既定: A\d+）",
    )
    parser.add_argument(
        "--min-session-minutes",
        type=float,
        default=0.0,
        help="統合後の有効視聴時間の下限（既定: 0分＝時間による除外なし）",
    )
    parser.add_argument(
        "--exclude-ids",
        nargs="*",
        default=["A014"],
        help="解析から除外する参加者ID（既定: A014）",
    )
    parser.add_argument("--dpi", type=int, default=220)
    return parser.parse_args()


def ensure_columns(df: pd.DataFrame, required: set[str], input_path: Path) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{input_path}: 必須列がありません: {missing}")


def load_and_filter(
    input_path: Path,
    id_pattern: str,
    min_session_minutes: float,
    exclude_ids: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not input_path.exists():
        raise FileNotFoundError(
            f"{input_path} がありません。先に analyze_youtube_logs.py を実行してください。"
        )
    df = pd.read_csv(input_path, encoding="utf-8-sig")
    df.columns = df.columns.astype(str).str.strip()
    ensure_columns(
        df,
        {"participant_id", "session_id", "session_minutes", *METRICS},
        input_path,
    )
    df = df.copy()
    df.insert(0, "source_row", np.arange(2, len(df) + 2))
    df["participant_id"] = df["participant_id"].astype("string").str.strip()
    df["session_minutes"] = pd.to_numeric(df["session_minutes"], errors="coerce")

    valid_id = df["participant_id"].str.fullmatch(id_pattern, na=False)
    report = df[["source_row", "participant_id", "session_id", "session_minutes"]].copy()
    report["included"] = False
    report["reason"] = np.where(valid_id, "candidate", "invalid_participant_id")

    explicitly_excluded = valid_id & df["participant_id"].isin(exclude_ids)
    report.loc[explicitly_excluded, "reason"] = "excluded_by_request"
    candidates = df.loc[valid_id & ~explicitly_excluded].copy()
    for metric in METRICS:
        candidates[metric] = pd.to_numeric(candidates[metric], errors="coerce")

    invalid_numeric = candidates[["session_minutes", *METRICS]].isna().all(axis=1)
    invalid_rows = set(candidates.loc[invalid_numeric, "source_row"].astype(int))
    report.loc[report["source_row"].isin(invalid_rows), "reason"] = (
        "all_numeric_metrics_missing"
    )
    candidates = candidates.loc[~invalid_numeric].copy()

    if candidates.empty:
        raise ValueError(
            "条件を満たすA系参加者がいません。入力CSVと --min-session-minutes を確認してください。"
        )
    participant_data = aggregate_participant_sessions(candidates)
    too_short_ids = set(
        participant_data.loc[
            participant_data["session_minutes"].fillna(-np.inf) < min_session_minutes,
            "participant_id",
        ].astype(str)
    )
    if too_short_ids:
        short_mask = report["participant_id"].isin(too_short_ids)
        report.loc[short_mask, "reason"] = (
            f"combined_duration_shorter_than_{min_session_minutes:g}_minutes"
        )
        participant_data = participant_data[
            ~participant_data["participant_id"].isin(too_short_ids)
        ].copy()

    if participant_data.empty:
        raise ValueError(
            "条件を満たすA系参加者がいません。入力CSVと --min-session-minutes を確認してください。"
        )

    for participant_id, group in candidates.groupby("participant_id", sort=False):
        if participant_id in too_short_ids:
            continue
        rows = set(group["source_row"].astype(int))
        mask = report["source_row"].isin(rows)
        reason = "included" if len(group) == 1 else f"included_combined_{len(group)}_sessions"
        report.loc[mask, ["included", "reason"]] = [True, reason]
    return participant_data.sort_values("participant_id"), report.sort_values("source_row")


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    numeric_values = pd.to_numeric(values, errors="coerce")
    numeric_weights = pd.to_numeric(weights, errors="coerce")
    valid = numeric_values.notna() & numeric_weights.notna() & (numeric_weights > 0)
    if not valid.any():
        return np.nan
    return float(np.average(numeric_values[valid], weights=numeric_weights[valid]))


def pooled_viewing_variance(group: pd.DataFrame) -> float:
    counts = pd.to_numeric(group["total_videos"], errors="coerce").fillna(0).to_numpy(float)
    means = pd.to_numeric(group["mean_view_sec"], errors="coerce").to_numpy(float)
    variances = pd.to_numeric(group["view_sec_var"], errors="coerce").fillna(0).to_numpy(float)
    valid = (counts > 0) & np.isfinite(means)
    counts, means, variances = counts[valid], means[valid], variances[valid]
    total_count = counts.sum()
    if total_count <= 1:
        return 0.0
    grand_mean = np.average(means, weights=counts)
    sum_squares = np.sum((counts - 1) * variances + counts * np.square(means - grand_mean))
    return float(sum_squares / (total_count - 1))


def split_joined_values(values: pd.Series) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values.dropna().astype(str):
        for item in value.split(" | "):
            cleaned = item.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
    return result


def aggregate_participant_sessions(candidates: pd.DataFrame) -> pd.DataFrame:
    """複数セッションを参加者単位に合算し、派生指標を再計算する。"""
    second_columns = sorted(
        column for column in candidates if column.startswith("view_time_sec__")
    )
    rows: list[dict[str, int | float | str]] = []
    for participant_id, group in candidates.groupby("participant_id", sort=True):
        group = group.sort_values("source_row")
        video_counts = pd.to_numeric(group["total_videos"], errors="coerce").fillna(0)
        session_minutes = pd.to_numeric(group["session_minutes"], errors="coerce").fillna(0)
        total_videos = float(video_counts.sum())
        total_view_sec = float(pd.to_numeric(group["total_view_sec"], errors="coerce").sum())
        row: dict[str, int | float | str] = {
            "participant_id": str(participant_id),
            "session_id": " | ".join(group["session_id"].dropna().astype(str)),
            "session_count": len(group),
            "watched_titles": " | ".join(
                value for value in group.get("watched_titles", pd.Series(dtype=str)).dropna().astype(str)
                if value
            ),
            "total_videos": int(total_videos),
            "total_view_sec": total_view_sec,
            "mean_view_sec": total_view_sec / total_videos if total_videos > 0 else np.nan,
            "completion_rate": weighted_mean(group["completion_rate"], video_counts),
            "early_skip_rate": weighted_mean(group["early_skip_rate"], video_counts),
            "switch_per_min": weighted_mean(group["switch_per_min"], session_minutes),
            "view_sec_var": pooled_viewing_variance(group),
            "max_consecutive_skip": pd.to_numeric(
                group["max_consecutive_skip"], errors="coerce"
            ).max(),
            "late_skip_increase": weighted_mean(group["late_skip_increase"], video_counts),
            "session_minutes": float(session_minutes.sum()),
        }

        watched_categories = split_joined_values(group["watched_categories"])
        row["watched_categories"] = " | ".join(watched_categories)
        row["unique_category_count"] = len(watched_categories)

        # 動画本数ベースの最多カテゴリは、各セッションの比率×本数から統合する。
        estimated_counts: dict[str, float] = {}
        for item in group.itertuples(index=False):
            raw_category = getattr(item, "top_category", "")
            category = str(raw_category).strip() if pd.notna(raw_category) else ""
            rate = getattr(item, "top_category_rate", np.nan)
            count = getattr(item, "total_videos", np.nan)
            if category and pd.notna(rate) and pd.notna(count):
                estimated_counts[category] = estimated_counts.get(category, 0.0) + float(rate) * float(count)
        if estimated_counts:
            top_category = max(estimated_counts, key=estimated_counts.get)
            row["top_category"] = top_category
            row["top_category_rate"] = (
                estimated_counts[top_category] / total_videos if total_videos > 0 else np.nan
            )
        else:
            row["top_category"] = ""
            row["top_category_rate"] = np.nan

        category_seconds: dict[str, float] = {}
        for column in second_columns:
            seconds = float(pd.to_numeric(group[column], errors="coerce").fillna(0).sum())
            row[column] = seconds
            suffix = column.removeprefix("view_time_sec__")
            category_seconds[suffix] = seconds

        summed_category_seconds = sum(category_seconds.values())
        labels = category_label_map(group)
        ratio_parts = []
        for suffix, seconds in sorted(
            category_seconds.items(), key=lambda item: item[1], reverse=True
        ):
            ratio = seconds / summed_category_seconds if summed_category_seconds > 0 else np.nan
            row[f"view_time_ratio__{suffix}"] = ratio
            if seconds > 0 and np.isfinite(ratio):
                label = labels.get(suffix, fallback_category_label(suffix))
                ratio_parts.append(f"{label}:{ratio:.6f}")
        row["category_view_time_ratios"] = " | ".join(ratio_parts)
        if category_seconds and summed_category_seconds > 0:
            top_suffix = max(category_seconds, key=category_seconds.get)
            row["top_view_time_category"] = labels.get(
                top_suffix, fallback_category_label(top_suffix)
            )
            row["top_view_time_category_rate"] = (
                category_seconds[top_suffix] / summed_category_seconds
            )
        else:
            row["top_view_time_category"] = ""
            row["top_view_time_category_rate"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def mean_confidence_interval(values: pd.Series) -> tuple[float, float]:
    clean = values.dropna().to_numpy(float)
    if clean.size < 2:
        return np.nan, np.nan
    sem = stats.sem(clean)
    if not np.isfinite(sem):
        return np.nan, np.nan
    margin = stats.t.ppf(0.975, clean.size - 1) * sem
    return float(clean.mean() - margin), float(clean.mean() + margin)


def descriptive_statistics(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric, (label, unit) in METRICS.items():
        values = pd.to_numeric(data[metric], errors="coerce")
        clean = values.dropna()
        ci_low, ci_high = mean_confidence_interval(values)
        rows.append(
            {
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


def overall_means(data: pd.DataFrame) -> pd.DataFrame:
    row: dict[str, int | float] = {"participant_count": len(data)}
    for metric in METRICS:
        values = pd.to_numeric(data[metric], errors="coerce")
        row[f"mean_{metric}"] = values.mean()
        if metric in RATE_METRICS:
            row[f"mean_{metric}_percent"] = values.mean() * 100
    return pd.DataFrame([row])


def category_suffix(category: str) -> str:
    suffix = category.lower().replace("&", "and")
    return re.sub(r"[^0-9a-zA-Z]+", "_", suffix).strip("_") or "unknown"


def category_label_map(data: pd.DataFrame) -> dict[str, str]:
    labels: dict[str, str] = {}
    if "category_view_time_ratios" not in data:
        return labels
    for value in data["category_view_time_ratios"].dropna().astype(str):
        for item in value.split(" | "):
            category, separator, _ratio = item.rpartition(":")
            if separator and category:
                labels[category_suffix(category)] = category
    return labels


def fallback_category_label(suffix: str) -> str:
    special = {
        "howto_and_style": "Howto & Style",
        "science_and_technology": "Science & Technology",
        "film_and_animation": "Film & Animation",
        "news_and_politics": "News & Politics",
        "pets_and_animals": "Pets & Animals",
        "autos_and_vehicles": "Autos & Vehicles",
    }
    return special.get(suffix, suffix.replace("_", " ").title())


def category_summary(data: pd.DataFrame) -> pd.DataFrame:
    seconds_prefix = "view_time_sec__"
    seconds_columns = sorted(column for column in data if column.startswith(seconds_prefix))
    labels = category_label_map(data)
    total_all_categories = 0.0
    seconds_by_suffix: dict[str, pd.Series] = {}
    for column in seconds_columns:
        suffix = column.removeprefix(seconds_prefix)
        values = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
        seconds_by_suffix[suffix] = values
        total_all_categories += float(values.sum())

    rows = []
    for suffix, seconds in seconds_by_suffix.items():
        ratio_column = f"view_time_ratio__{suffix}"
        ratios = (
            pd.to_numeric(data[ratio_column], errors="coerce").fillna(0.0)
            if ratio_column in data
            else pd.Series(0.0, index=data.index)
        )
        watched = seconds > 0
        viewers = int(watched.sum())
        total_seconds = float(seconds.sum())
        rows.append(
            {
                "category": labels.get(suffix, fallback_category_label(suffix)),
                "participants_watched": viewers,
                "participant_rate": viewers / len(data),
                "total_view_sec": total_seconds,
                "overall_view_time_share": (
                    total_seconds / total_all_categories if total_all_categories > 0 else np.nan
                ),
                "mean_view_sec_all_participants": seconds.mean(),
                "median_view_sec_all_participants": seconds.median(),
                "mean_within_participant_ratio_all": ratios.mean(),
                "mean_within_participant_ratio_viewers": (
                    ratios[watched].mean() if viewers else np.nan
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        "overall_view_time_share", ascending=False, ignore_index=True
    )


def top_category_counts(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column, basis in (
        ("top_category", "video_count"),
        ("top_view_time_category", "viewing_time"),
    ):
        if column not in data:
            continue
        counts = data[column].fillna("Unknown").replace("", "Unknown").value_counts()
        for category, count in counts.items():
            rows.append(
                {
                    "basis": basis,
                    "category": category,
                    "participant_count": int(count),
                    "participant_rate": count / len(data),
                }
            )
    return pd.DataFrame(rows)


def configure_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.linewidth": 1.2,
            "axes.titlesize": 12,
            "xtick.direction": "in",
            "ytick.direction": "in",
        }
    )


def plot_metric_distributions(data: pd.DataFrame, output: Path, dpi: int) -> None:
    configure_plot_style()
    fig, axes = plt.subplots(3, 4, figsize=(16, 11))
    for ax, metric in zip(axes.flat, PLOT_METRICS):
        values = pd.to_numeric(data[metric], errors="coerce").dropna()
        bins = min(10, max(4, math.ceil(math.sqrt(len(values)))))
        ax.hist(values, bins=bins, color="#4c78a8", alpha=0.78, edgecolor="white")
        mean = values.mean()
        median = values.median()
        ax.axvline(mean, color="#e41a1c", linewidth=2, label=f"Mean {mean:.2f}")
        ax.axvline(median, color="black", linestyle="--", linewidth=1.5, label=f"Median {median:.2f}")
        ax.set_title(METRICS[metric][0])
        ax.set_xlabel(PLOT_UNITS.get(METRICS[metric][1], METRICS[metric][1]))
        ax.set_ylabel("Participants")
        ax.legend(fontsize=8)
        ax.grid(axis="y", linestyle="--", alpha=0.25)
    fig.suptitle(f"YouTube Shorts Viewing Metrics (A participants, n={len(data)})", fontsize=18)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def plot_category_share(category: pd.DataFrame, output: Path, dpi: int) -> None:
    configure_plot_style()
    plotted = category.sort_values("overall_view_time_share", ascending=True)
    fig_height = max(5.5, 0.42 * len(plotted))
    fig, ax = plt.subplots(figsize=(10, fig_height))
    percentages = plotted["overall_view_time_share"] * 100
    bars = ax.barh(plotted["category"], percentages, color="#59a14f", alpha=0.85)
    ax.bar_label(bars, labels=[f"{value:.1f}%" for value in percentages], padding=3, fontsize=9)
    ax.set_xlabel("Share of total viewing time (%)")
    ax.set_title("YouTube Category Share by Total Viewing Time")
    ax.set_xlim(0, max(percentages.max() * 1.18, 1) if len(percentages) else 1)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def format_value(metric: str, value: float) -> str:
    if not np.isfinite(value):
        return "NA"
    if metric in RATE_METRICS:
        return f"{value * 100:.1f}%"
    return f"{value:.2f}"


def write_markdown_report(
    data: pd.DataFrame,
    descriptive: pd.DataFrame,
    categories: pd.DataFrame,
    filter_report: pd.DataFrame,
    output: Path,
    min_session_minutes: float,
) -> None:
    lines = [
        "# YouTubeショート動画視聴データ：記述統計",
        "",
        f"- 解析対象: A系参加者 {len(data)}名",
        f"- 有効セッション基準: {min_session_minutes:g}分以上",
        f"- 入力行数: {len(filter_report)}セッション",
        f"- 除外セッション数: {(~filter_report['included']).sum()}",
        "",
        "## 主要指標",
        "",
        "| 指標 | n | 平均 | SD | 中央値 | Q1–Q3 | 95% CI |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in descriptive.itertuples(index=False):
        lines.append(
            f"| {row.label_en} | {row.n} | {format_value(row.metric, row.mean)} "
            f"| {format_value(row.metric, row.sd)} | {format_value(row.metric, row.median)} "
            f"| {format_value(row.metric, row.q1)}–{format_value(row.metric, row.q3)} "
            f"| {format_value(row.metric, row.ci95_low)}–{format_value(row.metric, row.ci95_high)} |"
        )
    lines.extend(
        [
            "",
            "## 視聴時間が多いカテゴリ",
            "",
            "| カテゴリ | 総視聴時間割合 | 視聴者数 | 視聴者割合 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in categories.head(10).itertuples(index=False):
        lines.append(
            f"| {row.category} | {row.overall_view_time_share * 100:.1f}% "
            f"| {row.participants_watched} | {row.participant_rate * 100:.1f}% |"
        )
    lines.extend(
        [
            "",
            "注: 本レポートは記述統計であり、仮説検定や条件間の有意差検定は行っていません。",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def save_csv(df: pd.DataFrame, output: Path) -> None:
    df.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"  saved: {output}")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data, filter_report = load_and_filter(
        args.input,
        args.id_pattern,
        args.min_session_minutes,
        set(args.exclude_ids),
    )
    descriptive = descriptive_statistics(data)
    means = overall_means(data)
    categories = category_summary(data)
    top_categories = top_category_counts(data)

    export_columns = [
        "participant_id",
        "session_id",
        "session_count",
        *METRICS,
        "top_category",
        "top_view_time_category",
        "watched_categories",
        "category_view_time_ratios",
    ]
    export_columns.extend(
        column
        for column in data
        if column.startswith(("view_time_sec__", "view_time_ratio__"))
        and column not in export_columns
    )
    save_csv(filter_report, args.output_dir / "youtube_a_filter_report.csv")
    save_csv(data[export_columns], args.output_dir / "youtube_a_participant_data.csv")
    save_csv(means, args.output_dir / "youtube_a_overall_means.csv")
    save_csv(descriptive, args.output_dir / "youtube_a_descriptive_stats.csv")
    save_csv(categories, args.output_dir / "youtube_a_category_summary.csv")
    save_csv(top_categories, args.output_dir / "youtube_a_top_category_counts.csv")

    distributions_path = args.output_dir / "youtube_a_metric_distributions.png"
    category_path = args.output_dir / "youtube_a_category_view_time_share.png"
    plot_metric_distributions(data, distributions_path, args.dpi)
    plot_category_share(categories, category_path, args.dpi)
    print(f"  saved: {distributions_path}")
    print(f"  saved: {category_path}")

    report_path = args.output_dir / "youtube_a_descriptive_report.md"
    write_markdown_report(
        data,
        descriptive,
        categories,
        filter_report,
        report_path,
        args.min_session_minutes,
    )
    print(f"  saved: {report_path}")
    print(f"\nA系参加者 {len(data)}名の記述統計を作成しました。")
    print(
        descriptive[["label_en", "n", "mean", "sd", "median", "ci95_low", "ci95_high"]]
        .round(4)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
