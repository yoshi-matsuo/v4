#!/usr/bin/env python3
"""
merge_script.py — part1.json + part2.json を結合して script.json を生成する。

AIが気まぐれに出力するどんな形式でも、スライドを力技で全探索して抽出する。
対応形式の例:
  - {"script": {"parts": [{"part_number": 1, "slides": [...]}]}}   ← 現行形式
  - {"script": {"Part 1": [...], "Part 2": [...]}}                 ← 旧形式
  - {"slides": [{"part": "Part 1", ...}, ...]}                     ← フラット形式
  - {"parts": [...]} / {"Part 1": [...]} など 深い階層も含め全探索
"""

import json
import os
import re

HERE       = os.path.dirname(os.path.abspath(__file__))
PART1_PATH = os.path.join(HERE, "part1.json")
PART2_PATH = os.path.join(HERE, "part2.json")
OUT_PATH   = os.path.join(HERE, "script.json")

PART_ORDER = ["Part 1", "Part 2", "Part 3", "Part 4",
              "Part 5", "Part 6", "Part 7"]

# スライドと判定するための必須キー（1つでも含めばスライドとみなす）
SLIDE_KEYS = {"template_type", "narration", "content_bullets", "title"}


def convert_bullets(bullets) -> str:
    if isinstance(bullets, str):
        return bullets
    if not bullets:
        return ""
    if len(bullets) == 1:
        return bullets[0]
    return " | ".join(bullets)


def looks_like_slide(obj: dict) -> bool:
    """dictがスライドオブジェクトらしいかどうかを判定する。"""
    return bool(SLIDE_KEYS & obj.keys())


def normalize_part_name(raw) -> str | None:
    """
    part番号をあらゆる形式から "Part N" に正規化する。
    例: 1 / "1" / "Part 1" / "part1" / "part_1" / "PART 1" → "Part 1"
    """
    if raw is None:
        return None
    s = str(raw).strip()
    # すでに "Part N" 形式
    m = re.fullmatch(r"[Pp]art[\s_-]*(\d+)", s)
    if m:
        return f"Part {m.group(1)}"
    # 純粋な数字
    if re.fullmatch(r"\d+", s):
        return f"Part {s}"
    return None


def extract_slides(node, current_part: str | None = None) -> list[tuple[str | None, dict]]:
    """
    JSON ツリーを再帰的に探索し、(part_name_or_None, slide_dict) のリストを返す。
    part情報は以下の優先順で取得:
      1. 直近の "parts" リスト要素内の part_number / part_name
      2. dict のキーが "Part N" パターン
      3. スライド自体が持つ "part" フィールド
    """
    results: list[tuple[str | None, dict]] = []

    if isinstance(node, list):
        for item in node:
            results.extend(extract_slides(item, current_part))

    elif isinstance(node, dict):
        # ── ケース1: parts リスト形式 {"parts": [{"part_number": N, "slides": [...]}]} ──
        if "parts" in node and isinstance(node["parts"], list):
            for part_obj in node["parts"]:
                if not isinstance(part_obj, dict):
                    continue
                # part番号を取り出す
                raw = part_obj.get("part_number") or part_obj.get("part_name") or part_obj.get("part")
                pname = normalize_part_name(raw)
                slides_list = part_obj.get("slides", [])
                if isinstance(slides_list, list):
                    for s in slides_list:
                        if isinstance(s, dict) and looks_like_slide(s):
                            results.append((pname, s))
                        else:
                            results.extend(extract_slides(s, pname))
                # parts内の他のキーも再帰探索（slides以外に何か入っている場合）
                for k, v in part_obj.items():
                    if k in ("slides", "part_number", "part_name", "part"):
                        continue
                    results.extend(extract_slides(v, pname))
            # parts 以外のキーも探索（visual_metadata などを無視しつつ）
            for k, v in node.items():
                if k == "parts":
                    continue
                results.extend(extract_slides(v, current_part))
            return results

        # ── ケース2: "Part N" をキーに持つ dict {"Part 1": [...], "Part 2": [...]} ──
        part_key_found = False
        for k, v in node.items():
            pname = normalize_part_name(k)
            if pname and isinstance(v, list):
                part_key_found = True
                for s in v:
                    if isinstance(s, dict) and looks_like_slide(s):
                        results.append((pname, s))
                    else:
                        results.extend(extract_slides(s, pname))
        if part_key_found:
            return results

        # ── ケース3: スライド自体がここにある ──
        if looks_like_slide(node):
            part_from_slide = normalize_part_name(node.get("part"))
            results.append((part_from_slide or current_part, node))
            return results

        # ── ケース4: それ以外は全キーを再帰探索 ──
        for k, v in node.items():
            results.extend(extract_slides(v, current_part))

    return results


def load(path: str) -> list[tuple[str | None, dict]]:
    """JSONファイルを読み込み、(part_name_or_None, slide_dict) のリストを返す。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    slides = extract_slides(data)
    print(f"  {os.path.basename(path)}: {len(slides)} スライド抽出")
    return slides


def main() -> None:
    all_slides: list[tuple[str | None, dict]] = []
    for path in (PART1_PATH, PART2_PATH):
        all_slides.extend(load(path))

    print(f"読み込み合計: {len(all_slides)} スライド")

    grouped: dict[str, list] = {p: [] for p in PART_ORDER}

    for part, slide in all_slides:
        if part is None or part not in grouped:
            print(f"  [WARN] パート不明または未知: {part!r}  → スキップ")
            continue
        converted = {k: v for k, v in slide.items() if k != "part"}
        converted["content_bullets"] = convert_bullets(slide.get("content_bullets", ""))
        grouped[part].append(converted)

    script = {p: v for p, v in grouped.items() if v}

    output = {"script": script}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nscript.json を出力しました: {OUT_PATH}")
    for part, items in script.items():
        print(f"  {part}: {len(items)} スライド")


if __name__ == "__main__":
    main()
