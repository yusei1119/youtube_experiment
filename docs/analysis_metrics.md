# YouTube視聴ログの分析指標

## 基本情報

- `participant_id`: 参加者ID
- `session_id`: 視聴セッションID
- `watched_titles`: 視聴順の動画タイトル（` | ` 区切り）
- `watched_categories`: 視聴順の動画カテゴリ（` | ` 区切り）
- `total_videos`: 視聴した動画本数

## 視聴時間

- `total_view_sec`: 各動画で最も先まで見た秒数の合計
- `mean_view_sec`: 1本あたりの平均視聴時間
- `session_minutes`: セッションの開始時刻から終了時刻までの実測経過時間（終了時刻がない不完全セッションは、最初のログから最後のログまでの経過時間）
- `logged_session_minutes`: 最初のログから最後のログまでの経過時間（ログ欠落の診断用）
- `view_sec_var`: 動画ごとの視聴時間の分散

## 完了・スキップ

- `completion_rate`: 動画の90%以上を見た、または`ended`が記録された割合
- `early_skip_rate`: 2秒以内に離脱し、完了していない動画の割合
- `switch_per_min`: 1分あたりの動画切り替え頻度
- `max_consecutive_skip`: 早期スキップが連続した最大本数
- `late_skip_increase`: 後半の早期スキップ率 − 前半の早期スキップ率

## カテゴリ

- `unique_category_count`: 視聴したカテゴリ数
- `top_category`: 本数ベースで最も多く視聴したカテゴリ
- `top_category_rate`: 最多カテゴリが視聴本数に占める割合
- `category_view_time_ratios`: カテゴリ別の視聴時間割合
- `top_view_time_category`: 視聴時間が最長のカテゴリ
- `top_view_time_category_rate`: 最長カテゴリが総視聴時間に占める割合
- `view_time_sec__*`: カテゴリ別の視聴秒数
- `view_time_ratio__*`: カテゴリ別の視聴時間割合

例：`view_time_ratio__people_and_blogs = 0.8`なら、総視聴時間の80%が
`People & Blogs`カテゴリだったことを表します。

## 60分実験の記述タスク

既存の `latency_sec`、`writing_duration_sec`、回答文字数、総所要時間は
そのまま保存する。以下の追加指標は質問ごとに保存する。

- `min_chars_reached_text`: 最初に下限文字数へ到達した入力時点の文章
- `chars_after_min`: 最終回答文字数 − 下限文字数
- `deleted_char_count`: Backspace、Delete、切り取りなどのdelete系入力で減った文字数の累計
- `min_chars_reached_sec`: 質問を実際に表示していた時間のうち、最初の下限到達までの累計秒
- `latency_sec`: 質問表示から回答を書き始めるまでの既存指標

wide形式の回答CSVでは、上記の数値指標の5問平均を
`mean_*`列で出力する。分析結果では質問別の値を
`writing_60_question_data_long.csv`、5問平均を
`writing_60_analysis_data.csv`と`writing_60_descriptive_stats.csv`へ出力する。
