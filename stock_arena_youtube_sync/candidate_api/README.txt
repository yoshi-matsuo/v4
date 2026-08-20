STOCK ARENA Candidate Scout Cloud API

Macで自動更新される2CSVをCloud Runへ同期し、
Candidate ScoutのGPT Actionから常に最新データを参照するためのAPIです。

構成:
Mac updater -> Cloud Run /admin/sync -> Cloud Storage
Candidate Scout GPT Action -> Cloud Run read endpoints

READ_API_KEY はGPT Action専用。
WRITE_API_KEY はMacの自動同期専用。
WRITE用 /admin/sync はGPT ActionのOpenAPIスキーマには含めません。
