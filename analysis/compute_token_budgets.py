"""
Compute the exact per-row token budget (text_expected_len, as used by
mes_translate_reinsert.build_file()) for every row of a translation CSV,
WITHOUT needing any translation text yet.

This lets translators/agents see the hard per-block ceiling up front instead
of discovering budget overflows only after running the oracle - the mistake
that caused the dom3_common.csv (2026-08-31) and dom3_Mina.csv (2026-08-31)
mass-failure incidents (see ANALYSIS_NOTES.md).

Usage:
    python3 analysis/compute_token_budgets.py translations/dom3_Shiki.csv \
        > temp/dom3_Shiki_budgets.json

Output: JSON dict of {csv_row_index (str): text_expected_len (int)}.
For [선택지] (choice) rows, this is the COMBINED budget both options must
fit within together, same as every other row.
"""
import csv
import json
import sys
from collections import defaultdict

import mes_codec as mc
import mes_translate_extract as mte
import translate_io as tio


def compute_budgets(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_file = defaultdict(dict)
    row_index_by_file_block = {}
    for i, row in enumerate(rows):
        by_file[row["file"]][int(row["block"])] = row
        row_index_by_file_block[(row["file"], int(row["block"]))] = i

    budgets = {}
    for fname, rows_by_block in sorted(by_file.items()):
        first_row = next(iter(rows_by_block.values()))
        rel_path = first_row.get("rel_path")
        if rel_path:
            src_path = mc.os.path.join(mc.ROOT, "data", rel_path)
            if not mc.os.path.exists(src_path):
                src_path = mc.os.path.join(mc.ORIGIN_ROOT, "data", rel_path)
        else:
            src_path = mc.os.path.join(mc.ROOT, "data", "Script", fname)
            if not mc.os.path.exists(src_path):
                src_path = mc.os.path.join(mc.ORIGIN_ROOT, "data", "Script", fname)

        if not mc.os.path.exists(src_path):
            print(f"WARNING: source not found for {fname}, skipping", file=sys.stderr)
            continue

        values = mc.load_values(src_path)
        all_blocks = mc.find_dialogue_blocks(values)
        is_script = "Script" in src_path
        blocks = [
            (s, e) for s, e in all_blocks
            if not (is_script and mte.is_debug_menu_block(values[s:e]))
        ]

        if len(blocks) != len(rows_by_block):
            print(
                f"WARNING: block count mismatch for {fname}: CSV has "
                f"{len(rows_by_block)}, file has {len(blocks)} - skipping",
                file=sys.stderr,
            )
            continue

        for i, (s, e) in enumerate(blocks):
            expected_len = e - s
            has_page_turn = expected_len > 0 and values[e - 1] == tio.PAGE_TURN_TOKEN
            text_expected_len = expected_len - 1 if has_page_turn else expected_len
            row_idx = row_index_by_file_block[(fname, i)]
            budgets[str(row_idx)] = text_expected_len

    return budgets


def main():
    if len(sys.argv) != 2:
        print("usage: compute_token_budgets.py <csv_path>", file=sys.stderr)
        sys.exit(1)
    budgets = compute_budgets(sys.argv[1])
    print(json.dumps(budgets, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
