"""YouTube視聴実験ログの分析スクリプト。

data/logs.jsonl（1行1イベントのJSONL）を読み込み、統計分析に使えるCSVを出力する。

  - youtube_analysis_summary.csv … 参加者 = 1行（統計分析の解析単位）

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
  - watched_categories        視聴した動画カテゴリ（順番に " | " 区切り）
  - unique_category_count     視聴したカテゴリの種類数
  - top_category              最も多く視聴したカテゴリ
  - top_category_rate         最多カテゴリが占める割合
  - category_view_time_ratios 視聴時間ベースのカテゴリ割合（"カテゴリ:割合"）
  - view_time_ratio__*        カテゴリ別の視聴時間割合

使い方:
  python analyze_youtube_logs.py [入力JSONLパス]
  （省略時は data/logs.jsonl）
"""

import sys
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

# ---- 判定のしきい値（必要なら変更） --------------------------------------
COMPLETION_RATE = 0.9   # 視聴完了とみなす視聴到達率（max_time_sec / duration_sec）
EARLY_SKIP_SEC = 2.0    # 早期スキップとみなす視聴秒数の上限（これ以下なら早期スキップ）
# -------------------------------------------------------------------------

LOG_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/logs.jsonl"
SESSION_PATH = "data/sessions.json"
CATEGORY_LABEL_CSV = "youtube_video_category_labels.csv"
VIDEO_CATEGORY_CACHE_CSV = "youtube_video_category_cache.csv"
OUTPUT_CSV = "youtube_analysis_summary.csv"

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


def load_env_file(path=".env.local"):
    """必要な環境変数が未設定なら .env.local から読み込む。"""
    env_path = Path(path)
    if not env_path.exists():
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _first_existing_column(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    return None


def load_session_categories(path):
    """data/sessions.json の video_order からカテゴリ情報を取り出す。"""
    if not Path(path).exists():
        return pd.DataFrame()

    with open(path, "r", encoding="utf-8") as f:
        sessions = json.load(f)

    rows = []
    for session in sessions:
        session_id = session.get("session_id") or session.get("id")
        for video_index, video in enumerate(session.get("video_order") or []):
            rows.append(
                {
                    "session_id": session_id,
                    "video_index": video_index,
                    "video_id": video.get("video_id"),
                    "video_category_id": video.get("category_id") or video.get("categoryId"),
                    "video_category": (
                        video.get("category_title")
                        or video.get("category")
                        or video.get("category_label")
                    ),
                }
            )

    return pd.DataFrame(rows)


def load_category_labels(path):
    """カテゴリIDとカテゴリ名の対応CSVがあれば読み込む。"""
    if not Path(path).exists():
        return pd.DataFrame(columns=["video_category_id", "video_category_label"])

    labels = pd.read_csv(path, dtype=str)
    id_col = _first_existing_column(labels, ["category_id", "categoryId", "id"])
    label_col = _first_existing_column(
        labels,
        ["category_title", "category", "category_label", "label", "title", "name"],
    )

    if not id_col or not label_col:
        print(
            f"警告: {path} に category_id/category_title 相当の列がないため、カテゴリ名対応は使いません。"
        )
        return pd.DataFrame(columns=["video_category_id", "video_category_label"])

    return (
        labels[[id_col, label_col]]
        .rename(columns={id_col: "video_category_id", label_col: "video_category_label"})
        .dropna(subset=["video_category_id"])
        .drop_duplicates("video_category_id")
    )


def load_video_category_cache(path):
    """video_id とカテゴリの対応キャッシュがあれば読み込む。"""
    if not Path(path).exists():
        return pd.DataFrame(columns=["video_id", "video_category_id", "video_category"])

    cache = pd.read_csv(path, dtype=str)
    id_col = _first_existing_column(cache, ["video_id", "videoId", "id"])
    category_id_col = _first_existing_column(cache, ["video_category_id", "category_id", "categoryId"])
    category_col = _first_existing_column(
        cache,
        ["video_category", "category_title", "category", "category_label", "label", "title"],
    )

    if not id_col or not category_id_col:
        return pd.DataFrame(columns=["video_id", "video_category_id", "video_category"])

    columns = [id_col, category_id_col]
    rename = {
        id_col: "video_id",
        category_id_col: "video_category_id",
    }
    if category_col:
        columns.append(category_col)
        rename[category_col] = "video_category"

    cache = cache[columns].rename(columns=rename)
    if "video_category" not in cache.columns:
        cache["video_category"] = ""

    return cache.dropna(subset=["video_id"]).drop_duplicates("video_id")


def _fetch_youtube_json(endpoint, params):
    query = urllib.parse.urlencode(params)
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{query}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_youtube_video_categories(video_ids, api_key):
    """YouTube Data API から video_id ごとのカテゴリID/カテゴリ名を取得する。"""
    category_by_video_id = {}
    category_ids = set()

    for ids in _chunks(video_ids, 50):
        data = _fetch_youtube_json(
            "videos",
            {
                "part": "snippet",
                "id": ",".join(ids),
                "key": api_key,
            },
        )

        for item in data.get("items", []):
            category_id = item.get("snippet", {}).get("categoryId", "")
            if not item.get("id") or not category_id:
                continue
            category_by_video_id[item["id"]] = category_id
            category_ids.add(category_id)

    category_title_by_id = {}
    for ids in _chunks(sorted(category_ids), 50):
        data = _fetch_youtube_json(
            "videoCategories",
            {
                "part": "snippet",
                "id": ",".join(ids),
                "key": api_key,
            },
        )

        for item in data.get("items", []):
            category_title_by_id[item["id"]] = item.get("snippet", {}).get("title", "")

    return pd.DataFrame(
        [
            {
                "video_id": video_id,
                "video_category_id": category_id,
                "video_category": category_title_by_id.get(category_id, ""),
            }
            for video_id, category_id in category_by_video_id.items()
        ]
    )


def fill_from_video_category_cache(video):
    cache = load_video_category_cache(VIDEO_CATEGORY_CACHE_CSV)
    if cache.empty:
        return video

    video = video.merge(cache, on="video_id", how="left", suffixes=("", "_cached"))
    video["video_category_id"] = video["video_category_id"].where(
        video["video_category_id"].astype(str) != "",
        video["video_category_id_cached"],
    )
    video["video_category"] = video["video_category"].where(
        video["video_category"].astype(str) != "",
        video["video_category_cached"],
    )
    return video.drop(columns=["video_category_id_cached", "video_category_cached"])


def fetch_missing_categories(video):
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return video

    missing = video[
        (video["video_id"].notna())
        & (video["video_category_id"].fillna("").astype(str) == "")
    ]["video_id"].drop_duplicates().tolist()

    if not missing:
        return video

    fetched = fetch_youtube_video_categories(missing, api_key)
    if fetched.empty:
        return video

    video = video.merge(fetched, on="video_id", how="left", suffixes=("", "_fetched"))
    video["video_category_id"] = video["video_category_id"].where(
        video["video_category_id"].astype(str) != "",
        video["video_category_id_fetched"],
    )
    video["video_category"] = video["video_category"].where(
        video["video_category"].astype(str) != "",
        video["video_category_fetched"],
    )
    return video.drop(columns=["video_category_id_fetched", "video_category_fetched"])


def add_video_categories(video):
    """動画テーブルへカテゴリID/カテゴリ名を追加する。"""
    session_categories = load_session_categories(SESSION_PATH)

    if not session_categories.empty:
        video = video.merge(
            session_categories,
            on=["session_id", "video_index", "video_id"],
            how="left",
        )
    else:
        video["video_category_id"] = pd.NA
        video["video_category"] = pd.NA

    labels = load_category_labels(CATEGORY_LABEL_CSV)
    if not labels.empty:
        video = video.merge(labels, on="video_category_id", how="left")
        video["video_category"] = video["video_category"].fillna(video["video_category_label"])
        video = video.drop(columns=["video_category_label"])

    video["video_category_id"] = video["video_category_id"].fillna("")
    video["video_category"] = video["video_category"].fillna("")
    video = fill_from_video_category_cache(video)
    video = fetch_missing_categories(video)
    video["video_category_id"] = video["video_category_id"].fillna("")
    video["video_category"] = video["video_category"].fillna("")
    return video


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
    video = add_video_categories(video)
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


def _category_column_suffix(category):
    """カテゴリ名をCSV列名に使いやすい形へ変換する。"""
    suffix = category.lower().replace("&", "and")
    suffix = re.sub(r"[^0-9a-zA-Z]+", "_", suffix).strip("_")
    return suffix or "unknown"


def _category_view_time_stats(group):
    """カテゴリ別の視聴秒数・割合を返す。"""
    g = group.copy()
    g["category_for_ratio"] = g["video_category"].fillna("").replace("", "Unknown")
    total_view_sec = g["watched_sec"].sum()
    category_view_sec = (
        g.groupby("category_for_ratio")["watched_sec"]
        .sum()
        .sort_values(ascending=False)
    )

    if total_view_sec > 0:
        category_ratios = category_view_sec / total_view_sec
    else:
        category_ratios = category_view_sec * np.nan

    stats = {
        "category_view_time_ratios": " | ".join(
            f"{category}:{ratio:.6f}"
            for category, ratio in category_ratios.items()
            if pd.notna(ratio)
        ),
        "top_view_time_category": category_ratios.index[0] if len(category_ratios) else "",
        "top_view_time_category_rate": (
            category_ratios.iloc[0] if len(category_ratios) and pd.notna(category_ratios.iloc[0]) else np.nan
        ),
    }

    for category, view_sec in category_view_sec.items():
        suffix = _category_column_suffix(category)
        stats[f"view_time_sec__{suffix}"] = view_sec
        stats[f"view_time_ratio__{suffix}"] = (
            view_sec / total_view_sec if total_view_sec > 0 else np.nan
        )

    return stats


def summarize_participant(group):
    """1セッション分の video テーブルから参加者指標を計算する。"""
    g = group.sort_values("video_index")
    flags = g["early_skip"].tolist()
    categories = g["video_category"].fillna("").astype(str)
    non_empty_categories = categories[categories != ""]
    category_counts = non_empty_categories.value_counts()
    top_category = category_counts.index[0] if len(category_counts) else ""
    top_category_rate = (
        category_counts.iloc[0] / len(non_empty_categories)
        if len(non_empty_categories)
        else np.nan
    )

    # セッションの所要時間（分）。切り替え頻度の分母。
    span = g["last_time"].max() - g["first_time"].min()
    minutes = span.total_seconds() / 60.0 if pd.notna(span) else np.nan
    n = len(g)

    stats = {
            "watched_titles": " | ".join(g["video_title"].fillna("").astype(str)),
            "watched_categories": " | ".join(categories),
            "unique_category_count": non_empty_categories.nunique(),
            "top_category": top_category,
            "top_category_rate": top_category_rate,
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
    stats.update(_category_view_time_stats(g))
    return pd.Series(stats)


def build_summary_table(video):
    rows = []
    for keys, group in video.groupby(GROUP_KEYS, dropna=False):
        row = dict(zip(GROUP_KEYS, keys))
        row.update(summarize_participant(group).to_dict())
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    load_env_file()
    df = load_logs(LOG_PATH)
    video = build_video_table(df)

    summary = build_summary_table(video)
    summary.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"入力: {LOG_PATH}（{len(df)} イベント）")
    print(f"出力: {OUTPUT_CSV}（{len(summary)} 行）")
    print()
    cols = [
        "participant_id", "total_videos", "unique_category_count", "top_category",
        "top_category_rate", "top_view_time_category", "top_view_time_category_rate",
        "total_view_sec", "mean_view_sec", "completion_rate",
        "early_skip_rate", "switch_per_min", "view_sec_var",
        "max_consecutive_skip", "late_skip_increase",
    ]
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(summary[cols].to_string(index=False))


if __name__ == "__main__":
    main()
