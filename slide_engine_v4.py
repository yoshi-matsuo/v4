#!/usr/bin/env python3
"""
slide_engine_v4.py — Stock Arena V4 一括スライド生成エンジン
script.json を読み込み、make_single_slide.py を呼び出して全スライドを連番PNGで出力する。
"""

import glob
import json
import os
import random
import re
import shutil
import sys
import time
import importlib.util
import types

# ───────────────────────────────────────────────
# 引数チェック
# ───────────────────────────────────────────────
if len(sys.argv) < 2:
    print("使用方法: python3 slide_engine_v4.py <PROJECT_NAME>")
    print("例:       python3 slide_engine_v4.py valuenex_4422")
    sys.exit(1)

PROJECT_NAME = sys.argv[1]

# ───────────────────────────────────────────────
# 設定
# ───────────────────────────────────────────────
SCRIPT_JSON    = os.path.join(os.path.dirname(__file__), "script.json")
MAKE_SLIDE_PY  = os.path.join(os.path.dirname(__file__), "make_single_slide.py")
OUTPUT_DIR     = os.path.join(os.path.dirname(__file__),
                              "outputs", "projects", PROJECT_NAME, "slides")

PART_NUM = {"Part 1": 1, "Part 2": 2, "Part 3": 3, "Part 4": 4, "Part 5": 5,
            "Part 6": 6, "Part 7": 7}

TEMPLATE_COLOR = {
    "impact":      "\033[95m",
    "contrast":    "\033[93m",
    "grid":        "\033[96m",
    "template_Ar": "\033[92m",
    "template_Al": "\033[92m",
    "template_Sr": "\033[94m",
    "template_Sl": "\033[94m",
    "template_T":  "\033[91m",
    "template_Tu": "\033[91m",
    "template_Td": "\033[91m",
}
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"


# ───────────────────────────────────────────────
# make_single_slide をモジュールとしてインポート
# ───────────────────────────────────────────────
def _load_make_slide() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("make_single_slide", MAKE_SLIDE_PY)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────────────────────────────
# ログ / プログレス表示
# ───────────────────────────────────────────────
def _bar(done: int, total: int, width: int = 28) -> str:
    filled = int(width * done / total)
    return f"[{'█' * filled}{'░' * (width - filled)}]"

def _print_header(total: int) -> None:
    print()
    print(f"{BOLD}{'─' * 64}{RESET}")
    print(f"{BOLD}  Stock Arena V4  ─  Slide Engine  ─  全 {total} 枚一括生成{RESET}")
    print(f"{BOLD}{'─' * 64}{RESET}")
    print(f"  出力先: {DIM}{OUTPUT_DIR}{RESET}")
    print()

def _print_slide_start(seq: int, total: int, part: str, slide_idx: int,
                       tmpl: str, title: str) -> None:
    tcolor      = TEMPLATE_COLOR.get(tmpl, "")
    pct         = (seq - 1) / total * 100
    bar         = _bar(seq - 1, total)
    short_title = title[:36] + "…" if len(title) > 38 else title
    print(f"  {DIM}{bar}{RESET} {pct:5.1f}%  "
          f"{BOLD}#{seq:02d}{RESET}  "
          f"{part} / Slide {slide_idx}  "
          f"{tcolor}[{tmpl}]{RESET}  "
          f"{DIM}{short_title}{RESET}",
          end="  ", flush=True)

def _print_slide_done(filename: str, elapsed: float, ok: bool) -> None:
    status = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    print(f"{status}  {DIM}{filename}  ({elapsed:.1f}s){RESET}")

def _print_footer(total: int, errors: list, wall: float) -> None:
    print()
    print(f"  {_bar(total, total)}  100.0%")
    print()
    if errors:
        print(f"{YELLOW}  {len(errors)} 件のエラーが発生しました:{RESET}")
        for e in errors:
            print(f"    {RED}✗{RESET}  {e}")
    else:
        print(f"{GREEN}{BOLD}  全 {total} 枚のスライドを正常に生成しました。{RESET}")
    print(f"  合計時間: {wall:.1f}s   平均: {wall/total:.1f}s/枚")
    print(f"{BOLD}{'─' * 64}{RESET}")
    print()


# ───────────────────────────────────────────────
# 引用タグ除去（スライド描画テキスト用フェイルセーフ）
# ───────────────────────────────────────────────
def _clean_display_text(text: str) -> str:
    """
    スライド描画に渡す直前にAI出力の引用タグノイズを除去する。
    対象: <source>〜</source>, <source1>〜</source1> 等 / [cite:1], [cite: 12] 等
    """
    if not text:
        return text
    # <source> / <source1> / <source 1> など属性・数字付きを含む開閉タグをコンテンツごと除去
    text = re.sub(r'<source[^>]*>.*?</source[^>]*>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # [cite:1] / [cite: 1] / [cite:12] など表記揺れを一括除去
    text = re.sub(r'\[cite[^\]]*\]', '', text, flags=re.IGNORECASE)
    return text.strip()


# ───────────────────────────────────────────────
# narration 安全抽出（表示用フォールバック）
# ───────────────────────────────────────────────
def _first_sentence(text: str, max_chars: int = 50) -> str:
    """
    TTS 用長文 narration から「最初の一文」だけを抽出して返す。
    レイアウト崩壊防止のための防波堤として使用する。

    処理順:
      1. [BREAK_2S] などのマーカーを除去
      2. 句点・！？で区切られた最初の文を返す
      3. 句読点がない場合は先頭 max_chars 文字を返す
    """
    if not text:
        return ""
    text = re.sub(r'\[.*?\]', '', text).strip()
    m = re.search(r'^(.+?[。！？!?])', text)
    if m:
        return m.group(1).strip()
    return text[:max_chars].strip()


# ───────────────────────────────────────────────
# 画像パス絶対解決
# ───────────────────────────────────────────────
_ALL_DIR         = "/Users/matsuoyoshihiro/v4/outputs/images/all"
_STOCK_DIR       = "/Users/matsuoyoshihiro/v4/outputs/images/stock"
_BACKGROUNDS_DIR = "/Users/matsuoyoshihiro/v4/outputs/assets/backgrounds"


# ───────────────────────────────────────────────
# 山札（デッキ）方式 画像セレクター
# ───────────────────────────────────────────────
class ImageDeck:
    """
    全画像をシャッフルして保持し、1枚ずつ順に返す（非復元抽出）。

    山札が尽きると自動的にディスクを再スキャン・再シャッフルして補充する。
    これにより、長スライドのループでも各画像が均等に出現することを保証する。
    """

    def __init__(self, root: str, pattern: str = "**/*.png") -> None:
        self._root    = root
        self._pattern = pattern
        self._deck: list[str] = []
        self._refill()

    # ── private ────────────────────────────────────────────────────────
    def _refill(self) -> None:
        """ディスクから全ファイルを再取得してシャッフルし、山札を補充する。"""
        paths = glob.glob(
            os.path.join(self._root, self._pattern), recursive=True
        )
        random.shuffle(paths)
        self._deck = paths

    # ── public ─────────────────────────────────────────────────────────
    def draw(self) -> str:
        """
        山札から1枚取り出して返す。
        山札が空の場合は自動補充してから取り出す。
        ファイルが1枚も存在しない場合は空文字を返す。
        """
        if not self._deck:
            self._refill()
        return self._deck.pop() if self._deck else ""

    def __len__(self) -> int:
        return len(self._deck)

    def __repr__(self) -> str:
        return f"ImageDeck(root={self._root!r}, remaining={len(self._deck)})"


# デッキをモジュールスコープで初期化（スライドループ全体で状態を保持）
_all_deck   = ImageDeck(_ALL_DIR)
_stock_deck = ImageDeck(_STOCK_DIR)
_bg_deck    = ImageDeck(_BACKGROUNDS_DIR, pattern="*.png")

# テンプレートタイプ → 使用デッキのマッピング
_TEMPLATE_DECK: dict[str, ImageDeck] = {
    "title":       _all_deck,
    "impact":      _all_deck,
    "template_Sl": _all_deck,
    "template_Sr": _all_deck,
    "template_Td": _bg_deck,
    "template_Tu": _bg_deck,
    "template_Ar": _stock_deck,
    "template_Al": _stock_deck,
}


def _resolve_image(image_path: str) -> str:
    """
    明示的に指定された image_path を以下の順で探索し、最初に見つかった絶対パスを返す。
      1. OUTPUT_DIR (projects/{PROJECT_NAME}/slides/)
      2. stock/ の各サブディレクトリ
      3. backgrounds/
    どこにも見つからない場合は空文字を返す（呼び出し元でデッキフォールバックを行う）。
    """
    fname = os.path.basename(image_path)

    # 1. OUTPUT_DIR
    candidate = os.path.join(OUTPUT_DIR, fname)
    if os.path.exists(candidate):
        return candidate

    # 2. stock/ 各サブディレクトリ
    if os.path.isdir(_STOCK_DIR):
        for cat in sorted(os.listdir(_STOCK_DIR)):
            candidate = os.path.join(_STOCK_DIR, cat, fname)
            if os.path.exists(candidate):
                return candidate

    # 3. backgrounds/
    candidate = os.path.join(_BACKGROUNDS_DIR, fname)
    if os.path.exists(candidate):
        return candidate

    return ""


# ───────────────────────────────────────────────
# テンプレート別レンダー呼び出し
# ───────────────────────────────────────────────
def _call_render(mod, slide: dict, output_path: str) -> None:
    tmpl        = slide["template_type"]
    color       = mod.hex_to_rgb(slide.get("color_hex", "#ffffff"))

    # タイトル: 表示用の短いキーを優先し、最後に narration の一文を保険として使う
    title = _clean_display_text(
        slide.get("section_title")
        or slide.get("catch_copy")
        or slide.get("subtitle")
        or slide.get("title")
        or _first_sentence(slide.get("narration", ""))
    )

    # 本文: 画面表示用の短テキストを優先し、narration しかない場合は最初の一文だけ抽出
    raw = _clean_display_text(
        slide.get("content_bullets")
        or slide.get("body_text")
        or slide.get("body")
        or _first_sentence(slide.get("narration", ""))
    )

    _raw_image_path = slide.get("image_path", "")
    if _raw_image_path:
        # JSON で明示指定あり → パス解決を試みる。見つからなければデッキフォールバック
        img = _resolve_image(_raw_image_path)
        if not img:
            deck = _TEMPLATE_DECK.get(tmpl)
            img = deck.draw() if deck else ""
    else:
        # 指定なし → テンプレートタイプに対応したデッキから非復元抽出
        deck = _TEMPLATE_DECK.get(tmpl)
        img = deck.draw() if deck else ""
    footer      = slide.get("footer_text", "")
    part_marker = slide.get("_part_marker", "")

    if tmpl == "impact" or tmpl == "title":
        mod.render_impact(output_path, part_marker, color, title, img)

    elif tmpl == "contrast":
        left_b, right_b = mod._parse_contrast_bullets(raw)
        mod.render_contrast(output_path, part_marker, color, title, left_b, right_b)

    elif tmpl == "grid":
        cards = mod._parse_grid_content(raw)
        mod.render_grid(output_path, part_marker, color, title, cards, footer)

    elif tmpl == "template_Ar":
        bullets = raw.split("\\n") if "\\n" in raw else raw.split("\n")
        mod.render_standard(output_path, part_marker, color, title, bullets, img)

    elif tmpl == "template_Al":
        bullets = raw.split("\\n") if "\\n" in raw else raw.split("\n")
        mod.render_template_al(output_path, part_marker, color, title, bullets, img)

    elif tmpl == "template_Sr":
        price, price_label, body = mod._parse_s_content(raw)
        mod.render_template_sr(output_path, part_marker, color, title,
                               price, price_label, body, img)

    elif tmpl == "template_Sl":
        price, price_label, body = mod._parse_s_content(raw)
        mod.render_template_sl(output_path, part_marker, color, title,
                               price, price_label, body, img)

    elif tmpl == "template_T":
        bl1, bl2, br = mod._parse_t_content(raw)
        mod.render_template_t(output_path, part_marker, color, title, bl1, bl2, br, img)

    elif tmpl == "template_Tu":
        bl1, bl2, br = mod._parse_t_content(raw)
        mod.render_template_tu(output_path, part_marker, color, title, bl1, bl2, br, img)

    elif tmpl == "template_Td":
        bl1, bl2, br = mod._parse_t_content(raw)
        mod.render_template_td(output_path, part_marker, color, title, bl1, bl2, br, img)

    else:
        raise ValueError(f"未対応のテンプレート: {tmpl}")


# ───────────────────────────────────────────────
# メイン
# ───────────────────────────────────────────────
def main() -> None:
    if not os.path.exists(SCRIPT_JSON):
        print(f"{RED}[ERROR] script.json が見つかりません: {SCRIPT_JSON}{RESET}")
        sys.exit(1)
    if not os.path.exists(MAKE_SLIDE_PY):
        print(f"{RED}[ERROR] make_single_slide.py が見つかりません: {MAKE_SLIDE_PY}{RESET}")
        sys.exit(1)

    with open(SCRIPT_JSON, encoding="utf-8") as f:
        data = json.load(f)

    script: dict = data["script"]

    # 全スライドをフラット化（連番付き）
    all_slides = []
    for part_name, slides in script.items():
        pnum = PART_NUM.get(part_name, 0)
        for idx, slide in enumerate(slides, start=1):
            entry = dict(slide)
            entry["_part_name"]   = part_name
            entry["_part_num"]    = pnum
            entry["_slide_idx"]   = idx
            entry["_part_marker"] = f"● {part_name}"
            all_slides.append(entry)

    total = len(all_slides)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"{DIM}make_single_slide.py をロード中...{RESET}", end="", flush=True)
    mod = _load_make_slide()
    print(f"\r{' ' * 40}\r", end="")

    _print_header(total)

    errors = []
    wall_start     = time.perf_counter()
    output_seq     = 0   # 全体通し連番（pure_image スキップ、欠番なし）
    part_local_seq: dict[str, int] = {}  # パート内連番（同上）

    for seq, slide in enumerate(all_slides, start=1):
        part_name = slide["_part_name"]
        pnum      = slide["_part_num"]
        tmpl      = slide.get("template_type", "unknown")
        title     = slide.get("title", "")

        # pure_image は外部タイトル画像を流用するため生成をスキップ（連番も消費しない）
        if tmpl == "pure_image":
            print(f"  {DIM}skip  Part{pnum}  [pure_image]{RESET}")
            continue

        output_seq += 1
        part_local_seq[part_name] = part_local_seq.get(part_name, 0) + 1
        local_idx   = part_local_seq[part_name]
        filename    = f"{output_seq:02d}_Part{pnum}_{local_idx:02d}.png"
        output_path = os.path.join(OUTPUT_DIR, filename)

        _print_slide_start(output_seq, total, part_name, local_idx, tmpl, title)
        t0 = time.perf_counter()

        try:
            _call_render(mod, slide, output_path)
            ok = True
        except Exception as e:
            ok = False
            errors.append(f"#{output_seq:02d} {filename}: {e}")

        elapsed = time.perf_counter() - t0
        _print_slide_done(filename, elapsed, ok)

    wall = time.perf_counter() - wall_start
    _print_footer(total, errors, wall)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
