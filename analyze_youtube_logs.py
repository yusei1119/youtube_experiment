import json
import pandas as pd

LOG_PATH = "data/logs.jsonl"

rows = []
with open(LOG_PATH, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))

df = pd.DataFrame(rows)

progress = df[df["event_type"] == "progress"].copy()

summary = (
    progress
    .groupby(["participant_id", "session_id", "video_id", "video_title", "video_index"], dropna=False)
    .agg(
        max_time_sec=("max_time_sec", "max"),
        duration_sec=("duration_sec", "max"),
        last_current_time_sec=("current_time_sec", "max"),
        log_count=("event_type", "count"),
    )
    .reset_index()
)

summary["view_rate"] = summary["max_time_sec"] / summary["duration_sec"]
summary["completed_90"] = summary["view_rate"] >= 0.9

events = (
    df
    .groupby(["participant_id", "session_id", "video_id", "event_type"])
    .size()
    .unstack(fill_value=0)
    .reset_index()
)

result = summary.merge(
    events,
    on=["participant_id", "session_id", "video_id"],
    how="left"
)

result.to_csv("youtube_viewing_summary.csv", index=False, encoding="utf-8-sig")

participant_summary = (
    result
    .groupby(["participant_id", "session_id"])
    .agg(
        watched_video_count=("video_id", "nunique"),
        mean_view_rate=("view_rate", "mean"),
        total_max_view_sec=("max_time_sec", "sum"),
        completed_90_count=("completed_90", "sum"),
    )
    .reset_index()
)

participant_summary.to_csv("youtube_participant_summary.csv", index=False, encoding="utf-8-sig")

print(result.head())
print(participant_summary.head())