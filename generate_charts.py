#!/usr/bin/env python3
"""
generate_charts.py — 株価・財務チャート全自動生成スクリプト
yfinance でデータ取得 → ダークモード PNG (1920×1080) を出力する。

出力先: outputs/assets
  multi_timeframe_chart.png
  financial_trend_bar.png
  competitor_heatmap.png

実行:
  python3 generate_charts.py
"""

import warnings
warnings.filterwarnings("ignore")

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import seaborn as sns

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API キー設定
#   Financial Modeling Prep (FMP): https://financialmodelingprep.com/
#   無料プランでも四半期財務データを取得可能（リクエスト制限あり）。
#   取得したキーをここに貼り付けてください。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FMP_API_KEY: str = "HmAYXHd3deSWrjuwhb4Rwol76FzBm5Bm"

# Mac 標準日本語フォントを直接設定（japanize_matplotlib 不要）
for _jp_font in ["Hiragino Sans", "AppleGothic"]:
    try:
        matplotlib.font_manager.findfont(_jp_font, fallback_to_default=False)
        matplotlib.rcParams["font.family"] = _jp_font
        break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False
import yfinance as yf

# ── 出力先 ──────────────────────────────────────────────────────────────────
HERE    = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "outputs", "assets", "charts")
os.makedirs(OUT_DIR, exist_ok=True)

# ── カラーパレット（ダークモード） ──────────────────────────────────────────
BG       = "#111111"
BG2      = "#1a1a1a"
BG3      = "#222222"
GRID_COL = "#2a2a2a"
TEXT     = "#e0e0e0"
TEXT_DIM = "#888888"
UP       = "#00e676"    # 上昇 / 正値
DOWN     = "#ff1744"    # 下落 / 負値（赤字）
ACCENT   = "#00b4d8"    # 水色アクセント
ACCENT2  = "#b388ff"    # 紫アクセント
MA5_C    = "#ffd600"    # 5日MA
MA25_C   = "#ff9100"    # 25日MA
MA75_C   = "#e040fb"    # 75日MA
MA120_C  = "#e040fb"    # 120日/週MA

FIG_W = 1920 / 100      # matplotlib はインチ単位 (dpi=100)
FIG_H = 1080 / 100
DPI   = 100


# ── 共通ユーティリティ ───────────────────────────────────────────────────────
def _apply_dark(fig: plt.Figure, axes) -> None:
    """Figure/Axes 全体にダークモードを適用する"""
    fig.patch.set_facecolor(BG)
    for ax in (axes if hasattr(axes, "__iter__") else [axes]):
        ax.set_facecolor(BG2)
        ax.tick_params(colors=TEXT_DIM, labelsize=10)
        ax.xaxis.label.set_color(TEXT_DIM)
        ax.yaxis.label.set_color(TEXT_DIM)
        ax.title.set_color(TEXT)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID_COL)
        ax.grid(color=GRID_COL, linewidth=0.6, linestyle="--", alpha=0.7)


def _safe(info: dict, *keys, default=None):
    """info dict から最初に見つかったキーの値を返す（None なら next へ）"""
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return default


def _ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def _fmt_yen(v, _):
    return f"¥{v:,.0f}"


def _fmt_oku(v, _):
    return f"{v:,.0f}億"


def _currency_info(info: dict) -> tuple[str, str]:
    """(価格記号, 単位テキスト) を返す。例: ('¥', '円') or ('$', 'ドル')"""
    c = info.get("currency", "JPY")
    if c == "JPY":
        return "¥", "円"
    if c == "USD":
        return "$", "ドル"
    return c + " ", c


# ═══════════════════════════════════════════════════════════════════════════════
# 1. multi_timeframe_chart — 日足3ヶ月 / 週足3年
# ═══════════════════════════════════════════════════════════════════════════════
def multi_timeframe_chart(ticker: str) -> str:
    """
    上段: 過去3ヶ月の日足チャート（MA25 / MA120）
    下段: 過去3年の週足チャート （MA25 / MA120）
    通貨は info["currency"] で自動判定（JPY=円 / USD=ドル）。
    """
    sym = yf.Ticker(ticker)
    info = sym.info
    name = _safe(info, "shortName", "longName", default=ticker)
    price_sym, price_unit = _currency_info(info)

    # リアルタイム最新価格の取得（429対策で fast_info を優先）
    try:
        realtime_price = sym.fast_info.last_price
    except Exception:
        realtime_price = None
    if not realtime_price:
        realtime_price = info.get("currentPrice") or info.get("regularMarketPrice")

    df_d = sym.history(period="3mo", interval="1d").dropna(subset=["Close"])
    df_w = sym.history(period="3y",  interval="1wk").dropna(subset=["Close"])

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    gs  = GridSpec(2, 1, figure=fig,
                   hspace=0.50, top=0.88, bottom=0.07, left=0.07, right=0.97)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    _apply_dark(fig, [ax1, ax2])

    def _plot_panel(ax, df, ma_specs, title, realtime_price=None):
        close = df["Close"].copy()
        dates = df.index
        if len(close) == 0:
            ax.text(0.5, 0.5, "データなし", transform=ax.transAxes,
                    ha="center", va="center", color=TEXT_DIM, fontsize=14)
            ax.set_title(title, fontsize=13, pad=8, color=TEXT)
            return

        # チャート線の終点を最新価格で補正
        if realtime_price:
            close.iloc[-1] = realtime_price
        last = realtime_price if realtime_price else close.iloc[-1]

        trend_col = UP if last >= close.iloc[0] else DOWN

        # 終値ライン + エリア塗り
        ax.fill_between(dates, close, close.min() * 0.975,
                        alpha=0.13, color=trend_col, zorder=1)
        ax.plot(dates, close, color=trend_col, linewidth=2.0,
                label="終値", zorder=3)

        # 移動平均（min_periods=1 で短期データでも描画）
        for n, col, lbl in ma_specs:
            ax.plot(dates, _ma(close, n), color=col, linewidth=1.3,
                    linestyle="--", alpha=0.9, label=lbl, zorder=2)

        # 最高値 / 最安値マーカー（大きく・太字）
        i_max = close.idxmax()
        i_min = close.idxmin()
        ax.scatter([i_max], [close[i_max]], color=UP,   s=80, zorder=5)
        ax.scatter([i_min], [close[i_min]], color=DOWN, s=80, zorder=5)
        ax.annotate(f"高 {price_sym}{close[i_max]:,.0f}",
                    (i_max, close[i_max]), textcoords="offset points",
                    xytext=(10, 10), color=UP,   fontsize=14, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=BG3,
                              edgecolor=UP, alpha=0.85))
        ax.annotate(f"安 {price_sym}{close[i_min]:,.0f}",
                    (i_min, close[i_min]), textcoords="offset points",
                    xytext=(10, -20), color=DOWN, fontsize=14, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=BG3,
                              edgecolor=DOWN, alpha=0.85))

        # 最新価格（リアルタイム）を右上に大きく表示
        ax.text(0.98, 0.92, f"{price_sym}{last:,.0f}",
                transform=ax.transAxes, ha="right", va="top",
                color=trend_col, fontsize=34, fontweight="bold", alpha=0.92,
                bbox=dict(boxstyle="round,pad=0.3", facecolor=BG3,
                          edgecolor=trend_col, alpha=0.6))

        ax.set_title(title, fontsize=13, pad=8, color=TEXT)
        ax.set_ylabel(f"株価（{price_unit}）", color=TEXT_DIM, fontsize=10)
        fmt_price = plt.FuncFormatter(lambda v, _: f"{price_sym}{v:,.0f}")
        ax.yaxis.set_major_formatter(fmt_price)
        ax.legend(loc="upper left", fontsize=9,
                  facecolor=BG3, edgecolor=GRID_COL, labelcolor=TEXT,
                  framealpha=0.85)

    ma_day  = [(25, MA25_C, "MA25"), (120, MA120_C, "MA120")]
    ma_week = [(25, MA25_C, "MA25"), (120, MA120_C, "MA120")]

    _plot_panel(ax1, df_d, ma_day,  "日足チャート（過去3ヶ月）", realtime_price)
    _plot_panel(ax2, df_w, ma_week, "週足チャート（過去3年）",   realtime_price)

    mc = _safe(info, "marketCap")
    mc_str = (f"時価総額: {price_sym}{mc / 1e8:,.0f}億"
              if mc else "時価総額: N/A")
    fig.suptitle(f"{name}  ({ticker})  |  マルチタイムフレームチャート    {mc_str}",
                 fontsize=16, color=TEXT, fontweight="bold", y=0.97)

    out = os.path.join(OUT_DIR, "multi_timeframe_chart.png")
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  ✓ saved: {out}")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 財務データ取得ユーティリティ — 三段構えハイブリッドフォールバック
#   第一候補 : FMP API (requests)
#   第二候補 : yahooquery
#   最終手段 : yfinance 年次データ（呼び出し元でフォールバック）
#
# 戻り値の共通フォーマット (yfinance 互換 DataFrame):
#   rows  = 指標名 ("Total Revenue", "Net Income" など)
#   cols  = pd.Timestamp 昇順（古い→新しい） ※ _row() が [::-1] で反転済み想定
# ═══════════════════════════════════════════════════════════════════════════════

def _fmp_quarterly(ticker: str, api_key: str) -> "pd.DataFrame | None":
    """
    FMP API から四半期損益データを取得し、yfinance 互換 DataFrame を返す。
    失敗・空データの場合は None を返す。
    """
    import requests as _req

    url = (
        "https://financialmodelingprep.com/api/v3/income-statement/"
        f"{ticker}?period=quarter&limit=13&apikey={api_key}"
    )
    try:
        resp = _req.get(url, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [WARN] {ticker}: [FMP] リクエスト失敗: {e}")
        return None

    # エラーレスポンス or 空リストのチェック
    if not data or not isinstance(data, list):
        msg = str(data)[:120] if data else "空レスポンス"
        print(f"  [WARN] {ticker}: [FMP] 有効データなし ({msg})")
        return None
    if isinstance(data, dict) and "Error Message" in data:
        print(f"  [WARN] {ticker}: [FMP] APIエラー: {data['Error Message']}")
        return None

    records: dict[pd.Timestamp, dict] = {}
    for entry in data:
        try:
            ts  = pd.Timestamp(entry["date"])
            records[ts] = {
                "Total Revenue": entry.get("revenue"),
                "Net Income":    entry.get("netIncome"),
            }
        except Exception:
            continue

    if not records:
        print(f"  [WARN] {ticker}: [FMP] パース後データなし")
        return None

    # dates × metrics → transpose → metrics × dates（新しい順）
    df = pd.DataFrame(records).T
    df = df.sort_index(ascending=False)  # 新しい順（yfinance 互換）
    df = df.T
    df.index.name   = None
    df.columns.name = None
    return df


def _yq_quarterly(ticker: str) -> "pd.DataFrame | None":
    """
    yahooquery から四半期損益データ（periodType == '3M'）を取得し、
    yfinance 互換 DataFrame を返す。失敗・空データの場合は None を返す。
    """
    try:
        from yahooquery import Ticker as _YQTicker
    except ImportError:
        print("  [WARN] yahooquery 未インストール: pip install yahooquery")
        return None

    try:
        stmt = _YQTicker(ticker).income_statement(frequency="q")
    except Exception as e:
        print(f"  [WARN] {ticker}: [yahooquery] 取得例外: {e}")
        return None

    if stmt is None or isinstance(stmt, str):
        print(f"  [WARN] {ticker}: [yahooquery] レスポンスエラー: {stmt}")
        return None
    if isinstance(stmt, pd.DataFrame) and stmt.empty:
        return None

    try:
        # periodType == '3M' の行のみ使用（TTM / 12M を除外）
        if "periodType" in stmt.columns:
            stmt = stmt[stmt["periodType"] == "3M"].copy()
        if stmt.empty:
            print(f"  [DEBUG] {ticker}: [yahooquery] 3M四半期行なし")
            return None

        # asOfDate を DatetimeIndex に昇格
        if "asOfDate" in stmt.columns:
            stmt = stmt.set_index("asOfDate")
        stmt.index = pd.DatetimeIndex(stmt.index)
        stmt = stmt.sort_index(ascending=False)  # 新しい順

        # 売上高: TotalRevenue → OperatingRevenue の順で探す
        rev_col = next(
            (c for c in ["TotalRevenue", "OperatingRevenue"]
             if c in stmt.columns and stmt[c].notna().any()),
            None,
        )
        # 純利益: NetIncome → NetIncomeCommonStockholders の順で探す
        net_col = next(
            (c for c in ["NetIncome", "NetIncomeCommonStockholders",
                         "NetIncomeFromContinuingOperationNetMinorityInterest"]
             if c in stmt.columns and stmt[c].notna().any()),
            None,
        )

        if rev_col is None and net_col is None:
            print(f"  [DEBUG] {ticker}: [yahooquery] 売上高・純利益列なし。"
                  f"利用可能な列: {list(stmt.columns)[:8]}")
            return None

        rows: dict[str, pd.Series] = {}
        if rev_col:
            rows["Total Revenue"] = stmt[rev_col]
        if net_col:
            rows["Net Income"] = stmt[net_col]

        df = pd.DataFrame(rows).T
        df.columns.name = None
        df.index.name   = None
        return df

    except Exception as e:
        print(f"  [WARN] {ticker}: [yahooquery] DataFrame 変換失敗: {e}")
        return None


def _fetch_quarterly_fin(
    ticker: str,
) -> "tuple[pd.DataFrame, bool, str]":
    """
    三段構えで四半期財務 DataFrame を取得する。

    Returns
    -------
    (fin_df, is_quarterly, source_label)
      fin_df       : rows=指標名, cols=Timestamp(新しい順) ― yfinance 互換
      is_quarterly : False = 全四半期ソース失敗 → 呼び出し元で年次フォールバック
      source_label : "FMP" | "yahooquery" | "yfinance" | "annual"
    """
    MIN_COLS = 2  # 最低でも2四半期なければ「取得失敗」扱い

    # ── 第一候補: FMP API ──────────────────────────────────────────────────────
    if FMP_API_KEY and FMP_API_KEY != "YOUR_API_KEY_HERE":
        df = _fmp_quarterly(ticker, FMP_API_KEY)
        if df is not None and len(df.columns) >= MIN_COLS:
            print(f"  [INFO] {ticker}: [FMP] 四半期データ取得成功"
                  f" (列数={len(df.columns)})")
            return df, True, "FMP"
        print(f"  [WARN] {ticker}: [FMP] データ不足または失敗"
              f" → yahooquery にフォールバック")
    else:
        print(f"  [INFO] {ticker}: FMP_API_KEY 未設定"
              f" → yahooquery を試行")

    # ── 第二候補: yahooquery ───────────────────────────────────────────────────
    df = _yq_quarterly(ticker)
    if df is not None and len(df.columns) >= MIN_COLS:
        print(f"  [INFO] {ticker}: [yahooquery] 四半期データ取得成功"
              f" (列数={len(df.columns)})")
        return df, True, "yahooquery"
    print(f"  [WARN] {ticker}: [yahooquery] データ不足または失敗"
          f" → yfinance quarterly にフォールバック")

    # ── 第三候補: yfinance quarterly ──────────────────────────────────────────
    sym = yf.Ticker(ticker)
    for _attr in ("quarterly_financials", "quarterly_income_stmt"):
        try:
            df = getattr(sym, _attr)
            if df is not None and not df.empty:
                print(f"  [INFO] {ticker}: [yfinance] 四半期データ取得"
                      f" (列数={len(df.columns)})")
                return df, True, "yfinance"
        except Exception:
            continue

    # 全四半期ソース失敗 → 年次フォールバック指示
    print(f"  [WARN] {ticker}: 全ての四半期ソース失敗"
          f" → 年次（Annual）データにフォールバック")
    return pd.DataFrame(), False, "annual"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. financial_trend_bar — 財務トレンド棒グラフ（四半期別・YoY付き）
# ═══════════════════════════════════════════════════════════════════════════════
def financial_trend_bar(ticker: str) -> str:
    """
    売上高 / 純利益 の四半期推移（直近12四半期）を描画する。
    ・四半期優先 → 取得不可の場合は年次にフォールバック
    ・会計年度ごとに背景バンド + 区切り破線 + 年度ラベルを描画（参考: 学情スタイル）
    ・棒の真上に金額ラベル（大きめフォント）
    ・棒の真下 x 軸に前年同期比（YoY）を色分け表示
    ・ダークモード / 右上に実行日を表示
    """
    from datetime import date as date_cls
    from matplotlib.transforms import blended_transform_factory

    sym  = yf.Ticker(ticker)
    info = sym.info
    name = _safe(info, "shortName", "longName", default=ticker)
    _, price_unit = _currency_info(info)
    unit_label = f"億{'ドル' if price_unit == 'ドル' else '円'}"

    # ── 候補ラベル定義（大文字小文字・表記揺れ対応） ─────────────────────────
    REV_CANDIDATES = [
        "Total Revenue", "Revenue", "Operating Revenue",
        "Total Operating Revenue", "Net Sales",
        "Sales Revenue", "Revenues", "Net Revenue",
        "Sales And Services Revenue", "Service Revenue",
    ]
    NET_CANDIDATES = [
        "Net Income", "Net Income Common Stockholders",
        "Net Income Continuous Operations",
        "Net Income attributable to owners of parent",
        "Net Income From Continuing Operation Net Minority Interest",
        "Normalized Income", "Net Income Including Noncontrolling Interests",
        "Net Income Applicable To Common Shares",
    ]
    # キーワードフォールバック（上記で一致しない場合の部分一致）
    REV_KEYWORDS = ["revenue", "sales", "turnover"]
    NET_KEYWORDS = ["net income", "net profit", "profit attributable"]

    def _row(fin: pd.DataFrame, candidates: list[str],
             fallback_keywords: list[str] | None = None):
        """
        候補ラベルで完全一致検索 → なければキーワード部分一致 → どちらも失敗時は
        利用可能なラベルを DEBUG 出力して None を返す。
        fin の列は「新しい順」を想定し、最大 13 列を取って反転（古い→新しい）する。
        """
        if fin.empty:
            return None
        fin_w = fin.iloc[:, :13].iloc[:, ::-1]
        idx_lower = {str(i).lower(): i for i in fin_w.index}

        for c in candidates:
            actual = idx_lower.get(c.lower())
            if actual is not None:
                row = fin_w.loc[actual].dropna()
                if not row.empty:
                    print(f"  [INFO] {ticker}: 指標 '{actual}' で一致")
                    return row

        if fallback_keywords:
            for kw in fallback_keywords:
                for key_lower, actual in idx_lower.items():
                    if kw in key_lower:
                        row = fin_w.loc[actual].dropna()
                        if not row.empty:
                            print(f"  [INFO] {ticker}: キーワード '{kw}' でフォールバック"
                                  f" → '{actual}'")
                            return row

        print(f"  [DEBUG] {ticker}: 候補ラベル未一致。"
              f"利用可能なラベル: {list(fin_w.index)}")
        return None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # データ取得: 三段構えハイブリッドフォールバック
    #   FMP API → yahooquery → yfinance quarterly → yfinance annual
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    fin_q, is_quarterly, data_source = _fetch_quarterly_fin(ticker)

    rev_row = _row(fin_q, REV_CANDIDATES, fallback_keywords=REV_KEYWORDS)
    net_row = _row(fin_q, NET_CANDIDATES, fallback_keywords=NET_KEYWORDS)

    # ── 年次フォールバック（四半期ソース全滅 or 行マッチなし） ─────────────────
    if not is_quarterly or (rev_row is None and net_row is None):
        is_quarterly = False
        data_source  = "yfinance-annual"
        fin_a        = pd.DataFrame()
        for _attr in ("financials", "income_stmt"):
            try:
                _df = getattr(sym, _attr)
                if _df is not None and not _df.empty:
                    fin_a = _df
                    break
            except Exception:
                continue

        if fin_a.empty:
            print(f"  [ERROR] {ticker}: 年次データも取得できませんでした → スキップ")
            return ""

        print(f"  [INFO] {ticker}: [yfinance-annual] 年次データ取得"
              f" (列数={len(fin_a.columns)})")
        rev_row = _row(fin_a, REV_CANDIDATES, fallback_keywords=REV_KEYWORDS)
        net_row = _row(fin_a, NET_CANDIDATES, fallback_keywords=NET_KEYWORDS)

    # ── 最終チェック ──────────────────────────────────────────────────────────
    if rev_row is None and net_row is None:
        print(f"  [ERROR] {ticker}: 全データソースから売上高・純利益を取得できませんでした"
              f" → スキップ")
        return ""
    if rev_row is None:
        print(f"  [WARN] {ticker}: 売上高行が見つかりません → 純利益のみで描画します")
    if net_row is None:
        print(f"  [WARN] {ticker}: 純利益行が見つかりません → 売上高のみで描画します")

    # 年次データの列から決算月を検出
    af = sym.financials if not sym.financials.empty else sym.income_stmt
    fy_end_month = af.columns[0].month if not af.empty else 3

    def _to_億(row, label):
        return (row / 1e8).rename(label) if row is not None else None

    # Timestamp インデックスのまま結合（FY 判定に使う）
    df_raw = pd.concat(
        [s for s in [_to_億(rev_row, "売上高"), _to_億(net_row, "純利益")] if s is not None],
        axis=1,
    ).sort_index()

    # NaN クリーニング: 全列が NaN の行（期間）を除去して有効データのみグラフ化
    df_raw = df_raw.dropna(how="all")
    if df_raw.empty:
        print(f"  [ERROR] {ticker}: NaN 除去後にデータが残りませんでした → スキップ")
        return ""

    # ── 会計年度・四半期番号の算出 ────────────────────────────────────────────
    def _fy_q(ts):
        """(fy_label: '24年度', q: 1-4) を返す"""
        m, y = ts.month, ts.year
        fy_year = y if m <= fy_end_month else y + 1
        fy_start = (fy_end_month % 12) + 1
        elapsed  = (m - fy_start) % 12
        return f"{fy_year % 100:02d}年度", elapsed // 3 + 1

    # ── YoY をスライス前（全取得データ）に計算 → 表示9期すべてにYoYを付与 ──
    yoy_step = 4 if is_quarterly else 1
    x_labels_full = [f"{_fy_q(ts)[0]}{_fy_q(ts)[1]}期" for ts in df_raw.index]
    df_full = df_raw.copy()
    df_full.index = x_labels_full

    yoy_data: dict[str, dict[str, float]] = {}
    for col in df_full.columns:
        yoy_col: dict[str, float] = {}
        for i, lbl in enumerate(x_labels_full):
            if i < yoy_step:
                continue
            curr, prev = df_full[col].iloc[i], df_full[col].iloc[i - yoy_step]
            if pd.notna(curr) and pd.notna(prev) and prev != 0:
                yoy_col[lbl] = (curr - prev) / abs(prev) * 100
        yoy_data[col] = yoy_col

    # 表示は最新 9 期分に絞る（YoY は計算済み）
    df_raw = df_raw.iloc[-9:]
    print(f"  [INFO] {ticker}: グラフ化対象 {len(df_raw)} 期分")

    ts_list   = list(df_raw.index)
    fy_labels = [_fy_q(ts)[0] for ts in ts_list]
    x_labels  = [f"{_fy_q(ts)[0]}{_fy_q(ts)[1]}期" for ts in ts_list]

    df        = df_raw.copy()
    df.index  = x_labels

    # ── FY グループ ───────────────────────────────────────────────────────────
    unique_fys: list[str] = list(dict.fromkeys(fy_labels))
    fy_groups: dict[str, list[int]] = {}
    for i, fy in enumerate(fy_labels):
        fy_groups.setdefault(fy, []).append(i)

    # ── 描画準備 ──────────────────────────────────────────────────────────────
    n_dates = len(x_labels)
    n_cols  = len(df.columns)
    x       = np.arange(n_dates)
    bar_w   = 0.65 / max(n_cols, 1)
    # 棒数が多いほどラベルフォントを小さくして重なりを防ぐ
    label_fs = max(8, 13 - max(0, n_dates - 4))

    # 値フォーマット: 小さい値は小数1桁、大きい値は整数
    def _fmt_val(v: float) -> str:
        return f"{v:.1f}" if abs(v) < 100 else f"{v:,.0f}"

    COL_PALETTE = {"売上高": ACCENT, "純利益": UP}
    # 会計年度ごとの背景バンド色（非常に淡いダーク色）
    BAND_COLS   = ["#1c1900", "#001c1a", "#1a001c", "#001a08"]

    out = os.path.join(OUT_DIR, "financial_trend_bar.png")
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H), dpi=DPI)
    try:
        _apply_dark(fig, [ax])
        # 下部: YoY + 期ラベル / 上部: 年度ラベル + タイトル のために余白確保
        fig.subplots_adjust(bottom=0.26, top=0.86, left=0.09, right=0.96)

        # ── 会計年度 背景バンド & 区切り破線（四半期データのみ） ─────────────
        if is_quarterly:
            for fi, fy in enumerate(unique_fys):
                idxs = fy_groups[fy]
                ax.axvspan(idxs[0] - 0.45, idxs[-1] + 0.45,
                           color=BAND_COLS[fi % len(BAND_COLS)],
                           alpha=1.0, zorder=0)
            for fi in range(len(unique_fys) - 1):
                sep_x = fy_groups[unique_fys[fi]][-1] + 0.5
                ax.axvline(sep_x, color="#555555", linewidth=1.2,
                           linestyle="--", alpha=0.7, zorder=1)

        # ── 棒グラフ ──────────────────────────────────────────────────────────
        has_negative = False
        for i, col in enumerate(df.columns):
            vals     = df[col].values.astype(float)
            offset   = (i - (n_cols - 1) / 2) * bar_w
            base_col = COL_PALETTE.get(col, ACCENT)
            bar_cols = [DOWN if (not np.isnan(v) and v < 0) else base_col for v in vals]

            bars = ax.bar(x + offset, np.nan_to_num(vals, nan=0.0),
                          bar_w * 0.85, color=bar_cols, label=col,
                          zorder=3, edgecolor=BG, linewidth=0.5)

            for bar, val in zip(bars, vals):
                if np.isnan(val):
                    continue
                if val < 0:
                    has_negative = True
                bx = bar.get_x() + bar.get_width() / 2
                if val >= 0:
                    anchor_y, va, dy = bar.get_y() + bar.get_height(), "bottom", 4
                else:
                    anchor_y, va, dy = bar.get_y(), "top", -4
                ax.annotate(f"{_fmt_val(val)}{unit_label}",
                            xy=(bx, anchor_y), xytext=(0, dy),
                            textcoords="offset points",
                            ha="center", va=va,
                            fontsize=label_fs, fontweight="bold",
                            color=TEXT, zorder=5)

        # ゼロライン
        ax.axhline(0, color=TEXT_DIM, linewidth=1.0, zorder=2)

        # y 上限を拡張して上部ラベルが棒に被らないようにする
        ylo, yhi = ax.get_ylim()
        margin = yhi * 1.20 if yhi != 0 else 1.0
        ax.set_ylim(ylo, margin)
        ylo2, _ = ax.get_ylim()
        if ylo2 < 0:
            ax.axhspan(ylo2, 0, color=DOWN, alpha=0.04, zorder=1)

        # ── x 軸: デフォルト非表示 → 手動で YoY & 期ラベルを描画 ─────────────
        ax.set_xticks(x)
        ax.set_xticklabels([])
        ax.tick_params(axis="x", length=0)

        trans = blended_transform_factory(ax.transData, ax.transAxes)

        # 棒数が多い場合はラベルを縮小・傾けて重なりを防ぐ
        x_fs  = 8  if n_dates > 4 else 10
        x_rot = 30 if n_dates > 4 else 0
        x_ha  = "right" if n_dates > 4 else "center"
        yoy_fs = 9 if n_dates > 4 else 10

        for xi, lbl in enumerate(x_labels):
            # YoY テキスト（各棒の x 中心位置、x 軸直下）
            for ci, col in enumerate(df.columns):
                yoy = yoy_data[col].get(lbl)
                if yoy is None:
                    continue
                col_offset = (ci - (n_cols - 1) / 2) * bar_w
                yoy_color  = "#00c8b0" if yoy >= 0 else "#ff4455"
                sign       = "+" if yoy >= 0 else ""
                ax.text(xi + col_offset, -0.045,
                        f"{sign}{yoy:.1f}%",
                        ha="center", va="top", transform=trans,
                        fontsize=yoy_fs, fontweight="bold",
                        color=yoy_color, clip_on=False)

            # 四半期ラベル（グループ中央・YoY の下）
            ax.text(xi, -0.115, lbl,
                    ha=x_ha, va="top", transform=trans,
                    fontsize=x_fs, color=TEXT_DIM, clip_on=False,
                    rotation=x_rot)

        # "(前年同期比)" 行ヘッダ
        ax.text(0.0, -0.048, "(前年同期比)",
                ha="right", va="top", transform=ax.transAxes,
                fontsize=9, color=TEXT_DIM, clip_on=False)

        # ── 会計年度ラベル（バンド上部、棒グラフ上方） ───────────────────────
        if is_quarterly:
            for fy in unique_fys:
                cx = float(np.mean(fy_groups[fy]))
                ax.text(cx, 1.012, fy,
                        ha="center", va="bottom", transform=trans,
                        fontsize=13, fontweight="bold",
                        color=TEXT_DIM, clip_on=False)

        # ── 軸・凡例 ──────────────────────────────────────────────────────────
        ax.set_ylabel("金額（億円）", color=TEXT_DIM, fontsize=13)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(_fmt_oku))
        ax.tick_params(axis="y", labelsize=13, colors=TEXT_DIM)

        ax.legend(loc="upper left", fontsize=13,
                  facecolor=BG3, edgecolor=GRID_COL, labelcolor=TEXT,
                  framealpha=0.9, borderpad=0.8)

        if has_negative:
            ax.text(0.01, 0.03, "▼ = 赤字（マイナス値）",
                    transform=ax.transAxes, fontsize=11, color=DOWN, alpha=0.85)

        # 実行日（右上）
        today    = date_cls.today()
        date_str = f"{today.year}年{today.month:02d}月{today.day:02d}日現在"
        ax.text(0.99, 1.018, date_str,
                transform=ax.transAxes, ha="right", va="bottom",
                fontsize=12, color=TEXT_DIM, clip_on=False)

        freq_label = "四半期別" if is_quarterly else "年度別"
        fig.suptitle(
            f"{name}  ({ticker})  |  財務トレンド（{freq_label}）"
            f"  ─  データソース: {data_source}",
            fontsize=18, color=TEXT, fontweight="bold", y=0.97,
        )

    except Exception as e:
        # 描画中に予期しないエラーが発生しても、それまでに描けた内容で保存する
        print(f"  [WARN] {ticker}: 描画中にエラーが発生しました ({e})"
              f" → 途中状態で保存を試みます")

    finally:
        fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        print(f"  ✓ saved: {out}")

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 3. competitor_heatmap — 競合比較ヒートマップ
# ═══════════════════════════════════════════════════════════════════════════════
def competitor_heatmap(main_ticker: str, peer_tickers: list[str]) -> str:
    """
    複数銘柄の主要指標を列方向に正規化し、RdYlGn カラーマップで比較する。
    欠損値は「N/A」と表示してスキップ。
    """
    all_tickers = [main_ticker] + peer_tickers

    # ── 銘柄名の折返しヘルパー ────────────────────────────────────────────────
    def _wrap_label(name: str, sym_str: str, max_chars: int = 13) -> str:
        """長い銘柄名を単語単位で改行し、ティッカーを最終行に追加する"""
        words = name.split()
        lines, cur = [], ""
        for w in words:
            test = f"{cur} {w}".strip()
            if cur and len(test) > max_chars:
                lines.append(cur)
                cur = w
            else:
                cur = test
        if cur:
            lines.append(cur)
        lines.append(f"({sym_str})")
        return "\n".join(lines)

    # ── 指標定義（列順: 粗利率→52週高値比 に入れ替え） ───────────────────────
    # (表示名, 抽出関数(info) → float|None, 単位変換係数, 高い方が良いか, 通貨単位付与か)
    METRIC_DEFS: list[tuple[str, callable, float, bool, bool]] = [
        ("時価総額\n(億)",
         lambda info: _safe(info, "marketCap"),
         1e-8, True, True),
        ("PBR\n(倍)",
         lambda info: _safe(info, "priceToBook"),
         1.0, False, False),
        ("PER\n(倍)",
         lambda info: _safe(info, "trailingPE", "forwardPE"),
         1.0, False, False),
        ("売上高\n(億)",
         lambda info: _safe(info, "totalRevenue"),
         1e-8, True, True),
        ("粗利率\n(%)",                                   # ← 52週高値比より前へ
         lambda info: (
             round(_safe(info, "grossProfits", default=0)
                   / _safe(info, "totalRevenue", default=1) * 100, 1)
             if _safe(info, "totalRevenue") and _safe(info, "totalRevenue") != 0
             else None
         ),
         1.0, True, False),
        ("52週\n高値比(%)",                               # ← 粗利率より後へ
         lambda info: (
             round(_safe(info, "currentPrice", "regularMarketPrice", default=0)
                   / _safe(info, "fiftyTwoWeekHigh", default=1) * 100, 1)
             if _safe(info, "fiftyTwoWeekHigh") else None
         ),
         1.0, True, False),
    ]

    metric_labels = [m[0] for m in METRIC_DEFS]

    # ── データ収集 ────────────────────────────────────────────────────────────
    row_labels = []
    raw_vals   = []    # list[list[float | None]]
    currencies = []    # 各銘柄の通貨コード ("JPY" / "USD" 等)

    for sym_str in all_tickers:
        try:
            sym  = yf.Ticker(sym_str)
            info = sym.info
            if not info or info.get("quoteType") is None:
                print(f"  [WARN] {sym_str}: 有効な銘柄情報なし (404等) → ヒートマップから除外")
                continue
        except Exception as e:
            print(f"  [WARN] {sym_str}: 取得例外 ({e}) → ヒートマップから除外")
            continue

        name  = _safe(info, "shortName", "longName", default=sym_str)
        label = _wrap_label(name, sym_str)
        row_labels.append(label)
        currencies.append(info.get("currency", "JPY"))

        row = []
        for _, fn, scale, _, _ in METRIC_DEFS:
            try:
                v = fn(info)
                row.append(round(v * scale, 2) if v is not None else None)
            except Exception:
                row.append(None)

        raw_vals.append(row)
        print(f"    {sym_str}: {dict(zip(metric_labels, row))}")

    if not row_labels:
        print(f"  [ERROR] competitor_heatmap: 有効な銘柄データが1社も取得できませんでした → スキップ")
        return ""

    df_raw = pd.DataFrame(raw_vals, index=row_labels, columns=metric_labels)

    # ── 列ごとに min-max 正規化 ────────────────────────────────────────────────
    df_num    = df_raw.apply(pd.to_numeric, errors="coerce")
    df_scaled = pd.DataFrame(index=df_raw.index, columns=df_raw.columns,
                              dtype=float)

    for col_idx, (_, _, _, higher_is_better, _) in enumerate(METRIC_DEFS):
        col  = metric_labels[col_idx]
        vals = df_num[col]
        vmin, vmax = vals.min(), vals.max()
        if pd.notna(vmin) and pd.notna(vmax) and vmax > vmin:
            normed = (vals - vmin) / (vmax - vmin)
        else:
            normed = pd.Series(0.5, index=vals.index)
        if not higher_is_better:
            normed = 1.0 - normed
        df_scaled[col] = normed.fillna(0.5)

    # ── アノテーション（生値 + 通貨単位） ────────────────────────────────────
    annot = pd.DataFrame(index=df_raw.index, columns=df_raw.columns, dtype=object)
    for col_idx, (_, _, _, _, use_currency) in enumerate(METRIC_DEFS):
        col = metric_labels[col_idx]
        for row_idx, idx in enumerate(df_raw.index):
            v = df_num.loc[idx, col]
            if pd.notna(v):
                if use_currency:
                    cur = currencies[row_idx]
                    suffix = "億ドル" if cur != "JPY" else "億円"
                    annot.loc[idx, col] = f"{v:,.1f}\n{suffix}"
                else:
                    annot.loc[idx, col] = f"{v:,.1f}"
            else:
                annot.loc[idx, col] = "N/A"

    # ── 描画 ─────────────────────────────────────────────────────────────────
    n_rows = len(row_labels)
    n_cols = len(metric_labels)

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H), dpi=DPI)
    _apply_dark(fig, [ax])

    sns.heatmap(
        df_scaled.astype(float),
        annot=annot,
        fmt="",
        cmap="RdYlGn",
        linewidths=3.0,          # 行間を広げて視覚的分離を強調
        linecolor="#1e1e1e",
        ax=ax,
        cbar_kws={"shrink": 0.55, "pad": 0.02},
        annot_kws={"size": 12, "weight": "bold", "color": "#111111"},
        vmin=0.0, vmax=1.0,
    )

    # カラーバースタイル
    cbar = ax.collections[0].colorbar
    cbar.ax.tick_params(colors=TEXT_DIM, labelsize=9)
    cbar.set_label("相対スコア  (緑=優位 / 赤=劣位)  ※列内 min-max 正規化",
                   color=TEXT_DIM, fontsize=9, labelpad=8)

    # 軸ラベル（銘柄名は折返し済みなので rotation=0 で表示）
    ax.set_xticklabels(ax.get_xticklabels(),
                       rotation=0, ha="center", fontsize=13, color=TEXT)
    ax.set_yticklabels(ax.get_yticklabels(),
                       rotation=0, ha="right", fontsize=11, color=TEXT,
                       linespacing=1.4)
    ax.tick_params(left=False, bottom=False)

    # メイン銘柄（先頭行）を枠線で強調
    ax.add_patch(mpatches.FancyBboxPatch(
        (0, 0), n_cols, 1,
        boxstyle="square,pad=0",
        linewidth=3.0, edgecolor=ACCENT, facecolor="none",
        transform=ax.transData, zorder=10,
    ))

    ax.set_xlabel("")
    ax.set_ylabel("")

    # タイトル: メイン銘柄名を大きく・説明文は削除
    main_info = yf.Ticker(main_ticker).info
    main_name = _safe(main_info, "shortName", "longName", default=main_ticker)
    fig.suptitle(
        f"競合比較ヒートマップ\n基準銘柄: {main_name}  ({main_ticker})",
        fontsize=26, color=TEXT, fontweight="bold", y=0.99,
    )

    out = os.path.join(OUT_DIR, "competitor_heatmap.png")
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  ✓ saved: {out}")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 銘柄ごとの競合リスト定義
# ═══════════════════════════════════════════════════════════════════════════════
# キー: メイン銘柄ティッカー / 値: 競合銘柄リスト
PEER_MAP: dict[str, list[str]] = {
    "6702.T": ["6701.T", "9613.T", "6501.T"],   # 富士通 → NEC / NTTデータ / 日立
    "6701.T": ["6702.T", "9613.T", "6501.T"],   # NEC   → 富士通 / NTTデータ / 日立
    "6501.T": ["6702.T", "6701.T", "9613.T"],   # 日立  → 富士通 / NEC / NTTデータ
    "9613.T": ["6702.T", "6701.T", "6501.T"],   # NTTデータ → 富士通 / NEC / 日立
    "7203.T": ["7267.T", "7269.T", "7270.T"],   # トヨタ → ホンダ / スズキ / SUBARU
    "7267.T": ["7203.T", "7269.T", "7270.T"],   # ホンダ → トヨタ / スズキ / SUBARU
    "6758.T": ["6752.T", "6753.T", "6954.T"],   # ソニー → パナソニック / シャープ / ファナック
    "9984.T": ["9432.T", "9433.T", "4689.T"],   # ソフトバンクG → NTT / KDDI / Zホールディングス
    "8306.T": ["8316.T", "8411.T", "8309.T"],   # 三菱UFJ → 三井住友 / みずほ / 三井住友トラスト
    "4563.T": ["4587.T", "4592.T", "4568.T"],   # アンジェス → PeptiDream / サンバイオ / 第一三共
    "4564.T": ["4587.T", "4563.T", "4592.T"],   # OTS → PeptiDream / アンジェス / サンバイオ
    "9166.T": ["4680.T", "2157.T", "7832.T"],   # GENDA → ラウンドワン / コシダカHD / バンダイナムコ
    "8154.T": ["3132.T", "2760.T", "3156.T"],   # 加賀電子 → マクニカHD / 東京エレクトロンデバイス / レスターHD
}


def _resolve_peers(main_ticker: str, cli_peers: list[str]) -> list[str]:
    """
    競合リストを決定する。
    1. CLI で競合が明示指定されていればそれを優先。
    2. なければ PEER_MAP を引く。
    3. PEER_MAP に未登録の場合は警告を出して空リストを返す
       （無関係な大手銘柄との誤比較を防ぐため、デフォルト競合は廃止）。
    """
    if cli_peers:
        return cli_peers
    peers = PEER_MAP.get(main_ticker)
    if peers is not None:
        print(f"  [INFO] 競合リスト: {peers}  (PEER_MAP ヒット)")
        return peers
    print(f"  [WARN] {main_ticker}: PEER_MAP 未登録のため競合比較をスキップします。")
    print(f"         競合を指定する場合: python3 generate_charts.py {main_ticker} 競合1.T 競合2.T ...")
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════════════════════════════════════════
def _parse_ticker(arg: str) -> str:
    """
    引数から yfinance 用ティッカーを生成する。
    「4桁の数字」を正規表現で抽出し、末尾に '.T' を付与して返す。

    対応パターン例:
      富士通_6702   → 6702.T
      富士通_6702.T → 6702.T   ← .T 付きでも正しく抽出
      6702          → 6702.T
      6702.T        → 6702.T
    4桁数字が見つからない場合は引数をそのまま返す（米国株ティッカー等の保険）。
    """
    import re
    m = re.search(r"(\d{4})", arg)
    if m:
        return m.group(1) + ".T"
    # 4桁が見つからなければ元の文字列を使う（例: AAPL）
    return arg


if __name__ == "__main__":
    import sys

    # 第1引数: メイン銘柄（省略時は 4564.T）
    #   「銘柄名_コード」形式も受け付ける（例: 富士通_6702 → 6702.T）
    # 第2引数以降: 競合銘柄（省略時はデフォルト）
    # 使用例:
    #   python3 generate_charts.py 富士通_6702
    #   python3 generate_charts.py 7203.T 7267.T 7269.T 7270.T
    target_ticker = _parse_ticker(sys.argv[1]) if len(sys.argv) > 1 else "4564.T"
    cli_peers     = [_parse_ticker(t) for t in sys.argv[2:]] if len(sys.argv) > 2 else []
    PEER_TICKERS  = _resolve_peers(target_ticker, cli_peers)

    print("=" * 60)
    print("Stock Arena — チャート自動生成")
    print(f"対象: {target_ticker}  /  競合: {PEER_TICKERS}")
    print("=" * 60)

    print("\n▶ [1/3] multi_timeframe_chart ...")
    multi_timeframe_chart(target_ticker)

    print("\n▶ [2/3] financial_trend_bar ...")
    financial_trend_bar(target_ticker)

    if PEER_TICKERS:
        print("\n▶ [3/3] competitor_heatmap ...")
        competitor_heatmap(target_ticker, PEER_TICKERS)
    else:
        print("\n▶ [3/3] competitor_heatmap ... スキップ（PEER_MAP 未登録・競合銘柄未指定）")

    print(f"\n✅ 完了  →  {OUT_DIR}")
