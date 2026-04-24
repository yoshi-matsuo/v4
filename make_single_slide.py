"""
make_single_slide.py
Stock Arena V4 — 汎用1枚スライド生成スクリプト

テンプレート:
  template_Ar  左60%テキスト + 右40%イラスト（デフォルト）
  template_Al  左40%イラスト + 右60%テキスト（反転バリエーション）
  template_Sr  左40%テキスト | 右60%画像（Side-by-Side）
  template_Sl  左60%画像 | 右40%テキスト（Side-by-Side 反転）
  impact       フルスクリーン画像 + 黒オーバーレイ + 中央タイトル
  contrast     左右50%分割: Narrative（黒）vs Reality（渋色）

使い方:
  python3 make_single_slide.py \\
      <output_path> <part_marker> <color_hex> <title> \\
      "<content>" <image_path> \\
      [--template_type template_Ar|template_Al|template_Sr|template_Sl|impact|contrast]

  contrast の content_bullets: "|" でNarrative側とReality側を区切る
  例: "●順調な成長\\n●AIの需要が堅調|●内部売却\\n●高値で売り抜け"

例（contrast）:
  python3 make_single_slide.py \\
      outputs/slide_contrast.png "● Part 2: The Light" "#ffcc00" \\
      "光と影" \\
      "●順調な成長\\n●AIの需要が堅調|●内部売却\\n●高値で売り抜け" \\
      "" --template_type contrast
"""

import argparse
import colorsys
import os
import re
import sys
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────
# キャンバス定数
# ─────────────────────────────────────────────
W, H         = 1920, 1080
BG_COLOR     = (10, 10, 10)
WHITE        = (255, 255, 255)
GRAY_MID     = (170, 170, 170)
GRAY_DIM     = (75, 75, 75)

TEXT_RATIO   = 0.60
TEXT_W       = int(W * TEXT_RATIO)    # 1152px
ILLUST_W     = W - TEXT_W             #  768px

# Template S 専用定数
#
#  Sr: テキスト [0 .. S_TX_W]       画像 [S_TX_W .. W]
#  Sl: 画像     [0 .. S_IM_W]       テキスト [S_IM_W .. W]
#
#  テキストパネルを広め（62%）に取ることで余白を確保し、
#  画像パネルは狭め（38%）にして画像を上品に浮かせる。
S_TX_W = int(W * 0.62)    # 1190px — テキストパネル幅（62%）
S_IM_W = W - S_TX_W       #  730px — 画像パネル幅（38%）
S_SQ   = int(H * 0.55)    #  594px — 画像正方形（画面高さ55%）
# 後方互換エイリアス
S_TEXT_W = S_TX_W
S_IMG_W  = S_IM_W
SQ_SIZE  = S_SQ

FONT_BOLD    = "/System/Library/Fonts/ヒラギノ角ゴシック W9.ttc"
FONT_MEDIUM  = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
FONT_REG     = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_LIGHT   = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"   # Template S 本文用（細め）


# ─────────────────────────────────────────────
# カラーユーティリティ
# ─────────────────────────────────────────────
def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """#rrggbb → (r, g, b)"""
    h = hex_str.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"無効な色コード: {hex_str}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def mute_color(rgb: tuple[int, int, int],
               value_scale: float = 0.45,
               sat_scale: float   = 0.80) -> tuple[int, int, int]:
    """
    HSVで明度を落とし彩度をやや絞る「渋いトーン」に変換する。
    例: #ff3333(鮮やか赤) → #731616(暗く落ち着いた赤)
    """
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    v2 = min(v * value_scale, 1.0)
    s2 = min(s * sat_scale,   1.0)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s2, v2)
    return (int(r2 * 255), int(g2 * 255), int(b2 * 255))


# ─────────────────────────────────────────────
# フォント / テキストユーティリティ
# ─────────────────────────────────────────────
def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def text_w(text: str, font: ImageFont.FreeTypeFont,
           draw: ImageDraw.ImageDraw) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def text_h(text: str, font: ImageFont.FreeTypeFont,
           draw: ImageDraw.ImageDraw) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]


def autofit_font(text: str, font_path: str, start_size: int,
                 max_px: int, draw: ImageDraw.ImageDraw,
                 min_size: int = 36) -> ImageFont.FreeTypeFont:
    """テキストが max_px 以内に収まる最大フォントサイズを返す"""
    for size in range(start_size, min_size - 1, -2):
        f = load_font(font_path, size)
        if text_w(text, f, draw) <= max_px:
            return f
    return load_font(font_path, min_size)


def wrap_jp(text: str, font: ImageFont.FreeTypeFont,
            max_px: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """
    日本語テキストをピクセル幅で折り返す。
    英数字の塊（SEC, USD, 2025 等）は途中で分断しない。
    """
    tokens: list[str] = re.findall(r"[A-Za-z0-9]+|.", text)
    lines, current = [], ""
    for tok in tokens:
        test = current + tok
        if text_w(test, font, draw) > max_px and current:
            lines.append(current)
            current = tok
        else:
            current = test
    if current:
        lines.append(current)
    return lines


BULLET_CHARS = set("●・•◆▶—-*")

def split_bullet(line: str) -> tuple[str, str]:
    """
    "● テキスト" → marker="●  ", body="テキスト"
    マーカーのない行は ("", 行全体) を返す。
    """
    stripped = line.lstrip()
    if stripped and stripped[0] in BULLET_CHARS:
        m = re.match(r"^([●・•◆▶—\-\*]+\s*)", stripped)
        if m:
            marker = m.group(1)
            body   = stripped[len(marker):]
            return marker.rstrip() + "  ", body
    return "", stripped


# ─────────────────────────────────────────────
# Template: template_Ar / template_Al（左右分割レイアウト）
# ─────────────────────────────────────────────
def draw_illustration(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                      image_path: str,
                      area_x0: int = TEXT_W, area_w: int = ILLUST_W) -> None:
    """指定エリアにイラストをアスペクト比維持で配置する"""
    if os.path.exists(image_path):
        illust = Image.open(image_path).convert("RGBA")
        iw, ih  = illust.size
        scale   = min(area_w / iw, H / ih)
        nw, nh  = int(iw * scale), int(ih * scale)
        illust  = illust.resize((nw, nh), Image.LANCZOS)
        px = area_x0 + (area_w - nw) // 2
        py = (H - nh) // 2
        canvas.paste(illust, (px, py), illust.split()[3])
    else:
        m = 30
        draw.rectangle([area_x0 + m, m, area_x0 + area_w - m, H - m],
                       outline=GRAY_DIM, width=2)
        ph_font = load_font(FONT_REG, 24)
        draw.text((area_x0 + 40, H // 2 - 30),
                  f"[イラスト未配置]\n{image_path}",
                  font=ph_font, fill=GRAY_DIM)


def draw_text_area(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                   part_marker: str, color: tuple[int, int, int],
                   title: str, bullets: list[str],
                   text_x0: int = 0, area_w: int = TEXT_W,
                   divider_x: int = TEXT_W) -> None:
    """テキストエリア（ヘッダー + タイトルバンド + 箇条書き）を描画する"""

    muted = mute_color(color)    # 渋いトーン（タイトルバンドに使用）

    INNER_PAD = 80
    ABS_L  = text_x0 + INNER_PAD           # テキスト左端（絶対座標）
    ABS_R  = text_x0 + area_w - INNER_PAD  # テキスト右端（絶対座標）
    MAX_TW = ABS_R - ABS_L                 # 実効幅

    f_header  = load_font(FONT_MEDIUM, 30)
    f_title   = autofit_font(title, FONT_BOLD, 88, MAX_TW, draw, min_size=44)
    f_bullet  = load_font(FONT_MEDIUM, 48)

    # 1. パートヘッダー（鮮やかカラー）
    HEADER_Y = 88
    draw.text((ABS_L, HEADER_Y), part_marker, font=f_header, fill=color)

    # 2. タイトルバンド（渋いトーン）+ 白文字
    TITLE_Y    = HEADER_Y + 64
    t_h        = text_h(title, f_title, draw)
    BAND_PAD_V = 20
    band = (ABS_L - 16, TITLE_Y - BAND_PAD_V,
            text_x0 + area_w - 40, TITLE_Y + t_h + BAND_PAD_V)
    draw.rectangle(band, fill=muted)
    draw.text((ABS_L, TITLE_Y), title, font=f_title, fill=WHITE)

    # 3. 区切りライン
    DIV_Y = band[3] + 48
    draw.line([(ABS_L, DIV_Y), (ABS_R, DIV_Y)],
              fill=(45, 45, 45), width=2)

    # 4. 箇条書き（マーカー = 鮮やかカラー、本文 = 白）
    bul_y      = DIV_Y + 44
    LINE_GAP   = 10   # 同一箇条書き内の折り返し行間
    BUL_MARGIN = 56   # 箇条書き要素間の余白（画面下スカスカ解消のため2倍に拡大）
    b_h        = text_h("あ", f_bullet, draw)

    for item in bullets:
        if not item.strip():
            continue
        marker, body = split_bullet(item)
        if marker:
            mk_w  = text_w(marker, f_bullet, draw)
            lines = wrap_jp(body, f_bullet, MAX_TW - mk_w, draw)
            draw.text((ABS_L, bul_y), marker, font=f_bullet, fill=color)
            for j, ln in enumerate(lines):
                draw.text((ABS_L + mk_w, bul_y + j * (b_h + LINE_GAP)),
                          ln, font=f_bullet, fill=WHITE)
            n_lines = max(1, len(lines))
        else:
            lines = wrap_jp(body, f_bullet, MAX_TW, draw)
            for j, ln in enumerate(lines):
                draw.text((ABS_L, bul_y + j * (b_h + LINE_GAP)),
                          ln, font=f_bullet, fill=GRAY_MID)
            n_lines = max(1, len(lines))
        bul_y += n_lines * (b_h + LINE_GAP) + BUL_MARGIN

    # 5. 境界縦ライン
    draw.line([(divider_x, 0), (divider_x, H)], fill=(25, 25, 25), width=2)

    # 6. フッターバー（渋いトーン）
    draw.rectangle([text_x0, H - 5, text_x0 + area_w, H], fill=muted)


def render_standard(output_path: str, part_marker: str,
                    color: tuple[int, int, int], title: str,
                    bullets: list[str], image_path: str) -> None:
    """template_Ar: 左60%テキスト + 右40%イラスト"""
    canvas = Image.new("RGB", (W, H), BG_COLOR)
    draw   = ImageDraw.Draw(canvas)
    draw_illustration(canvas, draw, image_path,
                      area_x0=TEXT_W, area_w=ILLUST_W)
    draw_text_area(canvas, draw, part_marker, color, title, bullets,
                   text_x0=0, area_w=TEXT_W, divider_x=TEXT_W)
    _save(canvas, output_path)


def render_template_al(output_path: str, part_marker: str,
                       color: tuple[int, int, int], title: str,
                       bullets: list[str], image_path: str) -> None:
    """template_Al: 左40%イラスト + 右60%テキスト（反転バリエーション）"""
    canvas = Image.new("RGB", (W, H), BG_COLOR)
    draw   = ImageDraw.Draw(canvas)
    draw_illustration(canvas, draw, image_path,
                      area_x0=0, area_w=ILLUST_W)
    draw_text_area(canvas, draw, part_marker, color, title, bullets,
                   text_x0=ILLUST_W, area_w=TEXT_W, divider_x=ILLUST_W)
    _save(canvas, output_path)


# ─────────────────────────────────────────────
# Template S: Side-by-Side（62%テキスト | 38%画像、またはその逆）
#
#  Sr: テキスト [0 .. S_TX_W=1190]  /  画像 [S_TX_W=1190 .. W=1920]
#  Sl: 画像     [0 .. S_IM_W= 730]  /  テキスト [S_IM_W=730 .. W=1920]
#
#  _draw_s_text_panel(panel_x0):
#      パネル x 範囲 = [panel_x0, panel_x0 + S_TX_W]  ← 絶対に超えない
#
#  _draw_s_image_panel(panel_x0):
#      パネル x 範囲 = [panel_x0, panel_x0 + S_IM_W]  ← 絶対に超えない
# ─────────────────────────────────────────────

# ── 先頭バレット記号除去ユーティリティ ───────────────
_S_BULLET_RE = re.compile(r'^[●・•◆▶—\-\*\s]+')

def _s_strip(s: str) -> str:
    """先頭の箇条書き記号・空白を除去して返す"""
    return _S_BULLET_RE.sub('', s.strip()).strip()


def _parse_s_content(raw: str) -> tuple[str, str, str]:
    """
    content_bullets を (price, price_label, body) に分解する。

    3行構成（通常）:
      行0: 価格テキスト   例: "4,329円"  ← ●があっても自動除去
      行1: 価格ラベル     例: "現在株価"
      行2〜: 説明文（複数行は空白で結合して1文にする）

    2行構成（フォールバック）:
      行0: 見出し（price_label として使用）
      行1: 本文（body として使用）
      price は空文字になる
    """
    lines = raw.split("\\n") if "\\n" in raw else raw.split("\n")
    lines = [l for l in lines if l.strip()]  # 空行除去

    if len(lines) >= 3:
        price       = _s_strip(lines[0])
        price_label = _s_strip(lines[1])
        body        = "\n".join(_s_strip(l) for l in lines[2:] if l.strip())
    elif len(lines) == 2:
        price       = ""
        price_label = _s_strip(lines[0])
        body        = _s_strip(lines[1])
    else:
        price       = _s_strip(lines[0]) if lines else ""
        price_label = ""
        body        = ""

    return price, price_label, body


def _s_body_font(size: int) -> ImageFont.FreeTypeFont:
    """本文用フォント: W3（細め）→ W6 → W8 の順で日本語対応フォントを取得"""
    for path in [FONT_LIGHT,
                 "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
                 FONT_MEDIUM]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_s_text_panel(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                       part_marker: str, color: tuple[int, int, int],
                       title: str, price: str, price_label: str, body: str,
                       panel_x0: int) -> None:
    """
    テキストパネル（幅 S_TX_W = 1190px）を描画する。
    X 範囲: [panel_x0, panel_x0 + S_TX_W] — この外に一切描画しない。

    3層構成:
      [A] ヘッダー: パートマーカー → muted帯タイトル → 白罫線
      [B] 価格: 極太120px+ → グレーラベル → 区切り線
      [C] 本文: Light/Regular 38px、行間2.0倍
    """
    muted = mute_color(color)

    # ── X 境界を先に確定（これ以降は PX0/PX1 を使い、直接数値を書かない）
    PX0    = panel_x0               # テキストパネル左端
    PX1    = panel_x0 + S_TX_W     # テキストパネル右端 = panel_x0 + 1190
    PAD_H  = 72                     # 左右内側余白
    PAD_B  = 64                     # 下端セーフゾーン
    TXT_L  = PX0 + PAD_H           # テキスト描画開始 X
    TXT_R  = PX1 - PAD_H           # テキスト描画終了 X（これを超えない）
    MAX_TW = TXT_R - TXT_L         # 実効テキスト幅 = 1190 - 144 = 1046px
    CLIP_Y = H - PAD_B             # 描画 Y 下限 = 1016px

    # ── フォント（全て MAX_TW 内に収まることを保証）
    f_marker = load_font(FONT_MEDIUM,  26)
    f_title  = autofit_font(title,  FONT_BOLD,  70, MAX_TW, draw, min_size=44)
    f_price  = autofit_font(price,  FONT_BOLD, 120, MAX_TW, draw, min_size=72)
    f_label  = _s_body_font(28)    # Light体（価格ラベル）
    f_body   = _s_body_font(44)    # Light体（本文）

    # ── [A-0] パネル背景 #1a1a1a ─────────────
    draw.rectangle([PX0, 0, PX1, H], fill=(26, 26, 26))

    y = 58   # 描画カーソル

    # ── [A-1] パートマーカー ──────────────────
    draw.text((TXT_L, y), part_marker, font=f_marker, fill=color)
    y += text_h(part_marker, f_marker, draw) + 22

    # ── [A-2] タイトル帯（muted 全幅）+ 極太白文字 ──
    t_hv    = text_h(title, f_title, draw)
    BPV     = 20                            # 帯の上下パディング
    band_y1 = y + BPV + t_hv + BPV
    draw.rectangle([PX0, y, PX1, band_y1], fill=muted)
    draw.text((TXT_L, y + BPV), title, font=f_title, fill=WHITE)
    y = band_y1

    # ── [A-3] 白い罫線（全幅）────────────────
    draw.rectangle([PX0, y, PX1, y + 2], fill=WHITE)
    y += 2 + 54

    # ── [B-1] 価格（極太・120px+・白）── price が空の場合はスキップ
    if price:
        draw.text((TXT_L, y), price, font=f_price, fill=WHITE)
        y += text_h(price, f_price, draw) + 12

    # ── [B-2] 価格ラベル / 見出し（Light・28px・グレー）
    if price_label:
        draw.text((TXT_L, y), price_label, font=f_label, fill=GRAY_MID)
        y += text_h(price_label, f_label, draw) + 32

    # ── [B-3] 区切り線（内側余白内のみ）──────
    draw.rectangle([TXT_L, y, TXT_R, y + 1], fill=(55, 55, 55))
    y += 1 + 40

    # ── [C] 本文（Light・44px・行間2.0倍・段落間GAP付き・はみ出し防止）
    b_h           = text_h("あ", f_body, draw)
    LEADING       = int(b_h * 2.0)
    PARAGRAPH_GAP = int(b_h * 1.2)   # 段落（\n区切り）間の追加余白

    paragraphs = body.split("\n") if body else []
    for pi, para in enumerate(paragraphs):
        if not para.strip():
            continue
        for ln in wrap_jp(para, f_body, MAX_TW, draw):
            if y + b_h > CLIP_Y:
                break
            draw.text((TXT_L, y), ln, font=f_body, fill=WHITE)
            y += LEADING
        if pi < len(paragraphs) - 1:
            y += PARAGRAPH_GAP


def _draw_s_image_panel(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                        image_path: str, panel_x0: int) -> None:
    """
    画像パネル（幅 S_IM_W = 730px）を描画する。
    X 範囲: [panel_x0, panel_x0 + S_IM_W] — この外に一切描画しない。

    画像（S_SQ = 594px 正方形）だけをパネル中央に「浮かせて」配置。
    背景ボックスは描画しない。
    """
    sq  = S_SQ                          # 594px
    PX0 = panel_x0                      # 画像パネル左端
    # 中央座標（パネル内）
    px  = PX0 + (S_IM_W - sq) // 2     # 水平中央: panel_x0 + (730-594)//2 = panel_x0 + 68
    py  = (H - sq) // 2                 # 垂直中央: (1080-594)//2 = 243

    if os.path.exists(image_path):
        img    = Image.open(image_path).convert("RGBA")
        iw, ih = img.size
        # 短辺を sq にスケール → 中央クロップ → sq×sq 正方形
        scale  = max(sq / iw, sq / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img    = img.resize((nw, nh), Image.LANCZOS)
        cx     = (nw - sq) // 2
        cy     = (nh - sq) // 2
        img    = img.crop((cx, cy, cx + sq, cy + sq))
        # 背景なしで直接合成
        canvas.paste(img, (px, py), img.split()[3])
    else:
        # 枠なし・最小限プレースホルダー
        ph_font = load_font(FONT_MEDIUM, 20)
        ph_text = "[No Image]"
        pw = text_w(ph_text, ph_font, draw)
        draw.text((PX0 + (S_IM_W - pw) // 2, H // 2 - 12),
                  ph_text, font=ph_font, fill=GRAY_DIM)


def render_template_sr(output_path: str, part_marker: str,
                       color: tuple[int, int, int], title: str,
                       price: str, price_label: str, body: str,
                       image_path: str) -> None:
    """template_Sr: 左62%テキスト[0..1190] | 右38%画像[1190..1920]"""
    canvas = Image.new("RGB", (W, H), BG_COLOR)
    draw   = ImageDraw.Draw(canvas)
    _draw_s_image_panel(canvas, draw, image_path, panel_x0=S_TX_W)  # x:1190〜1920
    _draw_s_text_panel(canvas, draw, part_marker, color, title,
                       price, price_label, body, panel_x0=0)         # x:0〜1190
    _save(canvas, output_path)


def render_template_sl(output_path: str, part_marker: str,
                       color: tuple[int, int, int], title: str,
                       price: str, price_label: str, body: str,
                       image_path: str) -> None:
    """template_Sl: 左38%画像[0..730] | 右62%テキスト[730..1920]"""
    canvas = Image.new("RGB", (W, H), BG_COLOR)
    draw   = ImageDraw.Draw(canvas)
    _draw_s_image_panel(canvas, draw, image_path, panel_x0=0)        # x:0〜730
    _draw_s_text_panel(canvas, draw, part_marker, color, title,
                       price, price_label, body, panel_x0=S_IM_W)    # x:730〜1920
    _save(canvas, output_path)


# ─────────────────────────────────────────────
# Template: Impact（フルスクリーン画像 + 中央タイトル）
# ─────────────────────────────────────────────
def _scale_to_fill(img: Image.Image, tw: int, th: int) -> Image.Image:
    """アスペクト比維持で全面を埋めるようにスケール → 中央クロップ"""
    iw, ih = img.size
    scale  = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img    = img.resize((nw, nh), Image.LANCZOS)
    x0     = (nw - tw) // 2
    y0     = (nh - th) // 2
    return img.crop((x0, y0, x0 + tw, y0 + th))


def render_impact(output_path: str, part_marker: str,
                  color: tuple[int, int, int], title: str,
                  image_path: str) -> None:

    muted = mute_color(color)    # 渋いトーン（アクセントラインに使用）

    # ── 背景 ────────────────────────────────
    if os.path.exists(image_path):
        bg = Image.open(image_path).convert("RGB")
        bg = _scale_to_fill(bg, W, H)
    else:
        # プレースホルダー背景（ダークグレー）
        bg = Image.new("RGB", (W, H), (20, 20, 20))

    canvas = bg.copy()

    # ── 黒オーバーレイ（75% 不透明度） ──────
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    canvas  = Image.blend(canvas, overlay, alpha=0.75)

    draw = ImageDraw.Draw(canvas)

    # イラスト未配置の場合はガイドを描画（下部中央）
    if not os.path.exists(image_path):
        draw.rectangle([30, 30, W - 30, H - 30], outline=GRAY_DIM, width=2)
        ph_font = load_font(FONT_REG, 24)
        draw.text((60, H - 80), f"[イラスト未配置]  {image_path}",
                  font=ph_font, fill=GRAY_DIM)

    # ── タイトル（中央配置・自動フォントサイズ） ──
    TITLE_MARGIN = 120        # 左右マージン
    MAX_TITLE_W  = W - TITLE_MARGIN * 2
    f_title = autofit_font(title, FONT_BOLD, 150, MAX_TITLE_W, draw, min_size=60)

    t_w = text_w(title, f_title, draw)
    t_h = text_h(title, f_title, draw)
    tx  = (W - t_w) // 2
    ty  = (H - t_h) // 2

    # ── アクセントライン（タイトルの上下、渋いトーン） ──
    LINE_THICK  = 10
    LINE_MARGIN = 36    # タイトルとラインの間隔
    LINE_W      = min(t_w + 200, W - TITLE_MARGIN * 2)   # ラインはタイトルより少し広め
    line_x0     = (W - LINE_W) // 2
    line_x1     = line_x0 + LINE_W

    # 上ライン
    top_line_y = ty - LINE_MARGIN - LINE_THICK
    draw.rectangle([line_x0, top_line_y, line_x1, top_line_y + LINE_THICK],
                   fill=muted)

    # 下ライン
    bot_line_y = ty + t_h + LINE_MARGIN
    draw.rectangle([line_x0, bot_line_y, line_x1, bot_line_y + LINE_THICK],
                   fill=muted)

    # ── タイトルテキスト（白、中央）──────────
    draw.text((tx, ty), title, font=f_title, fill=WHITE)

    # ── パートマーカー（左上・鮮やかカラー）──
    f_marker = load_font(FONT_MEDIUM, 32)
    draw.text((60, 60), part_marker, font=f_marker, fill=color)

    # ── フッター細ライン（渋いトーン）────────
    draw.rectangle([0, H - 5, W, H], fill=muted)

    _save(canvas, output_path)


# ─────────────────────────────────────────────
# Template: Contrast（高密度・境界突破デザイン）
# ─────────────────────────────────────────────
def _parse_contrast_bullets(raw: str) -> tuple[list[str], list[str]]:
    """
    "|" を区切りに左側（Light）と右側（Shadow）の行リストを返す。
    例: "●A\\n●B|●C\\n●D" → (["●A","●B"], ["●C","●D"])
    """
    def split_lines(s: str) -> list[str]:
        return s.split("\\n") if "\\n" in s else s.split("\n")

    if "|" in raw:
        left_raw, right_raw = raw.split("|", 1)
    else:
        left_raw, right_raw = raw, ""

    return split_lines(left_raw), split_lines(right_raw)


def render_contrast(output_path: str, part_marker: str,
                    color: tuple[int, int, int], title: str,
                    left_bullets: list[str], right_bullets: list[str]) -> None:

    # ── カラーパレット ──────────────────────
    # LEFT (THE LIGHT)  : 引数 color のテーマカラーをベースに動的生成
    # RIGHT (THE SHADOW): 固定ダーク系（#111111 ベース）
    HALF = W // 2   # 960px

    # --- LEFT palette（color から導出） ---
    LEFT_BG     = mute_color(color, value_scale=0.18, sat_scale=0.85)  # 極暗カラー下地
    TITLE_L_BG  = mute_color(color, value_scale=0.28, sat_scale=0.80)  # タイトルバンド
    CARD_L_FILL = mute_color(color, value_scale=0.22, sat_scale=0.82)  # カード背景
    BORDER_L    = (*color, 80)                                          # テーマカラー枠
    MARKER_L    = color                                                 # 鮮やかマーカー
    ACC_L       = mute_color(color, value_scale=0.65, sat_scale=0.90)  # アクセントライン
    EVIDENCE_L  = mute_color(color, value_scale=0.55, sat_scale=0.70)  # エビデンス文字

    # --- RIGHT palette（固定ダーク系） ---
    RIGHT_BG    = (17,  17,  17)          # #111111
    TITLE_R_BG  = (10,  10,  10)          # #0a0a0a（バンドをさらに暗く）
    CARD_R_FILL = (22,  22,  22)          # #161616
    BORDER_R    = (50,  50,  50, 80)      # 暗めグレー枠
    MARKER_R    = (120, 120, 120)         # くすんだグレーマーカー
    ACC_R       = (45,  45,  45)          # アクセントライン
    EVIDENCE_R  = (80,  80,  80)          # エビデンス文字（暗め）

    # ── ベースキャンバス（RGB）─────────────
    canvas = Image.new("RGB", (W, H), LEFT_BG)
    draw   = ImageDraw.Draw(canvas)
    draw.rectangle([HALF, 0, W, H], fill=RIGHT_BG)

    # ── フォント ────────────────────────────
    f_part     = load_font(FONT_MEDIUM, 26)
    f_header   = load_font(FONT_BOLD,   52)
    f_title    = autofit_font(title, FONT_BOLD, 82, W - 160, draw, min_size=44)
    f_bullet   = load_font(FONT_MEDIUM, 42)
    f_evidence = load_font(FONT_REG,    22)

    PAD = 70    # パネル内左右パディング

    # ── 1. パートマーカー（左上） ─────────
    draw.text((PAD, 40), part_marker, font=f_part, fill=color)

    # ── 2. パネルヘッダー ─────────────────
    HEADER_Y = 108
    draw.text((PAD, HEADER_Y),
              "THE LIGHT（表の主張）", font=f_header, fill=WHITE)
    draw.text((HALF + PAD, HEADER_Y),
              "THE SHADOW（裏の真実）", font=f_header, fill=(130, 130, 130))

    h_h = text_h("THE LIGHT（表の主張）", f_header, draw)
    acc_y = HEADER_Y + h_h + 12
    draw.rectangle([0,    acc_y, HALF, acc_y + 2], fill=ACC_L)
    draw.rectangle([HALF, acc_y, W,    acc_y + 2], fill=ACC_R)

    # ── 3. タイトルバンド（全幅ツートン・境界突破）
    t_h_val    = text_h(title, f_title, draw)
    BAND_PAD_V = 24
    BAND_H     = t_h_val + BAND_PAD_V * 2
    BAND_Y     = acc_y + 44

    draw.rectangle([0,    BAND_Y, HALF, BAND_Y + BAND_H], fill=TITLE_L_BG)
    draw.rectangle([HALF, BAND_Y, W,    BAND_Y + BAND_H], fill=TITLE_R_BG)

    # タイトル文字：画面中央揃え
    t_w_val = text_w(title, f_title, draw)
    tx = (W - t_w_val) // 2
    ty = BAND_Y + BAND_PAD_V
    draw.text((tx, ty), title, font=f_title, fill=WHITE)

    # ── 4. カードをRGBA合成で描画 ──────────
    CARD_Y0      = BAND_Y + BAND_H + 38
    CARD_Y1      = H - 56
    CARD_MARGIN  = 28    # パネル端からカードまでの余白

    lcard_x0 = CARD_MARGIN
    lcard_x1 = HALF - CARD_MARGIN
    rcard_x0 = HALF + CARD_MARGIN
    rcard_x1 = W    - CARD_MARGIN

    card_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card_layer)

    cd.rounded_rectangle(
        [lcard_x0, CARD_Y0, lcard_x1, CARD_Y1],
        radius=14,
        fill=(*CARD_L_FILL, 210),
        outline=BORDER_L,
        width=2,
    )
    cd.rounded_rectangle(
        [rcard_x0, CARD_Y0, rcard_x1, CARD_Y1],
        radius=14,
        fill=(*CARD_R_FILL, 210),
        outline=BORDER_R,
        width=2,
    )

    canvas = Image.alpha_composite(canvas.convert("RGBA"), card_layer).convert("RGB")
    draw   = ImageDraw.Draw(canvas)

    # ── 5. カード内箇条書き（上下中央揃え・行間調整） ─
    CARD_PAD   = 44
    EV_PAD     = 33                                       # 枠線との余白 (+5px)
    BUL_MAX    = HALF - CARD_MARGIN - CARD_PAD * 2        # ≈800px
    b_h        = text_h("あ", f_bullet, draw)
    LINE_GAP   = 4                                        # 折り返し行間
    BUL_MARGIN = int(b_h * 1.35) - LINE_GAP              # 要素間余白（1行時の合計が旧 BUL_GAP と同等）

    ev_h     = text_h("A", f_evidence, draw)

    # 上下中央揃えの開始Y を各サイドで計算する
    # 利用可能エリア: カード上端パッド ～ エビデンスエリア上端
    bul_area_top  = CARD_Y0 + CARD_PAD
    bul_area_bot  = CARD_Y1 - EV_PAD - ev_h - 20   # 20px = エビデンスとの余白
    bul_available = bul_area_bot - bul_area_top

    def _item_height(item: str) -> int:
        """1箇条書きアイテムが実際に占める高さを返す"""
        if not item.strip():
            return 0
        _marker, _body = split_bullet(item)
        _max_w = BUL_MAX - (text_w(_marker, f_bullet, draw) if _marker else 0)
        n = max(1, len(wrap_jp(_body, f_bullet, _max_w, draw)))
        return n * (b_h + LINE_GAP)

    def compute_start_y(bullets: list[str]) -> int:
        items = [b for b in bullets if b.strip()]
        if not items:
            return bul_area_top
        total_h = (sum(_item_height(b) for b in items)
                   + (len(items) - 1) * BUL_MARGIN)
        offset  = max(0, (bul_available - total_h) // 2)
        return bul_area_top + offset

    def draw_bullets(bullets: list[str], x0: int, marker_col: tuple) -> None:
        y = compute_start_y(bullets)
        for item in bullets:
            if not item.strip():
                continue
            marker, body = split_bullet(item)
            if marker:
                mk_w  = text_w(marker, f_bullet, draw)
                lines = wrap_jp(body, f_bullet, BUL_MAX - mk_w, draw)
                draw.text((x0, y), marker, font=f_bullet, fill=marker_col)
                for j, ln in enumerate(lines):
                    draw.text((x0 + mk_w, y + j * (b_h + LINE_GAP)),
                              ln, font=f_bullet, fill=WHITE)
                n_lines = max(1, len(lines))
            else:
                lines = wrap_jp(body, f_bullet, BUL_MAX, draw)
                for j, ln in enumerate(lines):
                    draw.text((x0, y + j * (b_h + LINE_GAP)),
                              ln, font=f_bullet, fill=WHITE)
                n_lines = max(1, len(lines))
            y += n_lines * (b_h + LINE_GAP) + BUL_MARGIN

    draw_bullets(left_bullets,  lcard_x0 + CARD_PAD, MARKER_L)
    draw_bullets(right_bullets, rcard_x0 + CARD_PAD, MARKER_R)

    # ── 6. エビデンステキスト（カード右下・右詰め）
    ev_y = CARD_Y1 - EV_PAD - ev_h

    left_ev  = "EVIDENCE: SEC-FORM-4A"
    right_ev = "DOCUMENT ID: 2025-V4-CRM"

    lew = text_w(left_ev, f_evidence, draw)
    draw.text((lcard_x1 - EV_PAD - lew, ev_y),
              left_ev, font=f_evidence, fill=EVIDENCE_L)

    rew = text_w(right_ev, f_evidence, draw)
    draw.text((rcard_x1 - EV_PAD - rew, ev_y),
              right_ev, font=f_evidence, fill=EVIDENCE_R)

    # ── 7. フッターバー ────────────────────
    foot_col = mute_color(color)
    draw.rectangle([0, H - 5, W, H], fill=foot_col)

    _save(canvas, output_path)


# ─────────────────────────────────────────────
# Template: Grid（3カラム情報整理レイアウト）
# ─────────────────────────────────────────────
def _parse_grid_content(raw: str) -> list[tuple[str, list[str]]]:
    """
    "|" で3分割し、各セクションを (heading, [detail_lines]) に変換する。
    最初の非空行が見出し、残りが詳細テキスト。
    """
    def split_lines(s: str) -> list[str]:
        lines = s.split("\\n") if "\\n" in s else s.split("\n")
        return [l.strip() for l in lines if l.strip()]

    sections = [s.strip() for s in raw.split("|")]
    while len(sections) < 3:
        sections.append("")

    result: list[tuple[str, list[str]]] = []
    for sec in sections[:3]:
        lines = split_lines(sec)
        heading = lines[0] if lines else ""
        details = lines[1:] if len(lines) > 1 else []
        result.append((heading, details))
    return result


def render_grid(output_path: str, part_marker: str,
                color: tuple[int, int, int], title: str,
                cards_data: list[tuple[str, list[str]]],
                footer_text: str) -> None:

    muted   = mute_color(color)
    # カード背景: muted をさらに暗く（35%明度）
    card_bg = tuple(int(c * 0.75) for c in muted)
    # カード枠: muted より少し明るく
    card_bd = tuple(min(255, int(c * 1.6)) for c in muted)

    # ── レイアウト定数 ─────────────────────────
    OUTER_PAD  = 50    # 左右キャンバス余白
    CARD_GAP   = 22    # カード間隔
    HEADER_H   = 148   # part_marker + title エリア
    FOOTER_H   = 80    # フッターエリア高
    CARD_PAD   = 36    # カード内パディング

    card_w = (W - OUTER_PAD * 2 - CARD_GAP * 2) // 3   # ≈592px
    CARD_Y0 = HEADER_H + 18
    CARD_Y1 = H - FOOTER_H - 18
    CARD_H  = CARD_Y1 - CARD_Y0   # ≈814px

    card_x0s = [OUTER_PAD + i * (card_w + CARD_GAP) for i in range(3)]

    # ── ベースキャンバス ─────────────────────
    canvas = Image.new("RGB", (W, H), BG_COLOR)
    draw   = ImageDraw.Draw(canvas)

    # ── カードをRGBA合成 ─────────────────────
    card_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card_layer)
    for cx0 in card_x0s:
        cd.rounded_rectangle(
            [cx0, CARD_Y0, cx0 + card_w, CARD_Y1],
            radius=18,
            fill=(*card_bg, 230),
            outline=(*card_bd, 90),
            width=2,
        )
    canvas = Image.alpha_composite(canvas.convert("RGBA"), card_layer).convert("RGB")
    draw   = ImageDraw.Draw(canvas)

    # ── フォント ─────────────────────────────
    f_part    = load_font(FONT_MEDIUM, 28)
    f_title   = autofit_font(title, FONT_BOLD, 72, W - OUTER_PAD * 2, draw, min_size=40)
    f_num     = load_font(FONT_BOLD,   46)
    f_heading = load_font(FONT_BOLD,   56)
    f_detail  = load_font(FONT_REG,    42)
    f_footer  = load_font(FONT_MEDIUM, 32)

    # ── 1. パートマーカー ─────────────────────
    draw.text((OUTER_PAD, 38), part_marker, font=f_part, fill=color)

    # ── 2. タイトル ──────────────────────────
    t_h_val = text_h(title, f_title, draw)
    draw.text((OUTER_PAD, 80), title, font=f_title, fill=WHITE)
    # タイトル下アクセントライン（全幅）
    acc_y = 80 + t_h_val + 10
    draw.rectangle([0, acc_y, W, acc_y + 3], fill=muted)

    # ── 3. 各カード描画 ──────────────────────
    CIRCLE_R      = 40      # 円アイコン半径
    CONTENT_TOP   = 68      # カード上端から円上端までの固定パディング
    CIRC_HEAD_GAP = 32      # 円〜見出し間
    HEAD_SEP_GAP  = 22      # 見出し〜区切りライン間
    SEP_DET_GAP   = 22      # 区切りライン〜本文1行目まで

    # フォント高（ループ前に計算）
    h_lh = text_h("あ", f_heading, draw)
    d_lh = text_h("あ", f_detail,  draw)
    d_max = card_w - CARD_PAD * 2

    # ── Leading 定数 ─────────────────────────
    LEADING = int(d_lh * 1.55)  # 全行共通のLeading

    for i, (heading, details) in enumerate(cards_data):
        cx0 = card_x0s[i]
        cx1 = cx0 + card_w
        ccx = cx0 + card_w // 2

        head_max       = card_w - CARD_PAD * 2
        head_lines     = wrap_jp(heading, f_heading, head_max, draw)
        n_head         = len(head_lines)
        active_details = [l for l in details if l.strip()]
        n_detail       = len(active_details)

        # 各要素を上端から順に積み上げ（グループとしてひとかたまり）
        circle_cy = CARD_Y0 + CONTENT_TOP + CIRCLE_R
        head_y    = circle_cy + CIRCLE_R + CIRC_HEAD_GAP
        head_bot  = head_y + n_head * (h_lh + 6)
        sep_y     = head_bot + HEAD_SEP_GAP
        det_top   = sep_y + 2 + SEP_DET_GAP

        # 3-a. 番号アイコン
        draw.ellipse(
            [ccx - CIRCLE_R, circle_cy - CIRCLE_R,
             ccx + CIRCLE_R, circle_cy + CIRCLE_R],
            fill=color, outline=WHITE, width=2,
        )
        num_str = str(i + 1)
        nw = text_w(num_str, f_num, draw)
        nh = text_h(num_str, f_num, draw)
        draw.text((ccx - nw // 2, circle_cy - nh // 2),
                  num_str, font=f_num, fill=WHITE)

        # 3-b. 見出し（中央揃え）
        for j, ln in enumerate(head_lines):
            lw = text_w(ln, f_heading, draw)
            draw.text((ccx - lw // 2, head_y + j * (h_lh + 6)),
                      ln, font=f_heading, fill=WHITE)

        # 3-c. 区切りライン
        if n_detail > 0:
            draw.rectangle([cx0 + CARD_PAD, sep_y,
                            cx1 - CARD_PAD, sep_y + 2], fill=color)

        # 3-d. 本文テキスト ── 全行 LEADING 2.0倍・トップ寄せ
        d_y = det_top
        for line in active_details:
            marker, body = split_bullet(line)
            if marker:
                mk_w = text_w(marker, f_detail, draw)
                wrapped = wrap_jp(body, f_detail, d_max - mk_w, draw)
                for k, ln in enumerate(wrapped):
                    if k == 0:
                        draw.text((cx0 + CARD_PAD, d_y),
                                  marker, font=f_detail, fill=color)
                    draw.text((cx0 + CARD_PAD + mk_w, d_y),
                              ln, font=f_detail, fill=GRAY_MID)
                    d_y += LEADING
            else:
                wrapped = wrap_jp(line, f_detail, d_max, draw)
                for ln in wrapped:
                    draw.text((cx0 + CARD_PAD, d_y), ln, font=f_detail, fill=GRAY_MID)
                    d_y += LEADING

    # ── 4. フッター ──────────────────────────
    FOOTER_Y = H - FOOTER_H
    # フッター背景（薄いグレー帯）
    draw.rectangle([0, FOOTER_Y, W, H], fill=(28, 28, 28))
    # 上端アクセントライン
    draw.rectangle([0, FOOTER_Y, W, FOOTER_Y + 3], fill=muted)

    if footer_text:
        fw = text_w(footer_text, f_footer, draw)
        fh = text_h(footer_text, f_footer, draw)
        fx = (W - fw) // 2
        fy = FOOTER_Y + (FOOTER_H - fh) // 2
        draw.text((fx, fy), footer_text, font=f_footer, fill=GRAY_MID)

    _save(canvas, output_path)


# ─────────────────────────────────────────────
# Template T: Top Banner
#
#  バナー[y=0..280, x=0..1920] 全幅画像クロップ
#  左パネル  [x=100..1000]  タイトル + 2ブロック
#  右パネル  [x=1100..1820] 巨大数字（垂直中央）
# ─────────────────────────────────────────────
T_BANNER_H = 280
T_LEFT_L   = 100
T_LEFT_R   = 1000
T_LEFT_W   = T_LEFT_R - T_LEFT_L     # 900px
T_RIGHT_L  = 1100
T_RIGHT_R  = 1820
T_RIGHT_W  = T_RIGHT_R - T_RIGHT_L   # 720px
T_CONTENT_Y = 340                     # 左パネル コンテンツ開始Y

_T_HL_RE = re.compile(r'\[([^\]]+)\]')  # [テキスト] ハイライト検出用


def _t_draw_heading(draw: ImageDraw.ImageDraw,
                    x: int, y: int, raw_text: str,
                    font: ImageFont.FreeTypeFont,
                    fill: tuple, hl_color: tuple) -> int:
    """
    見出し1行を描画する。[...] 内のテキストを hl_color で背景ハイライト。
    ブラケット記号は描画せず除去する。
    戻り値: 描画した行の高さ（px）
    """
    parts = _T_HL_RE.split(raw_text)  # [normal, hl, normal, hl, ...]
    cx    = x
    lh    = text_h("あ", font, draw)
    HP    = 5   # ハイライト上下パディング

    for i, part in enumerate(parts):
        if not part:
            continue
        pw = text_w(part, font, draw)
        if i % 2 == 1:   # 奇数インデックス = ハイライト対象
            ph = text_h(part, font, draw)
            draw.rectangle([cx - 2, y - HP, cx + pw + 2, y + ph + HP],
                           fill=hl_color)
        draw.text((cx, y), part, font=font, fill=fill)
        cx += pw
    return lh


def _parse_t_content(raw: str) -> tuple[list[str], list[str], list[str]]:
    """
    content_bullets を '|' で3分割し、各ブロックを行リストに変換する。
    フォーマット: "左ブロック1|左ブロック2|右ブロック"
    各ブロック内は \\n または \\n で改行する。
    """
    def to_lines(s: str) -> list[str]:
        s = s.strip()
        lines = s.split("\\n") if "\\n" in s else s.split("\n")
        return [l.strip() for l in lines if l.strip()]

    parts = raw.split("|", 2)
    while len(parts) < 3:
        parts.append("")
    return to_lines(parts[0]), to_lines(parts[1]), to_lines(parts[2])


def render_template_t(output_path: str, part_marker: str,
                      color: tuple[int, int, int], title: str,
                      block_l1: list[str], block_l2: list[str],
                      block_r: list[str], image_path: str) -> None:
    """Template T: Top Banner レイアウト"""

    # ── キャンバス（#111111）────────────────
    canvas = Image.new("RGB", (W, H), (17, 17, 17))
    draw   = ImageDraw.Draw(canvas)

    # ── 上部バナー（全幅・高さ T_BANNER_H にクロップ）──
    if os.path.exists(image_path):
        banner  = Image.open(image_path).convert("RGB")
        bw, bh  = banner.size
        # 幅W・高さT_BANNER_H を両方満たすようにスケール（fill）
        scale   = max(W / bw, T_BANNER_H / bh)
        nw      = int(bw * scale)
        nh      = int(bh * scale)
        banner  = banner.resize((nw, nh), Image.LANCZOS)
        bx0     = (nw - W) // 2          # 水平中央クロップ
        banner  = banner.crop((bx0, 0, bx0 + W, T_BANNER_H))
        canvas.paste(banner, (0, 0))

        # バナー下端を #111111 にフェード（RGBA レイヤー合成）
        FADE_H  = 50
        fade    = Image.new("RGBA", (W, FADE_H), (0, 0, 0, 0))
        fd      = ImageDraw.Draw(fade)
        for row in range(FADE_H):
            a = int(255 * (row / FADE_H) ** 1.5)
            fd.line([(0, row), (W, row)], fill=(17, 17, 17, a))
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(fade, (0, T_BANNER_H - FADE_H), fade)
        canvas = canvas_rgba.convert("RGB")
        draw   = ImageDraw.Draw(canvas)

    # ── フォント定義（左パネル）─────────────
    f_title  = load_font(FONT_MEDIUM,  60)
    f_head   = load_font(FONT_BOLD,    48)
    f_body   = _s_body_font(32)           # W3/W6/W8 フォールバック
    f_marker = load_font(FONT_MEDIUM,  20)

    # ── 左パネル描画 ─────────────────────────
    y = T_CONTENT_Y

    # タイトル（--title, 60px, 白）
    draw.text((T_LEFT_L, y), title, font=f_title, fill=WHITE)
    y += text_h(title, f_title, draw) + 44

    def draw_left_block(lines: list[str]) -> int:
        """1ブロック（見出し＋本文）を描画して終端Yを返す"""
        nonlocal y
        if not lines:
            return y
        # 1行目: 見出し（48px + ハイライト）
        lh = _t_draw_heading(draw, T_LEFT_L, y, lines[0],
                             f_head, WHITE, color)
        y += lh + 14
        # 2行目以降: 本文（32px, グレー, 行間1.8倍）
        b_h     = text_h("あ", f_body, draw)
        LEADING = int(b_h * 1.8)
        for line in lines[1:]:
            for ln in wrap_jp(line, f_body, T_LEFT_W, draw):
                draw.text((T_LEFT_L, y), ln, font=f_body, fill=GRAY_MID)
                y += LEADING
        return y

    draw_left_block(block_l1)
    y += 56   # ブロック間スペース
    draw_left_block(block_l2)

    # ── 右パネル描画（垂直中央）─────────────
    r0 = block_r[0] if len(block_r) > 0 else ""
    r1 = block_r[1] if len(block_r) > 1 else ""
    r2 = block_r[2] if len(block_r) > 2 else ""

    f_big  = autofit_font(r0, FONT_BOLD, 160, T_RIGHT_W, draw, min_size=100)
    f_sub  = load_font(FONT_MEDIUM, 48)
    f_supp = _s_body_font(32)

    bh_big  = text_h("あ", f_big,  draw)
    bh_sub  = text_h("あ", f_sub,  draw)
    bh_supp = text_h("あ", f_supp, draw)
    GAP_12  = 20   # big → sub 間
    GAP_23  = 10   # sub → supp 間

    lines_big  = wrap_jp(r0, f_big,  T_RIGHT_W, draw) if r0 else []
    lines_sub  = wrap_jp(r1, f_sub,  T_RIGHT_W, draw) if r1 else []
    lines_supp = wrap_jp(r2, f_supp, T_RIGHT_W, draw) if r2 else []

    total_h = (len(lines_big)  * bh_big
               + (GAP_12 + len(lines_sub)  * bh_sub  if lines_sub  else 0)
               + (GAP_23 + len(lines_supp) * bh_supp if lines_supp else 0))

    avail_h = H - T_BANNER_H     # 800px
    ry = T_BANNER_H + max(0, (avail_h - total_h) // 2)

    for ln in lines_big:
        draw.text((T_RIGHT_L, ry), ln, font=f_big, fill=WHITE)
        ry += bh_big

    if lines_sub:
        ry += GAP_12
        for ln in lines_sub:
            draw.text((T_RIGHT_L, ry), ln, font=f_sub, fill=WHITE)
            ry += bh_sub

    if lines_supp:
        ry += GAP_23
        for ln in lines_supp:
            draw.text((T_RIGHT_L, ry), ln, font=f_supp, fill=GRAY_MID)
            ry += bh_supp

    # ── パートマーカー（左下・控えめ）────────
    draw.text((T_LEFT_L, H - 38), part_marker,
              font=f_marker, fill=(55, 55, 55))

    _save(canvas, output_path)


# ─────────────────────────────────────────────
# Template Tu / Td: Top Banner ミラー（上下撃ち分け）
#
#  template_Tu : バナー上部[y=0..280]   / テキスト下部[y=280..1080]
#  template_Td : テキスト上部[y=0..800] / バナー下部[y=800..1080]
# ─────────────────────────────────────────────

def _render_t_core(output_path: str, part_marker: str,
                   color: tuple[int, int, int], title: str,
                   block_l1: list[str], block_l2: list[str],
                   block_r: list[str], image_path: str,
                   banner_at_top: bool) -> None:
    """
    Template Tu / Td 共通描画コア。

    banner_at_top=True  (Tu): バナー y=[0, T_BANNER_H]
                              テキスト y=[T_BANNER_H, H]
                              フェード: バナー下端 → 黒
    banner_at_top=False (Td): バナー y=[H-T_BANNER_H, H]
                              テキスト y=[0, H-T_BANNER_H]
                              フェード: バナー上端 → 黒
    """
    BG = (17, 17, 17)
    canvas = Image.new("RGB", (W, H), BG)
    draw   = ImageDraw.Draw(canvas)

    # ── バナー配置座標 ────────────────────────
    if banner_at_top:
        banner_paste_y  = 0
        text_y0         = T_BANNER_H       # 280  テキストエリア開始Y
        text_y1         = H                # 1080 テキストエリア終了Y
        left_content_y  = T_BANNER_H + 60  # 340  左パネルコンテンツ開始
        fade_anchor     = T_BANNER_H       # フェードの下端
        fade_direction  = "bottom_of_banner"
    else:
        banner_paste_y  = H - T_BANNER_H   # 800  バナー貼り付けY
        text_y0         = 0                # 0    テキストエリア開始Y
        text_y1         = H - T_BANNER_H   # 800  テキストエリア終了Y
        left_content_y  = 100              # 100  左パネルコンテンツ開始
        fade_anchor     = H - T_BANNER_H   # フェードの上端
        fade_direction  = "top_of_banner"

    # ── バナー画像（全幅クロップ）────────────
    if os.path.exists(image_path):
        banner  = Image.open(image_path).convert("RGB")
        bw, bh  = banner.size
        scale   = max(W / bw, T_BANNER_H / bh)
        nw      = int(bw * scale)
        nh      = int(bh * scale)
        banner  = banner.resize((nw, nh), Image.LANCZOS)
        bx0     = (nw - W) // 2
        banner  = banner.crop((bx0, 0, bx0 + W, T_BANNER_H))
        canvas.paste(banner, (0, banner_paste_y))

        # ── バナー端フェード（#111111 へ）────
        FADE_H = 50
        fade   = Image.new("RGBA", (W, FADE_H), (0, 0, 0, 0))
        fd     = ImageDraw.Draw(fade)
        for row in range(FADE_H):
            if fade_direction == "bottom_of_banner":
                # row=0 が透明、row=FADE_H-1 が不透明（バナー下→黒）
                a = int(255 * (row / FADE_H) ** 1.5)
            else:
                # row=0 が不透明、row=FADE_H-1 が透明（バナー上→黒）
                a = int(255 * ((FADE_H - 1 - row) / FADE_H) ** 1.5)
            fd.line([(0, row), (W, row)], fill=(17, 17, 17, a))

        if fade_direction == "bottom_of_banner":
            fade_y = fade_anchor - FADE_H   # バナー下端の少し手前から
        else:
            fade_y = fade_anchor            # バナー上端から

        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(fade, (0, fade_y), fade)
        canvas = canvas_rgba.convert("RGB")

    draw = ImageDraw.Draw(canvas)

    # ── フォント定義 ─────────────────────────
    f_title  = load_font(FONT_MEDIUM,  60)
    f_head   = load_font(FONT_BOLD,    48)
    f_body   = _s_body_font(32)
    f_marker = load_font(FONT_MEDIUM,  20)

    r0 = block_r[0] if len(block_r) > 0 else ""
    r1 = block_r[1] if len(block_r) > 1 else ""
    r2 = block_r[2] if len(block_r) > 2 else ""
    f_big  = autofit_font(r0, FONT_BOLD, 160, T_RIGHT_W, draw, min_size=100)
    f_sub  = load_font(FONT_MEDIUM, 48)
    f_supp = _s_body_font(32)

    # ── 左パネル描画 ─────────────────────────
    y = left_content_y

    draw.text((T_LEFT_L, y), title, font=f_title, fill=WHITE)
    y += text_h(title, f_title, draw) + 44

    def draw_left_block(lines: list[str]) -> None:
        nonlocal y
        if not lines:
            return
        lh = _t_draw_heading(draw, T_LEFT_L, y, lines[0], f_head, WHITE, color)
        y += lh + 14
        b_h     = text_h("あ", f_body, draw)
        LEADING = int(b_h * 1.8)
        for line in lines[1:]:
            for ln in wrap_jp(line, f_body, T_LEFT_W, draw):
                if y + b_h > text_y1 - 20:
                    return
                draw.text((T_LEFT_L, y), ln, font=f_body, fill=GRAY_MID)
                y += LEADING

    draw_left_block(block_l1)
    y += 56
    draw_left_block(block_l2)

    # ── 右パネル（テキストエリア内で垂直中央）──
    bh_big  = text_h("あ", f_big,  draw)
    bh_sub  = text_h("あ", f_sub,  draw)
    bh_supp = text_h("あ", f_supp, draw)
    GAP_12  = 20
    GAP_23  = 10

    lines_big  = wrap_jp(r0, f_big,  T_RIGHT_W, draw) if r0 else []
    lines_sub  = wrap_jp(r1, f_sub,  T_RIGHT_W, draw) if r1 else []
    lines_supp = wrap_jp(r2, f_supp, T_RIGHT_W, draw) if r2 else []

    total_h = (len(lines_big) * bh_big
               + (GAP_12 + len(lines_sub)  * bh_sub  if lines_sub  else 0)
               + (GAP_23 + len(lines_supp) * bh_supp if lines_supp else 0))

    avail_h = text_y1 - text_y0
    ry = text_y0 + max(0, (avail_h - total_h) // 2)

    for ln in lines_big:
        draw.text((T_RIGHT_L, ry), ln, font=f_big, fill=WHITE)
        ry += bh_big
    if lines_sub:
        ry += GAP_12
        for ln in lines_sub:
            draw.text((T_RIGHT_L, ry), ln, font=f_sub, fill=WHITE)
            ry += bh_sub
    if lines_supp:
        ry += GAP_23
        for ln in lines_supp:
            draw.text((T_RIGHT_L, ry), ln, font=f_supp, fill=GRAY_MID)
            ry += bh_supp

    # ── パートマーカー（左下・控えめ）────────
    draw.text((T_LEFT_L, H - 38), part_marker,
              font=f_marker, fill=(55, 55, 55))

    _save(canvas, output_path)


def render_template_tu(output_path: str, part_marker: str,
                       color: tuple[int, int, int], title: str,
                       block_l1: list[str], block_l2: list[str],
                       block_r: list[str], image_path: str) -> None:
    """template_Tu: 上部バナー[y=0..280] + 下部テキスト左右分割"""
    _render_t_core(output_path, part_marker, color, title,
                   block_l1, block_l2, block_r, image_path,
                   banner_at_top=True)


def render_template_td(output_path: str, part_marker: str,
                       color: tuple[int, int, int], title: str,
                       block_l1: list[str], block_l2: list[str],
                       block_r: list[str], image_path: str) -> None:
    """template_Td: 上部テキスト左右分割 + 下部バナー[y=800..1080]"""
    _render_t_core(output_path, part_marker, color, title,
                   block_l1, block_l2, block_r, image_path,
                   banner_at_top=False)


# ─────────────────────────────────────────────
# pure_image — 加工なしパススルー出力
# ─────────────────────────────────────────────
def render_pure_image(output_path: str, image_path: str) -> None:
    """
    テキスト描画・オーバーレイを一切行わず、
    image_path を 1920x1080 にリサイズ/クロップして出力する。
    画像が存在しない場合は黒背景を出力する（エラーにしない）。
    """
    if image_path and os.path.exists(image_path):
        canvas = Image.open(image_path).convert("RGB")
        canvas = _scale_to_fill(canvas, W, H)
    else:
        canvas = Image.new("RGB", (W, H), (10, 10, 10))
    _save(canvas, output_path)


# ─────────────────────────────────────────────
# 共通保存
# ─────────────────────────────────────────────
def _save(canvas: Image.Image, output_path: str) -> None:
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    canvas.save(output_path, format="PNG")


# ─────────────────────────────────────────────
# エントリーポイント
# ─────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Stock Arena V4 — 汎用1枚スライド生成",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--template_type",
                   choices=["template_Ar", "template_Al",
                            "template_Sr", "template_Sl",
                            "template_T", "template_Tu", "template_Td",
                            "impact", "contrast", "grid", "pure_image"],
                   default="template_Ar",
                   help="テンプレート種別（デフォルト: template_Ar）")
    p.add_argument("--output_path",     required=True,
                   help="保存先パス（例: outputs/slide.png）")
    p.add_argument("--part_marker",     required=True,
                   help='左上ラベル（例: "● Part 3: The Shadow"）')
    p.add_argument("--color_hex",       required=True,
                   help="アクセントカラー（例: #ff3333）")
    p.add_argument("--title",           required=True,
                   help="見出しテキスト")
    p.add_argument("--content_bullets", required=True,
                   help=r"\\n区切りの箇条書き。contrast では '|' で左右を分ける")
    p.add_argument("--image_path",   default="",
                   help="イラストのパス（contrast/grid では未使用）")
    p.add_argument("--footer_text",  default="",
                   help="grid テンプレートの最下部サマリー文章")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # カラー変換
    try:
        color = hex_to_rgb(args.color_hex)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    muted = mute_color(color)

    raw = args.content_bullets

    # テンプレート分岐
    if args.template_type == "impact":
        render_impact(
            args.output_path, args.part_marker,
            color, args.title, args.image_path,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=impact")
        print(f"     イラスト  : {'あり' if os.path.exists(args.image_path) else 'プレースホルダー'}")

    elif args.template_type == "contrast":
        left_bullets, right_bullets = _parse_contrast_bullets(raw)
        render_contrast(
            args.output_path, args.part_marker,
            color, args.title, left_bullets, right_bullets,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=contrast")
        print(f"     Narrative : {len([b for b in left_bullets  if b.strip()])} 行")
        print(f"     Reality   : {len([b for b in right_bullets if b.strip()])} 行")

    elif args.template_type == "grid":
        cards_data = _parse_grid_content(raw)
        render_grid(
            args.output_path, args.part_marker,
            color, args.title, cards_data,
            getattr(args, "footer_text", ""),
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=grid")
        for i, (h, d) in enumerate(cards_data):
            print(f"     カード{i+1}  : 見出し=「{h}」 詳細{len(d)}行")

    elif args.template_type == "template_Al":
        bullets = raw.split("\\n") if "\\n" in raw else raw.split("\n")
        render_template_al(
            args.output_path, args.part_marker,
            color, args.title, bullets, args.image_path,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=template_Al")
        print(f"     箇条書き  : {len([b for b in bullets if b.strip()])} 行")
        print(f"     イラスト  : {'あり' if os.path.exists(args.image_path) else 'プレースホルダー'}")

    elif args.template_type == "template_Sr":
        price, price_label, body = _parse_s_content(raw)
        render_template_sr(
            args.output_path, args.part_marker,
            color, args.title, price, price_label, body, args.image_path,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=template_Sr")
        print(f"     価格      : {price}")
        print(f"     ラベル    : {price_label}")
        print(f"     イラスト  : {'あり' if os.path.exists(args.image_path) else 'プレースホルダー'}")

    elif args.template_type == "template_Sl":
        price, price_label, body = _parse_s_content(raw)
        render_template_sl(
            args.output_path, args.part_marker,
            color, args.title, price, price_label, body, args.image_path,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=template_Sl")
        print(f"     価格      : {price}")
        print(f"     ラベル    : {price_label}")
        print(f"     イラスト  : {'あり' if os.path.exists(args.image_path) else 'プレースホルダー'}")

    elif args.template_type == "template_T":
        block_l1, block_l2, block_r = _parse_t_content(raw)
        render_template_t(
            args.output_path, args.part_marker,
            color, args.title, block_l1, block_l2, block_r, args.image_path,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=template_T")
        print(f"     左ブロック1: {len(block_l1)} 行  左ブロック2: {len(block_l2)} 行  "
              f"右ブロック: {len(block_r)} 行")
        print(f"     バナー画像 : {'あり' if os.path.exists(args.image_path) else 'なし'}")

    elif args.template_type == "template_Tu":
        block_l1, block_l2, block_r = _parse_t_content(raw)
        render_template_tu(
            args.output_path, args.part_marker,
            color, args.title, block_l1, block_l2, block_r, args.image_path,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=template_Tu")
        print(f"     左ブロック1: {len(block_l1)} 行  左ブロック2: {len(block_l2)} 行  "
              f"右ブロック: {len(block_r)} 行")
        print(f"     バナー画像 : {'あり' if os.path.exists(args.image_path) else 'なし'}")

    elif args.template_type == "template_Td":
        block_l1, block_l2, block_r = _parse_t_content(raw)
        render_template_td(
            args.output_path, args.part_marker,
            color, args.title, block_l1, block_l2, block_r, args.image_path,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=template_Td")
        print(f"     左ブロック1: {len(block_l1)} 行  左ブロック2: {len(block_l2)} 行  "
              f"右ブロック: {len(block_r)} 行")
        print(f"     バナー画像 : {'あり' if os.path.exists(args.image_path) else 'なし'}")

    else:  # template_Ar
        bullets = raw.split("\\n") if "\\n" in raw else raw.split("\n")
        render_standard(
            args.output_path, args.part_marker,
            color, args.title, bullets, args.image_path,
        )
        print(f"[OK] {args.output_path}  ({W}x{H})  template=template_Ar")
        print(f"     箇条書き  : {len([b for b in bullets if b.strip()])} 行")
        print(f"     イラスト  : {'あり' if os.path.exists(args.image_path) else 'プレースホルダー'}")

    print(f"     パート    : {args.part_marker}")
    print(f"     カラー    : {args.color_hex} → RGB{color}  渋色→ RGB{muted}")
    print(f"     見出し    : {args.title}")


if __name__ == "__main__":
    main()
