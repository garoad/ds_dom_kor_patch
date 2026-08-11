#!/usr/bin/env python3
"""
rebuild_font_map_kr.py
======================
font_map_kr.json 을 올바르게 재구성하는 스크립트.

규칙 (2026-08-11 완성형 2,350자 확장 반영):
  - font_map_full.json 을 기반으로 시작
  - full_2350_hangul_manifest.json 매니페스트에 지정된 코드만 한글로 교체
  - 안전성은 "코드 자신의 카테고리"가 아니라 "그 코드의 real_tile을 공유하는
    모든 코드의 카테고리 집합"으로 판정한다 (2026-08-06 사고 재발 방지 - 당시
    미판독 코드를 코드 단위로만 안전 판단해 keep 카테고리 타일을 공유
    파손시켰음). 카테고리 집합이 정확히 {kanji} 이거나 정확히 {unresolved}
    인 real_tile 그룹만 안전. 히라가나/가타카나/구두점/keep(숫자·라틴·기호)/
    이름-변수 제어코드(sentinel)와 조금이라도 타일을 공유하면 그 그룹 전체를
    절대 건드리지 않는다.
  - 매니페스트에 없는 코드는 font_map_full.json 의 원본 값을 그대로 유지
"""

import json
import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FULL_MAP = os.path.join(BASE_DIR, "font_map_full.json")
KR_MAP_OUT = os.path.join(BASE_DIR, "font_map_kr.json")
MANIFEST = os.path.join(BASE_DIR, "..", "temp", "full_2350_hangul_manifest.json")

SENTINEL_CODES = {"505C", "485C", "3131", "3232"}


def classify_char(c):
    if len(c) != 1:
        return "keep"
    o = ord(c)
    if 0x3040 <= o <= 0x309F:
        return "hiragana"
    if 0x30A0 <= o <= 0x30FF or 0xFF66 <= o <= 0xFF9F:
        return "katakana"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
        return "kanji"
    if 0x3000 <= o <= 0x303F:
        return "cjk_punct"
    if 0xAC00 <= o <= 0xD7A3:
        return "hangul"
    return "keep"


def category_of(code, entry):
    if code in SENTINEL_CODES:
        return "sentinel"
    if entry.get("kind") != "full":
        return None
    if entry.get("char") is None:
        return "unresolved"
    return classify_char(entry["char"])


def main():
    with open(FULL_MAP, encoding="utf-8") as f:
        full = json.load(f)
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)  # {char: {tile, code, code_hex, source}}

    codes_full = full["codes"]

    # code_hex in manifest is "0xXXXX" format -> 4-char uppercase hex key
    manifest_code_to_char = {}
    for char, info in manifest.items():
        code_int = info["code"]
        code_hex_key = format(code_int, "04X").upper()
        manifest_code_to_char[code_hex_key] = char

    print(f"Manifest entries: {len(manifest_code_to_char)}")

    # real_tile 그룹별 카테고리 집합 계산 (핵심 안전 검증)
    groups = defaultdict(set)
    group_codes = defaultdict(list)
    for code, entry in codes_full.items():
        if entry.get("kind") != "full":
            continue
        rt = entry.get("real_tile")
        if rt is None:
            continue
        groups[rt].add(category_of(code, entry))
        group_codes[rt].append(code)

    unsafe = []
    for code_key, char in manifest_code_to_char.items():
        v = codes_full.get(code_key)
        if v is None:
            # font_map_full.json에 아예 없는 신규 발견 빈 타일 - 애초에 어떤
            # 코드도 참조하지 않는 완전 미사용 주소이므로 안전.
            continue
        rt = v.get("real_tile")
        cats = groups.get(rt, set())
        if cats not in ({"kanji"}, {"unresolved"}):
            unsafe.append((code_key, char, rt, cats, group_codes.get(rt, [])))

    if unsafe:
        print(f"\n⛔ SAFETY VIOLATION: {len(unsafe)}개 매니페스트 코드가 안전하지 않은 real_tile 그룹에 속함:")
        for code_key, char, rt, cats, gcodes in unsafe:
            print(f"   {code_key}: '{char}' -> tile {rt} categories={sorted(cats)} codes={gcodes}")
        raise SystemExit("Aborting - unsafe manifest assignments detected!")
    else:
        print("✅ Safety check passed: 모든 매니페스트 코드가 real_tile 배타적 kanji 또는 unresolved 그룹임")

    # Build kr map: start from full map, overlay manifest assignments
    new_codes = {}
    replaced = 0
    kept_original = 0

    for code_key, v in codes_full.items():
        # SAFETY: Never replace blank-kind codes (format control codes used by game engine)
        current_kind = v.get("kind", "")
        if code_key in manifest_code_to_char and current_kind != "blank":
            new_entry = dict(v)
            new_entry["char"] = manifest_code_to_char[code_key]
            new_codes[code_key] = new_entry
            replaced += 1
        else:
            existing_char = v.get("char", "")
            original_kind = v.get("kind", "")
            if existing_char and "가" <= existing_char <= "힣" and original_kind != "blank":
                # 이전 빌드에서 잘못 한글이 배정된 슬롯 - 원본 상태로 복원
                new_entry = dict(v)
                del new_entry["char"]
                new_codes[code_key] = new_entry
                print(f"  ⚠ Restoring non-safe slot {code_key} to original (was wrongly assigned '{existing_char}')")
            else:
                new_codes[code_key] = dict(v)
            kept_original += 1

    # 같은 real_tile을 공유하는 별칭 코드 동기화: 매니페스트는 그룹당 대표
    # 코드 하나에만 한글을 배정하지만, 물리 타일은 그룹 내 모든 코드가
    # 공유하므로 실제 렌더링은 이미 전부 한글로 바뀐다. JSON 메타데이터도
    # 이를 반영해야 한다 - 안 그러면 별칭 코드(예: 1D14/遠와 real_tile을
    # 공유하는 1B94)가 실제로는 한글을 보여주면서도 char 필드에는 옛 한자가
    # 남아 헷갈리고, 그 별칭 코드가 어딘가에서 원문자 표시 용도로 계속
    # 쓰이고 있었다면 발견도 못 하게 된다(2026-08-11 픽셀 비교로 발견).
    alias_synced = 0
    for code_key, char in manifest_code_to_char.items():
        v = codes_full.get(code_key)
        if v is None:
            continue
        rt = v.get("real_tile")
        for alias_code in group_codes.get(rt, []):
            if alias_code == code_key:
                continue
            alias_entry = new_codes.get(alias_code)
            if alias_entry is None or alias_entry.get("kind") == "blank":
                continue
            if alias_entry.get("char") != char:
                alias_entry["char"] = char
                alias_synced += 1

    # 매니페스트에는 있지만 font_map_full.json에는 전혀 없던 완전 신규 빈 주소
    new_free_added = 0
    for char, info in manifest.items():
        code_int = info["code"]
        code_key = format(code_int, "04X").upper()
        if code_key not in codes_full and code_key not in new_codes:
            new_codes[code_key] = {
                "kind": "full",
                "count": 0,
                "real_tile": info["tile"],
                "char": char,
            }
            new_free_added += 1

    hangul_in_new = sum(
        1 for v in new_codes.values() if "가" <= v.get("char", "") <= "힣"
    )

    print("\nResult:")
    print(f"  Total codes: {len(new_codes)}")
    print(f"  Replaced (full-map code -> hangul): {replaced}")
    print(f"  New free-address codes added: {new_free_added}")
    print(f"  Kept original (non-hangul): {kept_original}")
    print(f"  Hangul in new map: {hangul_in_new}")

    hira = [k for k, v in new_codes.items() if "ぁ" <= v.get("char", "") <= "ゟ"]
    kata = [k for k, v in new_codes.items() if "゠" <= v.get("char", "") <= "ヿ"]
    print(f"  Hiragana preserved: {len(hira)}")
    print(f"  Katakana preserved: {len(kata)}")

    kr_out = {
        "formula": full["formula"],
        "stats": {
            **full.get("stats", {}),
            "hangul_mapped": hangul_in_new,
            "hangul_budget": len(manifest_code_to_char),
            "rebuild_note": (
                "Rebuilt by rebuild_font_map_kr.py from full_2350_hangul_manifest.json. "
                "Safety is verified per real_tile group (all codes sharing a physical tile "
                "must belong to a single safe category - kanji or unresolved), not per-code. "
                "Hiragana, Katakana, punctuation, keep-category and sentinel control codes "
                "are 100% preserved."
            ),
        },
        "codes": new_codes,
    }

    with open(KR_MAP_OUT, "w", encoding="utf-8") as f:
        json.dump(kr_out, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Written: {KR_MAP_OUT}")
    print(f"   Hangul slots: {hangul_in_new} / 2350 target")


if __name__ == "__main__":
    main()
