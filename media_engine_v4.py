"""
media_engine_v4.py — Stock Arena V4 動画合成エンジン
yfinance でチャートを取得し、TTS・PIL スライド・MoviePy で
20分尺・5幕構成の金融ドキュメンタリー動画を合成する。
"""

import asyncio
import concurrent.futures
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont
from pydub import AudioSegment
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# ─────────────────────────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path("/Users/matsuoyoshihiro/v4/outputs")
RESOLUTION = (1920, 1080)
FPS        = 24
TTS_VOICE  = "ja-JP-NanamiNeural"   # edge-tts 日本語ナレーター

# カラーパレット（RGB タプル）
C_BG       = (5, 5, 16)
C_TEXT     = (255, 255, 255)
C_RED      = (255, 51, 51)
C_GRAY     = (150, 150, 165)
C_GOLD     = (204, 170, 0)
C_DARK_BAR = (8, 8, 24)

# パートごとのアクセントカラー
PART_COLORS = {
    "part_1_hook":        (204,  34,   0),   # 深紅
    "part_2_the_light":   (204, 136,   0),   # アンバー
    "part_3_the_shadow":  (119,   0, 204),   # パープル
    "part_4_the_chart":   (  0, 136, 204),   # シアン
    "part_5_the_verdict": (255,  51,  51),   # 赤
}

# パートタイトルカード用ラベル（英語 + 日本語）
PART_LABELS = {
    "part_1_hook":        ("PART 1", "HOOK  |  フック"),
    "part_2_the_light":   ("PART 2", "THE LIGHT  |  光の側面"),
    "part_3_the_shadow":  ("PART 3", "THE SHADOW  |  致命的リスク"),
    "part_4_the_chart":   ("PART 4", "THE CHART  |  チャート分析"),
    "part_5_the_verdict": ("PART 5", "THE VERDICT  |  最終審判"),
}

# 投資判断カラー
JUDGMENT_COLORS = {
    "強気買い":  (0, 210, 110),
    "押し目買い": (0, 180, 220),
    "売り推奨":  (255, 140, 0),
    "即時撤退":  (255, 51, 51),
}

# 日本語対応フォント候補（macOS 優先 → Linux フォールバック）
_FONT_PATHS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",           # macOS（CJK 対応）
    "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf",
    "/Library/Fonts/Arial Unicode MS.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

# ─────────────────────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────────────────────

def _run_async(coro) -> None:
    """asyncio コルーチンをスレッドセーフに実行する（ネストされたループでも安全）。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, coro).result()


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    """日本語対応フォントをシステムから検索して返す。見つからない場合はデフォルト。"""
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=0)
            except Exception:
                continue
    return ImageFont.load_default()


def _strip_breaks(text: str) -> str:
    """[BREAK_2S] タグを除去してスペースに置換する（スライド表示用）。"""
    return re.sub(r"\[BREAK_2S\]", " ", text).strip()


def _wrap_text(text: str, max_chars: int) -> list:
    """
    英語（スペース区切り）と日本語（文字数区切り）の両方に対応したテキスト折り返し。
    """
    import textwrap
    has_cjk = any("\u3000" <= c <= "\u9fff" or "\u4e00" <= c <= "\u9fff" for c in text)
    if not has_cjk and " " in text:
        return textwrap.wrap(text, width=max_chars) or [text]
    return [text[i: i + max_chars] for i in range(0, len(text), max_chars)]


def _make_silent_wav(duration_ms: int, output_path: str) -> str:
    """指定ミリ秒の無音 WAV ファイルを生成する。"""
    AudioSegment.silent(duration=duration_ms).export(output_path, format="wav")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# 音声合成（TTS）  ― [BREAK_2S] → 2秒無音処理
# ─────────────────────────────────────────────────────────────────────────────

async def _tts_async(text: str, out_mp3: str) -> None:
    """edge-tts で非同期 TTS 合成。rate/pitch でドキュメンタリーらしい重厚さを演出。"""
    communicate = edge_tts.Communicate(
        text,
        TTS_VOICE,
        rate="-15%",    # -15%: やや遅め → 尺が20分に近づく＋重厚感
        pitch="-5Hz",   # -5Hz: 低め → 落ち着いたトーン
    )
    await communicate.save(out_mp3)


def synthesize_narration(text: str, output_wav: str, tmp_dir: str) -> str:
    """
    [BREAK_2S] を区切りとしてテキストを分割し、各ブロックを TTS 合成後、
    正確に 2 秒の無音 (pydub.AudioSegment.silent(duration=2000)) を挟んで
    結合した WAV ファイルを生成する。

    Args:
        text:       [BREAK_2S] タグを含むナレーション文字列
        output_wav: 出力先 WAV ファイルパス
        tmp_dir:    一時 MP3 ファイルの保存先ディレクトリ

    Returns:
        output_wav のパス
    """
    silence_2s = AudioSegment.silent(duration=2000)   # 要件1: 2秒の無音
    blocks = [b.strip() for b in text.split("[BREAK_2S]") if b.strip()]
    print(f"    [INFO][TTS] テキストを {len(blocks)} ブロックに分割しました")

    if not blocks:
        _make_silent_wav(1000, output_wav)
        print(f"    [INFO][TTS] テキスト空のため無音 WAV を生成しました")
        return output_wav

    combined  = AudioSegment.empty()
    stem      = Path(output_wav).stem

    for i, block in enumerate(blocks):
        block_mp3 = os.path.join(tmp_dir, f"_{stem}_b{i}.mp3")
        print(f"    [INFO][TTS] ブロック {i+1}/{len(blocks)} を音声合成中... ({len(block)}文字)")
        try:
            _run_async(_tts_async(block, block_mp3))
            seg = AudioSegment.from_mp3(block_mp3)
        except Exception as e:
            print(f"    [INFO][TTS] ブロック {i+1} 合成失敗（無音で代替）: {e}")
            seg = AudioSegment.silent(duration=800)

        if i > 0:
            combined += silence_2s   # ブロック間に 2秒の無音を挿入
            print(f"    [INFO][TTS] [BREAK_2S] → 2秒の無音を挿入しました")
        combined += seg

    combined.export(output_wav, format="wav")
    print(f"    [INFO][TTS] 完了: {len(blocks)} ブロック → {Path(output_wav).name} "
          f"({len(combined) / 1000:.1f}秒)")
    return output_wav


# ─────────────────────────────────────────────────────────────────────────────
# スライド生成（PIL / Pillow）― 1920×1080 ダーク・インサイト・ビジュアル
# ─────────────────────────────────────────────────────────────────────────────

def _draw_top_bar(draw: ImageDraw.Draw, part_key: str, ticker: str, company: str) -> None:
    """上部バー（パートカラー帯 + パートラベル + ティッカー）を描画する。"""
    W, H   = RESOLUTION
    pc     = PART_COLORS.get(part_key, C_TEXT)
    pnum, plabel = PART_LABELS.get(part_key, ("PART ?", ""))

    draw.rectangle([0, 0, W, 74], fill=C_DARK_BAR)
    draw.rectangle([0, 74, W, 80], fill=pc)          # アクセントライン
    draw.rectangle([0, 0, 12, H], fill=pc)            # 左ストライプ

    f_sm = _find_font(27)
    draw.text((30, 24), f"{pnum}  ·  {plabel}", font=f_sm, fill=pc)
    draw.text((W - 30, 24), f"{ticker}  |  {company}", font=f_sm, fill=C_GRAY, anchor="ra")


def _draw_bottom_bar(draw: ImageDraw.Draw) -> None:
    """下部フッター（番組名ロゴ）を描画する。"""
    W, H = RESOLUTION
    draw.rectangle([0, H - 52, W, H], fill=C_DARK_BAR)
    draw.rectangle([0, H - 52, W, H - 50], fill=(30, 30, 60))
    f_sm = _find_font(24)
    draw.text((W - 32, H - 24), "▶  STOCK  ARENA", font=f_sm, fill=C_GOLD, anchor="rm")


def make_slide(
    part_key: str,
    section_title: str,
    narration_preview: str,
    ticker: str,
    company_name: str,
    output_path: str,
    is_part_title: bool = False,
    base_image: Optional[Image.Image] = None,
) -> str:
    """
    1920×1080 のダーク・インサイト・スライドを生成する。

    Args:
        is_part_title: True の場合、パートタイトルカードとして大きく描画する
        base_image:    指定した場合（Part 4）、この画像を背景としてオーバーレイする
    """
    W, H = RESOLUTION
    pc   = PART_COLORS.get(part_key, C_TEXT)

    # ── 背景レイヤー ──────────────────────────────────────────────
    is_chart_overlay = base_image is not None

    if is_chart_overlay:
        bg = base_image.resize(RESOLUTION, Image.LANCZOS).convert("RGBA")
        # 全体に薄いベール
        overall = Image.new("RGBA", RESOLUTION, (0, 0, 0, 130))
        img_rgba = Image.alpha_composite(bg, overall)
        # 下部 45% にテキスト可読用の濃いグラデーション帯
        bottom_band = Image.new("RGBA", RESOLUTION, (0, 0, 0, 0))
        bd = ImageDraw.Draw(bottom_band)
        bd.rectangle([0, int(H * 0.55), W, H], fill=(0, 0, 0, 155))
        img = Image.alpha_composite(img_rgba, bottom_band).convert("RGB")
    else:
        img = Image.new("RGB", RESOLUTION, C_BG)

    draw = ImageDraw.Draw(img)

    if is_part_title:
        # ── パートタイトルカード ──────────────────────────────────
        pnum, plabel = PART_LABELS.get(part_key, ("PART ?", ""))

        # 中央水平ライン
        draw.rectangle([60, H // 2 - 2, W - 60, H // 2 + 2], fill=pc)

        # パート番号（上）
        f_num = _find_font(110)
        draw.text((W // 2, H // 2 - 100), pnum, font=f_num, fill=pc, anchor="mm")

        # パートラベル（下）
        f_lbl = _find_font(60)
        draw.text((W // 2, H // 2 + 90), plabel, font=f_lbl, fill=C_TEXT, anchor="mm")

        # コーナー装飾（小さな円）
        for x, y in [(30, 30), (W - 30, 30), (30, H - 30), (W - 30, H - 30)]:
            draw.ellipse([x - 8, y - 8, x + 8, y + 8], fill=pc)

    elif is_chart_overlay:
        # ── チャート背景スライド: テキストを下部 45% に配置 ──────────
        _draw_top_bar(draw, part_key, ticker, company_name)
        _draw_bottom_bar(draw)

        # セクションタイトル（画面下寄り・大）
        f_title     = _find_font(72)
        title_lines = _wrap_text(section_title, 22)[:2]
        title_line_h = 90
        total_h      = len(title_lines) * title_line_h
        ty = int(H * 0.65) - total_h // 2
        for line in title_lines:
            draw.text((W // 2, ty), line, font=f_title, fill=C_TEXT, anchor="mm")
            ty += title_line_h

        # アクセントライン
        sep_y = ty + 14
        draw.rectangle([140, sep_y, W - 140, sep_y + 3], fill=pc)

        # 補助テキスト（最初の一文）
        sub = _first_sentence(narration_preview, 50)
        f_sub = _find_font(32)
        draw.text((W // 2, sep_y + 40), sub, font=f_sub, fill=pc, anchor="mm")

    else:
        # ── 通常コンテンツスライド: ミニマル・シリアスデザイン ─────────
        _draw_top_bar(draw, part_key, ticker, company_name)
        _draw_bottom_bar(draw)

        # 中央の使用可能エリア y: 90 〜 H-60
        area_top    = 90
        area_bottom = H - 60
        area_center = (area_top + area_bottom) // 2

        # ── セクションタイトル（大・中央より少し上） ──────────────────
        f_title     = _find_font(88)
        title_lines = _wrap_text(section_title, 20)[:2]
        title_line_h = 110
        total_title_h = len(title_lines) * title_line_h
        ty = area_center - total_title_h // 2 - 30   # 少し上にずらして余白を確保

        for line in title_lines:
            draw.text((W // 2, ty), line, font=f_title, fill=C_TEXT, anchor="mm")
            ty += title_line_h

        # アクセントライン（細く・短め → エレガント）
        sep_y = ty + 28
        line_w = 400
        draw.rectangle(
            [W // 2 - line_w, sep_y, W // 2 + line_w, sep_y + 3],
            fill=pc,
        )

        # ── 補助テキスト: 最初の一文のみ（小さく・パートカラー）─────
        sub = _first_sentence(narration_preview, 48)
        f_sub = _find_font(34)
        draw.text((W // 2, sep_y + 52), sub, font=f_sub, fill=pc, anchor="mm")

    img.save(output_path, format="PNG")
    return output_path


def make_verdict_slide(
    investment_judgment: str,
    judgment_rationale: str,
    short_term: str,
    mid_term: str,
    ticker: str,
    company_name: str,
    output_path: str,
) -> str:
    """
    Part 5 専用「最終審判」カードスライドを生成する。
    投資判断を大きく中央に配置し、短期・中期戦略を下部に表示する。
    """
    W, H = RESOLUTION
    img  = Image.new("RGB", RESOLUTION, C_BG)
    draw = ImageDraw.Draw(img)

    _draw_top_bar(draw, "part_5_the_verdict", ticker, company_name)
    _draw_bottom_bar(draw)

    jc = JUDGMENT_COLORS.get(investment_judgment, C_RED)

    # "FINAL VERDICT" サブラベル
    f_sub = _find_font(34)
    draw.text((W // 2, 150), "⚡  FINAL  VERDICT  ⚡", font=f_sub, fill=C_GRAY, anchor="mm")

    # 判断テキスト（超大・中央）
    f_big = _find_font(148)
    draw.text((W // 2, H // 2 - 40), investment_judgment, font=f_big, fill=jc, anchor="mm")

    # 区切りライン
    sep_y = H // 2 + 80
    draw.rectangle([80, sep_y, W - 80, sep_y + 4], fill=jc)

    # 短期・中期戦略サマリー
    f_strat = _find_font(28)
    short_preview = ("【短期】" + short_term[:90] + "…") if len(short_term) > 90 \
                    else ("【短期】" + short_term)
    mid_preview   = ("【中期】" + mid_term[:90] + "…") if len(mid_term) > 90 \
                    else ("【中期】" + mid_term)

    draw.text((W // 2, sep_y + 48), short_preview, font=f_strat, fill=C_GRAY, anchor="mm")
    draw.text((W // 2, sep_y + 100), mid_preview, font=f_strat, fill=C_GRAY, anchor="mm")

    img.save(output_path, format="PNG")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Part 4 専用 ― ダーク・チャート生成（matplotlib + yfinance）
# ─────────────────────────────────────────────────────────────────────────────

def make_chart_slide(
    ticker: str,
    output_path: str,
    ma_200_ref: Optional[float] = None,
) -> str:
    """
    yfinance から過去 1 年間の日足データを取得し、ダークモードの
    ローソク足チャート（+ 200日移動平均線 + 出来高）を 1920×1080 PNG で生成する。

    Args:
        ticker:     銘柄ティッカー（日本株 4 桁なら .T を自動付与）
        output_path: 出力 PNG パス
        ma_200_ref: yfinance から直接取得した 200日MAの参照値（取得失敗時の補完用）

    Returns:
        output_path
    """
    yf_ticker = f"{ticker}.T" if re.fullmatch(r"\d{4}", ticker) else ticker
    print(f"  [INFO][Chart] {yf_ticker} の 1 年日足データを yfinance で取得中...")

    try:
        df = yf.download(yf_ticker, period="1y", interval="1d",
                          progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("取得データが空")
        # yfinance の multi-level columns を正規化
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        print(f"  [INFO][Chart] データ取得完了: {len(df)} 日分")
    except Exception as e:
        print(f"  [INFO][Chart] データ取得失敗: {e} → フォールバックスライドを生成")
        _make_fallback_chart(ticker, output_path)
        return output_path

    n  = len(df)
    xs = np.arange(n)

    fig, (ax_c, ax_v) = plt.subplots(
        2, 1,
        figsize=(19.2, 10.8), dpi=100,
        gridspec_kw={"height_ratios": [4, 1]},
        sharex=True,
    )
    fig.patch.set_facecolor("#050510")
    for ax in (ax_c, ax_v):
        ax.set_facecolor("#090920")

    # ── ローソク足 ────────────────────────────────────────────────
    for i, (_, row) in enumerate(df.iterrows()):
        try:
            o, c = float(row["Open"]), float(row["Close"])
            h, l = float(row["High"]), float(row["Low"])
        except Exception:
            continue
        color = "#22cc66" if c >= o else "#ff3333"
        ax_c.plot([i, i], [l, h], color=color, linewidth=0.9, alpha=0.9)
        body_h = max(abs(c - o), c * 0.001)
        ax_c.bar(i, body_h, bottom=min(o, c), color=color, width=0.65, alpha=0.92)

    # ── 200日移動平均線（番組トーンのゴールド） ──────────────────
    if n >= 50:
        window = min(200, n)
        ma_series = df["Close"].rolling(window).mean().dropna()
        start_i   = n - len(ma_series)
        ax_c.plot(
            range(start_i, n), ma_series.values,
            color="#ffcc00", linewidth=2.4,
            label=f"{window}日移動平均", alpha=0.95, zorder=5,
        )
    elif ma_200_ref:
        ax_c.axhline(ma_200_ref, color="#ffcc00", linewidth=2,
                      linestyle="--", alpha=0.8, label="200日MA（参照値）")

    # ── 出来高 ────────────────────────────────────────────────────
    try:
        vol_colors = [
            "#22cc66" if float(df["Close"].iloc[i]) >= float(df["Open"].iloc[i]) else "#ff3333"
            for i in range(n)
        ]
        ax_v.bar(xs, df["Volume"].values, color=vol_colors, alpha=0.55, width=0.8)
    except Exception:
        pass
    ax_v.set_ylabel("Volume", color="#666688", fontsize=10)

    # ── X 軸ラベル（月初め） ──────────────────────────────────────
    monthly, prev_m = [], None
    for i, d in enumerate(df.index):
        if d.month != prev_m:
            monthly.append((i, d.strftime("%y/%m")))
            prev_m = d.month
    if monthly:
        ax_c.set_xticks([t[0] for t in monthly])
        ax_c.set_xticklabels([t[1] for t in monthly],
                               color="#888899", fontsize=10, rotation=0)

    # ── スタイリング ─────────────────────────────────────────────
    for ax in (ax_c, ax_v):
        for spine in ax.spines.values():
            spine.set_color("#1a1a3a")
        ax.tick_params(colors="#888899", labelsize=10)
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")

    ax_c.set_xlim(-1, n)
    ax_c.set_title(f"{ticker}  —  1年日足チャート", color="#aaaacc", fontsize=17, pad=14)
    ax_c.legend(facecolor="#090920", edgecolor="#1a1a3a",
                labelcolor="#ffcc00", fontsize=12)

    plt.subplots_adjust(hspace=0.04, left=0.04, right=0.92, top=0.95, bottom=0.06)
    plt.savefig(output_path, dpi=100, facecolor="#050510",
                bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    print(f"  [INFO][Chart] チャート画像生成完了 → {Path(output_path).name}")
    return output_path


def _make_fallback_chart(ticker: str, output_path: str) -> None:
    """チャートデータ取得失敗時のフォールバック画像を生成する。"""
    img  = Image.new("RGB", RESOLUTION, C_BG)
    draw = ImageDraw.Draw(img)
    font = _find_font(52)
    draw.text(
        (RESOLUTION[0] // 2, RESOLUTION[1] // 2),
        f"{ticker}  —  チャートデータ取得不可",
        font=font, fill=C_GRAY, anchor="mm",
    )
    img.save(output_path, format="PNG")


# ─────────────────────────────────────────────────────────────────────────────
# MoviePy クリップ構築
# ─────────────────────────────────────────────────────────────────────────────

def _apply_zoom(clip, zoom_ratio: float = 0.10):
    """
    Ken Burns ズームイン効果を適用する（100% → 110%）。

    実装: 時刻 t に応じてフレームの中央から小さくクロップし、
    元サイズに拡大することでズームインを表現する。
    ImageClip は全フレームが同一なので base_frame をクロージャにキャッシュし高速化。
    """
    W, H     = clip.size
    duration = max(clip.duration, 0.001)
    base_arr = clip.get_frame(0)   # ImageClip は全 t で同一フレーム → 事前取得

    def zoom_frame(gf, t):
        factor  = 1.0 + zoom_ratio * (t / duration)
        cw      = int(W / factor)
        ch      = int(H / factor)
        x0      = (W - cw) // 2
        y0      = (H - ch) // 2
        cropped = base_arr[y0: y0 + ch, x0: x0 + cw]
        return np.array(
            Image.fromarray(cropped).resize((W, H), Image.BILINEAR)
        )

    return clip.fl(zoom_frame)


def _build_clip(image_path: str, audio_path: str):
    """スライド画像 + 音声ファイルから MoviePy クリップを生成する（ズーム付き）。"""
    audio   = AudioFileClip(audio_path)
    img_arr = np.array(Image.open(image_path).convert("RGB"))
    clip = (
        ImageClip(img_arr)
        .set_duration(audio.duration)
        .set_audio(audio)
    )
    clip = _apply_zoom(clip)   # Ken Burns ズームインを全クリップに適用
    print(f"    [INFO][Clip] クリップ生成完了（ズーム付き）: {Path(image_path).name} ({audio.duration:.1f}秒)")
    return clip


def _build_title_card_clip(image_path: str, tmp_dir: str, name: str, duration: float = 4.5):
    """
    パートタイトルカード用のクリップを生成する。
    デフォルト 4.5 秒（3秒から延長）で緊張感のある"間"を演出する。
    ズームイン効果も _build_clip 経由で自動適用される。
    """
    print(f"    [INFO][Clip] タイトルカード生成中: {name} ({duration}秒)")
    silent_wav = os.path.join(tmp_dir, f"_silent_{name}.wav")
    _make_silent_wav(int(duration * 1000), silent_wav)
    return _build_clip(image_path, silent_wav)


# ─────────────────────────────────────────────────────────────────────────────
# JSON 正規化（複数形式の script.json に対応）
# ─────────────────────────────────────────────────────────────────────────────

def _extract_title(narration: str, max_chars: int = 28) -> str:
    """ナレーション文字列の先頭から最初の文末記号までをスライドタイトルとして抽出する。"""
    clean = re.sub(r"\[BREAK_2S\]", "", narration).strip()
    for sep in ["。", "！", "？", "…", ".", "!", "?"]:
        idx = clean.find(sep)
        if 0 < idx <= max_chars:
            return clean[: idx + 1]
    return (clean[:max_chars] + "…") if len(clean) > max_chars else clean


def _first_sentence(text: str, max_chars: int = 48) -> str:
    """
    ナレーションから最初の一文を抽出してスライドの補助テキストとして返す。
    句読点で切り取り、max_chars 文字を超える場合は省略する。
    """
    clean = re.sub(r"\[BREAK_2S\]", "", text).strip()
    for sep in ["。", "！", "？", "…"]:
        idx = clean.find(sep)
        if 0 < idx:
            sentence = clean[: idx + 1]
            return sentence if len(sentence) <= max_chars else sentence[:max_chars] + "…"
    return (clean[:max_chars] + "…") if len(clean) > max_chars else clean


def _normalize_script(raw: dict) -> dict:
    """
    任意形式の script JSON を render_v4_video が期待する内部標準形式に変換する。

    対応形式 A（script_engine_v4 標準出力）:
        { "ticker": "CRM", "part_1_hook": { "sub_sections": [{...}, ...] }, ... }

    対応形式 B（外部生成・手書き形式）:
        { "title": "...", "meta_info": {...},
          "script": { "part_1_hook": { "sub_section_1": "ナレ文字列", ... }, ... } }

    Returns:
        render_v4_video が直接処理できる標準形式の dict
    """
    PART_KEYS = [
        "part_1_hook", "part_2_the_light", "part_3_the_shadow",
        "part_4_the_chart", "part_5_the_verdict",
    ]

    # ── 形式 A: part_1_hook が既にルートに存在する ──────────────────
    if "part_1_hook" in raw:
        print("[INFO][Normalize] 形式 A（標準形式）を検出しました")
        return raw

    # ── 形式 B: "script" キーでラップされている ──────────────────────
    if "script" in raw:
        print("[INFO][Normalize] 形式 B（script ラッパー形式）を検出しました — 正規化します")
        meta        = raw.get("meta_info", {})
        script_body = raw["script"]

        # ticker / company_name を抽出
        ticker_val  = meta.get("target_ticker", "UNKNOWN")
        title_val   = raw.get("title", ticker_val)
        price_str   = meta.get("current_price", "取得不可")
        currency    = "USD" if "USD" in str(price_str) else ("JPY" if "円" in str(price_str) else "USD")

        normalized: dict = {
            "ticker":       ticker_val,
            "company_name": title_val,
            "_stock_data": {
                "two_hundred_day_ma": meta.get("ma200",       "取得不可"),
                "current_price":      price_str,
                "currency":           currency,
                "fifty_two_week_high": meta.get("high_52w",   "取得不可"),
                "fifty_two_week_low":  meta.get("low_52w",    "取得不可"),
                "trailing_pe":         meta.get("per",        "取得不可"),
                "market_cap":          meta.get("market_cap", "取得不可"),
            },
        }

        for part_key in PART_KEYS:
            part_data   = script_body.get(part_key, {})
            sub_sections = []
            i = 1
            while True:
                sec_key = f"sub_section_{i}"
                if sec_key not in part_data:
                    break
                narration = str(part_data[sec_key])
                sub_sections.append({
                    "section_title": _extract_title(narration),
                    "narration":     narration,
                })
                i += 1

            print(f"  [INFO][Normalize] {part_key}: sub_sections {len(sub_sections)} 件")
            normalized[part_key] = {"sub_sections": sub_sections}

        return normalized

    # ── 形式不明: そのまま返してエラーは呼び出し元に委ねる ──────────
    print("[WARN][Normalize] 既知の JSON 形式に一致しませんでした — そのまま処理します")
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# セクション処理ヘルパー
# ─────────────────────────────────────────────────────────────────────────────

def _process_section(
    part_key: str,
    section_title: str,
    narration: str,
    ticker: str,
    company_name: str,
    tmp_dir: str,
    idx: int,
    base_image: Optional[Image.Image] = None,
):
    """
    1 つの sub_section を処理してクリップを返す。

    Args:
        base_image: Part 4 のチャート背景など、背景に使う PIL Image
    """
    pnum = PART_LABELS.get(part_key, ("?",))[0]
    print(f"  [INFO][{pnum}] sub_section {idx+1} 処理中: 「{section_title[:35]}」")
    stem = f"{part_key}_s{idx}"

    audio_path = os.path.join(tmp_dir, f"{stem}.wav")
    synthesize_narration(narration, audio_path, tmp_dir)

    slide_path = os.path.join(tmp_dir, f"{stem}.png")
    make_slide(
        part_key=part_key,
        section_title=section_title,
        narration_preview=narration,
        ticker=ticker,
        company_name=company_name,
        output_path=slide_path,
        base_image=base_image,
    )
    return _build_clip(slide_path, audio_path)


def _process_intro(
    part_key: str,
    title: str,
    narration: str,
    ticker: str,
    company_name: str,
    tmp_dir: str,
    stem: str,
    base_image: Optional[Image.Image] = None,
):
    """
    パートの冒頭ナレーション（opening_narration / bull_thesis / fatal_weakness 等）を
    1 枚のスライドクリップとして処理する。
    """
    print(f"  [INFO][Intro] 冒頭スライド処理中: 「{title}」 ({len(narration)}文字)")
    audio_path = os.path.join(tmp_dir, f"{stem}.wav")
    synthesize_narration(narration, audio_path, tmp_dir)

    slide_path = os.path.join(tmp_dir, f"{stem}.png")
    make_slide(
        part_key=part_key,
        section_title=title,
        narration_preview=narration,
        ticker=ticker,
        company_name=company_name,
        output_path=slide_path,
        base_image=base_image,
    )
    return _build_clip(slide_path, audio_path)


# ─────────────────────────────────────────────────────────────────────────────
# メイン動画合成関数
# ─────────────────────────────────────────────────────────────────────────────

def render_v4_video(
    script: dict,
    ticker: str,
    output_dir: Optional[str] = None,
) -> str:
    """
    generate_v4_script() が返した台本 JSON を受け取り、
    全 5 パートを動画合成して最終 MP4 を出力する。

    処理フロー:
        1. yfinance でチャート画像を事前生成（Part 4 背景に再利用）
        2. 各パートの冒頭テキストと sub_sections を順番に処理:
           ① TTS 合成（[BREAK_2S] = 2秒無音挿入）
           ② PIL スライド生成（1920×1080 ダークモード）
           ③ ImageClip + AudioFileClip で MoviePy クリップ化
        3. 全クリップを concatenate_videoclips で結合
        4. v4_output_{ticker}.mp4 として書き出し

    Args:
        script:     generate_v4_script() が返した辞書
        ticker:     銘柄ティッカー（例: PLTR, 7203）
        output_dir: 出力先ディレクトリ（省略時は OUTPUT_DIR）

    Returns:
        出力 MP4 ファイルの絶対パス
    """
    # ── JSON 形式の正規化（複数形式に自動対応） ──────────────────────
    script = _normalize_script(script)

    # ticker は引数を優先し、JSONから取得できれば上書き
    ticker = script.get("ticker", ticker) or ticker

    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="v4_tmp_")

    company  = script.get("company_name", ticker)
    sd       = script.get("_stock_data", {})
    ma200_v  = sd.get("two_hundred_day_ma")
    # MA200 の値が "288.50 USD" のような文字列の場合、数値部分だけ抽出する
    if ma200_v and ma200_v != "取得不可":
        try:
            ma200_f = float(re.sub(r"[^\d.]", "", str(ma200_v)))
        except ValueError:
            ma200_f = None
    else:
        ma200_f = None

    all_clips = []

    print(f"\n{'='*60}")
    print(f"[INFO] Stock Arena V4  動画合成開始")
    print(f"[INFO] 銘柄        : {ticker}  |  {company}")
    print(f"[INFO] 出力ディレクトリ: {out_dir}")
    print(f"[INFO] 一時ディレクトリ: {tmp_dir}")
    print(f"{'='*60}\n")

    try:
        # ── 事前：チャート画像生成（Part 4 で背景として再利用） ──────
        print("[INFO] チャート画像を事前生成中（Part 4 背景として再利用）...")
        chart_png = os.path.join(tmp_dir, "chart_bg.png")
        make_chart_slide(ticker, chart_png, ma200_f)
        chart_img = Image.open(chart_png)
        print("[INFO] チャート画像の準備完了\n")

        # ══════════════════════════════════════════════════════════════
        # PART 1 — HOOK
        # ══════════════════════════════════════════════════════════════
        print("── [INFO] PART 1: HOOK 処理開始 ─────────────────────────")
        p1 = script.get("part_1_hook", {})

        tc1 = os.path.join(tmp_dir, "tc1.png")
        make_slide("part_1_hook", "", "", ticker, company, tc1, is_part_title=True)
        all_clips.append(_build_title_card_clip(tc1, tmp_dir, "tc1"))

        if p1.get("opening_narration"):
            all_clips.append(_process_intro(
                "part_1_hook",
                p1.get("catch_copy", "HOOK"),
                p1["opening_narration"],
                ticker, company, tmp_dir, "p1_open",
            ))

        p1_subs = p1.get("sub_sections", [])
        print(f"  [INFO] PART 1 sub_sections: {len(p1_subs)} 件")
        for i, sec in enumerate(p1_subs):
            title_val     = sec.get("section_title") or sec.get("subtitle") or sec.get("title", "")
            narration_val = sec.get("narration")     or sec.get("content") or sec.get("text", "")
            print(f"  [INFO] PART 1 sec {i+1}/{len(p1_subs)}: title={title_val[:30]!r}, narration={len(narration_val)}文字")
            try:
                all_clips.append(_process_section(
                    "part_1_hook", title_val, narration_val, ticker, company, tmp_dir, i,
                ))
            except Exception as e:
                print(f"  [WARN] PART 1 sec {i+1} スキップ（エラー）: {e}")
                traceback.print_exc()

        # ══════════════════════════════════════════════════════════════
        # PART 2 — THE LIGHT
        # ══════════════════════════════════════════════════════════════
        print("\n── [INFO] PART 2: THE LIGHT 処理開始 ────────────────────")
        p2 = script.get("part_2_the_light", {})

        tc2 = os.path.join(tmp_dir, "tc2.png")
        make_slide("part_2_the_light", "", "", ticker, company, tc2, is_part_title=True)
        all_clips.append(_build_title_card_clip(tc2, tmp_dir, "tc2"))

        if p2.get("bull_thesis"):
            all_clips.append(_process_intro(
                "part_2_the_light", "強気論の全貌",
                p2["bull_thesis"], ticker, company, tmp_dir, "p2_thesis",
            ))

        p2_subs = p2.get("sub_sections", [])
        print(f"  [INFO] PART 2 sub_sections: {len(p2_subs)} 件")
        for i, sec in enumerate(p2_subs):
            title_val     = sec.get("section_title") or sec.get("subtitle") or sec.get("title", "")
            narration_val = sec.get("narration")     or sec.get("content") or sec.get("text", "")
            print(f"  [INFO] PART 2 sec {i+1}/{len(p2_subs)}: title={title_val[:30]!r}, narration={len(narration_val)}文字")
            try:
                all_clips.append(_process_section(
                    "part_2_the_light", title_val, narration_val, ticker, company, tmp_dir, i,
                ))
            except Exception as e:
                print(f"  [WARN] PART 2 sec {i+1} スキップ（エラー）: {e}")
                traceback.print_exc()

        # ══════════════════════════════════════════════════════════════
        # PART 3 — THE SHADOW
        # ══════════════════════════════════════════════════════════════
        print("\n── [INFO] PART 3: THE SHADOW 処理開始 ───────────────────")
        p3 = script.get("part_3_the_shadow", {})

        tc3 = os.path.join(tmp_dir, "tc3.png")
        make_slide("part_3_the_shadow", "", "", ticker, company, tc3, is_part_title=True)
        all_clips.append(_build_title_card_clip(tc3, tmp_dir, "tc3"))

        if p3.get("fatal_weakness"):
            all_clips.append(_process_intro(
                "part_3_the_shadow", "致命的欠陥",
                p3["fatal_weakness"], ticker, company, tmp_dir, "p3_fatal",
            ))

        p3_subs = p3.get("sub_sections", [])
        print(f"  [INFO] PART 3 sub_sections: {len(p3_subs)} 件")
        for i, sec in enumerate(p3_subs):
            title_val     = sec.get("section_title") or sec.get("subtitle") or sec.get("title", "")
            narration_val = sec.get("narration")     or sec.get("content") or sec.get("text", "")
            print(f"  [INFO] PART 3 sec {i+1}/{len(p3_subs)}: title={title_val[:30]!r}, narration={len(narration_val)}文字")
            try:
                all_clips.append(_process_section(
                    "part_3_the_shadow", title_val, narration_val, ticker, company, tmp_dir, i,
                ))
            except Exception as e:
                print(f"  [WARN] PART 3 sec {i+1} スキップ（エラー）: {e}")
                traceback.print_exc()

        # ══════════════════════════════════════════════════════════════
        # PART 4 — THE CHART（チャート画像を背景として全スライドに使用）
        # ══════════════════════════════════════════════════════════════
        print("\n── [INFO] PART 4: THE CHART 処理開始 ────────────────────")
        p4 = script.get("part_4_the_chart", {})

        tc4 = os.path.join(tmp_dir, "tc4.png")
        make_slide("part_4_the_chart", "", "", ticker, company, tc4,
                    is_part_title=True, base_image=chart_img)
        all_clips.append(_build_title_card_clip(tc4, tmp_dir, "tc4"))

        if p4.get("chart_reading"):
            all_clips.append(_process_intro(
                "part_4_the_chart", "チャートが語る真実",
                p4["chart_reading"], ticker, company, tmp_dir, "p4_reading",
                base_image=chart_img,
            ))

        p4_subs = p4.get("sub_sections", [])
        print(f"  [INFO] PART 4 sub_sections: {len(p4_subs)} 件")
        for i, sec in enumerate(p4_subs):
            title_val     = sec.get("section_title") or sec.get("subtitle") or sec.get("title", "")
            narration_val = sec.get("narration")     or sec.get("content") or sec.get("text", "")
            print(f"  [INFO] PART 4 sec {i+1}/{len(p4_subs)}: title={title_val[:30]!r}, narration={len(narration_val)}文字")
            try:
                all_clips.append(_process_section(
                    "part_4_the_chart", title_val, narration_val, ticker, company, tmp_dir, i,
                    base_image=chart_img,
                ))
            except Exception as e:
                print(f"  [WARN] PART 4 sec {i+1} スキップ（エラー）: {e}")
                traceback.print_exc()

        # ══════════════════════════════════════════════════════════════
        # PART 5 — THE VERDICT
        # ══════════════════════════════════════════════════════════════
        print("\n── [INFO] PART 5: THE VERDICT 処理開始 ──────────────────")
        p5       = script.get("part_5_the_verdict", {})
        judgment = p5.get("investment_judgment", "")
        strat    = p5.get("survival_strategy", {})

        tc5 = os.path.join(tmp_dir, "tc5.png")
        make_slide("part_5_the_verdict", "", "", ticker, company, tc5, is_part_title=True)
        all_clips.append(_build_title_card_clip(tc5, tmp_dir, "tc5"))

        # 最終審判カード（投資判断 + 根拠ナレーション）
        rationale = p5.get("judgment_rationale", "")
        if judgment and rationale:
            vr_audio = os.path.join(tmp_dir, "p5_verdict.wav")
            synthesize_narration(rationale, vr_audio, tmp_dir)
            vr_slide = os.path.join(tmp_dir, "p5_verdict.png")
            make_verdict_slide(
                judgment, rationale,
                strat.get("short_term", ""),
                strat.get("mid_term", ""),
                ticker, company, vr_slide,
            )
            all_clips.append(_build_clip(vr_slide, vr_audio))

        p5_subs = p5.get("sub_sections", [])
        print(f"  [INFO] PART 5 sub_sections: {len(p5_subs)} 件")
        for i, sec in enumerate(p5_subs):
            title_val     = sec.get("section_title") or sec.get("subtitle") or sec.get("title", "")
            narration_val = sec.get("narration")     or sec.get("content") or sec.get("text", "")
            print(f"  [INFO] PART 5 sec {i+1}/{len(p5_subs)}: title={title_val[:30]!r}, narration={len(narration_val)}文字")
            try:
                all_clips.append(_process_section(
                    "part_5_the_verdict", title_val, narration_val, ticker, company, tmp_dir, i,
                ))
            except Exception as e:
                print(f"  [WARN] PART 5 sec {i+1} スキップ（エラー）: {e}")
                traceback.print_exc()

        # クロージングナレーション
        if p5.get("closing_narration"):
            all_clips.append(_process_intro(
                "part_5_the_verdict", "生き残るための答え",
                p5["closing_narration"], ticker, company, tmp_dir, "p5_closing",
            ))

        # ══════════════════════════════════════════════════════════════
        # 全クリップ結合 → MP4 書き出し
        # ══════════════════════════════════════════════════════════════
        print(f"\n[INFO] 全 {len(all_clips)} クリップを concatenate_videoclips で結合中...")
        final = concatenate_videoclips(all_clips, method="compose")
        total_sec = final.duration

        safe_ticker = re.sub(r"[^\w\-]", "_", ticker)
        output_path = str(out_dir / f"v4_output_{safe_ticker}.mp4")

        print(f"[INFO] MP4 書き出し中: {output_path}")
        print(f"[INFO] 合計尺: {total_sec / 60:.1f} 分 ({total_sec:.0f} 秒)")
        final.write_videofile(
            output_path,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            audio_fps=44100,
            verbose=False,
            logger=None,
        )

        # リソース解放
        for clip in all_clips:
            try:
                clip.close()
            except Exception:
                pass
        final.close()

        print(f"\n{'='*60}")
        print(f"[INFO] 動画合成完了")
        print(f"[INFO] 出力ファイル : {output_path}")
        print(f"[INFO] 合計尺       : {total_sec / 60:.1f} 分 ({total_sec:.0f} 秒)")
        print(f"{'='*60}")
        return output_path

    except Exception:
        print("\n[ERROR] 動画合成中にエラーが発生しました:")
        traceback.print_exc()
        raise

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"[INFO] 一時ファイルを削除しました: {tmp_dir}")


# ─────────────────────────────────────────────────────────────────────────────
# エントリポイント
# 使い方:
#   python media_engine_v4.py <script_json_path> <ticker>
#
# 例:
#   python media_engine_v4.py outputs/script_PLTR.json PLTR
#   python media_engine_v4.py outputs/script_7203.json 7203
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[INFO] media_engine_v4.py を直接実行しています")

    # ── 引数チェック ───────────────────────────────────────────────
    if len(sys.argv) < 3:
        print("[ERROR] 引数が不足しています。")
        print("使い方: python media_engine_v4.py <script_json_path> <ticker>")
        print("  例  : python media_engine_v4.py outputs/script_PLTR.json PLTR")
        sys.exit(1)

    json_path   = sys.argv[1]
    cli_ticker  = sys.argv[2]
    cli_out_dir = sys.argv[3] if len(sys.argv) >= 4 else None

    # ── JSON 読み込み ──────────────────────────────────────────────
    print(f"[INFO] JSON を読み込み中: {json_path}")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            script_data = json.load(f)
        print(f"[INFO] JSON 読み込み完了: ticker={script_data.get('ticker', '?')}, "
              f"company={script_data.get('company_name', '?')}")
    except FileNotFoundError:
        print(f"[ERROR] JSON ファイルが見つかりません: {json_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON のパースに失敗しました: {e}")
        sys.exit(1)

    # ── 出力ディレクトリの自動作成 ────────────────────────────────
    out_dir_path = Path(cli_out_dir) if cli_out_dir else OUTPUT_DIR
    if not out_dir_path.exists():
        print(f"[INFO] 出力ディレクトリを作成します: {out_dir_path}")
        os.makedirs(out_dir_path, exist_ok=True)
    else:
        print(f"[INFO] 出力ディレクトリ確認済み: {out_dir_path}")

    # ── 動画合成実行 ───────────────────────────────────────────────
    try:
        output_mp4 = render_v4_video(
            script=script_data,
            ticker=cli_ticker,
            output_dir=str(out_dir_path),
        )
        print(f"\n[INFO] 処理が正常に完了しました。")
        print(f"[INFO] 出力MP4: {output_mp4}")
        sys.exit(0)
    except Exception:
        print("\n[ERROR] render_v4_video の実行中に予期しないエラーが発生しました:")
        traceback.print_exc()
        sys.exit(1)
