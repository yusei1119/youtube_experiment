"""登録URLを未ログイン状態で取得し、閲覧制限とリンク切れを検査する。"""

import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import generate_experiment_mail as mail


DRIVE_ID_PATTERN = re.compile(r"/file/d/([^/]+)")
RESTRICTED_MARKERS = (
    "you need access",
    "request access",
    "アクセス権が必要です",
    "アクセスをリクエスト",
    "permission denied",
    "sign in to continue",
)


def url_entries() -> list[tuple[str, int, str]]:
    groups = {
        "映画予告": mail.TRAILER_URLS,
        "日常動画": mail.DAILY_VIDEO_URLS,
        "理解度テスト": mail.COMPREHENSION_TEST_URLS,
        "共通URL": {
            1: mail.SHORT_VIDEO_URL,
            2: mail.MEDITATION_VIDEO_URL,
            3: mail.FINAL_SURVEY_URL,
        },
    }
    return [
        (group, number, url)
        for group, urls in groups.items()
        for number, url in urls.items()
    ]


def check_target(url: str) -> str:
    """Driveは共有ページでなく、認証要否が分かるファイル取得先を調べる。"""
    match = DRIVE_ID_PATTERN.search(url)
    if match:
        file_id = match.group(1)
        return (
            "https://drive.usercontent.google.com/download"
            f"?id={file_id}&export=download&confirm=t"
        )
    return url


def check_one(entry: tuple[str, int, str]) -> tuple[str, int, str, str]:
    group, number, original_url = entry
    if not original_url.strip():
        return group, number, "未登録", original_url

    request = urllib.request.Request(
        check_target(original_url),
        headers={"User-Agent": "Mozilla/5.0 (URL access checker)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(500_000).decode("utf-8", "ignore").lower()
            marker = next((item for item in RESTRICTED_MARKERS if item in body), None)
            if marker or "accounts.google.com" in response.geturl():
                status = "要確認（ログイン要求）"
            else:
                status = f"閲覧可能（HTTP {response.status}）"
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            status = f"閲覧制限あり（HTTP {error.code}）"
        else:
            status = f"リンクエラー（HTTP {error.code}）"
    except Exception as error:  # ネットワーク切断やタイムアウトも結果に含める
        status = f"確認失敗（{type(error).__name__}）"

    return group, number, status, original_url


def main() -> None:
    entries = url_entries()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(check_one, entries))

    print("未ログイン状態でのURL確認結果")
    print("=" * 72)
    for group, number, status, url in results:
        print(f"{group} {number:>2}: {status}")
        print(f"  {url}")

    problems = [result for result in results if not result[2].startswith("閲覧可能")]
    print("=" * 72)
    print(f"全{len(results)}件 / 要確認{len(problems)}件")
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
