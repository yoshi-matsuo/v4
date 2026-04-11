"""
script_engine_v4.py — Stock Arena V4 AIスクリプト生成エンジン
yfinanceでリアルタイムデータを取得し、20分尺・5幕構成の金融ドキュメンタリー台本を生成する。
"""
import json
import json_repair
import re
import time
import yfinance as yf
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

_MODEL = "gemini-2.5-flash"
_MAX_RETRIES = 3
_RETRY_WAIT = 30

_SAFETY_BLOCK_NONE = [
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_NONE"),
]

_SYSTEM_INSTRUCTION = """\
あなたは金融ドキュメンタリー番組『Stock Arena』の専属脚本家です。
提供された【絶対ファクト】の現在株価と通貨単位を絶対的な基準とし、20分尺（8,000文字以上）の冷徹な動画台本を作成してください。

【執筆ルール】
1. 抽象的なポエムを禁止し、具体的な数字・企業名・事例を必ず用いること。通貨単位（円・ドル）を絶対に間違えないこと。
2. 重要な真実を告げる前には、必ず [BREAK_2S] を挿入すること（1台本に10箇所以上）。
3. 結論（Part 5）では「静観」を禁止し、【即時撤退 / 売り推奨 / 押し目買い】等の明確なスタンスと、現在株価に基づいた具体的な撤退ライン（損切り価格）を断言すること。
4. 提供された【絶対ファクト】以外の株価データを捏造した場合はシステムエラーとなるため、厳守すること。
"""

# ── JSON スキーマ定義（5幕・sub_sections 構造） ──────────────────────

_section = {
    "type": "object",
    "required": ["section_title", "narration"],
    "properties": {
        "section_title": {
            "type": "string",
            "description": "このセクションの小見出し（例：「AIの怪物、その正体」）",
        },
        "narration": {
            "type": "string",
            "description": "ナレーション本文。[BREAK_2S] を効果的に挿入し、600文字以上で書くこと。",
        },
    },
}

V4_JSON_SCHEMA = {
    "type": "object",
    "required": [
        "ticker", "company_name",
        "part_1_hook",
        "part_2_the_light",
        "part_3_the_shadow",
        "part_4_the_chart",
        "part_5_the_verdict",
    ],
    "properties": {
        "ticker":       {"type": "string"},
        "company_name": {"type": "string"},

        # ── Part 1: Hook ─────────────────────────────────────────────
        "part_1_hook": {
            "type": "object",
            "description": "陶酔の終焉と現実——視聴者を最初の1分で引き込む衝撃の導入",
            "required": ["catch_copy", "opening_narration", "sub_sections"],
            "properties": {
                "catch_copy": {
                    "type": "string",
                    "description": (
                        "サムネ・冒頭10秒に使う強烈な一言。"
                        "「致命的な罠」「ウォール街が恐れる真実」など、"
                        "不安と好奇心を同時に爆発させるコピー。"
                    ),
                },
                "opening_narration": {
                    "type": "string",
                    "description": (
                        "番組冒頭のナレーション（800文字以上）。"
                        "[BREAK_2S] を2箇所以上挿入すること。"
                        "「この動画を最後まで見た者だけが、生き残れる」という緊張感を持たせること。"
                    ),
                },
                "sub_sections": {
                    "type": "array",
                    "description": "Hook パートを構成する小セクション（2〜3個）",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": _section,
                },
            },
        },

        # ── Part 2: The Light ─────────────────────────────────────────
        "part_2_the_light": {
            "type": "object",
            "description": "圧倒的な実需と光の側面——初心者が「今すぐ買いたい」と熱狂する強気論",
            "required": ["bull_thesis", "sub_sections"],
            "properties": {
                "bull_thesis": {
                    "type": "string",
                    "description": (
                        "この銘柄の強気論を一段落で要約（300文字以上）。"
                        "「なぜ機関投資家・メディアが絶賛しているのか」を具体的数字で示すこと。"
                    ),
                },
                "sub_sections": {
                    "type": "array",
                    "description": "Light パートを構成する小セクション（3〜5個）。各セクションで異なるブル材料を掘り下げること。",
                    "minItems": 3,
                    "maxItems": 5,
                    "items": _section,
                },
            },
        },

        # ── Part 3: The Shadow ────────────────────────────────────────
        "part_3_the_shadow": {
            "type": "object",
            "description": "SBCやインサイダー売却など、光に隠れた致命的リスク——前パートの熱狂を完全に破壊する冷水",
            "required": ["fatal_weakness", "sub_sections"],
            "properties": {
                "fatal_weakness": {
                    "type": "string",
                    "description": (
                        "この銘柄の構造的欠陥・最悪シナリオを一段落で断言（300文字以上）。"
                        "「もし〇〇が起きれば、現在株価から何%下落するか」を具体的に示すこと。"
                    ),
                },
                "sub_sections": {
                    "type": "array",
                    "description": (
                        "Shadow パートを構成する小セクション（3〜5個）。"
                        "最初のセクションの narration は必ず [BREAK_2S] から書き始めること。"
                        "SBC（株式報酬）・インサイダー売却・財務リスク・競合圧力など、それぞれ異なるリスクを深掘りすること。"
                    ),
                    "minItems": 3,
                    "maxItems": 5,
                    "items": _section,
                },
            },
        },

        # ── Part 4: The Chart ─────────────────────────────────────────
        "part_4_the_chart": {
            "type": "object",
            "description": "現在株価と移動平均線に基づいた、機関と大衆の心理戦描写",
            "required": ["key_levels", "chart_reading", "sub_sections"],
            "properties": {
                "key_levels": {
                    "type": "object",
                    "description": "絶対ファクトの株価データに基づいた、具体的な価格水準（数値の捏造禁止）",
                    "required": ["support", "resistance", "retreat_line", "entry_point"],
                    "properties": {
                        "support": {
                            "type": "string",
                            "description": "絶対に割ってはいけないサポートライン。具体的な価格と根拠を記述すること。",
                        },
                        "resistance": {
                            "type": "string",
                            "description": "上値の壁（レジスタンス）。具体的な価格と突破時の目標値を記述すること。",
                        },
                        "retreat_line": {
                            "type": "string",
                            "description": "保有者が即撤退すべき損切りライン。「終値で〇〇を割り込んだら即売却」と具体的な価格で断言すること。",
                        },
                        "entry_point": {
                            "type": "string",
                            "description": "次に買い向かうエントリーポイント。「〇〇まで押したら分割買い」など具体的な価格と戦略を記述すること。",
                        },
                    },
                },
                "chart_reading": {
                    "type": "string",
                    "description": (
                        "必ず「業績の罠は、すでにチャートに現れています」から始まるチャート概要（400文字以上）。"
                        "現在株価と200日移動平均線の位置関係を分析し、「大衆のパニック」「機関の思惑」を読み解くこと。"
                        "テクニカル用語（三尊天井・デッドクロス等）が出るたびに「——これは、〇〇という意味です」と説明を挟むこと。"
                    ),
                },
                "sub_sections": {
                    "type": "array",
                    "description": "Chart パートを構成する小セクション（2〜3個）。出来高・移動平均・トレンドラインなど観点を分けて分析すること。",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": _section,
                },
            },
        },

        # ── Part 5: The Verdict ───────────────────────────────────────
        "part_5_the_verdict": {
            "type": "object",
            "description": "冷徹な最終審判と、現在株価を基準とした具体的な撤退/エントリー価格",
            "required": [
                "investment_judgment",
                "judgment_rationale",
                "survival_strategy",
                "closing_narration",
                "sub_sections",
            ],
            "properties": {
                "investment_judgment": {
                    "type": "string",
                    "enum": ["強気買い", "押し目買い", "売り推奨", "即時撤退"],
                    "description": "「静観」禁止。4択から必ず1つを選び断言すること。",
                },
                "judgment_rationale": {
                    "type": "string",
                    "description": (
                        "上記判断の根拠（400文字以上）。"
                        "Part2〜Part4の分析を統合し、現在株価・PER・200日移動平均線の数値を引用しながら論理的に説明すること。"
                    ),
                },
                "survival_strategy": {
                    "type": "object",
                    "required": ["short_term", "mid_term"],
                    "properties": {
                        "short_term": {
                            "type": "string",
                            "description": "今後1〜3ヶ月の具体的アクション。撤退ライン・エントリー価格を現在株価から計算した具体的数値で示すこと。",
                        },
                        "mid_term": {
                            "type": "string",
                            "description": "今後6〜12ヶ月の見通し。株価を動かすカタリスト（決算・製品発表・規制変更等）を具体的に列挙すること。",
                        },
                    },
                },
                "closing_narration": {
                    "type": "string",
                    "description": (
                        "必ず「生き残るための答えはひとつだ」から始まるアウトロナレーション（1,500文字以上）。"
                        "[BREAK_2S] を2箇所以上挿入すること。"
                        "「静観」「自己責任」の使用禁止。チャンネル登録・いいねの促しを自然に織り込むこと。"
                    ),
                },
                "sub_sections": {
                    "type": "array",
                    "description": "Verdict パートを構成する小セクション（2〜3個）。ブル・ベア・テクニカルの総合評価を段階的に語ること。",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": _section,
                },
            },
        },
    },
}


# ── yfinance リアルタイムデータ取得 ───────────────────────────────────

def _format_market_cap(value) -> str:
    """時価総額を億・兆・Billion・Trillion 表記に変換する。"""
    if value is None:
        return "取得不可"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "取得不可"
    if v >= 1_000_000_000_000:
        return f"{v / 1_000_000_000_000:.2f} 兆（Trillion）"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f} 十億（Billion）"
    if v >= 100_000_000:
        return f"{v / 100_000_000:.2f} 億"
    return f"{v:,.0f}"


def fetch_stock_data(ticker: str) -> dict:
    """
    yfinance を使用してリアルタイム株式データを取得する。

    Args:
        ticker: 銘柄ティッカー。数字4桁のみ（例: "7203"）の場合は ".T" を自動付与。

    Returns:
        currency, current_price, fifty_two_week_high, fifty_two_week_low,
        trailing_pe, market_cap, two_hundred_day_ma を含む辞書。
        取得失敗のフィールドは "取得不可" を返す。
    """
    # 日本株対応：数字4桁のみなら ".T" を付与
    yf_ticker = f"{ticker}.T" if re.fullmatch(r"\d{4}", ticker) else ticker

    print(f"[V4] yfinance データ取得中: {yf_ticker}")
    info = {}
    try:
        stock = yf.Ticker(yf_ticker)
        info = stock.info or {}
    except Exception as e:
        print(f"[V4] yfinance 取得エラー: {e}")

    def get(key, fallback="取得不可"):
        val = info.get(key)
        return val if val is not None else fallback

    currency        = get("currency")
    current_price   = get("currentPrice") or get("regularMarketPrice")
    fifty_two_high  = get("fiftyTwoWeekHigh")
    fifty_two_low   = get("fiftyTwoWeekLow")
    trailing_pe     = get("trailingPE")
    market_cap_raw  = info.get("marketCap")
    two_hundred_ma  = get("twoHundredDayAverage")

    result = {
        "yf_ticker":           yf_ticker,
        "currency":            currency,
        "current_price":       current_price,
        "fifty_two_week_high": fifty_two_high,
        "fifty_two_week_low":  fifty_two_low,
        "trailing_pe":         trailing_pe if trailing_pe != "取得不可" else "N/A",
        "market_cap":          _format_market_cap(market_cap_raw),
        "two_hundred_day_ma":  two_hundred_ma,
    }

    print(
        f"[V4] 取得完了 | 株価: {result['current_price']} {result['currency']} | "
        f"PER: {result['trailing_pe']} | 時価総額: {result['market_cap']}"
    )
    return result


# ── 台本生成メイン関数 ─────────────────────────────────────────────────

def generate_v4_script(ticker: str, market: str, news_text: str) -> dict:
    """
    yfinance のリアルタイムデータと定性ニュースを組み合わせ、
    Stock Arena V4 仕様の5幕構成ドキュメンタリー台本を生成する。

    Args:
        ticker:    銘柄ティッカー（例: 7203, NVDA, PLTR）
        market:    市場区分（例: "JP", "US", "NASDAQ", "東証プライム"）
        news_text: 企業分析データやニュース群のテキスト

    Returns:
        V4_JSON_SCHEMA に準拠した辞書
    """
    # ── Step 1: リアルタイムデータ取得 ──────────────────────────────
    stock = fetch_stock_data(ticker)

    currency       = stock["currency"]
    current_price  = stock["current_price"]
    high_52w       = stock["fifty_two_week_high"]
    low_52w        = stock["fifty_two_week_low"]
    trailing_pe    = stock["trailing_pe"]
    market_cap     = stock["market_cap"]
    ma_200         = stock["two_hundred_day_ma"]

    # ── Step 2: 動的プロンプト構築 ──────────────────────────────────
    prompt = f"""\
以下の【絶対ファクト】と【定性ニュース】のみを使用して、指定の5幕構成で台本を作成せよ。
過去の学習データにある古い株価や数字は一切使用してはならない。

【絶対ファクト（システム自動取得・捏造厳禁）】
銘柄           : {ticker} ({market})
通貨単位       : {currency}
　※ 以降のすべての価格・時価総額は必ずこの通貨単位を使用すること。日本株なら円、米国株ならドル。
現在株価       : {current_price} {currency}
52週レンジ     : {low_52w} - {high_52w} {currency}
PER            : {trailing_pe} 倍
時価総額       : {market_cap}
200日移動平均  : {ma_200} {currency}

【定性ニュース（人間からの入力）】
{news_text}

【生成の絶対ルール】

■ 文字数
- 台本全体で合計8,000文字以上を必ず達成すること。
- 各 narration フィールドは600文字以上、opening_narration・closing_narration は1,500文字以上。

■ [BREAK_2S] の配置
- 台本全体で合計10箇所以上挿入すること。
- 重要な数字・致命的リスク・最終判決の直前に必ず挿入すること。
- part_3_the_shadow の最初のセクション narration は [BREAK_2S] から書き始めること。
- part_4_the_chart の chart_reading は必ず「業績の罠は、すでにチャートに現れています」から書き始めること。
- part_5_the_verdict の closing_narration は必ず「生き残るための答えはひとつだ」から書き始めること。

■ 用語解説（初出時に必ず実施）
- SBC（株式報酬）、逆イールド、上昇ウェッジ、三尊天井、デッドクロス、フリーキャッシュフロー、PER、EPS 等
  専門用語が初めて登場する際は「——これは、〇〇という意味です」と括弧・ダッシュを使って自然に説明すること。

■ 価格水準の具体性
- part_4_the_chart の key_levels は【絶対ファクト】の現在株価・52週レンジ・200日移動平均を根拠とした
  具体的な価格（{currency}）で記述すること。「重要な水準」などの曖昧表現は禁止。

■ 投資判断の断言
- part_5_the_verdict の investment_judgment は「強気買い」「押し目買い」「売り推奨」「即時撤退」の4択から選ぶこと。
- 「静観」「自己責任」は台本全体で使用禁止。

■ データ捏造の禁止
- 【絶対ファクト】に記載されていない株価・時価総額・PERの数値を台本中に使用することは絶対禁止。
- 「取得不可」のフィールドは「データ未取得のため言及しない」として扱うこと。
"""

    # ── Step 3: Gemini API 呼び出し（リトライ付き） ──────────────────
    client = genai.Client(api_key=GEMINI_API_KEY)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            print(f"[V4] 台本生成中... (試行 {attempt}/{_MAX_RETRIES})")
            response = client.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    safety_settings=_SAFETY_BLOCK_NONE,
                    temperature=0.7,
                    max_output_tokens=65536,
                    response_mime_type="application/json",
                    response_schema=V4_JSON_SCHEMA,
                ),
            )
            raw = re.sub(r"```(?:json)?\s*|\s*```", "", response.text).strip()
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = json_repair.loads(raw)

            # 取得済みのリアルタイムデータをルートに付与（呼び出し元で参照可能に）
            result.setdefault("ticker", ticker)
            result["_stock_data"] = stock

            # Part 1 先頭スライドにタイトル画像を強制挿入（LLM出力に依存しない堅牢な後処理）
            try:
                first_slide = result["part_1_hook"]["sub_sections"][0]
                first_slide["template_type"] = "pure_image"
                first_slide["image_path"]    = "01_Part1_00.png"
            except (KeyError, IndexError, TypeError):
                pass  # 構造が壊れていても他の処理に影響させない

            print("[V4] 台本生成完了")
            return result

        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                print(f"[V4] レート制限。{_RETRY_WAIT}秒後にリトライ...")
                time.sleep(_RETRY_WAIT)
                continue
            print(f"[V4] エラー: {err}")
            raise

    raise RuntimeError(
        f"[V4] {_MAX_RETRIES}回試行しても台本生成に失敗しました。"
    )
