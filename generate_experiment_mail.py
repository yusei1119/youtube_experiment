"""実験参加者に送るメール本文を生成するスクリプト。

UIを使う場合は、次のコマンドで起動してください。

    python3 experiment_mail_ui.py

UIを使わず直接出力する場合は、「ここから設定」内を書き換えて実行します。

    python3 generate_experiment_mail.py

テキストファイルに保存する場合:

    python3 generate_experiment_mail.py > experiment_mail.txt
"""


# =============================================================================
# ここから設定：参加者ごとに変更する項目
# =============================================================================

# 参加者ID
PARTICIPANT_ID = "XX"

# 条件の実施順。short、meditation、dailyを1回ずつ並べてください。
CONDITION_ORDER = ["short", "meditation", "daily"]

# 各条件で使用する映画予告映像の番号（1〜8）
TRAILER_SELECTION = {
    "short": 1,
    "meditation": 2,
    "daily": 3,
}

# 日常動画と理解度テストの番号（1〜10）
DAILY_VIDEO_SELECTION = 1
COMPREHENSION_TEST_SELECTION = 1


# =============================================================================
# ここにURLをペースト：一度設定すれば、参加者ごとの変更は不要です
# =============================================================================

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

# 日常動画（10種類）
DAILY_VIDEO_URLS = {
    1: "https://drive.google.com/file/d/1gfa9WprHTOXuAOP1SQv4G6E6iUqZu-_y/view?usp=sharing",
    2: "https://drive.google.com/file/d/1X-BEmrZHQqC4Xvjfq8a_wyKZ0H8O9xLB/view?usp=drive_link",
    3: "https://drive.google.com/file/d/15kq4fx2l-JvW01oKyKFpv3hJKWTzd-re/view?usp=sharing",
    4: "https://drive.google.com/file/d/1Rko4-V7mHFPSj5C_IGP4mORsirn8KsBS/view?usp=drive_link",
    5: "https://drive.google.com/file/d/1kELQxxy8aHRVvFFWakdpAn8Vb4XxRWqF/view?usp=drive_link",
    6: "https://drive.google.com/file/d/1VraCSeLDd30d342HBZmOoSJYIqD4WQXP/view?usp=drive_link",
    7: "https://drive.google.com/file/d/1_Zd_6qFn5efMpMVAy55C8wvXX6E5b8r4/view?usp=drive_link",
    8: "https://drive.google.com/file/d/1ua8xcg1Bquj-z3cHl5Cb0KGb-pZ5OiYK/view?usp=sharing",
    9: "https://drive.google.com/file/d/1WmmyvH3apEUGrpxAXhyZAUaS8RMviwTU/view?usp=sharing",
    10: "https://drive.google.com/file/d/106sMdCG48PKu7_3Se6wOinxBsSLQ8Pww/view?usp=drive_link",
}

# 理解度テスト（10種類）
COMPREHENSION_TEST_URLS = {
    1: "https://forms.gle/m2XQcZVnZrobMXpR9",
    2: "https://forms.gle/M8KnLJZq7wJs2VbX7",
    3: "https://forms.gle/cxVW8Qdbdx2tNWq17",
    4: "https://forms.gle/qC7nuCLWAahTyVAW9",
    5: "https://forms.gle/DGAaxRS3jghoiXVg6",
    6: "https://forms.gle/Vi6rX1fFseJNbSjH9",
    7: "https://forms.gle/8p5pNc8C9xrdny7C8",
    8: "https://forms.gle/4F15493CQrRKtdJv9",
    9: "https://forms.gle/YFPF5zV6bGnV13828",
    10: "https://forms.gle/hxQoFDjyXf9LyUpP6",
}

# 毎回共通で使用するURL
SHORT_VIDEO_URL = "https://youtube-experiment.vercel.app/"
MEDITATION_VIDEO_URL = (
    "https://drive.google.com/file/d/1JbmShwdUFkXOnLbwJp-MvXP0iJGA8z6O/"
    "view?usp=sharing"
)
FINAL_SURVEY_URL = "https://forms.gle/C21LeEya8L2UBUcA7"


# =============================================================================
# ここまで設定：以下は通常、変更する必要はありません
# =============================================================================

CONDITION_NAMES = {
    "short": "ショート動画",
    "meditation": "瞑想動画",
    "daily": "日常動画",
}

NASA_TASK_FILE = "NASA_task_90.html"
WRITING_TASK_FILE = "Writing_task_90.html"
SEPARATOR = "*" * 24


def get_url(urls: dict[int, str], number: int, label: str) -> str:
    """番号に対応するURLを取得し、未登録なら分かりやすいエラーを出す。"""
    if number not in urls:
        raise ValueError(f"{label}の番号は {number} ではなく、{min(urls)}〜{max(urls)} で指定してください。")

    url = urls[number].strip()
    if not url:
        raise ValueError(
            f"{label} {number} のURLが未登録です。スクリプト上部のURL欄にペーストしてください。"
        )
    return url


def validate_settings() -> None:
    """条件順と参加者IDの設定ミスを検出する。"""
    expected = set(CONDITION_NAMES)
    if len(CONDITION_ORDER) != 3 or set(CONDITION_ORDER) != expected:
        raise ValueError(
            "CONDITION_ORDERには short、meditation、dailyを1回ずつ指定してください。"
        )
    if not PARTICIPANT_ID.strip():
        raise ValueError("PARTICIPANT_IDを入力してください。")


def trailer_url(condition: str) -> str:
    number = TRAILER_SELECTION[condition]
    return get_url(TRAILER_URLS, number, "映画予告映像")


def make_short_block() -> str:
    return f"""[1] ショート動画**(スマホ)**URL:
{SHORT_VIDEO_URL}
↓

[2] ショート動画後のアンケート:
添付ファイル参照：{NASA_TASK_FILE}
↓

[3] 2分間の映画予告映像URL:
{trailer_url("short")}
↓

[4] ショート動画後の記述タスク:
添付ファイル参照：{WRITING_TASK_FILE}"""


def make_meditation_block() -> str:
    return f"""[1] 瞑想動画URL:
{MEDITATION_VIDEO_URL}
↓

[2] 瞑想動画後のアンケート:
添付ファイル参照：{NASA_TASK_FILE}
↓

[3] 2分間の映画予告映像URL:
{trailer_url("meditation")}
↓

[4] 瞑想動画後の記述タスク:
添付ファイル参照：{WRITING_TASK_FILE}"""


def make_daily_block() -> str:
    daily_url = get_url(DAILY_VIDEO_URLS, DAILY_VIDEO_SELECTION, "日常動画")
    test_url = get_url(
        COMPREHENSION_TEST_URLS,
        COMPREHENSION_TEST_SELECTION,
        "理解度テスト",
    )

    return f"""[1] 日常動画URL:
{daily_url}
↓

[2] 理解度テストURL:
{test_url}
↓

[3] 日常動画後のアンケート:
添付ファイル参照：{NASA_TASK_FILE}
↓

[4] 2分間の映画予告映像URL:
{trailer_url("daily")}
↓

[5] 日常動画後の記述タスク:
添付ファイル参照：{WRITING_TASK_FILE}"""


BLOCK_BUILDERS = {
    "short": make_short_block,
    "meditation": make_meditation_block,
    "daily": make_daily_block,
}


def generate_mail() -> str:
    """設定内容から、時系列順のメール本文を生成する。"""
    validate_settings()
    experiment_blocks = []

    for index, condition in enumerate(CONDITION_ORDER, start=1):
        block = (
            f"実験{index}（{CONDITION_NAMES[condition]}条件）\n\n"
            f"{SEPARATOR}\n{BLOCK_BUILDERS[condition]()}"
        )
        if index < len(CONDITION_ORDER):
            block += "\n\n休憩（3分）"
        experiment_blocks.append(block)

    experiments = "\n\n".join(experiment_blocks)
    return f"""実験参加者ID:
{PARTICIPANT_ID.strip()}

{experiments}

{SEPARATOR}
[6] 実験後のアンケートURL:
{FINAL_SURVEY_URL}"""


if __name__ == "__main__":
    try:
        print(generate_mail())
    except (KeyError, ValueError) as error:
        raise SystemExit(f"設定エラー：{error}") from error
