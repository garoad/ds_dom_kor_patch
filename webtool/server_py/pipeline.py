"""
CSV extract/save/reinsert pipeline - Python port of webtool/server/lib/pipeline.js,
adapted to per-project workspaces. Unlike the JS version (which had to
re-implement mes_codec/translate_io/speaker_map/debug-filter logic on its own),
this calls straight into analysis/*.py - see CLAUDE.md rule 6 background /
ANALYSIS_NOTES.md 2026-08-28 "웹툴 백엔드 Node.js -> Python 재작성" for why.
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
ANALYSIS_DIR = os.path.join(REPO_ROOT, "analysis")
for _p in (ANALYSIS_DIR, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import apply_font_art as afa  # noqa: E402
import mes_codec as mc  # noqa: E402
import mes_translate_extract as mte  # noqa: E402
import mes_translate_reinsert as mtr  # noqa: E402
import speaker_map  # noqa: E402
import translate_io as tio  # noqa: E402

import project as proj  # noqa: E402

# Reused directly from analysis/*.py rather than redefined - these already
# match the webtool's contract exactly (verified against pipeline.js during
# the 2026-08-28 rewrite).
FIELDS = mte.FIELDS
OUTSIDE_MES_FILES = mte.OUTSIDE_MES_FILES
PLAYERNAME_FILE = mtr.PLAYERNAME_FILE
PLAYERNAME_MAX_TOKENS = mtr.PLAYERNAME_MAX_TOKENS
LIST_NO_LENGTH_CAP_FILES = mtr.LIST_NO_LENGTH_CAP_FILES
CHOICE_SPEAKER = mtr.CHOICE_SPEAKER
CHOICE_SPLIT_MARK = mtr.CHOICE_SPLIT_MARK
CHOICE_HEADER_SLOTS = mtr.CHOICE_HEADER_SLOTS
PAGE_TURN_TOKEN = tio.PAGE_TURN_TOKEN

# Windows renders (and, on some Korean keyboard layouts/IMEs, actually
# inputs) the backslash key as a won-sign look-alike instead of a literal
# "\" - both are treated as equivalent to CHOICE_SPLIT_MARK. Webtool-only
# robustness with no analysis/ equivalent (translators don't hit this in the
# CLI CSV workflow), ported from translateIo.js's
# CHOICE_SPLIT_MARK_ALIASES/normalizeChoiceSplitMarks.
CHOICE_SPLIT_MARK_ALIASES = ["₩", "￦"]


def normalize_choice_split_marks(text):
    result = text
    for alias in CHOICE_SPLIT_MARK_ALIASES:
        result = result.replace(alias, CHOICE_SPLIT_MARK)
    return result


def real_blocks_of(values):
    """Real (non-debug-menu) dialogue blocks for one .mes file, in CSV row order."""
    return [
        (s, e) for s, e in mc.find_dialogue_blocks(values)
        if not mte.is_debug_menu_block(values[s:e])
    ]


def read_csv(name):
    trans_dir = proj.csv_dir(name)
    rows = []
    if os.path.exists(trans_dir):
        for fname in sorted(os.listdir(trans_dir)):
            if not fname.endswith(".csv"):
                continue
            path = os.path.join(trans_dir, fname)
            with open(path, newline="", encoding="utf-8") as f:
                if f.read().strip():
                    f.seek(0)
                    rows.extend(csv.DictReader(f))
    return rows


def write_csv(name, rows):
    trans_dir = proj.csv_dir(name)
    unpack_dir = proj.unpack_dir(name)
    os.makedirs(trans_dir, exist_ok=True)

    cat_map = {}
    for r in rows:
        file_path = os.path.join(unpack_dir, "data", r.get("rel_path") or r["file"])
        cat = mte.get_category(file_path, origin_root=unpack_dir)
        cat_map.setdefault(cat, []).append(r)

    for cat, cat_rows in cat_map.items():
        out_path = os.path.join(trans_dir, f"{cat}.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(cat_rows)


def extract_project(name):
    """Scan every .mes file in the project's unpack/data/Script (+ the fixed
    OUTSIDE_MES_FILES list), extract real dialogue blocks, and merge with any
    existing CSV - rows matching on (file, block, n_tokens) keep their
    existing translation, since the CSV is the translator's save file and
    re-extraction must never wipe work.

    2026-08-28: the merge key deliberately excludes `source` - see
    pipeline.js's extractProject() comment for the full data-loss bug history
    this fixes (a font_map_full.json decode correction silently orphaned 26
    rows' translations when `source` was part of the key)."""
    unpack_dir = proj.unpack_dir(name)
    unpack_data_dir = os.path.join(unpack_dir, "data")
    script_dir = os.path.join(unpack_data_dir, "Script")

    script_files = []
    if os.path.exists(script_dir):
        script_files = sorted(
            os.path.join(script_dir, f) for f in os.listdir(script_dir)
            if f.lower().endswith(".mes")
        )

    outside_files = [os.path.join(unpack_data_dir, f) for f in OUTSIDE_MES_FILES]
    outside_files = [p for p in outside_files if os.path.exists(p)]
    all_files = script_files + outside_files

    existing = read_csv(name)
    existing_by_key = {}
    for row in existing:
        key = f"{row['file']} {row['block']} {row['n_tokens']}"
        existing_by_key[key] = {
            "ai_draft": row.get("ai_draft") or "",
            "translation": row.get("translation") or "",
        }

    rows = []
    files_with_blocks = 0
    skipped_debug = 0

    for file_path in all_files:
        fname = os.path.basename(file_path)
        rel_path = os.path.relpath(file_path, unpack_data_dir)
        values = mc.load_values(file_path)
        blocks = mc.find_dialogue_blocks(values)
        is_script = file_path.startswith(script_dir)

        real_blocks = []
        for s, e in blocks:
            if is_script and mte.is_debug_menu_block(values[s:e]):
                skipped_debug += 1
            else:
                real_blocks.append((s, e))
        if real_blocks:
            files_with_blocks += 1

        for i, (s, e) in enumerate(real_blocks):
            # Hide the trailing page-turn marker from the CSV text entirely
            # (see tio.PAGE_TURN_TOKEN) - build_file_tokens()/validate_row()
            # restore it automatically.
            text_end = e - 1 if values[e - 1] == tio.PAGE_TURN_TOKEN else e
            text = tio.tokens_to_text(values[s:text_end])
            header_val = values[s - 1] if s - 1 >= 0 else None
            speaker = speaker_map.speaker_of(header_val) if header_val is not None else None
            n_tokens = e - s
            key = f"{fname} {i} {n_tokens}"
            saved = existing_by_key.get(key, {"ai_draft": "", "translation": ""})

            rows.append({
                "file": fname,
                "rel_path": rel_path,
                "block": i,
                "n_tokens": n_tokens,
                "speaker": (
                    speaker if speaker is not None
                    else (f"UNKNOWN_{header_val:02x}" if header_val is not None else "")
                ),
                "source": text,
                "ai_draft": saved["ai_draft"],
                "translation": saved["translation"],
            })

    write_csv(name, rows)
    return {
        "filesScanned": len(all_files),
        "filesWithBlocks": files_with_blocks,
        "totalBlocks": len(rows),
        "skippedDebug": skipped_debug,
        "translatedCount": sum(1 for r in rows if r["translation"] and r["translation"].strip()),
    }


def file_summaries(name):
    rows = read_csv(name)
    by_file = {}
    for row in rows:
        f = row["file"]
        if f not in by_file:
            by_file[f] = {"file": f, "blockCount": 0, "translatedCount": 0}
        by_file[f]["blockCount"] += 1
        if row.get("translation") and row["translation"].strip():
            by_file[f]["translatedCount"] += 1
    return list(by_file.values())


def real_block_page_turn_flags(name, fname, rel_path):
    """Per-block "does this block's real on-disk token stream end with the
    hidden PAGE_TURN_TOKEN" flags, read directly from the pristine unpack/
    file - the same authoritative source build_file_tokens() uses. Returns
    None if the file can't be resolved (falls back to
    detect_has_page_turn()'s text-based guess in that case)."""
    unpack_data_dir = os.path.join(proj.unpack_dir(name), "data")
    src_path = os.path.join(unpack_data_dir, rel_path) if rel_path else os.path.join(proj.script_dir(name), fname)
    if not os.path.exists(src_path):
        src_path = os.path.join(unpack_data_dir, fname)
    if not os.path.exists(src_path):
        return None

    values = mc.load_values(src_path)
    is_script = src_path.startswith(os.path.join(unpack_data_dir, "Script"))
    blocks = real_blocks_of(values) if is_script else mc.find_dialogue_blocks(values)
    return [e > s and values[e - 1] == PAGE_TURN_TOKEN for s, e in blocks]


def detect_has_page_turn(src_text, expected_token_count):
    """Fallback used only when the real .mes file can't be resolved."""
    if expected_token_count is None:
        return False
    src_token_count = expected_token_count
    try:
        src_token_count = len(tio.text_to_tokens(src_text))
    except ValueError:
        pass
    return src_token_count == expected_token_count - 1


def max_len_of(row, fname, has_page_turn_hint=None):
    """The usable character budget for a row's translation, for display to
    the translator. Returns None when the file has no length cap at all
    (see LIST_NO_LENGTH_CAP_FILES)."""
    if fname == PLAYERNAME_FILE:
        return PLAYERNAME_MAX_TOKENS
    if fname in LIST_NO_LENGTH_CAP_FILES:
        return None
    n_tokens = int(row["n_tokens"])
    has_page_turn = (
        has_page_turn_hint if has_page_turn_hint is not None
        else detect_has_page_turn(row["source"], n_tokens)
    )
    return n_tokens - 1 if has_page_turn else n_tokens


def rows_for_file(name, fname):
    rows = [r for r in read_csv(name) if r["file"] == fname]
    rel_path = next((r["rel_path"] for r in rows if r.get("rel_path")), None)
    page_turn_flags = real_block_page_turn_flags(name, fname, rel_path)
    out = []
    for r in rows:
        r = dict(r)
        hint = page_turn_flags[int(r["block"])] if page_turn_flags is not None else None
        r["max_len"] = max_len_of(r, fname, hint)
        out.append(r)
    return out


def validate_row(src_text, dst_text_raw, expected_token_count, fname, has_page_turn_hint=None, speaker=None):
    """Validate one row's translation without writing anything. See
    pipeline.js's validateRow for the full behavior contract this mirrors."""
    dst_text = normalize_choice_split_marks(dst_text_raw if dst_text_raw else src_text)
    problems = tio.validate_placeholders(src_text, dst_text)
    if problems:
        return {"ok": False, "error": "; ".join(problems)}

    has_page_turn = (
        has_page_turn_hint if has_page_turn_hint is not None
        else detect_has_page_turn(src_text, expected_token_count)
    )
    text_expected = expected_token_count - 1 if has_page_turn else expected_token_count

    if speaker == CHOICE_SPEAKER and CHOICE_SPLIT_MARK in dst_text:
        opt_texts = dst_text.split(CHOICE_SPLIT_MARK)
        if len(opt_texts) - 1 > CHOICE_HEADER_SLOTS - 1:
            return {
                "ok": False,
                "error": (
                    f"too many choice options - {len(opt_texts)} option markers found, "
                    f"max {CHOICE_HEADER_SLOTS} options allowed"
                ),
            }
        try:
            opt_tokens = [tio.text_to_tokens(t) for t in opt_texts]
        except ValueError as ex:
            return {"ok": False, "error": str(ex)}
        total = sum(len(t) for t in opt_tokens)
        if total > text_expected:
            return {
                "ok": False,
                "error": f"choice options too long - encode to {total} tokens combined, original allows {text_expected}",
            }
        return {"ok": True, "tokenCount": text_expected + (1 if has_page_turn else 0)}

    try:
        tokens = tio.text_to_tokens(dst_text)
    except ValueError as ex:
        return {"ok": False, "error": str(ex)}

    if fname == PLAYERNAME_FILE:
        if len(tokens) > PLAYERNAME_MAX_TOKENS:
            return {
                "ok": False,
                "error": (
                    f"player name too long - encodes to {len(tokens)} characters, "
                    f"but names are capped at {PLAYERNAME_MAX_TOKENS} in-game"
                ),
            }
        return {"ok": True, "tokenCount": len(tokens)}

    if fname in LIST_NO_LENGTH_CAP_FILES:
        return {"ok": True, "tokenCount": len(tokens)}

    if text_expected is not None and len(tokens) < text_expected:
        tokens = tokens + [tio.SPACE_TOKEN] * (text_expected - len(tokens))
    return {"ok": True, "tokenCount": len(tokens) + (1 if has_page_turn else 0)}


def save_file(name, fname, edits):
    """Save a batch of {block, translation, ai_draft} edits for one file,
    validating each row against its original n_tokens. Validation failures
    do not block saving (drafts are allowed) - the caller gets a per-row
    report."""
    rows = read_csv(name)
    edit_by_block = {str(e["block"]): e for e in edits}
    report = []

    file_rows = [r for r in rows if r["file"] == fname]
    rel_path = next((r["rel_path"] for r in file_rows if r.get("rel_path")), None)
    page_turn_flags = real_block_page_turn_flags(name, fname, rel_path)

    for row in rows:
        if row["file"] != fname:
            continue
        if str(row["block"]) not in edit_by_block:
            continue
        item = edit_by_block[str(row["block"])]
        if item.get("translation") is not None:
            row["translation"] = item["translation"]
        if item.get("ai_draft") is not None:
            row["ai_draft"] = item["ai_draft"]

        block_idx = int(row["block"])
        has_page_turn_hint = page_turn_flags[block_idx] if page_turn_flags is not None else None
        v = validate_row(
            row["source"], row["translation"], int(row["n_tokens"]), fname,
            has_page_turn_hint, row.get("speaker"),
        )
        if not v["ok"]:
            report.append({"block": block_idx, "ok": False, "error": v["error"]})
        elif (
            fname != PLAYERNAME_FILE
            and fname not in LIST_NO_LENGTH_CAP_FILES
            and v["tokenCount"] != int(row["n_tokens"])
        ):
            # Shorter translations are already padded to match inside
            # validate_row, so only "longer" (which would drop content if
            # trimmed) reaches here.
            report.append({
                "block": block_idx,
                "ok": False,
                "error": (
                    f"token count mismatch - original has {row['n_tokens']} tokens, "
                    f"translation encodes to {v['tokenCount']} (longer)"
                ),
            })
        else:
            report.append({"block": block_idx, "ok": True})

    write_csv(name, rows)
    return report


# 2026-08-20: is_dangerous_opcode_block() below blanket-preserves any block
# whose source text embeds what looks like a control-code/opcode tag. Kept
# empty as an escape hatch (mirrors pipeline.js's SAFE_OPCODE_OVERRIDES) -
# see that file's comment for the full rationale.
SAFE_OPCODE_OVERRIDES = set()


def is_dangerous_opcode_block(src_text):
    if not src_text:
        return False
    for prefix in (
        "<000", "<001", "<002", "<003", "<004", "<005", "<006", "<007",
        "<008", "<009", "<00A", "<00B", "<00C", "<00D", "<00E", "<00F",
        "<FF", "<FC",
    ):
        if prefix in src_text:
            return True
    if src_text.startswith("<0"):
        return True
    return bool(re.match(r"^[a-zA-Z0-9~,.<>]{1,5}<00", src_text))


def compute_header_splice(src_values, src_text, dst_text):
    """See pipeline.js's computeHeaderSplice for the full rationale: finds
    how many leading text units (tio.split_units) are character-for-character
    identical between source and translation, then splices the SOURCE's own
    raw tokens for that many units (byte-exact, no re-encoding) and only
    encodes the translation's remaining suffix. Returns None when no header
    prefix survived untouched, or the leftover suffix still looks
    dangerous."""
    src_units = tio.split_units(src_text)
    dst_units = tio.split_units(dst_text)
    header_token_len = 0
    src_char_len = 0
    dst_char_len = 0
    i = 0
    while i < len(src_units) and i < len(dst_units) and src_units[i] == dst_units[i]:
        header_token_len += tio.unit_token_length(src_units[i])
        src_char_len += len(src_units[i])
        dst_char_len += len(dst_units[i])
        i += 1
    if header_token_len == 0 or header_token_len > len(src_values):
        return None
    src_suffix_text = src_text[src_char_len:]
    if is_dangerous_opcode_block(src_suffix_text):
        return None
    return {"headerTokenLen": header_token_len, "srcCharLen": src_char_len, "dstCharLen": dst_char_len}


def build_file_tokens(name, fname, rows_by_block):
    """Re-derive blocks from the pristine unpack/ file (never from stale CSV
    offsets) and build the translated token stream. Returns
    {tokens, relPath, problems}. Non-empty `problems` means the caller must
    skip this file entirely (matches mes_translate_reinsert.py's
    all-or-nothing per-file behavior). rows_by_block: {block_index: row}."""
    unpack_data_dir = os.path.join(proj.unpack_dir(name), "data")
    rel_path = None
    for r in rows_by_block.values():
        if r.get("rel_path"):
            rel_path = r["rel_path"]
            break

    src_path = os.path.join(unpack_data_dir, rel_path) if rel_path else os.path.join(proj.script_dir(name), fname)
    if not os.path.exists(src_path):
        src_path = os.path.join(unpack_data_dir, fname)
    if not os.path.exists(src_path):
        return {"tokens": None, "relPath": rel_path, "problems": [f"source file not found: {src_path}"]}

    values = mc.load_values(src_path)
    is_script = src_path.startswith(os.path.join(unpack_data_dir, "Script"))
    blocks = real_blocks_of(values) if is_script else mc.find_dialogue_blocks(values)

    if len(blocks) != len(rows_by_block):
        return {
            "tokens": None,
            "relPath": rel_path,
            "problems": [
                f"block count mismatch: CSV has {len(rows_by_block)} rows for {fname}, "
                f"current file has {len(blocks)} real dialogue blocks (CSV is stale - re-run extract)"
            ],
        }

    problems = []
    out = []
    last = 0

    for i, (s, e) in enumerate(blocks):
        row = rows_by_block[i]
        src_text = row["source"]
        translation = row.get("translation") or ""
        dst_text = normalize_choice_split_marks(translation if translation else src_text)

        if not translation or translation == src_text:
            out.extend(values[last:s])
            out.extend(values[s:e])
            last = e
            continue

        # See pipeline.js's buildFileTokens comment (2026-08-27 entry) for
        # the full boundary-header-drift rationale: find_dialogue_blocks()'s
        # backward scan can classify a block's start earlier than the
        # extractor originally computed it, so the CSV's n_tokens can be
        # narrower than the true (e - s) span.
        full_len = e - s
        has_page_turn = full_len > 0 and values[e - 1] == PAGE_TURN_TOKEN
        text_expected_len = full_len - 1 if has_page_turn else full_len

        csv_len = int(row.get("n_tokens") or 0)
        boundary_header_len = full_len - csv_len if full_len > csv_len else 0
        content_start = s + boundary_header_len

        prefix_tokens = values[s:content_start] if boundary_header_len > 0 else []
        effective_src_text = src_text
        effective_dst_text = dst_text

        if boundary_header_len == 0 and is_dangerous_opcode_block(src_text):
            src_values = values[s:s + text_expected_len]
            splice = compute_header_splice(src_values, src_text, dst_text)
            if not splice:
                out.extend(values[last:s])
                out.extend(values[s:e])
                last = e
                continue
            prefix_tokens = src_values[:splice["headerTokenLen"]]
            effective_src_text = src_text[splice["srcCharLen"]:]
            effective_dst_text = dst_text[splice["dstCharLen"]:]

        # [선택지] blocks: if the translator marked explicit option
        # boundaries with CHOICE_SPLIT_MARK, and the block's original header
        # matches the "clean N-option" pattern, split+encode each option
        # separately and patch the header's own split-point fields. Gated to
        # boundary_header_len == 0 so this never interacts with the
        # header-splice drift-correction path above.
        choice_split_count = dst_text.count(CHOICE_SPLIT_MARK) if row.get("speaker") == CHOICE_SPEAKER else 0
        choice_header_sum = (
            values[s - 6] + values[s - 5] + values[s - 4] + values[s - 3] + values[s - 2]
            if s - 6 >= 0 else None
        )
        is_choice_split = (
            row.get("speaker") == CHOICE_SPEAKER
            and boundary_header_len == 0
            and s - 6 >= last
            and 1 <= choice_split_count <= CHOICE_HEADER_SLOTS - 1
            and choice_header_sum == 2 * text_expected_len
        )

        new_tokens = None
        choice_header_patch = None

        if is_choice_split:
            opt_texts = dst_text.split(CHOICE_SPLIT_MARK)
            placeholder_problems = tio.validate_placeholders(effective_src_text, effective_dst_text)
            if placeholder_problems:
                problems.append(f"block {i}: " + "; ".join(placeholder_problems))
                continue
            try:
                opt_tokens = [tio.text_to_tokens(t) for t in opt_texts]
            except ValueError as ex:
                problems.append(f"block {i}: {ex}")
                continue
            total = sum(len(t) for t in opt_tokens)
            if total > text_expected_len:
                problems.append(
                    f"block {i}: choice options too long - encode to {total} tokens combined, "
                    f"original allows {text_expected_len}"
                )
                continue
            if total < text_expected_len:
                opt_tokens[-1] = opt_tokens[-1] + [tio.SPACE_TOKEN] * (text_expected_len - total)
            new_tokens = [tok for opt in opt_tokens for tok in opt]
            lengths = [len(opt) * 2 for opt in opt_tokens]
            lengths += [0] * (CHOICE_HEADER_SLOTS - len(lengths))
            choice_header_patch = lengths
        else:
            if f"{fname}:{i}" not in SAFE_OPCODE_OVERRIDES:
                placeholder_problems = tio.validate_placeholders(effective_src_text, effective_dst_text)
                if placeholder_problems:
                    problems.append(f"block {i}: " + "; ".join(placeholder_problems))
                    continue

            try:
                new_tokens = tio.text_to_tokens(effective_dst_text)
            except ValueError as ex:
                problems.append(f"block {i}: {ex}")
                continue
            if prefix_tokens:
                new_tokens = list(prefix_tokens) + new_tokens

            if fname == PLAYERNAME_FILE:
                if len(new_tokens) > PLAYERNAME_MAX_TOKENS:
                    problems.append(
                        f"block {i}: player name too long - encodes to {len(new_tokens)} characters, "
                        f"but names are capped at {PLAYERNAME_MAX_TOKENS} in-game"
                    )
                    continue
                out.extend(values[last:s])
                out.extend(new_tokens)
                last = e
                continue

            if fname in LIST_NO_LENGTH_CAP_FILES:
                out.extend(values[last:s])
                out.extend(new_tokens)
                last = e
                continue

            if len(new_tokens) < text_expected_len:
                new_tokens = new_tokens + [tio.SPACE_TOKEN] * (text_expected_len - len(new_tokens))

            if len(new_tokens) != text_expected_len:
                problems.append(
                    f"block {i}: token count mismatch - original has {text_expected_len} tokens, "
                    f"translation encodes to {len(new_tokens)} (longer). Dialogue blocks "
                    "must keep an identical token count or the game hangs on real hardware/melonDS."
                )
                continue

        if has_page_turn:
            new_tokens = new_tokens + [PAGE_TURN_TOKEN]

        out.extend(values[last:s])
        if choice_header_patch:
            out[-6], out[-5], out[-4], out[-3], out[-2] = choice_header_patch
        out.extend(new_tokens)
        last = e

    if problems:
        return {"tokens": None, "relPath": rel_path, "problems": problems}

    out.extend(values[last:])
    return {"tokens": out, "relPath": rel_path, "problems": []}


def apply_font_art(name):
    """Bake Hangul glyphs into build/data/Font_DOM.nbfc for one project - a
    thin wrapper around analysis/apply_font_art.py, which already IS the
    canonical, hardware-validated implementation (no separate
    parse_bdf/render_glyph reimplementation needed here, unlike the JS
    port)."""
    build_dir = proj.build_dir(name)
    nbfc_path = os.path.join(build_dir, "data", "Font_DOM.nbfc")
    if not os.path.exists(nbfc_path):
        return
    bdf_path = os.path.join(REPO_ROOT, "analysis", "fonts", "Galmuri11.bdf")
    if not os.path.exists(bdf_path):
        return
    font_map_path = os.path.join(REPO_ROOT, "analysis", "font_map_kr.json")
    # reset_from=None: the webtool's build/ dir is already a fresh copy of
    # unpack/ before this runs (see routes/build.py's reinsert handler), so
    # there is no pristine origin to reset from here.
    afa.apply_font_art(nbfc_path, font_map_path=font_map_path, bdf_path=bdf_path, reset_from=None)


def search_csv(name, query, target="all", limit=200):
    rows = read_csv(name)
    if not rows:
        return {"total": 0, "results": []}

    q_lower = query.lower()
    matched = []
    for r in rows:
        source = (r.get("source") or "").lower()
        translation = (r.get("translation") or "").lower()
        ai_draft = (r.get("ai_draft") or "").lower()
        speaker = (r.get("speaker") or "").lower()
        file_ = (r.get("file") or "").lower()

        if target == "source":
            is_match = q_lower in source
        elif target == "translation":
            is_match = q_lower in translation or q_lower in ai_draft
        elif target == "speaker":
            is_match = q_lower in speaker
        elif target == "file":
            is_match = q_lower in file_
        else:
            is_match = (
                q_lower in source or q_lower in translation
                or q_lower in ai_draft or q_lower in speaker or q_lower in file_
            )

        if is_match:
            matched.append(r)

    total = len(matched)
    sliced = matched[:limit] if limit > 0 else matched
    return {"total": total, "query": query, "results": sliced}
