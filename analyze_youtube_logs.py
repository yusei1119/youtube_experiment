"""YouTube視聴実験ログの分析スクリプト。

data/logs.jsonl（1行1イベントのJSONL）を読み込み、統計分析に使える2つのCSVを出力する。

  1. youtube_viewing_summary.csv     … 1動画 = 1行（参加者 × セッション × 動画）
  2. youtube_participant_summary.csv … 参加者 = 1行（統計分析の解析単位）

参加者サマリーに含める指標（ご要望）:
  - watched_titles            視聴した動画のタイトル（順番に " | " 区切り）
  - total_videos              総視聴本数（何本見たか）
  - total_view_sec            総視聴時間（全動画の視聴秒数の合計）
  - mean_view_sec             平均視聴時間（1本あたり何秒見たか）
  - completion_rate           視聴完了率（最後まで見た割合）
  - early_skip_rate           早期スキップ率（2秒以内に飛ばした割合）
  - switch_per_min            切り替え頻度（1分あたり何本切り替えたか）
  - view_sec_var              視聴時間の分散（視聴時間が安定しているか）
  - max_consecutive_skip      連続スキップ長（何本連続で早期スキップしたか）
  - late_skip_increase        後半スキップ増加率（後半 − 前半の早期スキップ率）

使い方:
  python analyze_youtube_logs.py [入力JSONLパス]
  （省略時は data/logs.jsonl）
"""

import sys
import json

import numpy as np
import pandas as pd

# ---- 判定のしきい値（必要なら変更） --------------------------------------
COMPLETION_RATE = 0.9   # 視聴完了とみなす視聴到達率（max_time_sec / duration_sec）
EARLY_SKIP_SEC = 2.0    # 早期スキップとみなす視聴秒数の上限（これ以下なら早期スキップ）
# -------------------------------------------------------------------------

LOG_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/logs.jsonl"
VIDEO_CSV = "youtube_viewing_summary.csv"
PARTICIPANT_CSV = "youtube_participant_summary.csv"

# 1セッションのまとまり（解析単位）を表すキー
GROUP_KEYS = ["participant_id", "session_id"]


def load_logs(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"ログが空です: {path}")
    return pd.DataFrame(rows)


def build_video_table(df):
    """1動画（参加者 × セッション × video_index）= 1行のテーブルを作る。"""
    # 数値列を数値型へ
    for col in ["current_time_sec", "duration_sec", "max_time_sec", "video_index"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["server_time"] = pd.to_datetime(df["server_time"], errors="coerce", utc=True)

    # 「最後まで見た（ended）」が記録された動画を抽出
    ended = (
        df[df["event_type"] == "ended"]
        .groupby(GROUP_KEYS + ["video_index"])
        .size()
        .rename("ended_count")
        .reset_index()
    )

    video = (
        df.groupby(GROUP_KEYS + ["video_index", "video_id", "video_title"], dropna=False)
        .agg(
            watched_sec=("max_time_sec", "max"),     # その動画で最も先まで見た位置 ≒ 視聴秒数
            duration_sec=("duration_sec", "max"),    # 動画の長さ
            first_time=("server_time", "min"),       # その動画を見始めた時刻
            last_time=("server_time", "max"),        # その動画の最後のイベント時刻
            log_count=("event_type", "count"),
        )
        .reset_index()
    )

    video = video.merge(ended, on=GROUP_KEYS + ["video_index"], how="left")
    video["ended_count"] = video["ended_count"].fillna(0)

    video["watched_sec"] = video["watched_sec"].fillna(0.0)

    # 視聴到達率（0〜1にクリップ）
    video["view_rate"] = np.where(
        video["duration_sec"] > 0,
        (video["watched_sec"] / video["duration_sec"]).clip(upper=1.0),
        np.nan,
    )

    # 視聴完了: 到達率が基準以上、または ended が記録された
    video["completed"] = (video["view_rate"] >= COMPLETION_RATE) | (video["ended_count"] > 0)

    # 早期スキップ: 視聴秒数が基準以下、かつ完了していない
    video["early_skip"] = (video["watched_sec"] <= EARLY_SKIP_SEC) & (~video["completed"])

    # 視聴順（video_index 昇順）に並べる
    video = video.sort_values(GROUP_KEYS + ["video_index"]).reset_index(drop=True)
    return video


def _max_consecutive(flags):
    """True が連続する最大長を返す。"""
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def _late_skip_increase(flags):
    """視聴順に並んだ早期スキップ flag 列について、後半 − 前半の早期スキップ率。"""
    n = len(flags)
    if n < 2:
        return np.nan
    half = n // 2
    first = np.mean(flags[:half]) if half > 0 else np.nan
    second = np.mean(flags[half:])
    return second - first


def summarize_participant(group):
    """1セッション分の video テーブルから参加者指標を計算する。"""
    g = group.sort_values("video_index")
    flags = g["early_skip"].tolist()

    # セッションの所要時間（分）。切り替え頻度の分母。
    span = g["last_time"].max() - g["first_time"].min()
    minutes = span.total_seconds() / 60.0 if pd.notna(span) else np.nan
    n = len(g)

    return pd.Series(
        {
            "watched_titles": " | ".join(g["video_title"].fillna("").astype(str)),
            "total_videos": n,
            "total_view_sec": g["watched_sec"].sum(),
            "mean_view_sec": g["watched_sec"].mean(),
            "completion_rate": g["completed"].mean(),
            "early_skip_rate": g["early_skip"].mean(),
            "switch_per_min": (n - 1) / minutes if minutes and minutes > 0 else np.nan,
            "view_sec_var": g["watched_sec"].var(ddof=1) if n > 1 else 0.0,
            "max_consecutive_skip": _max_consecutive(flags),
            "late_skip_increase": _late_skip_increase(flags),
            "session_minutes": minutes,
        }
    )


def main():
    df = load_logs(LOG_PATH)
    video = build_video_table(df)
    video.to_csv(VIDEO_CSV, index=False, encoding="utf-8-sig")

    participant = (
        video.groupby(GROUP_KEYS, dropna=False)
        .apply(summarize_participant, include_groups=False)
        .reset_index()
    )
    participant.to_csv(PARTICIPANT_CSV, index=False, encoding="utf-8-sig")

    print(f"入力: {LOG_PATH}（{len(df)} イベント）")
    print(f"動画レベル: {VIDEO_CSV}（{len(video)} 行）")
    print(f"参加者レベル: {PARTICIPANT_CSV}（{len(participant)} 行）")
    print()
    cols = [
        "participant_id", "total_videos", "total_view_sec", "mean_view_sec", "completion_rate",
        "early_skip_rate", "switch_per_min", "view_sec_var",
        "max_consecutive_skip", "late_skip_increase",
    ]
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(participant[cols].to_string(index=False))


if __name__ == "__main__":
    main()
