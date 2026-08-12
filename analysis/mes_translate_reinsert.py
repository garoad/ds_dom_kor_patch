"""
Read back translation CSV files (produced by mes_translate_extract.py into
temp/translations/*.csv, with the 'translation' column filled in) and
build translated .mes files into temp/translated_output/.
"""
import csv
import glob
import os
import sys
from collections import defaultdict

import mes_codec as mc
import mes_translate_extract as mte
import translate_io as tio

TRANSLATIONS_DIR = os.path.join(mc.PROJECT_ROOT, "temp", "translations")
OUT_BASE_DIR = os.path.join(mc.PROJECT_ROOT, "temp", "translated_output")

# playername.mes stores default preset names (surname/given name entries),
# each capped at 3 displayed characters by the in-game name UI itself -
# unlike dialogue blocks, an entry's length isn't tied to a fixed ROM slot,
# so it doesn't need to match the original token count exactly (2026-08-10,
# see pipeline.js's PLAYERNAME_FILE for the JS-side mirror of this).
PLAYERNAME_FILE = "playername.mes"
PLAYERNAME_MAX_TOKENS = 3

# namelist1.mes (speaker/NPC display-name table, see speaker_map.py's
# module docstring) - like playername.mes, entries here aren't dialogue-box
# text tied to a fixed ROM slot. Hardware-confirmed safe on melonDS
# 2026-08-12 (translated names of varying length render correctly, game
# runs normally, including the Athena nameplate - proving that scene reads
# names from here too rather than from its separate image-based nameplate
# asset).
#
# Extended 2026-08-12 to the other headerless-list-format files (see
# speaker_map.py's module docstring) that share the same structural
# signature - back-to-back entries with no per-entry header, found by
# scanning for 0x6E5C 0x6E5C markers rather than by jumping to a hardcoded
# byte offset - so the same "not tied to a fixed ROM slot" reasoning
# applies:
#   - dom1chara.mes/dom2chara.mes/dom3chara.mes: per-character profile
#     cards (birthday/age/hometown/blood type/height/weight)
#   - soundnamedom1/2/3.mes: sound-test music track name list
#   - endtitledom1/2/3.mes: unlockable ending title name list
# No max-tokens cap (unlike PLAYERNAME_FILE) since none of these have a
# known in-game character limit. This extension itself is still
# experimental pending its own real hardware/melonDS confirmation - only
# namelist1.mes has been confirmed so far.
#
# NOT included: extraopen.mes/common.mes (real per-entry headers, not the
# headerless-list pattern - structurally just normal one-off strings);
# strindex.mes (the font glyph index table itself, not player-facing text);
# orochiendroll.mes (staff credits - real people's names, must stay as-is,
# not translated); saveload.mes (save/load UI mixes translatable words with
# fixed-position date/time digit formatting via dense control codes - too
# fragile to blanket-exempt, left on strict matching if ever added to the
# pipeline).
LIST_NO_LENGTH_CAP_FILES = {
    "namelist1.mes",
    "dom1chara.mes",
    "dom2chara.mes",
    "dom3chara.mes",
    "soundnamedom1.mes",
    "soundnamedom2.mes",
    "soundnamedom3.mes",
    "endtitledom1.mes",
    "endtitledom2.mes",
    "endtitledom3.mes",
}

# See tio.PAGE_TURN_TOKEN for how the trailing page-turn marker is hidden
# from the CSV text and re-appended here automatically.


def load_csv(path):
    by_file = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_file[row["file"]][int(row["block"])] = row
    return by_file


def build_file(fname, rows_by_block):
    # Determine source path via rel_path from the first row if present, else fallback to Script/
    first_row = next(iter(rows_by_block.values()))
    rel_path = first_row.get("rel_path")
    if rel_path:
        src_path = os.path.join(mc.ROOT, "data", rel_path)
    else:
        src_path = os.path.join(mc.ROOT, "data", "Script", fname)

    if not os.path.exists(src_path):
        # Fallback to unpack_origin if unpack doesn't have it yet
        if rel_path:
            src_path = os.path.join(mc.ORIGIN_ROOT, "data", rel_path)
        else:
            src_path = os.path.join(mc.ORIGIN_ROOT, "data", "Script", fname)

    if not os.path.exists(src_path):
        return None, rel_path or fname, [f"source file not found: {src_path}"]

    values = mc.load_values(src_path)
    all_blocks = mc.find_dialogue_blocks(values)
    is_script = "Script" in src_path
    blocks = [
        (s, e) for s, e in all_blocks
        if not (is_script and mte.is_debug_menu_block(values[s:e]))
    ]

    if len(blocks) != len(rows_by_block):
        return None, rel_path or fname, [
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
        # If the real on-disk block ends with the page-turn marker, it was
        # hidden from the CSV text by mes_translate_extract.py - the
        # translator's text encodes everything BUT that final token, and we
        # append it back below (see tio.PAGE_TURN_TOKEN).
        has_page_turn = expected_len > 0 and values[e - 1] == tio.PAGE_TURN_TOKEN
        text_expected_len = expected_len - 1 if has_page_turn else expected_len

        block_problems = tio.validate_placeholders(src_text, dst_text)
        if block_problems:
            problems.append(f"block {i}: " + "; ".join(block_problems))
            continue

        try:
            new_tokens = tio.text_to_tokens(dst_text)
        except ValueError as ex:
            problems.append(f"block {i}: {ex}")
            continue

        if fname == PLAYERNAME_FILE:
            # No fixed-slot constraint here - just the in-game 3-character
            # name cap (see PLAYERNAME_FILE comment above).
            if len(new_tokens) > PLAYERNAME_MAX_TOKENS:
                problems.append(
                    f"block {i}: player name too long - encodes to "
                    f"{len(new_tokens)} characters, but names are capped at "
                    f"{PLAYERNAME_MAX_TOKENS} in-game"
                )
                continue
            out.extend(values[last:s])
            out.extend(new_tokens)
            last = e
            continue

        if fname in LIST_NO_LENGTH_CAP_FILES:
            # No length constraint at all (see LIST_NO_LENGTH_CAP_FILES
            # comment above) - hardware-confirmed for namelist1.mes only so
            # far; the other files here are the same experiment, pending
            # their own real hardware/melonDS confirmation.
            out.extend(values[last:s])
            out.extend(new_tokens)
            last = e
            continue

        if len(new_tokens) < text_expected_len:
            # Pad with trailing space tokens rather than failing the block -
            # a shorter translation is safe to pad, unlike a longer one
            # (which would have to drop content to fit and is still reported
            # below). Padded against text_expected_len (excluding the
            # page-turn marker, if any) so the marker appended below always
            # ends up last - see tio.PAGE_TURN_TOKEN for why it must never
            # be pushed off the end by padding. Uses tio.SPACE_TOKEN
            # (full-width) - see its comment for why the half-width blank is
            # not used.
            new_tokens = new_tokens + [tio.SPACE_TOKEN] * (text_expected_len - len(new_tokens))

        if len(new_tokens) != text_expected_len:
            problems.append(
                f"block {i}: token count mismatch - original has {text_expected_len} "
                f"tokens, translation encodes to {len(new_tokens)} (longer). "
                "Dialogue blocks must keep an identical token count or the game "
                "hangs on real hardware/melonDS (confirmed 2026-08-05). Shorten "
                "the wording."
            )
            continue

        if has_page_turn:
            new_tokens = new_tokens + [tio.PAGE_TURN_TOKEN]

        out.extend(values[last:s])
        out.extend(new_tokens)
        last = e

    if problems:
        return None, rel_path or fname, problems

    out.extend(values[last:])
    return out, rel_path or fname, []


def main():
    csv_files = []
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if os.path.isdir(arg):
            csv_files = sorted(glob.glob(os.path.join(arg, "*.csv")))
        else:
            csv_files = [arg]
    else:
        if os.path.exists(TRANSLATIONS_DIR):
            csv_files = sorted(glob.glob(os.path.join(TRANSLATIONS_DIR, "*.csv")))

    if not csv_files:
        print(f"No CSV files found in {TRANSLATIONS_DIR}. Run mes_translate_extract.py first.")
        sys.exit(1)

    total_written, total_skipped = 0, 0
    for csv_path in csv_files:
        by_file = load_csv(csv_path)
        written, skipped = 0, 0
        for fname, rows_by_block in sorted(by_file.items()):
            out_values, rel_path, problems = build_file(fname, rows_by_block)
            if problems:
                skipped += 1
                print(f"SKIPPED [{os.path.basename(csv_path)}] {fname}:")
                for p in problems:
                    print(f"    {p}")
                continue

            # Output path mirroring rel_path under translated_output/
            out_path = os.path.join(OUT_BASE_DIR, rel_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            mc.dump_values(out_values, out_path)
            written += 1

        total_written += written
        total_skipped += skipped
        print(f"CSV {os.path.basename(csv_path)}: {written} written, {skipped} skipped")

    print(f"\nTOTAL: {total_written} file(s) written to {OUT_BASE_DIR}, {total_skipped} file(s) skipped due to validation errors")


if __name__ == "__main__":
    main()

