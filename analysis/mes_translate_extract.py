"""
Bulk-extract every confirmed dialogue block from every .mes script into a
single CSV for translation. One row = one dialogue block. The 'source'
column is the lossless text form from translate_io.tokens_to_text() - real
glyphs as literal characters, everything else (control/formatting codes) as
explicit <HEX> placeholders the translator must copy through untouched.

Fill in the 'translation' column (leave <HEX> placeholders in place,
anywhere in the line) and run mes_translate_reinsert.py to build translated
.mes files.
"""
import csv
import glob
import os

import mes_codec as mc
import speaker_map
import translate_io as tio

SCRIPT_DIR = f"{mc.ROOT}/data/Script"
OUT_CSV = os.path.join(mc.HERE, "translation_export.csv")
FIELDS = ["file", "block", "n_tokens", "speaker", "source", "translation"]


def iter_mes_files():
    return sorted(glob.glob(os.path.join(SCRIPT_DIR, "*.mes")))


# Raw token IDs for the literal phrase "次のページ" ("next page"), captured
# from font_map_full.json BEFORE the 2026-08-06 full-wanseong repaint (backup:
# temp/backups_wanseong_full/font_map_full.json.pre_full). Matched against raw
# token values rather than decoded text so this detection stays correct even
# though those same codes now decode to unrelated Hangul characters post-
# repaint - the underlying .mes token stream itself never changed.
_NEXT_PAGE_TOKENS = (0x5904, 0xB0A, 0x1102, 0x21E, 0xE1E)


def is_debug_menu_block(values):
    """Leftover dev QA menu entries that match the real dialogue box shape
    but aren't player-facing text. Two known shapes:
    (1) "<name><0087><costume><0087><emotion>" portrait/costume test entries
        - every confirmed instance contains a literal 0x0087 separator; no
        confirmed real dialogue block does.
    (2) sound/BGM/emotion test-menu screens ("ムーディ悲しみ恐怖次のページ",
        "停止サウンドテスト終了次のページ", etc.) - every confirmed instance
        ends with the literal phrase "次のページ" ("next page"), which does
        not occur in any real dialogue line in the corpus.
    """
    if 0x0087 in values:
        return True
    n = len(_NEXT_PAGE_TOKENS)
    if len(values) >= n and tuple(values[-n:]) == _NEXT_PAGE_TOKENS:
        return True
    return False


def main():
    files = iter_mes_files()
    rows = []
    files_with_blocks = 0
    skipped_debug = 0
    for path in files:
        fname = os.path.basename(path)
        values = mc.load_values(path)
        blocks = mc.find_dialogue_blocks(values)
        real_blocks = []
        for s, e in blocks:
            if is_debug_menu_block(values[s:e]):
                skipped_debug += 1
            else:
                real_blocks.append((s, e))
        if real_blocks:
            files_with_blocks += 1
        for i, (s, e) in enumerate(real_blocks):
            text = tio.tokens_to_text(values[s:e])
            header_val = values[s - 1] if s - 1 >= 0 else None
            speaker = speaker_map.speaker_of(header_val) if header_val is not None else None
            rows.append({
                "file": fname,
                "block": i,
                "n_tokens": e - s,
                "speaker": speaker if speaker is not None else f"UNKNOWN_{header_val:#04x}" if header_val is not None else "",
                "source": text,
                "translation": "",
            })

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"scanned {len(files)} .mes files ({files_with_blocks} contain dialogue blocks)")
    print(f"wrote {len(rows)} dialogue blocks -> {OUT_CSV}")


if __name__ == "__main__":
    main()
