#!/usr/bin/env python3
"""
fact_fetcher.py — 株価ファクト取得CLIツール
yfinance で最新データを取得し、LLMプロンプト用テキストを出力する。
"""

import datetime
import sys

try:
    import yfinance as yf
except ImportError:
    print("[ERROR] yfinance が未インストールです。pip3 install yfinance を実行してください。")
    sys.exit(1)


# ───────────────────────────────────────────────
# ユーティリティ
# ───────────────────────────────────────────────

def _is_jp_code(code: str) -> bool:
    """4桁数字なら日本株と判定する。"""
    return code.isdigit() and len(code) == 4


def _to_ticker(code: str) -> str:
    """yfinance に渡すティッカーを返す。日本株は '.T' を付与。"""
    return f"{code}.T" if _is_jp_code(code) else code.upper()


def _fmt_price(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:,.0f}"


def _fmt_market_cap(val) -> str:
    if val is None:
        return "N/A"
    oku = val / 1_0000_0000
    if oku >= 10000:
        return f"約{oku / 10000:.1f}兆円"
    return f"約{oku:.0f}億円"


def _fmt_per(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.1f}倍"


def _safe_get(info: dict, *keys):
    """複数キーを優先順に試し、最初に取得できた値を返す。"""
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return None


# ───────────────────────────────────────────────
# データ取得
# ───────────────────────────────────────────────

def fetch(code: str) -> dict:
    ticker_str = _to_ticker(code)
    ticker = yf.Ticker(ticker_str)

    # info（基本データ）
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    # 現在株価
    current_price = _safe_get(info, "currentPrice", "regularMarketPrice", "previousClose")

    # 52週レンジ
    week52_low  = _safe_get(info, "fiftyTwoWeekLow")
    week52_high = _safe_get(info, "fiftyTwoWeekHigh")

    # 時価総額
    market_cap = _safe_get(info, "marketCap")

    # PER（trailing → forward の順）
    per = _safe_get(info, "trailingPE", "forwardPE")

    # 年初来安値: 今年1月1日〜今日の最安値を history から計算
    ytd_low = None
    try:
        start_of_year = datetime.date(datetime.date.today().year, 1, 1).isoformat()
        hist = ticker.history(start=start_of_year)
        if not hist.empty:
            ytd_low = float(hist["Low"].min())
    except Exception:
        pass

    return {
        "current_price": current_price,
        "week52_low":    week52_low,
        "week52_high":   week52_high,
        "ytd_low":       ytd_low,
        "market_cap":    market_cap,
        "per":           per,
    }


# ───────────────────────────────────────────────
# 出力フォーマット
# ───────────────────────────────────────────────

def build_output(company: str, code: str, market: str, data: dict) -> str:
    price_unit = "円" if _is_jp_code(code) else "USD"

    lines = [
        f"【提供された最新ファクト：{company}（{code}）】",
        f"・銘柄：{company}（{market}）",
        f"・現在株価：{_fmt_price(data['current_price'])}{price_unit}",
        f"・52週レンジ：{_fmt_price(data['week52_low'])}{price_unit} - {_fmt_price(data['week52_high'])}{price_unit}",
        f"・年初来安値：{_fmt_price(data['ytd_low'])}{price_unit}",
        f"・時価総額：{_fmt_market_cap(data['market_cap'])}",
        f"・PER：{_fmt_per(data['per'])}",
        "・直近トピック：[※ここに最近のニュースやトピックを1〜2文で入力してください]",
        "・リスク：[※ここに懸念点や市場リスクを入力してください]",
    ]
    return "\n".join(lines)


# ───────────────────────────────────────────────
# メイン
# ───────────────────────────────────────────────

def main() -> None:
    print("── 株価ファクト取得ツール ──")

    code    = input("証券コード（例: 4422 / AAPL）: ").strip()
    if not code:
        print("[ERROR] 証券コードを入力してください。")
        sys.exit(1)

    company = input("企業名（例: VALUENEX）: ").strip() or code
    market  = input("上場市場（Enter で「東証グロース」）: ").strip() or "東証グロース"

    print(f"\nデータ取得中: {_to_ticker(code)} ...")
    try:
        data = fetch(code)
    except Exception as e:
        print(f"[ERROR] データ取得に失敗しました: {e}")
        sys.exit(1)

    print("\n" + "─" * 60)
    print(build_output(company, code, market, data))
    print("─" * 60 + "\n")


if __name__ == "__main__":
    main()
