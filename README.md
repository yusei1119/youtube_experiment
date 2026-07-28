# YouTubeショート動画実験

実験用Next.jsアプリと、Supabaseの結果取得・統計分析を同じリポジトリで管理します。
分析結果は参加者の追加状況に応じて保存し、入力データや手修正ファイルを
直接上書きしません。

## 実験結果を追加した後の分析

1. Google Formsの実験後アンケートCSVを
   [`data/post_survey`](data/post_survey) の対応ファイルへ反映します。
2. `.env.local`に次のSupabase接続情報があることを確認します。

   ```text
   NEXT_PUBLIC_SUPABASE_URL=...
   SUPABASE_SERVICE_ROLE_KEY=...
   ```

3. リポジトリ直下で一括分析を実行します。

   ```bash
   python run_analysis.py
   ```

この1コマンドで、次の処理を順番に実行します。

1. YouTube視聴ログ、NASA-TLX、記述課題をSupabaseから取得
2. セッション情報・カテゴリキャッシュ・補正定義・採用者一覧・実験後アンケートをスナップショット保存
3. YouTube参加者IDの補正・除外ルールを適用して視聴指標を集計
4. A系・B系YouTube記述統計を作成
5. 共通のA系採用者一覧を使ってNASA-TLX、記述課題、実験後アンケートを分析
6. 入力元・SHA-256・実行状態を`manifest.json`へ記録

### runの保存ルール

Supabaseから取得した5種類のデータに含まれる`participant_id`を、直近の正常完了
runと比較します。

- 新しい参加者IDが1件以上ある：日時付きの新規runとして保存
- 新しい参加者IDが0件：全分析の正常完了後、直近runを今回の内容で上書き
- exportが空、または分析が失敗：直近runは上書きしない

既存参加者の回答・ログだけが追加または修正された場合は、直近runを更新します。
`--local`による再分析はSupabase参加者比較の対象外で、常に別runとして保存します。

出力例：

```text
analysis_runs/
└── run_20260729_143000/
    ├── manifest.json
    ├── raw/
    └── analysis/
        ├── youtube/
        ├── nasa_tlx/
        ├── writing/
        └── post_survey/
```

実行内容だけ確認する場合：

```bash
python run_analysis.py --dry-run
```

Supabaseへ接続せず、整理前に保存したローカルデータで再分析する場合：

```bash
python run_analysis.py --local
```

## 初期設定

分析用Pythonパッケージ：

```bash
python -m pip install -r requirements-analysis.txt
```

実験アプリ：

```bash
npm install
npm run dev
```

ブラウザで <http://localhost:3000> を開きます。

## フォルダ構成

```text
app/                 Next.js画面・API
lib/                 実験アプリの共通処理
public/              NASA・記述課題ページと静的ファイル
scripts/
  analysis/          統計分析
  export/            Supabaseからの取得
  experiment/        タイマー・案内メール生成
  common/            共通出力処理
schemas/             Supabase SQL
data/
  logs.jsonl         ローカル実験ログ
  sessions.json      ローカルセッション
  post_survey/       Google Forms入力CSV
  local_exports/     整理時点のSupabase export（ローカル再分析用）
  reference/         YouTubeカテゴリ対応キャッシュ
  corrections/       実験データ補正記録
analysis_runs/       一括分析結果（Git対象外）
archive/             整理前・本実験前の保存データ
docs/                指標定義と運用資料
```

## 個別スクリプト

通常は`run_analysis.py`を使用してください。個別確認が必要な場合は、リポジトリ
直下からモジュールとして実行します。

```bash
python -m scripts.export.export_supabase_logs
python -m scripts.analysis.analyze_youtube_logs data/logs.jsonl
python -m scripts.analysis.analyze_nasa_tlx --study all
python -m scripts.analysis.analyze_writing_task --study all
python -m scripts.analysis.analyze_post_survey --study all
```

## データ修正時の注意

分析結果を直接修正せず、可能な限り入力データまたはSupabase側を修正します。
補正内容は [`data/corrections/README.md`](data/corrections/README.md) に記録します。
A系の全分析で共通利用する有効採用者は
[`data/corrections/analysis_participants.csv`](data/corrections/analysis_participants.csv)
の`included`列で編集します。`true`は採用、`false`は除外です。
YouTubeログの補正は
[`data/corrections/youtube_participant_corrections.csv`](data/corrections/youtube_participant_corrections.csv)
と
[`data/corrections/youtube_session_corrections.csv`](data/corrections/youtube_session_corrections.csv)
で管理し、元ログを変更せず分析時に適用します。適用件数は分析出力の
`youtube_log_correction_report.csv`と`youtube_session_correction_report.csv`
で確認できます。
新しい参加者が追加された時点のrunは別フォルダとして残るため、参加者追加前後の
結果を比較できます。
