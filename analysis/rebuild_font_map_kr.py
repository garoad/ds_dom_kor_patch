#!/usr/bin/env python3
"""
rebuild_font_map_kr.py
======================
font_map_kr.json 을 올바르게 재구성하는 스크립트.

규칙:
  - font_map_full.json 을 기반으로 시작
  - 한자(CJK 4E00-9FFF)로 분류된 코드 1,363개와 '빈(free)' 200개 슬롯만
    kanji_only_hangul_glyphs.json 매니페스트에 따라 한글로 교체
  - 히라가나, 가타카나, 라틴, 문장부호, 반각, 제어코드 등은 절대 건드리지 않음
  - 매니페스트에 없는 코드는 font_map_full.json 의 원본 값을 그대로 유지
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FULL_MAP = os.path.join(BASE_DIR, "font_map_full.json")
KR_MAP_OUT = os.path.join(BASE_DIR, "font_map_kr.json")
MANIFEST = os.path.join(BASE_DIR, "..", "temp", "kanji_only_hangul_glyphs.json")

def main():
    with open(FULL_MAP, encoding="utf-8") as f:
        full = json.load(f)
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)  # {char: {tile, code, code_hex, source}}

    codes_full = full["codes"]

    # Build char -> code mapping from manifest
    # code_hex in manifest is "0xXXXX" format
    # Convert to 4-char uppercase hex key used in codes dict
    manifest_code_to_char = {}
    for char, info in manifest.items():
        code_int = info["code"]
        code_hex_key = format(code_int, "04X").upper()
        manifest_code_to_char[code_hex_key] = char

    print(f"Manifest entries: {len(manifest_code_to_char)}")

    # Verify safety: all manifest codes must be kanji or free slots in full map
    kanji_codes_in_full = {
        k for k, v in codes_full.items()
        if "char" in v and "\u4e00" <= v["char"] <= "\u9fff"
    }
    unsafe = []
    for code_key, char in manifest_code_to_char.items():
        v = codes_full.get(code_key, {})
        kind = v.get("kind", "unknown")
        existing_char = v.get("char", "")
        # Safe if: it's a kanji code, or it's a full kind with no char (free slot),
        # or it doesn't exist in full map at all (newly discovered empty tile, source='free')
        is_kanji = code_key in kanji_codes_in_full
        is_free = kind == "full" and "char" not in v  # full kind but no char = free tile
        is_blank = kind == "blank"
        is_new_free = not v  # not in font_map_full.json at all = completely free new slot
        if not (is_kanji or is_free or is_blank or is_new_free):
            unsafe.append((code_key, char, v))

    if unsafe:
        print(f"\n⛔ SAFETY VIOLATION: {len(unsafe)} manifest codes are NOT kanji/free:")
        for code_key, char, v in unsafe:
            print(f"   {code_key}: '{char}' -> full={v}")
        raise SystemExit("Aborting - unsafe manifest assignments detected!")
    else:
        print(f"✅ Safety check passed: all manifest codes are kanji or free slots")

    # Build kr map: start from full map, overlay manifest assignments
    new_codes = {}
    replaced_kanji = 0
    replaced_free = 0
    kept_original = 0
    kept_hangul_already = 0

    for code_key, v in codes_full.items():
        # SAFETY: Never replace blank-kind codes (format control codes used by game engine)
        current_kind = v.get("kind", "")
        if code_key in manifest_code_to_char and current_kind != "blank":

            # Replace with Hangul
            new_entry = dict(v)
            new_entry["char"] = manifest_code_to_char[code_key]
            new_codes[code_key] = new_entry
            if code_key in kanji_codes_in_full:
                replaced_kanji += 1
            else:
                replaced_free += 1
        else:
            # Keep original (hiragana, katakana, punctuation, ctrl, blank, etc.)
            existing_char = v.get("char", "")
            original_kind = v.get("kind", "")
            if existing_char and "\uac00" <= existing_char <= "\ud7a3" and original_kind != "blank":
                # This was a hangul in the old wrong kr map - do NOT keep it
                # Restore to original full map state (remove the char field)
                new_entry = dict(v)
                del new_entry["char"]
                new_codes[code_key] = new_entry
                print(f"  ⚠ Restoring non-kanji slot {code_key} to original (was wrongly assigned '{existing_char}')")
            else:
                new_codes[code_key] = dict(v)
            kept_original += 1

    # Also add newly-discovered free slot codes from manifest that aren't in font_map_full.json
    # These are empty tile slots (tile=X, source='free') that the build script found and assigned
    new_free_added = 0
    for char, info in manifest.items():
        code_int = info["code"]
        code_key = format(code_int, "04X").upper()
        if code_key not in codes_full and code_key not in new_codes:
            # Newly discovered free slot - add it
            new_codes[code_key] = {
                "kind": "full",
                "count": 0,
                "real_tile": info["tile"],
                "char": char
            }
            new_free_added += 1


    # Count hangul in new map
    hangul_in_new = sum(
        1 for v in new_codes.values()
        if "\uac00" <= v.get("char", "") <= "\ud7a3"
    )

    print(f"\nResult:")
    print(f"  Total codes: {len(new_codes)}")
    print(f"  Replaced (kanji->hangul): {replaced_kanji}")
    print(f"  Replaced (free->hangul): {replaced_free}")
    print(f"  Kept original (non-hangul): {kept_original}")
    print(f"  Hangul in new map: {hangul_in_new}")

    # Verify hiragana/katakana are preserved
    hira = [(k, v) for k, v in new_codes.items()
            if "\u3041" <= v.get("char", "") <= "\u309f"]
    kata = [(k, v) for k, v in new_codes.items()
            if "\u30a0" <= v.get("char", "") <= "\u30ff"]
    print(f"  Hiragana preserved: {len(hira)}")
    print(f"  Katakana preserved: {len(kata)}")

    # Build output
    kr_out = {
        "formula": full["formula"],
        "stats": {
            **full.get("stats", {}),
            "hangul_mapped": hangul_in_new,
            "hangul_budget": len(manifest_code_to_char),
            "rebuild_note": (
                "Rebuilt by rebuild_font_map_kr.py from kanji_only_hangul_glyphs.json manifest. "
                "Only kanji (CJK 4E00-9FFF) and free full-kind slots are replaced with Hangul. "
                "Hiragana, Katakana, punctuation, control codes are 100% preserved."
            )
        },
        "codes": new_codes
    }

    with open(KR_MAP_OUT, "w", encoding="utf-8") as f:
        json.dump(kr_out, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Written: {KR_MAP_OUT}")
    print(f"   Hangul slots: {hangul_in_new} / 1559 budget")


if __name__ == "__main__":
    main()
