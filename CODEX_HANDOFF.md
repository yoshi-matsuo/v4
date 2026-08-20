# v4 引き継ぎドキュメント（Codex / Claude Code 共通）

作成日: 2026-08-16
対象: `/Users/matsuoyoshihiro/v4` 配下全体
想定読者: このドキュメントを最初に読む Codex（および将来の Claude Code セッション）

このファイルは、実際のコード・設定・ログ・launchd 定義・git 状態を調査したうえで書かれています。
推測で書いた項目はありません（不明点は「不明」「未確認」と明記しています）。

**別プロジェクトの`jstock`（日本株/米国株速報・朝のニュース等のPodcast生成、`/Users/matsuoyoshihiro/jstock`）を
扱う場合は、本ファイルではなく `jstock/AGENTS.md` を参照してください。v4とjstockはコード上の依存関係がない
完全に独立したプロジェクトです。**

---

## 1. v4全体の概要

`v4` は主に2つの独立した系統で構成されています。

### 1-A. 動画コンテンツ生成パイプライン（v4直下）
STOCK ARENA（株式投資の迷宮）などの長尺（約20分・5幕構成）金融ドキュメンタリー動画を、
台本生成→スライド生成→ナレーション合成→動画合成まで自動化するパイプライン。
Google Gemini（台本）・Google Cloud TTS Chirp3-HD（ナレーション）・yfinance（株価データ）・
PIL/MoviePy（スライド・動画合成）を使用。

主なファイル（v4直下）:
- `script_engine_v4.py` — yfinanceで株価データ取得 → Gemini 2.5 Flashで台本(JSON)生成
- `merge_script.py` — `part1.json` + `part2.json` → `script.json` に結合
- `slide_engine_v4.py` — `script.json` からスライドPNGを一括生成（`make_single_slide.py` を呼び出す）
- `make_single_slide.py` — 1枚スライド生成（テンプレート: template_Ar/Al/Sr/Sl, impact, contrast）
- `narration_engine_v4.py` — `script.json` のナレーションをGoogle Cloud TTSで音声合成・BGMミキシング
- `media_engine_v4.py` — チャート・スライド・音声を合成し最終動画を生成
- `generate_charts.py`, `fact_fetcher.py` — 補助ツール（株価チャート・ファクトCLI）
- `pronunciation_dict.json` — TTS読み上げ辞書。2026-08-19より `/Users/matsuoyoshihiro/shared_assets/pronunciation_dict.json` へのシンボリックリンクに変更（jstock・deep_infと共通辞書化）。**編集は shared_assets 側の実体ファイルで行うこと**（v4直下のこのパスはリンクなので直接編集しても実体は同じファイル）。shared_assets はgit管理外のため、辞書のバックアップは別途行うこと
- `script_old/` — 過去プロジェクトの `script.json` アーカイブ
- `outputs/` — 生成物（音声・画像・プロジェクト単位の出力。git管理外）
- `脚本用Gemへの指示例/` — 台本生成プロンプトの指示例集

**注意**: `script_engine_v4.py` は `from config import GEMINI_API_KEY` を参照しますが、
今回の調査時点で v4 直下に `config.py` が見つかりませんでした（`.gitignore` 対象外だが実ファイルなし）。
台本生成を実行する前に、このファイルの所在を確認してください（詳細は 10章）。

### 1-B. YouTube Analytics 自動取得基盤（`stock_arena_youtube_sync/`）
STOCK ARENA・NEXT投資ワード（将来的にCOMPANY ARCHIVEも）のYouTube動画実績データを
自動取得し、Cloud経由でGPT（Candidate Scout / 将来のNEXTディレクターGPT）に供給する基盤。
**現在このドキュメントで最も重要な稼働中システムです。** 詳細は3章以降。

このフォルダは `.gitignore` の `*.json` ルールにより秘密情報を含むJSON類がgit管理外になっており、
かつ `stock_arena_youtube_sync/` 自体が現在untracked（`git status` で `??` 表示）です。
つまりこのフォルダの内容は**git履歴に一切含まれていません**。バックアップは各自の責任で行ってください。

### その他のプロジェクト
- `crm.json`, `valuenex_4422.json`, `part1.json`, `part2.json`, `script.json` — 直近の制作案件の作業ファイル（現在進行中の案件データ。銘柄が変わるたびに上書きされる想定）
- `v4_output_CRMTEMP_MPY_wvf_snd.mp4` — 過去の動画合成出力サンプル（大容量ファイル、13.8MB）
- `メモ.txt` — 作業メモ（台本生成コマンド例、サムネ指示など。都度書き換えられる個人メモ）

---

## 2. ディレクトリ構成（重要フォルダのみ）

```
v4/
├── script_engine_v4.py / merge_script.py / slide_engine_v4.py
│   / make_single_slide.py / narration_engine_v4.py / media_engine_v4.py
│   / generate_charts.py / fact_fetcher.py         … 動画生成パイプライン本体
├── pronunciation_dict.json                         … TTS読み上げ辞書（shared_assets/pronunciation_dict.json へのsymlink）
├── script_old/                                     … 過去案件のscript.jsonアーカイブ
├── outputs/{assets,images,projects}/                … 生成物（音声・画像・プロジェクト別出力）
├── 脚本用Gemへの指示例/                              … 台本生成プロンプト例
└── stock_arena_youtube_sync/                        … ★ YouTube Analytics自動取得基盤（3章参照）
    ├── update_stock_arena_youtube.py               … SA本体スクリプト
    ├── update_next_investment_word_youtube.py      … NEXT本体スクリプト
    ├── run_youtube_sync_all.sh                     … launchdから呼ばれる統合ラッパー
    ├── stock_arena_sync_config.json                … SA設定（cloud_api_url, cloud_write_key含む）
    ├── next_investment_word_sync_config.json       … NEXT設定（同上）
    ├── client_secret.json / youtube_token.json     … OAuth関連（秘密情報）
    ├── stock_arena_history.csv / stock_arena_youtube_performance.csv
    │   / stock_arena_baseline_performance.csv / stock_arena_reach_daily.csv
    ├── next_investment_word_history.csv / next_investment_word_youtube_performance.csv
    │   / next_investment_word_reach_daily.csv
    ├── youtube_sync.log / youtube_sync_error.log   … 実行ログ
    ├── fix_stock_arena_*.py / update_stock_arena_youtube_before_*.py
    │                                                … 過去の一回限りパッチ適用スクリプトとその適用前バックアップ（履歴保存目的、通常は再実行不要）
    ├── apply_stock_arena_cloud_credentials.py / enable_cloud_push.py
    │                                                … Cloud連携の初期設定を`update_stock_arena_youtube.py`へ組み込んだ一回限りのセットアップスクリプト
    ├── setup_stock_arena_youtube_sync.sh            … 初回OAuth認証セットアップ
    ├── requirements_stock_arena_youtube_sync.txt    … SA/NEXT共通の依存関係
    ├── .venv_youtube_sync/                          … 専用venv（Python 3.10.2）
    └── candidate_api/                                … Cloud Run APIソース（4章参照）
        ├── main.py                                  … FastAPIアプリ本体
        ├── deploy_cloud_run.sh                       … Cloud Runへのデプロイスクリプト
        ├── openapi_action.yaml                       … Candidate Scout GPT Action用スキーマ（SAのみ）
        ├── cloud_api_credentials.txt / .generated_keys … デプロイ時生成の秘密情報
        └── requirements.txt
```

他フォルダとの関係:
- `stock_arena_youtube_sync/` は動画生成パイプライン（1-A）とはコード上の依存関係がありません（完全に独立）。共通点は「同じYouTubeチャンネルで公開される動画を後から分析する」という点のみ。
- `candidate_api/` はローカルの `stock_arena_youtube_sync/*.py` から見て「送信先」であり、Google Cloud Run上で独立して動作するサービスです（ローカルのフォルダはソースの置き場であり、実行はCloud Run側）。

---

## 3. 現在正常稼働している重要システム：`stock_arena_youtube_sync/`

### 3-1. 全体像
このフォルダは名称に「STOCK ARENA」とありますが、**STOCK ARENA・NEXT投資ワード・将来のCOMPANY ARCHIVEの
YouTube Analytics共通基盤**として設計されています。実装は次の2本立てです。

| スクリプト | 対象 | 独立性 |
|---|---|---|
| `update_stock_arena_youtube.py` | STOCK ARENA | 単独で完結。NEXT側の失敗の影響を受けない |
| `update_next_investment_word_youtube.py` | NEXT投資ワード | STOCK ARENA側のCSV・reachキャッシュには一切書き込まない |

両者は同じYouTubeチャンネル・同じOAuthトークン（`youtube_token.json`）・同じ
`client_secret.json` を**読み取り専用で共有**します（コメントに明記: 「別トークンを新規発行すると同一チャンネルへの二重同意を招くだけなので、あえて共有する」）。

### 3-2. `run_youtube_sync_all.sh`（launchdから呼ばれる統合ラッパー）
`stock_arena_youtube_sync/run_youtube_sync_all.sh` の実処理:
1. `.venv_youtube_sync/bin/python update_stock_arena_youtube.py` を実行し、終了コードを保持
2. 続けて `.venv_youtube_sync/bin/python update_next_investment_word_youtube.py` を実行
3. `set -uo pipefail`（`set -e` は使わない）— これによりSTOCK ARENA側の完了済み更新結果や
   ラッパー全体の終了コードが、NEXT側の失敗によって巻き込まれないようにしている
4. 最終的な終了コードはSTOCK ARENA側（`SA_STATUS`）のみを反映する

**→ SA失敗/NEXT失敗の障害分離はこの設計で実現されています。** コード上、NEXT側の例外はNEXTスクリプト内でも
個別にcatchされ（Cloud同期失敗時は警告のみ）、ラッパーレベルでも独立実行されています。

### 3-3. OAuth共有 / YouTube API群
`update_stock_arena_youtube.py` と `update_next_investment_word_youtube.py` はどちらも同じ3つのAPIを使用:
- **YouTube Data API v3** — アップロード済み動画一覧・タイトル・公開日時・長さ・公開ステータス取得
- **YouTube Analytics API (v2)** — 視聴回数・総再生時間・平均視聴時間・平均視聴率・登録者増減など取得
- **YouTube Reporting API (v1)** — サムネイルインプレッション数・CTR（`channel_reach_basic_a1` レポートジョブ）

OAuthスコープ（両スクリプト共通）:
```
https://www.googleapis.com/auth/youtube.readonly
https://www.googleapis.com/auth/yt-analytics.readonly
```
= 読み取り専用スコープのみ。書き込み系スコープは使用していません。

### 3-4. Reporting APIジョブの扱い（SA/NEXT共有）
`channel_reach_basic_a1` ジョブはチャンネル単位で1つしか存在せず、**STOCK ARENA側が作成者**です
(`ensure_reach_job`)。NEXT側 (`find_existing_reach_job`) は新規ジョブを作成せず、既存ジョブの
レポートを読み取って、NEXT動画IDに該当する行だけを `next_investment_word_reach_daily.csv` に抽出保存します。
→ もしSTOCK ARENA側を一度も実行せずにNEXT単体を実行すると、ジョブが存在せず
「ジョブ未作成」というReachデータ状態になります（コード上に警告メッセージあり）。

### 3-5. SA/NEXTの番組識別ルール（詳細は4章）

### 3-6. CSV保存先（分離）
| 系統 | history | performance | reach日次キャッシュ |
|---|---|---|---|
| STOCK ARENA | `stock_arena_history.csv` | `stock_arena_youtube_performance.csv`（初回のみ `stock_arena_baseline_performance.csv` に複製保存） | `stock_arena_reach_daily.csv` |
| NEXT投資ワード | `next_investment_word_history.csv` | `next_investment_word_youtube_performance.csv` | `next_investment_word_reach_daily.csv` |

NEXT側のCSVスキーマはSA側より簡素（企業名・証券コード・主テーマ・フック型のカラムなし）。
NEXT側のコード内コメントに明記: 「テーマ分類・フック分類などの独自分析ロジックは今回実装しない。
まずはYouTubeから取得できる客観的な実績データの蓄積のみを行う」。

### 3-7. Mac → Cloud 同期
各スクリプトの `main()` の最後で、CSVを読み込みJSONペイロードにしてCloud Run APIへPOSTします。
- SA: `push_candidate_scout_data()` → `POST {cloud_api_url}/admin/sync`
- NEXT: `push_next_data()` → `POST {cloud_api_url}/admin/sync/next`

どちらも `Authorization: Bearer {cloud_write_key}` ヘッダーで認証。送信失敗時は
例外を握りつぶして警告ログのみ（ローカルCSV生成自体は失敗させない設計）。

### 3-8. Cloud Run API（`candidate_api/main.py`）
FastAPIアプリ。Cloud Storage上のJSONを読み書きするだけのシンプルな構成（詳細は5章）。

### 3-9. Candidate Scout向けAPI / NEXT向けAPI
- Candidate Scout（カスタムGPT）向け読み取りエンドポイント: `/snapshot`, `/company`, `/recent`, `/benchmarks`（すべてSTOCK ARENAデータ）
- NEXT向け読み取りエンドポイント: `/next/snapshot`, `/next/benchmarks`
- `candidate_api/openapi_action.yaml` には **SA用の4エンドポイントのみ**定義されています。NEXT用エンドポイント
  (`/next/snapshot`, `/next/benchmarks`) はコード上は実装済みですが、GPT Action用のOpenAPIスキーマには
  まだ追加されていません（= NEXTディレクターGPTへの接続はまだ保留、11章参照）。

### 3-10. launchdの実行構成
- plist: `~/Library/LaunchAgents/com.stockarena.youtube-sync.plist`
- `Label`: `com.stockarena.youtube-sync`
- 実行対象: `stock_arena_youtube_sync/run_youtube_sync_all.sh`
- `StartInterval`: 21600秒（**6時間ごと**）
- `RunAtLoad`: true（ログイン/ロード時にも即実行）
- ログ出力: `youtube_sync.log`（標準出力）、`youtube_sync_error.log`（標準エラー）
- `launchctl list` で `com.stockarena.youtube-sync` がロード済みであることを確認済み（終了コード0）

### 3-11. SA失敗/NEXT失敗時の障害分離
3-2節参照。加えてコード内部でも:
- SA本体: Analytics取得失敗（HttpError）は動画単位でcatchし、その動画だけ空値にして処理続行（全体は止めない）
- NEXT本体: 同様にAnalytics取得失敗は動画単位でcatch。Reportingジョブ未作成時も全体を止めずreach欄を空欄化
- Cloud同期失敗（SA/NEXTとも）は例外を握りつぶし警告ログのみ。ローカルCSV生成の成否には影響しない

### 3-12. Reporting APIの日付正規化対応
`normalize_report_date()`（SA・NEXT両方に実装）:
```python
def normalize_report_date(d: str) -> str:
    # YouTube Reporting APIのCSVは日付を"YYYYMMDD"（ハイフンなし）で返す場合がある。
    d = (d or "").strip()
    if d and "-" not in d and len(d) == 8 and d.isdigit():
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return d
```
これは実際に過去のエラーログ（`youtube_sync_error.log`）で確認された不具合への対応です（10章参照）。

---

## 4. 番組識別ルール（実コード確認済み）

### STOCK ARENA (`update_stock_arena_youtube.py` の `is_stock_arena_video()`)
判定優先順位:
1. `privacy_status == "public"` かつ `duration_seconds >= min_duration_seconds`（設定: 180秒）が前提条件
2. **baseline維持**: 動画IDが `stock_arena_baseline_performance.csv` に既に存在する場合は無条件で採用（後述4-3）
3. **新方式（最優先の明示判定）**: タイトル末尾（前後空白除去後）が
   - `｜STOCK ARENA` → 採用
   - `｜NEXT投資ワード` または `｜COMPANY ARCHIVE` → 除外
4. **旧方式（互換フォールバック）**: 末尾タグが付いていない動画のみ対象
   - `exclude_title_keywords`（設定ファイル内: `NEXT投資ワード`, `今日の日本株速報`, `今日の米国株速報`, `朝イチマーケット情報`, `COMPANY ARCHIVE`）を含むタイトルは除外
   - タイトルが `【企業名】` で始まらない場合は除外
   - `【 】` 内が汎用ラベル（`日本株`, `米国株`, `NEXT投資ワード`, `AI`, `半導体` 等）の場合は除外

### NEXT投資ワード (`update_next_investment_word_youtube.py` の `is_next_investment_word_video()`)
判定はシンプルに1条件のみ:
- `privacy_status == "public"` かつ `duration_seconds >= min_duration_seconds`
- タイトル末尾（前後空白除去後）が `｜NEXT投資ワード`（設定ファイル `title_suffix` で指定）

コード内コメント: 「STOCK ARENAや他番組の動画を混入させないよう、判定はこの1条件のみに絞る」。

### COMPANY ARCHIVE（将来）
現時点ではタイトル末尾 `｜COMPANY ARCHIVE` はSTOCK ARENA判定ロジック内で**除外条件としてのみ**
参照されています。COMPANY ARCHIVE専用の取得スクリプトはまだ存在しません（11章参照）。

### SAのbaseline互換仕様（重要・変更注意）
- 初回実行時、既存の `stock_arena_youtube_performance.csv`（当時101本）を
  `stock_arena_baseline_performance.csv` としてそのままコピー保存（`snapshot_baseline_if_needed()`、
  ファイルが存在しない場合のみ実行・上書きしない）。
- 設定 `baseline_cutoff`（現在値: `2026-08-13`）以前のインプレッション/CTRはbaseline側の値を正とし、
  それ以降のReporting APIデータのみを加算する（`aggregate_reach()`）。
- baseline収録済みの動画IDは、たとえYouTube Data APIのuploads一覧から取得できなくなった場合でも
  （非公開化やAPI側の一時的な欠落等）、baselineのタイトル・公開日・長さから最小限のmetadataを
  補完してSTOCK ARENAとして扱い続ける（`missing_baseline_ids` 処理）。
- 動画IDは読み込み時に必ず前後空白を除去（`.strip()`）してから同一性判定に使う
  （`fix_stock_arena_video_id_normalize.py` で過去に適用された修正）。

**→ `stock_arena_baseline_performance.csv` は「歴史的事実の記録」であり、削除・再生成すると
過去のインプレッション/CTR基準値が失われます（9章の禁止事項を参照）。**

---

## 5. Cloud / API構成

### 5-1. 保存先（Cloud Storage）
Cloud Run サービス `candidate_api/main.py` がGCSバケット（環境変数 `DATA_BUCKET`）に対し、
JSONオブジェクトとして2系統を完全分離して保存:
- STOCK ARENA: `DATA_OBJECT`（デフォルト `stock_arena/latest.json`）
- NEXT投資ワード: `NEXT_DATA_OBJECT`（デフォルト `next_investment_word/latest.json`）

各オブジェクトの中身は `{updated_at, source_updated_at, history:[...], performance:[...]}`。

### 5-2. 主な書き込みエンドポイント
- `POST /admin/sync` — STOCK ARENA用。`WRITE_API_KEY` 必須。Macの自動同期専用（GPT Actionのスキーマには含めない）
- `POST /admin/sync/next` — NEXT投資ワード用。同じく `WRITE_API_KEY` 必須

### 5-3. 主な読み取りエンドポイント
- `GET /health` — 稼働確認（SAデータの件数・更新時刻。認証不要）
- `GET /snapshot`, `/company`, `/recent`, `/benchmarks` — STOCK ARENA用。`READ_API_KEY` 必須
- `GET /next/snapshot`, `/next/benchmarks` — NEXT投資ワード用。`READ_API_KEY` 必須

### 5-4. READ_API_KEY / WRITE_API_KEY の役割分離
`candidate_api/README.txt` に明記:
> READ_API_KEY はGPT Action専用。WRITE_API_KEY はMacの自動同期専用。
> WRITE用 /admin/sync はGPT ActionのOpenAPIスキーマには含めません。

つまり、Candidate Scout（GPT）側には読み取り専用キーしか渡らない設計。書き込みはMac側の
自動更新プロセスからのみ行われます。

### 5-5. 秘密情報の保存場所（値は非掲載）
- SA/NEXT共通の `cloud_api_url` と `cloud_write_key`:
  - `stock_arena_youtube_sync/stock_arena_sync_config.json`
  - `stock_arena_youtube_sync/next_investment_word_sync_config.json`
  （両ファイルとも同じCloud Run URL・同じWRITE鍵を使用）
- Cloud Run側の `READ_API_KEY` / `WRITE_API_KEY`（デプロイ時生成）:
  - `stock_arena_youtube_sync/candidate_api/cloud_api_credentials.txt`
  - `stock_arena_youtube_sync/candidate_api/.generated_keys`
- これらのファイルは `.gitignore` の `*.json` ルール等によりgit管理外、かつ
  `stock_arena_youtube_sync/` フォルダ自体がuntrackedのため、git履歴には含まれていません。

---

## 6. OAuth・認証

- **Google Cloud Project**: `candidate_api/deploy_cloud_run.sh` は `gcloud config get-value project` で
  現在設定中のプロジェクトを使う方式（プロジェクトIDはスクリプト内にハードコードされていない）。
- **有効化されているAPI**（README記載の初回セットアップ手順より）:
  YouTube Data API v3 / YouTube Analytics API / YouTube Reporting API
  （Cloud Run側は別途 `run.googleapis.com`, `cloudbuild.googleapis.com`, `artifactregistry.googleapis.com`,
  `storage.googleapis.com`, `iam.googleapis.com` を有効化）
- **OAuthクライアント種別**: Desktop app（`client_secret.json` として保存）
- **OAuth同意画面のステータスに関する重要な既知事項**（README明記）:
  > OAuth同意画面が External / Testing のままだと、Googleの仕様上、
  > 今回使うようなスコープのrefresh tokenが7日で失効します。
  > 長期無人運用する場合は、Google Cloud側でOAuthアプリを「In production」にしてください。
  → **再認証が頻発する場合、まずOAuth同意画面のPublishing statusを確認すること。**
- **トークンファイル**: `youtube_token.json`（SA/NEXT共有、読み取り専用スコープで再利用）。
  期限切れ時は `get_credentials()` が `creds.refresh(Request())` で自動更新を試みる。
  refresh_tokenごと失効した場合は `flow.run_local_server(port=0, ...)` がブラウザを開いて再認証を要求する
  （= ヘッドレス/リモート実行環境では手動介入が必要。ローカルMacでの対話的実行が前提）。
- 値そのもの（client_secret / token内容）は本文に記載しません。所在は上記の通りローカルファイルです。

---

## 7. 自動実行（launchd）

| 項目 | 内容 |
|---|---|
| plist名称 | `com.stockarena.youtube-sync` |
| plistパス | `~/Library/LaunchAgents/com.stockarena.youtube-sync.plist` |
| 実行対象 | `/Users/matsuoyoshihiro/v4/stock_arena_youtube_sync/run_youtube_sync_all.sh` |
| 実行間隔 | `StartInterval` 21600秒 = 約6時間ごと |
| RunAtLoad | true（ログイン/ロード時にも実行） |
| ラッパースクリプト | `run_youtube_sync_all.sh`（SA→NEXTの順に実行、詳細は3-2節） |
| ログ | `youtube_sync.log`（stdout）/ `youtube_sync_error.log`（stderr） |

**Macが停止・スリープしている場合の注意**:
- launchdの `StartInterval` はMacが起動していない/スリープ中は実行されません。
- 次回Macが起動・復帰した際、`RunAtLoad: true` により即座に1回実行されるため、長時間の
  停止があっても復帰後にキャッチアップされる設計です（ただしその間のYouTube Analyticsデータの
  「取りこぼし」自体は発生しません。APIは過去分もさかのぼって取得するため）。
- 完全に無人運用する場合、Macがスリープしないよう電源設定（`caffeinate` や省エネルギー設定）を
  別途検討する必要がありますが、**今回の調査範囲でその設定ファイルは確認していません（未確認）**。

---

## 8. 実行・確認方法

### 8-1. 手動実行
```bash
cd /Users/matsuoyoshihiro/v4/stock_arena_youtube_sync
./run_youtube_sync_all.sh
```
個別に実行する場合:
```bash
.venv_youtube_sync/bin/python update_stock_arena_youtube.py
.venv_youtube_sync/bin/python update_next_investment_word_youtube.py
```

### 8-2. 正常確認方法（ログ）
```bash
tail -40 /Users/matsuoyoshihiro/v4/stock_arena_youtube_sync/youtube_sync.log
```
正常時は末尾が以下のような形式になる:
```
===== STOCK ARENA sync exit code: 0 =====
...
===== NEXT投資ワード sync exit code: 0 =====
```
エラーがあれば `youtube_sync_error.log` を確認。

### 8-3. launchd登録確認
```bash
launchctl list | grep com.stockarena.youtube-sync
```
（終了コード列が `0` であれば直近実行は正常終了）

### 8-4. CSV件数確認
```bash
cd /Users/matsuoyoshihiro/v4/stock_arena_youtube_sync
wc -l stock_arena_history.csv stock_arena_youtube_performance.csv \
      next_investment_word_history.csv next_investment_word_youtube_performance.csv
```

### 8-5. Cloud health確認（秘密情報を表示しないコマンド）
```bash
curl -s https://stock-arena-candidate-api-cvlzhreyja-an.a.run.app/health
```
`READ_API_KEY`/`WRITE_API_KEY` は不要な公開エンドポイント。`history_count` / `performance_count` /
`updated_at` が返れば正常。

### 8-6. 読み取りAPI確認（キーが必要。値は環境変数等で渡し、画面に平文表示しないこと）
```bash
curl -s -H "Authorization: Bearer $READ_API_KEY" \
  "https://stock-arena-candidate-api-cvlzhreyja-an.a.run.app/snapshot?recent_limit=3"
```

---

## 9. 変更禁止・慎重に扱う領域

- **正常稼働中のPodcast/動画生成系（1-A章のスクリプト群）を、動画やAnalytics都合だけで変更しない。**
  `stock_arena_youtube_sync/` は完全に独立したシステムであり、動画生成パイプラインに手を入れる理由にはならない。
- **OAuthやCloud認証を不要に作り直さない。** 特に `youtube_token.json` を削除して再認証を強制すると、
  無人運用が一時的に止まる（ブラウザでの対話的同意が必要になるため）。
- **`stock_arena_baseline_performance.csv` を勝手に再生成・削除しない。** これは2026-08-13以前の
  インプレッション/CTR基準値の唯一の記録であり、失うと過去データの正確性が失われる（4章参照）。
- **SA/NEXTのデータ・CSV・reachキャッシュ・Cloud Storageオブジェクトを混在させない。** 両者は意図的に
  別ファイル・別エンドポイント・別GCSオブジェクトに分離されている設計（3-6, 5-1章参照）。
- **秘密鍵（client_secret, youtube_token, READ/WRITE_API_KEY, cloud_write_key）をソースコードや
  Markdownドキュメントへ埋め込まない。** 現状これらは正しくgit管理外になっている。
- **launchdの `com.stockarena.youtube-sync.plist` を変更する場合は、既存の6時間ごと自動運用への
  影響を必ず確認する。** `launchctl unload/load` が必要な変更は既存の自動実行を一時的に止めるため、
  実行タイミングに注意する。
- **`candidate_api/main.py` の既存SAエンドポイント（`/snapshot`, `/company`, `/recent`, `/benchmarks`,
  `/admin/sync`）の後方互換性を壊さない。** Candidate Scout GPT Actionが `openapi_action.yaml` の
  スキーマに依存しているため、レスポンス形式の変更はGPT側の動作に影響する。
- **`update_stock_arena_youtube.py` の番組識別ロジック（`is_stock_arena_video`）の優先順位を変えない。**
  特にbaseline維持判定を旧方式の判定より先に行っている順序は、既存動画の互換性維持に必須。
- **`.venv_youtube_sync` を安易に作り直さない。** Python 3.10.2固定の専用venvであり、
  `requirements_stock_arena_youtube_sync.txt` から再構築可能だが、launchd実行パスが
  `.venv_youtube_sync/bin/python` に固定されているため、venvの場所・名称を変えると自動実行が壊れる。

---

## 10. 既知の注意点・不具合履歴（実ログ・実コードから確認）

1. **YouTube Reporting APIの日付が `YYYYMMDD` 形式（ハイフンなし）で返り、SA更新が止まったことがある。**
   `youtube_sync_error.log` に実際のトレースバックが残っている:
   `ValueError: Invalid isoformat string: '20260810'`（`aggregate_reach()` 内の `date.fromisoformat()` で発生）。
   現在は `normalize_report_date()` により両スクリプトで対応済み（3-12章参照）。同様の日付形式ゆれが
   再発しないか、Reporting API側の仕様変更時は要注意。
2. **最新AnalyticsはYouTube Studio表示より遅れることがある。** `analytics_latest_complete_day()` は
   直近10日分を問い合わせて「確定済み最終日」を判定するロジックになっており、直近1〜2日分は
   まだAnalyticsに反映されていない前提で設計されている。
3. **空欄データを0と解釈してはいけない。** `Reachデータ状態` カラムが `取得待ち` の場合、
   インプレッション/CTRは意図的に空文字列（`""`）のまま出力される（`aggregate_reach()` /
   `aggregate_next_reach()`）。0という数値ではなく「未取得」を表す。
4. **Google APIの一時的な500エラーは個別動画だけ空欄になる場合がある。** 実際にログで確認済み:
   `youtube_sync.log` に `[WARN] Analytics取得失敗 BvnWdTTwSys: <HttpError 500 ... backendError>` の記録あり。
   コード上は動画単位でtry/exceptしており、1本の失敗が全体停止にはならない設計。
5. **動画IDの前後空白によるbaseline/重複判定の問題があった。** `fix_stock_arena_video_id_normalize.py`
   （適用済み、バックアップ: `update_stock_arena_youtube_before_video_id_normalize.py`）で対応済み。
   現在は `read_csv_dict()` とID取得処理の両方で `.strip()` を徹底している。
6. **NEXT投資ワードのReporting APIジョブは新規作成されない。** STOCK ARENA側が未実行のままNEXT単体を
   動かすと `channel_reach_basic_a1` ジョブが存在せず、`Reachデータ状態` が「ジョブ未作成」になる
   （3-4章参照）。運用上、`run_youtube_sync_all.sh` はSA→NEXTの順で実行することでこれを回避している。
7. **過去に段階的なパッチ適用の履歴がある。** `fix_stock_arena_*.py` 群と対応する
   `update_stock_arena_youtube_before_*_fix.py` バックアップ群は、baseline union・cloud sync追加・
   フィルタ修正・missing baseline fallback・video_id正規化の5つの修正が段階的に適用されてきた記録。
   通常は再実行不要（すでに `update_stock_arena_youtube.py` 本体に反映済み）。

---

## 11. 現在の未完了・今後予定（コード・設定から確認できる範囲のみ）

- **NEXTディレクターGPTへのAnalytics Action接続は保留。** `candidate_api/openapi_action.yaml` には
  SA用の4エンドポイントのみ定義されており、NEXT用エンドポイント（`/next/snapshot`, `/next/benchmarks`、
  実装済み）はまだOpenAPIスキーマに追加されていない＝GPT Action経由でNEXT側データを参照する接続は未設定。
- **COMPANY ARCHIVE向けのAnalytics取得は将来追加予定。** 現状 `｜COMPANY ARCHIVE` はSTOCK ARENA判定の
  除外条件としてのみ参照されており、COMPANY ARCHIVE専用の取得・保存スクリプトは存在しない。
- **NEXT側のテーマ分類・フック分類ロジックは未実装。** コード内コメントに明記されている通り、
  現段階では客観的な実績データの蓄積のみで、SA側にある `主テーマ`/`フック型` の推定ロジック
  (`infer_theme_and_hook`) はNEXT側には存在しない。
- **NEXT/COMPANY ARCHIVEの番組制作フロー自体は本ドキュメントの調査範囲外であり、詳細不明。**
  （このドキュメントはAnalytics基盤の現状記録が主目的であり、制作フロー改善の状況までは調査していません）
- 上記以外の新規TODOは本ドキュメント作成時点で推測を避けたため記載していません。

---

## 12. Codex作業時の基本ルール

1. **まず既存コードを読む。** 特に `update_stock_arena_youtube.py` / `update_next_investment_word_youtube.py`
   / `candidate_api/main.py` は本ドキュメントの要約より詳細な実装判断が書かれている。
2. **最小変更を心がける。** 大規模リファクタリングを勝手に行わない。
3. **正常稼働中の部分を壊さない。** 特にSA/NEXTの分離設計・baseline維持ロジック・launchd自動実行は
   意図的な設計であり、単純化・統合のための変更をしない。
4. **変更前後を検証する。** コードを変更した場合は、まず手動実行（8章）でSA/NEXT両方が正常終了するか、
   CSV件数が不自然に減っていないか、Cloud `/health` の `history_count`/`performance_count` が
   妥当な値かを確認すること。
5. **不明点は既存コード・設定・ログを確認する。** 推測で仕様を補わない（本ドキュメント自体もその方針で書かれている）。
6. **秘密情報を出力・記載しない。** `client_secret.json`, `youtube_token.json`,
   `stock_arena_sync_config.json` / `next_investment_word_sync_config.json` 内の
   `cloud_write_key`, `candidate_api/cloud_api_credentials.txt`, `candidate_api/.generated_keys` の中身を
   ターミナル出力・ログ・コミット・ドキュメントに書かない。

---

## 付録: 現在の稼働スナップショット（本ドキュメント作成時点）

- `stock_arena_history.csv` / `stock_arena_youtube_performance.csv`: 105本
- `stock_arena_baseline_performance.csv`: 101本（2026-08-13時点の基準値、baseline_cutoff設定と一致）
- `stock_arena_reach_daily.csv`: 2781日次レコード
- `next_investment_word_history.csv` / `next_investment_word_youtube_performance.csv`: 2本
- 直近の `run_youtube_sync_all.sh` 実行（2026-08-16 11:30 JST台）: SA exit code 0 / NEXT exit code 0（`youtube_sync.log` 末尾で確認）
- `launchctl list` 上で `com.stockarena.youtube-sync` はロード済み、直近終了コード0
- Cloud Run URL: `stock_arena_sync_config.json` / `next_investment_word_sync_config.json` の `cloud_api_url` を参照（本ドキュメントでは伏せない扱いだが、URL自体は秘密情報ではなく `--allow-unauthenticated` の公開サービスであるため記載可。ただし `cloud_write_key` は非掲載）
