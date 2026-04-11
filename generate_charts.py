#!/usr/bin/env python3
"""
generate_charts.py — 株価・財務チャート全自動生成スクリプト
yfinance でデータ取得 → ダークモード PNG (1920×1080) を出力する。

出力先: outputs/images/stock/charts/
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
OUT_DIR = os.path.join(HERE, "outputs", "images", "stock", "charts")
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
MA13W_C  = "#69f0ae"    # 13週MA
MA26W_C  = "#40c4ff"    # 26週MA

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


# ═══════════════════════════════════════════════════════════════════════════════
# 1. multi_timeframe_chart — 日足3ヶ月 / 週足3年
# ═══════════════════════════════════════════════════════════════════════════════
def multi_timeframe_chart(ticker: str) -> str:
    """
    上段: 過去3ヶ月の日足チャート（MA5 / MA25 / MA75）
    下段: 過去3年の週足チャート （MA13 / MA26）
    """
    sym = yf.Ticker(ticker)
    info = sym.info
    name = _safe(info, "shortName", "longName", default=ticker)

    df_d = sym.history(period="3mo", interval="1d").dropna(subset=["Close"])
    df_w = sym.history(period="3y",  interval="1wk").dropna(subset=["Close"])

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    gs  = GridSpec(2, 1, figure=fig,
                   hspace=0.50, top=0.88, bottom=0.07, left=0.07, right=0.97)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    _apply_dark(fig, [ax1, ax2])

    def _plot_panel(ax, df, ma_specs, title):
        close = df["Close"]
        dates = df.index
        if len(close) == 0:
            ax.text(0.5, 0.5, "データなし", transform=ax.transAxes,
                    ha="center", va="center", color=TEXT_DIM, fontsize=14)
            ax.set_title(title, fontsize=13, pad=8, color=TEXT)
            return

        trend_col = UP if close.iloc[-1] >= close.iloc[0] else DOWN

        # 終値ライン + エリア塗り
        ax.fill_between(dates, close, close.min() * 0.975,
                        alpha=0.13, color=trend_col, zorder=1)
        ax.plot(dates, close, color=trend_col, linewidth=2.0,
                label="終値", zorder=3)

        # 移動平均
        for n, col, lbl in ma_specs:
            if len(close) >= n:
                ax.plot(dates, _ma(close, n), color=col, linewidth=1.3,
                        linestyle="--", alpha=0.9, label=lbl, zorder=2)

        # 最高値 / 最安値マーカー
        i_max = close.idxmax()
        i_min = close.idxmin()
        ax.scatter([i_max], [close[i_max]], color=UP,   s=60, zorder=5)
        ax.scatter([i_min], [close[i_min]], color=DOWN, s=60, zorder=5)
        ax.annotate(f"高 ¥{close[i_max]:,.0f}",
                    (i_max, close[i_max]), textcoords="offset points",
                    xytext=(6, 6),  color=UP,   fontsize=9)
        ax.annotate(f"安 ¥{close[i_min]:,.0f}",
                    (i_min, close[i_min]), textcoords="offset points",
                    xytext=(6, -14), color=DOWN, fontsize=9)

        # 直近終値ラベル（右端）
        last = close.iloc[-1]
        ax.annotate(f" ¥{last:,.0f}",
                    xy=(dates[-1], last),
                    xytext=(4, 0), textcoords="offset points",
                    color=trend_col, fontsize=11, fontweight="bold", va="center")

        ax.set_title(title, fontsize=13, pad=8, color=TEXT)
        ax.set_ylabel("株価（円）", color=TEXT_DIM, fontsize=10)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(_fmt_yen))
        ax.legend(loc="upper left", fontsize=9,
                  facecolor=BG3, edgecolor=GRID_COL, labelcolor=TEXT,
                  framealpha=0.85)

    _plot_panel(ax1, df_d,
                [(5, MA5_C, "MA5"), (25, MA25_C, "MA25"), (75, MA75_C, "MA75")],
                "日足チャート（過去3ヶ月）")
    _plot_panel(ax2, df_w,
                [(13, MA13W_C, "MA13w"), (26, MA26W_C, "MA26w")],
                "週足チャート（過去3年）")

    mc = _safe(info, "marketCap")
    mc_str = f"時価総額: ¥{mc / 1e8:,.0f}億" if mc else "時価総額: N/A"
    fig.suptitle(f"{name}  ({ticker})  |  マルチタイムフレームチャート    {mc_str}",
                 fontsize=16, color=TEXT, fontweight="bold", y=0.97)

    out = os.path.join(OUT_DIR, "multi_timeframe_chart.png")
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  ✓ saved: {out}")
    return out


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

    # ── 候補ラベル定義（大文字小文字・表記揺れ対応） ─────────────────────────
    REV_CANDIDATES = [
        "Total Revenue", "Revenue", "Operating Revenue",
        "Total Operating Revenue", "Net Sales",
    ]
    NET_CANDIDATES = [
        "Net Income", "Net Income Common Stockholders",
        "Net Income Continuous Operations",
        "Net Income attributable to owners of parent",
    ]

    def _first_nonempty(*frames: pd.DataFrame) -> pd.DataFrame:
        """渡した DataFrame を順番に試し、空でない最初のものを返す"""
        for f in frames:
            if f is not None and not f.empty:
                return f
        return pd.DataFrame()

    def _row(fin: pd.DataFrame, candidates: list[str]):
        """大文字小文字を区別せずに候補行を探し、最初にヒットした行を返す"""
        if fin.empty:
            return None
        idx_lower = {str(i).lower(): i for i in fin.index}
        for c in candidates:
            actual = idx_lower.get(c.lower())
            if actual is not None:
                row = fin.loc[actual].dropna()
                if not row.empty:
                    print(f"  [INFO] {ticker}: '{actual}' で一致")
                    return row.sort_index()
        return None

    # ── Step 1: 四半期データを試す ────────────────────────────────────────────
    is_quarterly = True
    fin_q = _first_nonempty(sym.quarterly_financials, sym.quarterly_income_stmt)

    if not fin_q.empty:
        print(f"  [INFO] {ticker}: 四半期データ取得 "
              f"(行数={len(fin_q.index)}, 列数={len(fin_q.columns)})")

    rev_row = _row(fin_q, REV_CANDIDATES)
    net_row = _row(fin_q, NET_CANDIDATES)

    # ── Step 2: 四半期で行が取れなければ通期にフォールバック ─────────────────
    if rev_row is None and net_row is None:
        if not fin_q.empty:
            print(f"  [WARN] {ticker}: 四半期データ内に対象行なし"
                  f" → 通期データに切り替えます")
            print(f"  [DEBUG] 四半期インデックス一覧: {list(fin_q.index)}")
        else:
            print(f"  [INFO] {ticker}: 四半期データが空 → 通期データを試行")

        is_quarterly = False
        fin_a = _first_nonempty(sym.financials, sym.income_stmt)

        if fin_a.empty:
            print(f"  [ERROR] {ticker}: 通期データも取得できませんでした → スキップ")
            return ""

        print(f"  [INFO] {ticker}: 通期データ取得 "
              f"(行数={len(fin_a.index)}, 列数={len(fin_a.columns)})")
        rev_row = _row(fin_a, REV_CANDIDATES)
        net_row = _row(fin_a, NET_CANDIDATES)
        fin     = fin_a
    else:
        fin = fin_q

    # ── Step 3: 通期でも見つからなければ全インデックスを出力して諦める ─────────
    if rev_row is None and net_row is None:
        print(f"  [ERROR] {ticker}: 四半期・通期ともに売上高・純利益行が見つかりません → スキップ")
        print(f"  [DEBUG] 通期インデックス一覧: {list(fin.index)}")
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

    df_raw = df_raw.iloc[-(12 if is_quarterly else 8):]
    print(f"  [INFO] {ticker}: グラフ化対象 {len(df_raw)} 期分")

    # ── 会計年度・四半期番号の算出 ────────────────────────────────────────────
    def _fy_q(ts):
        """(fy_label: '24年度', q: 1-4) を返す"""
        m, y = ts.month, ts.year
        fy_year = y if m <= fy_end_month else y + 1
        fy_start = (fy_end_month % 12) + 1
        elapsed  = (m - fy_start) % 12
        return f"{fy_year % 100:02d}年度", elapsed // 3 + 1

    ts_list   = list(df_raw.index)
    fy_labels = [_fy_q(ts)[0] for ts in ts_list]
    x_labels  = [f"{_fy_q(ts)[0]}{_fy_q(ts)[1]}期" for ts in ts_list]

    df        = df_raw.copy()
    df.index  = x_labels

    # ── YoY 計算（四半期: 4期前 / 年次: 1期前） ───────────────────────────────
    yoy_step = 4 if is_quarterly else 1
    yoy_data: dict[str, dict[str, float]] = {}
    for col in df.columns:
        yoy_col: dict[str, float] = {}
        for i, lbl in enumerate(x_labels):
            if i < yoy_step:
                continue
            curr, prev = df[col].iloc[i], df[col].iloc[i - yoy_step]
            if pd.notna(curr) and pd.notna(prev) and prev != 0:
                yoy_col[lbl] = (curr - prev) / abs(prev) * 100
        yoy_data[col] = yoy_col

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
                ax.annotate(_fmt_val(val),
                            xy=(bx, anchor_y), xytext=(0, dy),
                            textcoords="offset points",
                            ha="center", va=va,
                            fontsize=13, fontweight="bold",
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
                        fontsize=10, fontweight="bold",
                        color=yoy_color, clip_on=False)

            # 四半期ラベル（グループ中央・YoY の下）
            ax.text(xi, -0.115, lbl,
                    ha="center", va="top", transform=trans,
                    fontsize=10, color=TEXT_DIM, clip_on=False)

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
        fig.suptitle(f"{name}  ({ticker})  |  財務トレンド（{freq_label}）",
                     fontsize=18, color=TEXT, fontweight="bold", y=0.97)

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

    # ── 指標定義 ──────────────────────────────────────────────────────────────
    # (表示名, 抽出関数(info) → float | None, 単位変換係数, 高い方が良いか)
    METRIC_DEFS: list[tuple[str, callable, float, bool]] = [
        ("時価総額\n(億円)",
         lambda info: _safe(info, "marketCap"),
         1e-8, True),
        ("PBR\n(倍)",
         lambda info: _safe(info, "priceToBook"),
         1.0, False),
        ("PER\n(倍)",
         lambda info: _safe(info, "trailingPE", "forwardPE"),
         1.0, False),
        ("売上高\n(億円)",
         lambda info: _safe(info, "totalRevenue"),
         1e-8, True),
        ("52週\n高値比(%)",
         lambda info: (
             round(_safe(info, "currentPrice", "regularMarketPrice", default=0)
                   / _safe(info, "fiftyTwoWeekHigh", default=1) * 100, 1)
             if _safe(info, "fiftyTwoWeekHigh") else None
         ),
         1.0, True),
        ("粗利率\n(%)",
         lambda info: (
             round(_safe(info, "grossProfits", default=0)
                   / _safe(info, "totalRevenue", default=1) * 100, 1)
             if _safe(info, "totalRevenue") and _safe(info, "totalRevenue") != 0
             else None
         ),
         1.0, True),
    ]

    metric_labels = [m[0] for m in METRIC_DEFS]

    # ── データ収集 ────────────────────────────────────────────────────────────
    row_labels = []
    raw_vals   = []    # list[list[float | None]]

    for sym_str in all_tickers:
        # ── 銘柄情報の取得（404 / 空レスポンスはスキップ） ──────────────────
        try:
            sym  = yf.Ticker(sym_str)
            info = sym.info
            # yfinance は無効ティッカーでも例外を投げずに空 or 最小限の dict を返す場合がある。
            # quoteType が存在しなければ実質 404 と判断してスキップする。
            if not info or info.get("quoteType") is None:
                print(f"  [WARN] {sym_str}: 有効な銘柄情報なし (404等) → ヒートマップから除外")
                continue
        except Exception as e:
            print(f"  [WARN] {sym_str}: 取得例外 ({e}) → ヒートマップから除外")
            continue

        name  = _safe(info, "shortName", "longName", default=sym_str)
        label = f"{name}\n({sym_str})"
        row_labels.append(label)

        row = []
        for _, fn, scale, _ in METRIC_DEFS:
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

    for col_idx, (_, _, _, higher_is_better) in enumerate(METRIC_DEFS):
        col  = metric_labels[col_idx]
        vals = df_num[col]
        vmin, vmax = vals.min(), vals.max()
        if pd.notna(vmin) and pd.notna(vmax) and vmax > vmin:
            normed = (vals - vmin) / (vmax - vmin)
        else:
            normed = pd.Series(0.5, index=vals.index)
        # 高い方が悪い指標（PBR/PER）は反転
        if not higher_is_better:
            normed = 1.0 - normed
        df_scaled[col] = normed.fillna(0.5)

    # ── アノテーション（生値文字列） ───────────────────────────────────────────
    annot = pd.DataFrame(index=df_raw.index, columns=df_raw.columns, dtype=object)
    for col in df_raw.columns:
        for idx in df_raw.index:
            v = df_num.loc[idx, col]
            annot.loc[idx, col] = f"{v:,.1f}" if pd.notna(v) else "N/A"

    # ── 描画 ─────────────────────────────────────────────────────────────────
    n_rows = len(row_labels)
    n_cols = len(metric_labels)
    cell_h = max(1.8, FIG_H / n_rows)

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H), dpi=DPI)
    _apply_dark(fig, [ax])

    sns.heatmap(
        df_scaled.astype(float),
        annot=annot,
        fmt="",
        cmap="RdYlGn",
        linewidths=1.8,
        linecolor=BG,
        ax=ax,
        cbar_kws={"shrink": 0.55, "pad": 0.02},
        annot_kws={"size": 13, "weight": "bold", "color": "#111111"},
        vmin=0.0, vmax=1.0,
    )

    # カラーバースタイル
    cbar = ax.collections[0].colorbar
    cbar.ax.tick_params(colors=TEXT_DIM, labelsize=9)
    cbar.set_label("相対スコア  (緑=優位 / 赤=劣位)  ※列内 min-max 正規化",
                   color=TEXT_DIM, fontsize=9, labelpad=8)

    # 軸ラベル
    ax.set_xticklabels(ax.get_xticklabels(),
                       rotation=0, ha="center", fontsize=12, color=TEXT)
    ax.set_yticklabels(ax.get_yticklabels(),
                       rotation=0, ha="right",  fontsize=11, color=TEXT)
    ax.tick_params(left=False, bottom=False)

    # メイン銘柄（先頭行）を枠線で強調
    for dx, dy, dw, dh in [(0, 0, n_cols, 1)]:
        ax.add_patch(mpatches.FancyBboxPatch(
            (dx, dy), dw, dh,
            boxstyle="square,pad=0",
            linewidth=2.8, edgecolor=ACCENT, facecolor="none",
            transform=ax.transData, zorder=10,
        ))

    ax.set_xlabel("")
    ax.set_ylabel("")

    fig.suptitle(
        f"競合比較ヒートマップ  |  基準銘柄: {main_ticker}\n"
        "PER は取得できない場合 N/A。スコアは列内相対値（高い方が緑）",
        fontsize=14, color=TEXT, fontweight="bold", y=0.97,
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
}

# PEER_MAP に登録がない銘柄に使うデフォルト競合リスト（TOPIX 主力）
DEFAULT_PEERS: list[str] = ["7203.T", "6758.T", "9984.T", "8306.T"]


def _resolve_peers(main_ticker: str, cli_peers: list[str]) -> list[str]:
    """
    競合リストを決定する。
    1. CLI で競合が明示指定されていればそれを優先。
    2. なければ PEER_MAP を引く。
    3. PEER_MAP にもなければ DEFAULT_PEERS を使う。
    """
    if cli_peers:
        return cli_peers
    peers = PEER_MAP.get(main_ticker, DEFAULT_PEERS)
    print(f"  [INFO] 競合リスト: {peers}  (PEER_MAP {'ヒット' if main_ticker in PEER_MAP else 'なし → デフォルト'})")
    return peers


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

    print("\n▶ [3/3] competitor_heatmap ...")
    competitor_heatmap(target_ticker, PEER_TICKERS)

    print(f"\n✅ 完了  →  {OUT_DIR}")
