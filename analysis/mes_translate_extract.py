"""
Bulk-extract confirmed dialogue blocks from all .mes script files into separate
CSV files per series/character and system scripts.

CSV directory: temp/translations/
Categories:
  - dom1_<Character>.csv, dom2_<Character>.csv, dom3_<Character>.csv
  - dom1_common.csv, dom2_common.csv, dom3_common.csv (for non-character scripts like OP, DefScn, ENC, HZR, etc.)
  - system_common.csv (for .mes files outside Script/ directory like soundnamedom*.mes, endtitledom*.mes, etc.)

One row = one dialogue block. The 'source' column is the lossless text form from
translate_io.tokens_to_text() - real glyphs as literal characters, everything else
(control/formatting codes) as explicit <HEX> placeholders that must be preserved.
"""
import csv
import glob
import os

import mes_codec as mc
import speaker_map
import translate_io as tio

TRANSLATIONS_DIR = os.path.join(mc.PROJECT_ROOT, "temp", "translations")
FIELDS = ["file", "rel_path", "block", "n_tokens", "speaker", "source", "ai_draft", "translation"]

# Outside Script/ system .mes files
OUTSIDE_MES_FILES = [
    "soundnamedom1.mes",
    "soundnamedom2.mes",
    "soundnamedom3.mes",
    "dom3chara.mes",
    "dom2chara.mes",
    "playername.mes",
    "extraopen.mes",
    "common.mes",
    "endtitledom3.mes",
    "endtitledom2.mes",
    "endtitledom1.mes",
    # Master speaker/NPC name table - index N == the header ID used by
    # find_dialogue_blocks() to tag a dialogue block's speaker (verified
    # 2026-08-12 by cross-referencing every known speaker_map.SPEAKER_NAMES/
    # SPECIAL_NAMES ID against this file's entry at the same index - all
    # matched exactly). Headerless list format like dom2chara.mes/
    # playername.mes, so speaker labels for its own rows come out as
    # UNKNOWN_0x6e5c (the literal separator token, not a real header) -
    # same pre-existing behavior as those other list files.
    "namelist1.mes",
    # dom1chara.mes was missing entirely from this list until 2026-08-12
    # (dom2chara.mes/dom3chara.mes were already here) - same per-character
    # profile-card format, just for dom1's cast.
    "dom1chara.mes",
    # Short one-off UI prompt strings (map-move / name-confirm dialogs) -
    # real per-entry headers, NOT the headerless-list pattern, so they get
    # standard strict length matching on reinsert, not the
    # LIST_NO_LENGTH_CAP_FILES treatment.
    "mapmove.mes",
    "nameinput.mes",
]


def get_category(path):
    fname = os.path.basename(path)
    if not path.startswith(os.path.join(mc.ORIGIN_ROOT, "data", "Script")):
        return "system_common"

    if fname.startswith("dom1"):
        dom = "dom1"
        rest = fname[4:]
    elif fname.startswith("dom2"):
        dom = "dom2"
        rest = fname[4:]
    elif fname.startswith("dom3"):
        dom = "dom3"
        rest = fname[4:]
    else:
        dom = "other"
        rest = fname

    char_name = ""
    for ch in rest:
        if ch.isalpha():
            char_name += ch
        else:
            break

    if not char_name or char_name in ["OP", "DefScn", "ENC", "HZR", "ED", "CHOICE", "MEZ", "Ed"]:
        return f"{dom}_common"
    else:
        return f"{dom}_{char_name}"


# Raw token IDs for the literal phrase "次のページ" ("next page")
_NEXT_PAGE_TOKENS = (0x5904, 0xB0A, 0x1102, 0x21E, 0xE1E)


def is_debug_menu_block(values):
    """Leftover dev QA menu entries that match the real dialogue box shape
    but aren't player-facing text."""
    if 0x0087 in values:
        return True
    n = len(_NEXT_PAGE_TOKENS)
    if len(values) >= n and tuple(values[-n:]) == _NEXT_PAGE_TOKENS:
        return True
    return False


def main():
    os.makedirs(TRANSLATIONS_DIR, exist_ok=True)

    # 1. Script/*.mes
    script_files = sorted(glob.glob(os.path.join(mc.ORIGIN_ROOT, "data", "Script", "*.mes")))
    # 2. Outside Script/ system .mes files
    outside_paths = [
        os.path.join(mc.ORIGIN_ROOT, "data", fname) for fname in OUTSIDE_MES_FILES
    ]
    all_files = script_files + [p for p in outside_paths if os.path.exists(p)]

    csv_data = {}
    total_blocks = 0
    total_files = 0

    for path in all_files:
        cat = get_category(path)
        if cat not in csv_data:
            csv_data[cat] = []

        fname = os.path.basename(path)
        rel_path = os.path.relpath(path, os.path.join(mc.ORIGIN_ROOT, "data"))
        values = mc.load_values(path)
        blocks = mc.find_dialogue_blocks(values)

        is_script = path.startswith(os.path.join(mc.ORIGIN_ROOT, "data", "Script"))
        real_blocks = []
        for s, e in blocks:
            if is_script and is_debug_menu_block(values[s:e]):
                continue
            real_blocks.append((s, e))

        if real_blocks:
            total_files += 1

        for i, (s, e) in enumerate(real_blocks):
            # Hide the trailing page-turn marker from the CSV text entirely
            # (see tio.PAGE_TURN_TOKEN) - mes_translate_reinsert.py restores
            # it automatically based on the real on-disk block boundary.
            text_end = e - 1 if values[e - 1] == tio.PAGE_TURN_TOKEN else e
            text = tio.tokens_to_text(values[s:text_end])
            header_val = values[s - 1] if s - 1 >= 0 else None
            speaker = speaker_map.speaker_of(header_val) if header_val is not None else None
            csv_data[cat].append({
                "file": fname,
                "rel_path": rel_path,
                "block": i,
                "n_tokens": e - s,
                "speaker": speaker if speaker is not None else f"UNKNOWN_{header_val:#04x}" if header_val is not None else "",
                "source": text,
                "ai_draft": "",
                "translation": "",
            })
            total_blocks += 1

    for cat, rows in sorted(csv_data.items()):
        out_csv = os.path.join(TRANSLATIONS_DIR, f"{cat}.csv")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows):4d} blocks -> temp/translations/{cat}.csv")

    print(f"\nScanned {len(all_files)} .mes files ({total_files} contain dialogue blocks)")
    print(f"Total {total_blocks} dialogue blocks extracted across {len(csv_data)} CSV files in {TRANSLATIONS_DIR}")


if __name__ == "__main__":
    main()
