# YouTubeショート動画実験

実験用Next.jsアプリと、Supabaseの結果取得・統計分析を同じリポジトリで管理します。
分析は実行ごとに独立したフォルダへ保存され、過去のCSVや手修正ファイルを
上書きしません。

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
2. セッション情報・カテゴリキャッシュ・実験後アンケートをスナップショット保存
3. YouTube視聴指標を集計
4. A系・B系YouTube記述統計を作成
5. NASA-TLX、記述課題、実験後アンケートを分析
6. 入力元・SHA-256・実行状態を`manifest.json`へ記録

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
各分析実行は別フォルダへ保存されるため、過去結果との比較や復元が可能です。
