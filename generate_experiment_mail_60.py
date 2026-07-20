"""60分実験（ショート動画条件）の参加案内メールを生成する。"""

from __future__ import annotations


SHORT_VIDEO_OPTIONS = (5, 10, 15, 20, 25, 30)

# 2分間の映画予告映像（8種類）
TRAILER_URLS = {
    1: "https://drive.google.com/file/d/1KPx7E5qjovn7aYjQ_2gMy0Aiiw5WEISY/view?usp=sharing",
    2: "https://drive.google.com/file/d/1WWLCzHESQl3aLkDKoj314iw2jHFTO1Gu/view?usp=drive_link",
    3: "https://drive.google.com/file/d/1EZPGKXA5mq9G08ksG4glzTxLZ82HRe--/view?usp=drive_link",
    4: "https://drive.google.com/file/d/1WgwqKWkuqEcvw_aJNDeM7yg1lu40xL1X/view?usp=drive_link",
    5: "https://drive.google.com/file/d/1SK7k7t4AkPKQV7BvCrkFDnNuQ1AR37Q4/view?usp=drive_link",
    6: "https://drive.google.com/file/d/1Zfhg6Fw6m-sU1IIo1y0wwT1ujWKnPyXh/view?usp=drive_link",
    7: "https://drive.google.com/file/d/1Lq13jk9W1M-eNCG4sAfiaNFbx-3s9eZj/view?usp=drive_link",
    8: "https://drive.google.com/file/d/1rIKmh9cBn6cwmitlpM-kvZEUkKxe7Y7y/view?usp=drive_link",
}

SHORT_VIDEO_URL = "https://youtube-experiment.vercel.app/"
NASA_TASK_URL = "https://youtube-experiment.vercel.app/nasa-task-60.html"
WRITING_TASK_URL = (
    "https://youtube-experiment.vercel.app/writing-task-60.html"
)
FINAL_SURVEY_URL = "https://forms.gle/zhTjncyo8sH6UgKY7"
SEPARATOR = "*" * 24


def validate_settings(
    participant_id: str,
    short_video_minutes: int,
    trailer_number: int,
) -> None:
    """入力値を検証し、メール生成前に設定ミスを知らせる。"""
    if not participant_id.strip():
        raise ValueError("実験参加者IDを入力してください。")
    if short_video_minutes not in SHORT_VIDEO_OPTIONS:
        raise ValueError("動画視聴時間は5〜30分の5分刻みで指定してください。")
    if trailer_number not in TRAILER_URLS:
        raise ValueError("映画予告映像は1〜8から選択してください。")


def generate_mail(
    participant_id: str = "XX",
    short_video_minutes: int = 5,
    trailer_number: int = 1,
) -> str:
    """選択内容から60分実験のメール本文を生成する。"""
    validate_settings(participant_id, short_video_minutes, trailer_number)

    return f"""実験参加者ID:
{participant_id.strip()}

動画視聴時間:{short_video_minutes}分

実験1（ショート動画条件）

{SEPARATOR}
[1] ショート動画**(スマホ)**URL:
{SHORT_VIDEO_URL}
↓

[2] 認知負荷アンケート:
{NASA_TASK_URL}
※送信完了の表示を確認してから、実験案内メールに戻って次のタスクへ進んでください。
↓

[3] 2分間の映画予告映像URL:
{TRAILER_URLS[trailer_number]}
↓

[4] 記述タスク:
{WRITING_TASK_URL}
※送信完了の表示を確認してから、実験案内メールに戻って次のタスクへ進んでください。
↓

[5] 実験後のアンケートURL:
{FINAL_SURVEY_URL}"""


if __name__ == "__main__":
    try:
        print(generate_mail())
    except ValueError as error:
        raise SystemExit(f"設定エラー：{error}") from error
