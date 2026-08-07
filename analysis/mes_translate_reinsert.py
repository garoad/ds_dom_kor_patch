"""
Read back a translation CSV (produced by mes_translate_extract.py, with the
'translation' column filled in) and build translated .mes files.

Safety model:
  - Never touches unpack/data/Script/*.mes directly. Writes to
    analysis/translated_output/Script/ instead. Copying the results into
    unpack/ and repacking the ROM is a separate, explicit step for the user.
  - Re-derives dialogue block boundaries from the ORIGINAL file each time
    (not from stale start/end offsets in the CSV), so block-length changes
    from translation don't corrupt later blocks in the same file.
  - Per block, validates that every <HEX> control/formatting placeholder in
    the source appears the same number of times in the translation (see
    translate_io.validate_placeholders). A file with ANY validation error is
    skipped entirely (not partially written) and reported; every other file
    is still processed.
  - Per block, validates that the translation encodes to EXACTLY the same
    number of u16 tokens as the original block. The opening-scene field test
    (2026-08-05, dom1OP_0701_1.mes) confirmed on real hardware/melonDS that a
    block whose token count differs from the original corrupts the speaker
    name and hangs the game - `diff -rq` round-trip checks alone don't catch
    this. A mismatch is reported and the file is skipped, the same as a
    placeholder error; there is no auto-padding here (padding requires a
    'blank' filler code chosen per font/scene, see opening_scene_font.py).
  - Blank (or unchanged) 'translation' cells fall back to the block's
    ORIGINAL TOKENS, copied verbatim - not re-encoded from the decoded text.
    This matters because Font_DOM.nbfc's kanji/kana tiles have since been
    repainted as Hangul (2026-08-06, full wanseong registration) to make room
    for the complete 완성형 set; re-encoding untranslated Japanese source text
    via text_to_tokens would fail outright since those characters no longer
    have a font code. Reusing the original tokens sidesteps this entirely -
    untranslated dialogue keeps displaying (garbled, since its glyphs are now
    Hangul-shaped) exactly as it always played back, just not translated yet.
  - Aborts a file (with a clear error) if the CSV's block count for that file
    doesn't match what's actually in the current .mes file - this catches a
    stale CSV after the source scripts changed.

Run mes_translate_extract.py first if translation_export.csv doesn't exist.
"""
import csv
import os
import sys
from collections import defaultdict

import mes_codec as mc
import mes_translate_extract as mte
import translate_io as tio

SCRIPT_DIR = f"{mc.ROOT}/data/Script"
DEFAULT_CSV = os.path.join(mc.HERE, "translation_export.csv")
OUT_DIR = os.path.join(mc.HERE, "translated_output", "Script")


def load_csv(path):
    by_file = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_file[row["file"]][int(row["block"])] = row
    return by_file


def build_file(fname, rows_by_block):
    src_path = os.path.join(SCRIPT_DIR, fname)
    if not os.path.exists(src_path):
        return None, [f"source file not found: {src_path}"]

    values = mc.load_values(src_path)
    # mes_translate_extract.py numbers CSV rows over real (non-debug-menu)
    # blocks only - re-deriving from mc.find_dialogue_blocks() without the
    # same filter here would misalign every row after the first debug block
    # and then hard-fail on the block-count check for any file that has one
    # (discovered 2026-08-06 testing the CSV-edit pipeline on
    # dom1OP_0701_1.mes, which has 113 debug-menu blocks interleaved with
    # its 119 real ones - 232 vs 119 always mismatched before this fix).
    all_blocks = mc.find_dialogue_blocks(values)
    blocks = [(s, e) for s, e in all_blocks if not mte.is_debug_menu_block(values[s:e])]

    if len(blocks) != len(rows_by_block):
        return None, [
            f"block count mismatch: CSV has {len(rows_by_block)} rows for "
            f"{fname}, current file has {len(blocks)} real dialogue blocks "
            "(CSV is stale - re-run mes_translate_extract.py)"
        ]

    problems = []
    out = []
    last = 0
    for i, (s, e) in enumerate(blocks):
        row = rows_by_block[i]
        src_text = row["source"]
        translation = row["translation"].strip()

        if not translation or translation == src_text:
            out.extend(values[last:s])
            out.extend(values[s:e])
            last = e
            continue

        dst_text = translation
        expected_len = e - s

        block_problems = tio.validate_placeholders(src_text, dst_text)
        if block_problems:
            problems.append(f"block {i}: " + "; ".join(block_problems))
            continue

        try:
            new_tokens = tio.text_to_tokens(dst_text)
        except ValueError as ex:
            problems.append(f"block {i}: {ex}")
            continue

        if len(new_tokens) != expected_len:
            direction = "longer" if len(new_tokens) > expected_len else "shorter"
            problems.append(
                f"block {i}: token count mismatch - original has {expected_len} "
                f"tokens, translation encodes to {len(new_tokens)} ({direction}). "
                "Dialogue blocks must keep an identical token count or the game "
                "hangs on real hardware/melonDS (confirmed 2026-08-05). Pad short "
                "translations with a blank/filler code or shorten the wording."
            )
            continue

        out.extend(values[last:s])
        out.extend(new_tokens)
        last = e

    if problems:
        return None, problems

    out.extend(values[last:])
    return out, []


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    if not os.path.exists(csv_path):
        print(f"no such CSV: {csv_path}\nrun mes_translate_extract.py first.")
        sys.exit(1)

    by_file = load_csv(csv_path)
    os.makedirs(OUT_DIR, exist_ok=True)

    written, skipped = 0, 0
    for fname, rows_by_block in sorted(by_file.items()):
        out_values, problems = build_file(fname, rows_by_block)
        if problems:
            skipped += 1
            print(f"SKIPPED {fname}:")
            for p in problems:
                print(f"    {p}")
            continue
        out_path = os.path.join(OUT_DIR, fname)
        mc.dump_values(out_values, out_path)
        written += 1

    print(f"\n{written} file(s) written to {OUT_DIR}, {skipped} file(s) skipped due to validation errors")


if __name__ == "__main__":
    main()
