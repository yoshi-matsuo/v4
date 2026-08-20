STOCK ARENA YouTubeデータ自動更新 - 初回設定

■ 今回の仕組み
・YouTube Data APIから新しい公開動画を自動取得
・YouTube Analytics APIから再生数、平均視聴時間、平均視聴率等を自動更新
・YouTube Reporting APIからインプレッション数とCTRを自動更新
・Macのlaunchdで約6時間ごとに自動実行
・8/8〜8/14の動画も、APIに存在する公開動画なら自動的に追加
・今後の新規動画も自動追加

■ 初回だけ必要な作業
1. Google Cloud Consoleでプロジェクトを1つ作る
2. 次の3 APIを有効にする
   - YouTube Data API v3
   - YouTube Analytics API
   - YouTube Reporting API
3. OAuth同意画面を設定する
4. OAuthクライアントを「Desktop app」で作成する
5. ダウンロードしたJSONを client_secret.json に名前変更
6. このフォルダに client_secret.json を置く
7. ターミナルでこのフォルダへ移動し、次を1回だけ実行

   chmod +x setup_stock_arena_youtube_sync.sh
   ./setup_stock_arena_youtube_sync.sh

Google認証画面がブラウザで1回開きます。
認証後は youtube_token.json が保存され、自動更新に使われます。

■ 重要
OAuth同意画面が External / Testing のままだと、Googleの仕様上、
今回使うようなスコープのrefresh tokenが7日で失効します。
長期無人運用する場合は、Google Cloud側でOAuthアプリを「In production」にしてください。

■ インプレッション / CTRについて
YouTube Reporting APIはジョブ作成後すぐには数字が出ません。
通常24〜48時間程度でレポートが生成され、作成時点から過去30日もバックフィルされます。
そのため最初の1〜2日は新しい動画のCTR欄が「取得待ち」になることがありますが、
その後の自動実行で埋まります。

■ 既存データ
現在の stock_arena_youtube_performance.csv は初回実行時に
stock_arena_baseline_performance.csv として自動保存します。
8/13までの既存インプレッション/CTRを基準値として保持し、
それ以降のReporting APIデータを自動的に加算します。

■ 出力
stock_arena_history.csv
stock_arena_youtube_performance.csv

■ ログ
youtube_sync.log
youtube_sync_error.log

■ Candidate Scoutとの接続について
このスクリプトでCSV自体は完全自動更新できます。
ただし、カスタムGPTの「Knowledge」に手でアップロードしたファイルは静的なため、
ローカルCSVが更新されてもKnowledge側へ自動反映はされません。

完全に手作業ゼロにするには次の段階で、
この最新データをWeb APIとして公開し、Candidate ScoutのGPT Actionから
直接取得する方式にします。
