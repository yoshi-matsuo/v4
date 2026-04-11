#!/usr/bin/env python3
"""
narration_engine_v4.py — Stock Arena V4 ナレーション自動生成エンジン

script.json の各スライドの narration を連結し、
Google Cloud TTS (Chirp3-HD) で1文ずつ音声合成し、
pydub で物理結合 → BGMとダッキングミキシングする。

[BREAK_2S] はSSMLではなく pydub.AudioSegment.silent(2000) として挿入する。
1文ずつ個別APIコールするため「文が長すぎる」エラーは物理的に発生しない。

出力:
  outputs/projects/<PROJECT_NAME>/<PROJECT_NAME>_full_narration.mp3

使用方法:
  python3 narration_engine_v4.py <PROJECT_NAME>
  例: python3 narration_engine_v4.py valuenex_4422
"""

import collections
import io
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time

# ───────────────────────────────────────────────
# 引数チェック
# ───────────────────────────────────────────────
if len(sys.argv) < 2:
    print("使用方法: python3 narration_engine_v4.py <PROJECT_NAME>")
    print("例:       python3 narration_engine_v4.py valuenex_4422")
    sys.exit(1)

PROJECT_NAME = sys.argv[1]

# ───────────────────────────────────────────────
# ログカラー（他の定数より先に定義）
# ───────────────────────────────────────────────
RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"; CYAN = "\033[96m"

# ───────────────────────────────────────────────
# パス定数
# ───────────────────────────────────────────────
HERE        = os.path.dirname(os.path.abspath(__file__))
SCRIPT_JSON = os.path.join(HERE, "script.json")
OUT_DIR     = os.path.join(HERE, "outputs", "projects", PROJECT_NAME)
SLIDES_DIR  = os.path.join(OUT_DIR, "slides")
TEMP_MP3    = os.path.join(OUT_DIR, "temp_narration.mp3")
FINAL_MP3   = os.path.join(OUT_DIR, f"{PROJECT_NAME}_full_narration.mp3")
FINAL_VIDEO = os.path.join(OUT_DIR, f"{PROJECT_NAME}_final_video.mp4")

# BGM: Stock Arena V4 シリーズ共通アセット（固定パス）
BGM_PATH        = "/Users/matsuoyoshihiro/v4/outputs/assets/audio/v4_standard_bgm.mp3"

# 共通素材ディレクトリ
STOCK_DIR       = "/Users/matsuoyoshihiro/v4/outputs/images/stock"
BACKGROUNDS_DIR = "/Users/matsuoyoshihiro/v4/outputs/assets/backgrounds"

# 認証キー（jstock プロジェクトの共有アセットを参照）
_JSTOCK_DIR     = os.path.join(os.path.dirname(HERE), "jstock")
CREDENTIAL_JSON = os.path.join(_JSTOCK_DIR, "credential.json")

# ───────────────────────────────────────────────
# TTS 設定
# ───────────────────────────────────────────────
TTS_VOICE         = "ja-JP-Chirp3-HD-Schedar"
TTS_SPEAKING_RATE = 1.15
TTS_MAX_CHARS     = 150   # 1トークンあたりの最大文字数（これを超えたら読点で再分割）

# ───────────────────────────────────────────────
# BGM ミキシング設定
# ───────────────────────────────────────────────
BGM_INTRO_MS       = 2000   # イントロ（BGMのみ）: 2秒
BGM_OUTRO_MS       = 8000   # アウトロ（BGMのみ）: 8秒
BGM_FADEOUT_MS     = 5000   # アウトロのフェードアウト: 5秒
BGM_DUCK_DB        = -20    # ナレーション中のBGM音量低減
BGM_DUCK_FADE_MS   = 700    # ダッキング開始フェード: 0.7秒
BGM_UNDUCK_FADE_MS = 3000   # アンダッキング復帰フェード: 3秒

# 内部マーカー（[BREAK_2S] を配列内で識別するための定数）
_BREAK_TOKEN = "__BREAK_2S__"

# ───────────────────────────────────────────────
# 読み仮名辞書（起動時1回ロード）
# ───────────────────────────────────────────────
_PRONUNCIATION_DICT_PATH = os.path.join(HERE, "pronunciation_dict.json")
_PRONUNCIATION_DICT: list[tuple[str, str]] = []   # [(original, reading), ...] 長さ降順

def _load_pronunciation_dict() -> None:
    """
    pronunciation_dict.json をロードし、誤爆防止のため長さ降順にソートして保持する。
    ファイルが存在しない場合は警告のみ出力して続行する。
    """
    global _PRONUNCIATION_DICT
    if not os.path.exists(_PRONUNCIATION_DICT_PATH):
        print(f"  {YELLOW}⚠{RESET}  pronunciation_dict.json が見つかりません（置換スキップ）")
        return
    try:
        with open(_PRONUNCIATION_DICT_PATH, encoding="utf-8") as f:
            raw: dict = json.load(f)
        # キーを文字数の長い順にソートして部分置換の誤爆を防ぐ
        _PRONUNCIATION_DICT = sorted(raw.items(), key=lambda kv: len(kv[0]), reverse=True)
        print(f"  {DIM}読み仮名辞書: {len(_PRONUNCIATION_DICT)} 件ロード{RESET}")
    except Exception as e:
        print(f"  {YELLOW}⚠{RESET}  pronunciation_dict.json の読み込みに失敗しました: {e}")

_load_pronunciation_dict()

# ───────────────────────────────────────────────
# ログヘルパー
# ───────────────────────────────────────────────
def _ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def _fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def _info(msg): print(f"  {DIM}…{RESET}  {msg}", end="\r", flush=True)
def _head(msg): print(f"\n{BOLD}{msg}{RESET}")
def _sep():     print(f"{BOLD}{'─' * 64}{RESET}")


# ───────────────────────────────────────────────
# ① ストック画像バリエーション管理
# ───────────────────────────────────────────────

class VariantPicker:
    """
    同一ベース画像パスに対し、連番バリエーション (_01, _02 ...) を
    シャッフルしてラウンドロビンで返す。重複使用を最大限回避する。

    解決ルール（優先順）:
        1. `{stem}_01{ext}`, `{stem}_02{ext}` ... が存在 → それらをシャッフルRR
        2. バリエーションなし・ベース自体が存在        → ベース画像を返す
        3. どちらも存在しない                         → None を返す（警告済み）
    """

    def __init__(self) -> None:
        # key: base_path → {"variants": list[str], "queue": deque[str]}
        self._state: dict[str, dict] = {}

    def _resolve_variants(self, base_path: str) -> list[str]:
        """base_path に対応する使用可能ファイルリストを返す（キャッシュなし）。"""
        import glob as _glob
        stem, ext = os.path.splitext(base_path)
        variants = sorted(_glob.glob(f"{stem}_*{ext}"))
        if variants:
            return variants
        if os.path.exists(base_path):
            return [base_path]
        return []

    def pick(self, base_path: str) -> str | None:
        """
        base_path に対し次のバリエーションファイルパスを返す。
        - 初回: バリエーション一覧をシャッフルしてキューに積む
        - 枯渇時: 再シャッフルしてリセット（ラウンドロビン）
        - 存在するファイルが皆無: None を返す
        """
        if base_path not in self._state:
            variants = self._resolve_variants(base_path)
            if not variants:
                return None
            shuffled = variants[:]
            random.shuffle(shuffled)
            self._state[base_path] = {
                "variants": variants,
                "queue":    collections.deque(shuffled),
            }

        state = self._state[base_path]
        if not state["queue"]:
            # 全バリエーション使い切り → 再シャッフルしてリセット
            refreshed = state["variants"][:]
            random.shuffle(refreshed)
            state["queue"] = collections.deque(refreshed)

        return state["queue"].popleft()

    def summary(self) -> str:
        """ログ用: 各ベース画像のバリエーション枚数を返す。"""
        return ", ".join(
            f"{os.path.basename(k)}({len(v['variants'])}枚)"
            for k, v in self._state.items()
        )


# ───────────────────────────────────────────────
# ① 共通資産ピッカー（stock / backgrounds）
# ───────────────────────────────────────────────

class AssetPicker:
    """
    共通資産（stock / backgrounds）から template_type に基づいてスライド素材を選択。

    template_type マッピング:
        "title", "Template A" → stock カテゴリ画像（縦長）
        "impact", "Template S" → backgrounds 横長背景
        その他                 → stock（デフォルト）

    各プールはラウンドロビンで消費し、枯渇したら先頭に戻る。
    指定プールが空の場合は他方のプールへ自動フォールバックし、
    絶対に None を返さないよう保証する（両方空の場合のみ None）。
    """

    _TEMPLATE_TO_KIND: dict[str, str] = {
        "title":      "stock",
        "Template A": "stock",
        "impact":     "bg",
        "Template S": "bg",
    }

    def __init__(self) -> None:
        import glob as _glob

        # ── backgrounds プール ────────────────────────────────────────
        bgs = sorted(_glob.glob(os.path.join(BACKGROUNDS_DIR, "*.png")))
        random.shuffle(bgs)
        self._bg_pool: list[str] = bgs
        self._bg_idx: int = 0

        # ── stock カテゴリ別プール + 全体プール ──────────────────────
        self._cat_pools: dict[str, list[str]] = {}
        self._cat_idx:   dict[str, int]       = {}
        all_stock: list[str] = []

        if os.path.isdir(STOCK_DIR):
            for cat in sorted(os.listdir(STOCK_DIR)):
                cat_dir = os.path.join(STOCK_DIR, cat)
                if not os.path.isdir(cat_dir):
                    continue
                imgs = sorted(_glob.glob(os.path.join(cat_dir, "*.png")))
                if imgs:
                    pool = imgs[:]
                    random.shuffle(pool)
                    self._cat_pools[cat] = pool
                    self._cat_idx[cat]   = 0
                    all_stock.extend(imgs)

        random.shuffle(all_stock)
        self._stock_pool: list[str] = all_stock
        self._stock_idx: int = 0

    # ── 内部ユーティリティ ──────────────────────────────────────────

    def _rr(self, pool: list[str], idx: int) -> tuple[str | None, int]:
        """プールからラウンドロビンで1枚取り出し、(path, next_idx) を返す。"""
        if not pool:
            return None, idx
        return pool[idx % len(pool)], idx + 1

    # ── 公開メソッド ────────────────────────────────────────────────

    def pick_background(self) -> str | None:
        """backgrounds フォルダからラウンドロビンで1枚返す。"""
        path, self._bg_idx = self._rr(self._bg_pool, self._bg_idx)
        return path

    def pick_stock(self, category: str | None = None) -> str | None:
        """stock フォルダからラウンドロビンで1枚返す。category 指定で絞り込み可。"""
        if category and category in self._cat_pools:
            pool = self._cat_pools[category]
            idx  = self._cat_idx[category]
            path, self._cat_idx[category] = self._rr(pool, idx)
            return path
        path, self._stock_idx = self._rr(self._stock_pool, self._stock_idx)
        return path

    def resolve(self, slide: dict) -> str | None:
        """
        template_type に基づいて素材パスを返す。
        指定プールが空の場合は他方へフォールバックし、絶対 None を返さないよう保証する。
        """
        ttype    = slide.get("template_type", "").strip()
        category = slide.get("category", "").strip() or None
        kind     = self._TEMPLATE_TO_KIND.get(ttype, "stock")

        if kind == "bg":
            path = self.pick_background()
            return path if path else self.pick_stock(category)
        else:
            path = self.pick_stock(category)
            return path if path else self.pick_background()


# ───────────────────────────────────────────────
# ② スライド収集
# ───────────────────────────────────────────────
PART_ORDER = ["Part 1", "Part 2", "Part 3", "Part 4", "Part 5", "Part 6", "Part 7"]
_PART_NUM  = {"Part 1": 1, "Part 2": 2, "Part 3": 3, "Part 4": 4, "Part 5": 5,
              "Part 6": 6, "Part 7": 7}


def collect_slides(script_json_path: str) -> tuple[list[dict], str | None]:
    """
    script.json を読み、slide_engine_v4.py が生成した完成済みスライド画像を
    そのまま png_path にセットして返す。素材収集・コピー・リネームは行わない。

    ファイル名規則（slide_engine と同一）:
        {output_seq:02d}_Part{pnum}_{idx:02d}.png
        - output_seq : pure_image をスキップした実出力連番
        - pnum       : パート番号 (1–5)
        - idx        : パート内スライド番号 (1始まり)

    pure_image スライド:
        slide_engine はこれをスキップするため対応ファイルが存在しない。
        代わりに image_path（例: 01_Part1_00.png）を SLIDES_DIR 内で直接参照する。

    dict 構造:
        part          : "Part 1" 等
        slide_index   : パート内インデックス (1始まり、slide_engine の idx と一致)
        narration     : ナレーションテキスト
        template_type : script.json の template_type
        png_path      : ffmpeg に渡す PNG の絶対パス（SLIDES_DIR 内の完成済みファイル）
    """
    with open(script_json_path, encoding="utf-8") as f:
        data = json.load(f)

    all_slides: list[dict] = []
    output_seq     = 0   # 全体通し連番（slide_engine と同一ロジック）
    part_local_seq: dict[str, int] = {}  # パート内連番（同上）
    missing        = 0

    for part in PART_ORDER:
        pnum = _PART_NUM.get(part, 0)
        for raw_slide in data["script"].get(part, []):
            ttype     = raw_slide.get("template_type", "").strip()
            narration = raw_slide.get("narration", "").strip()

            if ttype == "pure_image":
                # 探索順:
                #   1. image_path をそのまま絶対パスとして確認
                #   2. HERE 基準の相対パスとして解決（"outputs/assets/..." 形式に対応）
                #   3. SLIDES_DIR / basename で確認
                raw_img = (raw_slide.get("image_path") or "").strip()
                png_path = None
                candidates = [
                    raw_img if os.path.isabs(raw_img) else None,
                    os.path.join(HERE, raw_img) if raw_img else None,
                    os.path.join(SLIDES_DIR, os.path.basename(raw_img)) if raw_img else None,
                ]
                # image_path が未設定の場合、SLIDES_DIR 内の *_Part{pnum}_00.png を探索
                if pnum:
                    import glob as _glob
                    pattern = os.path.join(SLIDES_DIR, f"*_Part{pnum}_00.png")
                    for found in sorted(_glob.glob(pattern)):
                        candidates.append(found)
                for candidate in candidates:
                    if candidate and os.path.exists(candidate):
                        png_path = candidate
                        break

                if not png_path:
                    _fail(f"{part} pure_image 画像なし: {raw_img!r}")
                    missing += 1
                else:
                    _info(f"{part} pure_image → {os.path.basename(png_path)}          ")
            else:
                # slide_engine が生成したファイルを参照（命名規則を完全再現）
                output_seq += 1
                part_local_seq[part] = part_local_seq.get(part, 0) + 1
                local_idx  = part_local_seq[part]
                filename   = f"{output_seq:02d}_Part{pnum}_{local_idx:02d}.png"
                png_path   = os.path.join(SLIDES_DIR, filename)
                if not os.path.exists(png_path):
                    _fail(f"{part} スライド画像なし: {filename}")
                    png_path = None
                    missing += 1
                else:
                    _info(f"{part} → {filename}          ")

            all_slides.append({
                "part":          part,
                "narration":     narration,
                "template_type": ttype,
                "png_path":      png_path,
            })

    intro_png = all_slides[0]["png_path"] if all_slides else None
    _ok(
        f"スライド収集: {len(all_slides)} スライド  "
        f"(output_seq={output_seq} / 欠損={missing} / "
        f"イントロ: {os.path.basename(intro_png) if intro_png else 'なし'})"
    )
    return all_slides, intro_png


def build_narration_text(script_json_path: str) -> str:
    """script.json の narration フィールドを順番に連結して1本の原稿テキストを返す。"""
    with open(script_json_path, encoding="utf-8") as f:
        data = json.load(f)

    script: dict = data["script"]
    blocks: list[str] = []
    total = 0

    for part in PART_ORDER:
        slides = script.get(part, [])
        for slide in slides:
            narr = slide.get("narration", "").strip()
            if narr:
                blocks.append(narr)
                total += 1

    raw = "\n".join(blocks)
    _ok(f"ナレーション抽出完了: {total} スライド / {len(raw)} 文字")
    return raw


# ───────────────────────────────────────────────
# ② テキストクリーニング
# ───────────────────────────────────────────────
def _clean_for_tts(text: str) -> str:
    """TTSエラー原因となる記号・構文をクリーニングする。[BREAK_2S] は保持する。"""
    # 読み仮名辞書置換（長さ降順適用済みのため誤爆なし）
    for original, reading in _PRONUNCIATION_DICT:
        text = text.replace(original, reading)
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'(\d),(\d)', r'\1\2', text)          # 数字カンマ除去
    text = re.sub(r'[——―]+', '。', text)                 # 長いダッシュ → 句点
    text = re.sub(r'[……\.]{2,}', '。', text)             # 三点リーダー → 句点
    text = re.sub(r'\n{3,}', '\n\n', text)               # 過剰空行を縮小
    return text.strip()


# ───────────────────────────────────────────────
# ③ トークン分割（1文ずつ＋ブレークマーカー）
# ───────────────────────────────────────────────
def _split_long(text: str, max_chars: int = TTS_MAX_CHARS) -> list[str]:
    """150文字超のテキストを読点・スペースで再分割する。"""
    if len(text) <= max_chars:
        return [text]

    result: list[str] = []
    # 読点で分割を試みる
    sub_parts = re.split(r'(?<=、)', text)
    current = ""
    for sp in sub_parts:
        if len(current) + len(sp) <= max_chars:
            current += sp
        else:
            if current.strip():
                result.append(current.strip())
            # スペースでも長い場合は文字数で強制分割
            if len(sp) > max_chars:
                for i in range(0, len(sp), max_chars):
                    chunk = sp[i:i + max_chars].strip()
                    if chunk:
                        result.append(chunk)
                current = ""
            else:
                current = sp
    if current.strip():
        result.append(current.strip())

    return [r for r in result if r]


def tokenize(raw_text: str) -> list[str]:
    """
    テキストを1文ずつのトークン配列に変換する。

    - 区切り文字: 。！？ / 改行 / [BREAK_2S]
    - [BREAK_2S] は _BREAK_TOKEN として配列内に保持
    - 150文字超のトークンは読点・スペースでさらに再分割
    返り値: テキストトークン または _BREAK_TOKEN の配列
    """
    # [BREAK_2S] を改行で囲った内部マーカーに置換（独立したセグメントにする）
    text = _clean_for_tts(raw_text)
    text = text.replace("[BREAK_2S]", f"\n{_BREAK_TOKEN}\n")

    # 句点・感嘆符・疑問符を区切りとして分割（区切り文字を直前のトークンに付ける）
    segments: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line == _BREAK_TOKEN:
            segments.append(_BREAK_TOKEN)
            continue
        # 句点系で分割（区切り文字を前のトークンに保持）
        parts = re.split(r'(?<=[。！？])', line)
        for p in parts:
            p = p.strip()
            if p:
                segments.append(p)

    # 150文字超のトークンをさらに再分割
    tokens: list[str] = []
    for seg in segments:
        if seg == _BREAK_TOKEN:
            tokens.append(_BREAK_TOKEN)
        else:
            tokens.extend(_split_long(seg, TTS_MAX_CHARS))

    return [t for t in tokens if t]


# ───────────────────────────────────────────────
# ④ Google Cloud TTS 合成（1文ずつ）
# ───────────────────────────────────────────────
def _ssml_escape(text: str) -> str:
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def _build_ssml(sentence: str) -> str:
    """
    sentence を SSML 文字列に変換する。
    処理順:
      1. XML 特殊文字をエスケープ（&, <, >）
      2. 句点「。」の直後に <break time='600ms'/> を挿入（文末の間を確保）
      3. <speak> タグで包む
    ※ pronunciation_dict による読み仮名置換は _clean_for_tts で完了済みのため競合しない。
    """
    escaped = _ssml_escape(sentence)
    escaped = escaped.replace('。', "。<break time='600ms'/>")
    return f"<speak>{escaped}</speak>"


def _gcloud_tts_call(client, voice_params, audio_config, sentence: str) -> bytes:
    """1文を TTS 合成し MP3 バイト列を返す。最大2回リトライ。"""
    from google.cloud import texttospeech

    ssml = _build_ssml(sentence)

    for attempt in range(1, 3):
        try:
            synthesis_input = texttospeech.SynthesisInput(ssml=ssml)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice_params,
                audio_config=audio_config,
            )
            if not response.audio_content or len(response.audio_content) < 256:
                raise ValueError(f"音声データが空または小さすぎます ({len(response.audio_content)} bytes)")
            return response.audio_content

        except Exception as e:
            err = str(e)
            # SSMLエラーの場合はプレーンテキストでリトライ
            if "400" in err and attempt == 1:
                try:
                    plain_input = texttospeech.SynthesisInput(text=sentence)
                    r2 = client.synthesize_speech(
                        input=plain_input, voice=voice_params, audio_config=audio_config
                    )
                    if r2.audio_content and len(r2.audio_content) >= 256:
                        return r2.audio_content
                except Exception:
                    pass
            if attempt < 2:
                time.sleep(2)
            else:
                raise


def synthesize_narration(raw_text: str, output_path: str) -> str:
    """
    テキスト全体を1文ずつ TTS 合成し pydub で物理結合して output_path に保存する。
    [BREAK_2S] は AudioSegment.silent(2000ms) として挿入する。
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise RuntimeError("pydub が未インストールです。\n  pip3 install pydub")

    # 認証設定
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        if os.path.exists(CREDENTIAL_JSON):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIAL_JSON
        else:
            raise FileNotFoundError(
                f"Google Cloud 認証ファイルが見つかりません: {CREDENTIAL_JSON}\n"
                "GOOGLE_APPLICATION_CREDENTIALS 環境変数を設定するか credential.json を配置してください。"
            )

    try:
        from google.cloud import texttospeech
    except ImportError:
        raise RuntimeError("google-cloud-texttospeech が未インストールです。\n  pip3 install google-cloud-texttospeech")

    client = texttospeech.TextToSpeechClient()
    voice_params = texttospeech.VoiceSelectionParams(language_code="ja-JP", name=TTS_VOICE)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=TTS_SPEAKING_RATE,
    )

    # ── トークン分割 ──────────────────────────────────────────────
    tokens = tokenize(raw_text)
    text_tokens = [t for t in tokens if t != _BREAK_TOKEN]
    break_count = tokens.count(_BREAK_TOKEN)
    _ok(f"トークン分割: {len(tokens)} トークン "
        f"({len(text_tokens)} 文 + {break_count} ブレーク, 最大 {TTS_MAX_CHARS} 文字/文)")

    # ── 1文ずつTTS → pydub結合 ────────────────────────────────────
    segments: list[AudioSegment] = []
    failed: list[int] = []
    tts_count = 0

    for i, tok in enumerate(tokens, 1):
        if tok == _BREAK_TOKEN:
            segments.append(AudioSegment.silent(duration=2000))
            _info(f"  [{i:03d}/{len(tokens):03d}]  [BREAK_2S] → 2秒無音を挿入            ")
            continue

        tts_count += 1
        _info(f"  [{i:03d}/{len(tokens):03d}]  TTS中: {tok[:40]}…          ")

        try:
            mp3_bytes = _gcloud_tts_call(client, voice_params, audio_config, tok)
            seg = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
            segments.append(seg)
        except Exception as e:
            msg = str(e).split("\n")[0][:80]
            print(f"\n  {RED}✗{RESET}  [{i:03d}] 失敗: {msg}")
            failed.append(i)
            # 失敗した文は無音(500ms)で代替して続行
            segments.append(AudioSegment.silent(duration=500))

    print()  # \r のカーソルをクリア

    if failed:
        print(f"  {YELLOW}⚠{RESET}  {len(failed)} 文が失敗し無音(500ms)で代替: トークン番号 {failed}")

    if not segments:
        raise RuntimeError("音声セグメントが1つも生成されませんでした")

    # ── 全セグメントを結合してエクスポート ────────────────────────
    _info("pydub で全セグメントを結合中…")
    combined = segments[0]
    for seg in segments[1:]:
        combined += seg

    total_sec = len(combined) / 1000
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    combined.export(output_path, format="mp3", bitrate="192k")

    size_kb = os.path.getsize(output_path) / 1024
    _ok(f"TTS 結合完了: {len(tokens)} トークン → {total_sec:.1f}秒 / {size_kb:,.0f} KB")
    return output_path


# ───────────────────────────────────────────────
# ④-b スライドごとの TTS 合成（音声長記録付き）
# ───────────────────────────────────────────────
def synthesize_per_slide(
    slides: list[dict],
    output_path: str,
    client,
    voice_params,
    audio_config,
) -> tuple[str, list[int]]:
    """
    スライドごとにナレーションを TTS 合成し、各スライドの音声長(ms)を記録する。

    Returns:
        (output_path, slide_durations_ms)
            slide_durations_ms[i] は slides[i] の音声長（ミリ秒）。
    """
    from pydub import AudioSegment

    all_segments: list[AudioSegment] = []
    slide_durations_ms: list[int] = []
    total_tokens = sum(len(tokenize(s["narration"])) for s in slides if s["narration"])
    processed = 0

    for si, slide in enumerate(slides, 1):
        narration = slide["narration"]
        if not narration:
            slide_durations_ms.append(0)
            continue

        tokens = tokenize(narration)
        slide_segs: list[AudioSegment] = []
        failed_local: list[int] = []

        for tok in tokens:
            processed += 1
            if tok == _BREAK_TOKEN:
                slide_segs.append(AudioSegment.silent(duration=2000))
                _info(f"  [{processed:03d}/{total_tokens:03d}]  [BREAK_2S] → 2秒無音          ")
                continue

            _info(f"  [{processed:03d}/{total_tokens:03d}]  スライド{si:02d} TTS: {tok[:35]}…  ")
            try:
                mp3_bytes = _gcloud_tts_call(client, voice_params, audio_config, tok)
                slide_segs.append(AudioSegment.from_mp3(io.BytesIO(mp3_bytes)))
            except Exception as e:
                msg = str(e).split("\n")[0][:80]
                print(f"\n  {RED}✗{RESET}  スライド{si} トークン失敗: {msg}")
                failed_local.append(processed)
                slide_segs.append(AudioSegment.silent(duration=500))

        if failed_local:
            print(f"  {YELLOW}⚠{RESET}  スライド{si}: {len(failed_local)} トークン失敗")

        if slide_segs:
            combined_slide = slide_segs[0]
            for seg in slide_segs[1:]:
                combined_slide += seg
        else:
            combined_slide = AudioSegment.silent(duration=500)

        slide_durations_ms.append(len(combined_slide))
        all_segments.append(combined_slide)

    print()

    if not all_segments:
        raise RuntimeError("音声セグメントが1つも生成されませんでした")

    _info("pydub で全スライドを結合中…")
    combined_all = all_segments[0]
    for seg in all_segments[1:]:
        combined_all += seg

    total_sec = len(combined_all) / 1000
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    combined_all.export(output_path, format="mp3", bitrate="192k")

    size_kb = os.path.getsize(output_path) / 1024
    _ok(
        f"TTS 結合完了: {len(slides)} スライド → {total_sec:.1f}秒 / {size_kb:,.0f} KB\n"
        f"  スライド別音声長(秒): "
        + " / ".join(f"{d/1000:.1f}" for d in slide_durations_ms)
    )
    return output_path, slide_durations_ms


# ───────────────────────────────────────────────
# ⑥ 動画合成（ffmpeg concat demuxer）
# ───────────────────────────────────────────────
def build_video(
    intro_png: str | None,
    slides: list[dict],
    slide_durations_ms: list[int],
    audio_path: str,
    output_path: str,
) -> str:
    """
    スライド画像 + 音声（BGM合成済み）から MP4 を生成する。

    タイムライン:
        - イントロカード: BGM_INTRO_MS (6秒)
        - スライド[0..N-2]: 各スライドの音声長
        - スライド[N-1]: 音声長 + BGM_UNDUCK_FADE_MS + BGM_OUTRO_MS (11秒)
    """
    import subprocess, glob as _glob

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg が見つかりません。brew install ffmpeg でインストールしてください。")

    # ── concat リスト構築 ──────────────────────────────────────────────
    concat_lines: list[str] = []

    # イントロカード（6秒）
    if intro_png and os.path.exists(intro_png):
        concat_lines += [f"file '{intro_png}'", f"duration {BGM_INTRO_MS / 1000:.6f}"]
    else:
        _fail(f"イントロカードが見つかりません: {intro_png}  →  先頭スライドで代替します")

    # スライドカード
    # png_path が有効な「最後のスライド」を先に特定する
    # （pure_image など画像なしスライドが末尾にある場合の対策）
    last_valid_idx = None
    last_valid_png = None
    for i in range(len(slides) - 1, -1, -1):
        png = slides[i].get("png_path")
        if png and os.path.exists(png):
            last_valid_idx = i
            last_valid_png = png
            break

    for i, slide in enumerate(slides):
        png = slide.get("png_path")
        if not png or not os.path.exists(png):
            _fail(f"  スライド{i+1} PNG が見つかりません: {png}")
            continue

        dur_ms = slide_durations_ms[i] if i < len(slide_durations_ms) else 3000
        # 有効な最終スライドにアンダック復帰 + アウトロ分を加算
        if i == last_valid_idx:
            dur_ms += BGM_UNDUCK_FADE_MS + BGM_OUTRO_MS

        concat_lines += [f"file '{png}'", f"duration {dur_ms / 1000:.6f}"]

    # ffmpeg concat demuxer は最終エントリを末尾に重複追加する必要がある
    if last_valid_png:
        concat_lines.append(f"file '{last_valid_png}'")

    # concat ファイル書き出し
    concat_path = os.path.join(OUT_DIR, "_concat_list.txt")
    with open(concat_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_lines) + "\n")

    # ── ffmpeg コマンド ────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fd, tmp_video = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_path,
        "-i", audio_path,
        "-vf", (
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
            "format=yuv420p"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        tmp_video,
    ]

    _info("ffmpeg で動画を合成中…（数分かかることがあります）")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # 一時ファイルを残してデバッグ用途に
        _fail("ffmpeg エラー詳細:")
        print(result.stderr[-2000:])
        raise RuntimeError(f"ffmpeg が終了コード {result.returncode} で失敗しました")

    shutil.move(tmp_video, output_path)

    # concat リスト削除
    if os.path.exists(concat_path):
        os.remove(concat_path)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    _ok(f"動画合成完了: {os.path.basename(output_path)} ({size_mb:.1f} MB)")
    return output_path


# ───────────────────────────────────────────────
# ⑤ BGM ミキシング（スムーズダッキング）
# ───────────────────────────────────────────────
def mix_with_bgm(narration_path: str, output_path: str, bgm_path: str = BGM_PATH) -> str:
    """ナレーション MP3 に BGM をダッキング合成し output_path へ書き出す。"""
    try:
        from pydub import AudioSegment
    except ImportError:
        raise RuntimeError("pydub が未インストールです。\n  pip3 install pydub")

    if not os.path.exists(bgm_path):
        raise FileNotFoundError(f"BGMファイルが見つかりません: {bgm_path}")

    _info("ナレーション音声を読み込み中…")
    narration = AudioSegment.from_mp3(narration_path)
    _ok(f"ナレーション: {len(narration)/1000:.1f} 秒")

    _info("BGMを読み込み中…")
    bgm_orig = AudioSegment.from_mp3(bgm_path)
    _ok(f"BGM: {len(bgm_orig)/1000:.1f} 秒")

    total_needed_ms = BGM_INTRO_MS + len(narration) + BGM_UNDUCK_FADE_MS + BGM_OUTRO_MS

    if len(bgm_orig) < total_needed_ms:
        loops = (total_needed_ms // len(bgm_orig)) + 1
        bgm_full = bgm_orig * loops
    else:
        bgm_full = bgm_orig
    bgm_full = bgm_full[:total_needed_ms]

    _info("BGMダッキング合成中…")

    narr_start      = BGM_INTRO_MS
    narr_end        = narr_start + len(narration)
    duck_fade_start = max(0, narr_start - BGM_DUCK_FADE_MS)
    unduck_fade_end = narr_end + BGM_UNDUCK_FADE_MS

    seg_intro  = bgm_full[:duck_fade_start]
    seg_duck   = bgm_full[duck_fade_start:narr_start].fade(
        to_gain=BGM_DUCK_DB, from_gain=0, start=0,
        duration=max(1, narr_start - duck_fade_start),
    )
    seg_under  = bgm_full[narr_start:narr_end] + BGM_DUCK_DB
    seg_unduck = bgm_full[narr_end:unduck_fade_end].fade(
        from_gain=BGM_DUCK_DB, to_gain=0, start=0,
        duration=max(1, unduck_fade_end - narr_end),
    )
    seg_outro  = bgm_full[unduck_fade_end:total_needed_ms].fade_out(BGM_FADEOUT_MS)

    bgm_track = seg_intro + seg_duck + seg_under + seg_unduck + seg_outro

    narration = narration.set_frame_rate(bgm_track.frame_rate).set_channels(bgm_track.channels)
    final = bgm_track.overlay(narration, position=BGM_INTRO_MS)

    _ok(f"ミキシング完了: {len(final)/1000:.1f} 秒")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    _info(f"{os.path.basename(output_path)} を書き出し中…")
    final.export(tmp, format="mp3", bitrate="192k")
    shutil.move(tmp, output_path)

    size_kb = os.path.getsize(output_path) / 1024
    _ok(f"保存完了: {os.path.basename(output_path)} ({size_kb:,.0f} KB / {len(final)/1000:.1f} 秒)")
    return output_path


# ───────────────────────────────────────────────
# メイン
# ───────────────────────────────────────────────
def main() -> None:
    _sep()
    print(f"{BOLD}  Stock Arena V4  ─  Narration + Video Engine{RESET}")
    _sep()
    print(f"  script.json : {DIM}{SCRIPT_JSON}{RESET}")
    print(f"  slides dir  : {DIM}{SLIDES_DIR}{RESET}")
    print(f"  BGM         : {DIM}{BGM_PATH}{RESET}")
    print(f"  音声出力     : {DIM}{FINAL_MP3}{RESET}")
    print(f"  動画出力     : {DIM}{FINAL_VIDEO}{RESET}")
    print()

    # ── 前提チェック ───────────────────────────────────────────────────
    _head("前提チェック")
    ok = True
    if not os.path.exists(BGM_PATH):
        _fail(f"BGMファイルが見つかりません: {BGM_PATH}")
        ok = False
    else:
        _ok(f"BGM: {BGM_PATH}")

    if not os.path.exists(SCRIPT_JSON):
        _fail(f"script.json が見つかりません: {SCRIPT_JSON}")
        ok = False
    else:
        _ok(f"script.json: {SCRIPT_JSON}")

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(SLIDES_DIR, exist_ok=True)
    _ok(f"slides dir: {SLIDES_DIR}")

    if not ok:
        sys.exit(1)

    # ── STEP 1: スライド収集（script.json + PNG マッピング）────────────
    _head("STEP 1  スライド収集・PNG マッピング")
    try:
        slides, intro_png = collect_slides(SCRIPT_JSON)
    except Exception as e:
        _fail(f"スライド収集失敗: {e}")
        sys.exit(1)

    # 最長トークンのプレビュー
    all_tokens = []
    for s in slides:
        all_tokens.extend(tokenize(s["narration"]))
    max_len = max((len(t) for t in all_tokens if t != _BREAK_TOKEN), default=0)
    print(f"  {DIM}最長トークン: {max_len} 文字（{TTS_MAX_CHARS} 文字以下なら全て安全）{RESET}")

    # ── STEP 2: Google Cloud TTS（スライド単位・音声長記録）──────────
    _head("STEP 2  Google Cloud TTS 音声合成 (Chirp3-HD)  ─  スライド単位結合方式")
    print(f"  voice={TTS_VOICE}  rate={TTS_SPEAKING_RATE}  max_chars={TTS_MAX_CHARS}")

    # 認証設定
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        _jstock = os.path.join(os.path.dirname(HERE), "jstock")
        cred_path = os.path.join(_jstock, "credential.json")
        if os.path.exists(cred_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        else:
            _fail(f"Google Cloud 認証ファイルが見つかりません: {cred_path}")
            sys.exit(1)

    try:
        from google.cloud import texttospeech
        from pydub import AudioSegment  # noqa: F401 – import check
    except ImportError as e:
        _fail(f"必要ライブラリが未インストール: {e}")
        sys.exit(1)

    client      = texttospeech.TextToSpeechClient()
    voice_params = texttospeech.VoiceSelectionParams(language_code="ja-JP", name=TTS_VOICE)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=TTS_SPEAKING_RATE,
    )

    t0 = time.perf_counter()
    try:
        _, slide_durations_ms = synthesize_per_slide(
            slides, TEMP_MP3, client, voice_params, audio_config
        )
    except Exception as e:
        _fail(f"TTS 合成失敗: {e}")
        sys.exit(1)
    _ok(f"TTS 完了 ({time.perf_counter()-t0:.1f}秒)")

    # ── STEP 3: BGM ミキシング ────────────────────────────────────────
    _head("STEP 3  BGMミキシング（スムーズダッキング）")
    t1 = time.perf_counter()
    try:
        mix_with_bgm(TEMP_MP3, FINAL_MP3)
    except Exception as e:
        _fail(f"BGMミキシング失敗: {e}")
        sys.exit(1)
    _ok(f"ミキシング完了 ({time.perf_counter()-t1:.1f}秒)")

    # ── STEP 4: 動画合成 ────────────────────────────────────────────────
    _head("STEP 4  動画合成（ffmpeg concat + 音声合成）")
    t2 = time.perf_counter()
    try:
        build_video(intro_png, slides, slide_durations_ms, FINAL_MP3, FINAL_VIDEO)
    except Exception as e:
        _fail(f"動画合成失敗: {e}")
        sys.exit(1)
    _ok(f"動画合成完了 ({time.perf_counter()-t2:.1f}秒)")

    # ── STEP 5: クリーンアップ ────────────────────────────────────────
    _head("STEP 5  クリーンアップ")
    if os.path.exists(TEMP_MP3):
        os.remove(TEMP_MP3)
        _ok(f"一時ファイルを削除: {os.path.basename(TEMP_MP3)}")

    # ── 完了サマリ ─────────────────────────────────────────────────────
    print()
    _sep()
    mp3_kb  = os.path.getsize(FINAL_MP3)  / 1024        if os.path.exists(FINAL_MP3)  else 0
    mp4_mb  = os.path.getsize(FINAL_VIDEO) / (1024*1024) if os.path.exists(FINAL_VIDEO) else 0
    print(f"{GREEN}{BOLD}  完了！{RESET}")
    print(f"  音声: {FINAL_MP3}  ({mp3_kb:,.0f} KB)")
    print(f"  動画: {FINAL_VIDEO}  ({mp4_mb:.1f} MB)")
    _sep()
    print()


if __name__ == "__main__":
    main()
