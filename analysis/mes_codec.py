"""
Unified .mes decoder/encoder.

Token stream model: a decoded .mes file is a flat list of u16 values (ints).
For editing/translation purposes we don't need to interpret ctrl codes -
they are opaque integers that must be preserved verbatim in position
relative to the text codes around them. Only 'full'/'half' codes (real
glyphs) are candidates for replacement during translation.

encode(decode(raw)) must reproduce `raw`'s decompressed bytes exactly - this
is the core correctness property this module is built around (verified by
mes_codec_roundtrip_test.py).
"""
import json
import os
import struct

import lz10

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.join(PROJECT_ROOT, "unpack")
ORIGIN_ROOT = os.path.join(PROJECT_ROOT, "unpack_origin")

with open(os.path.join(HERE, "font_map_full.json")) as f:
    _FM = json.load(f)
CODES = _FM["codes"]


def num_tiles_for(data_dir):
    """Tile count for a project's own Font_DOM.nbfc (64 bytes/8bpp tile).
    Different projects (webtool workspaces built from different ROM copies)
    can have a different tile count, so this must never be hardcoded to a
    single global file - see webtool/server_py/pipeline.py callers."""
    with open(os.path.join(data_dir, "Font_DOM.nbfc"), "rb") as f:
        return len(f.read()) // 64


# Backward-compatible default for analysis/ CLI scripts, which always target
# the single fixed unpack/ directory this repo's own translation work uses.
# Lazy/tolerant so importing mes_codec doesn't require that file to exist
# (e.g. from a webtool process operating on a different project's workspace).
try:
    NUM_TILES = num_tiles_for(os.path.join(ROOT, "data"))
except FileNotFoundError:
    NUM_TILES = None


def decode_value(v, num_tiles=NUM_TILES):
    bank = (v >> 8) & 0xFF
    low = v & 0xFF
    if bank == 0:
        if low >= 0x80:
            return ("half", low - 128)
        return ("ctrl", v)
    if num_tiles is not None and v + 33 >= num_tiles:
        return ("ctrl", v)
    return ("full", v)


def load_values(path):
    """Read a .mes file (LZ10-compressed or raw) and return list[int] u16 values."""
    with open(path, "rb") as f:
        raw = f.read()
    dec = lz10.decompress(raw) if raw and raw[0] == 0x10 else raw
    n = len(dec) // 2
    return list(struct.unpack(f"<{n}H", dec[: n * 2]))


def dump_values(values, path, compress=True):
    """Write list[int] u16 values back out as a .mes file (LZ10-compressed by default)."""
    body = struct.pack(f"<{len(values)}H", *values)
    out = lz10.compress(body) if compress else body
    with open(path, "wb") as f:
        f.write(out)


def render(values):
    """Render a value list to a display string. Unresolved/ctrl codes shown as <HEX>."""
    out = []
    for v in values:
        k = "%04X" % v
        e = CODES.get(k)
        if e is not None and e.get("kind") in ("full", "half"):
            out.append(e.get("char", f"<{k}>"))
        elif e is not None and e.get("kind") == "blank":
            out.append(" ")
        else:
            out.append(f"<{k}>")
    return "".join(out)


def find_dialogue_blocks(values):
    """Return list of (start, end) index ranges (content only, box-boundary
    marker excluded) for real dialogue/text boxes.

    A box boundary is a literal double 0x6E5C 0x6E5C (usually preceded by
    the 0x485C page-turn marker, but not always - what follows the double
    0x6E5C varies: 0x0000 is common but far from universal, so it is NOT
    part of the match). Content within a box starts at the first token
    classified 'full' in the corpus-derived CODES map, extended backward
    over any immediately-adjacent 'half' tokens (to keep a leading
    half-width digit like the "3" in "3人とも" - CODES marks header/counter
    ints as 'half' too when they happen to fall in the same byte range, but
    those are never directly adjacent to the first real glyph).

    This replaces two earlier, narrower attempts: (1) a forward scan for
    "0x0002 then next 0x0000" that latched onto stray 0/2 values inside
    header data and silently dropped real blocks; (2) a terminator-first
    backward scan for a literal 0x0002 opener, which recovers most blocks
    but still misses every box whose header happens to end in a value
    other than 0x0002 (0x0003, 0x17, 0x18, ... all observed in the wild).
    Requiring only the double-0x6E5C boundary and using the CODES 'kind'
    classification (not a fixed opener value) to find content is the
    format-agnostic version of both.
    """
    n = len(values)
    terms = []
    i = 0
    while i < n - 1:
        if values[i] == 0x6E5C and values[i + 1] == 0x6E5C:
            terms.append(i)
            i += 2
        else:
            i += 1

    def kind_of(v):
        return CODES.get("%04X" % v, {}).get("kind")

    # Sentinels deliberately tagged 'full' in font_map_full.json despite not
    # being real characters (see translate_io.py's NAME_VAR_PREFIX/
    # PAGE_TURN_TOKEN) - they mark meaningful content-adjacent positions
    # (name-insertion point, page-turn boundary) and are valid block-start
    # anchors even standing alone with nothing after them but a terminator.
    _SENTINEL_STARTS = {0x505C, 0x485C}

    def is_real_glyph_start(i2, t):
        """True if values[i2] is a trustworthy text-glyph block start.

        decode_value()'s 'full' classification is a pure value-range test
        (bank!=0 and within the tile table) - it can't tell a real glyph
        from a header/parameter value that coincidentally falls in the same
        numeric range (e.g. 0x0100, seen only as a call-scene header token
        in *_O0727_0.mes, never inside real text - see ANALYSIS_NOTES.md
        "깨진 숫자 프리픽스 버그 근본원인 규명"). A 'full' code is trusted as a
        real block start only if it's independently corroborated: either
        it's one of the known no-char sentinels above, or the very next
        token is itself full/half (part of a multi-glyph run, as real text
        always is), or it already has a corpus-confirmed 'char' label AND
        stands truly alone (immediately followed by the box terminator at
        `t`) - matching genuine single-token blocks like '♪' or a lone
        kanji in namelist1.mes.

        Without the "immediately before terminator" condition, a
        char-labeled value can still be a false positive: repeated menu/
        list structures pad each item with a decrementing counter param
        whose value coincidentally lands on a char-labeled tile (e.g.
        0x0144='tu', 0x0134='bc' in dom3HZR.mes block 0) but is followed by
        many more control tokens before the real text run starts - not a
        real glyph, just numeric coincidence like 0x0100 above, just with
        the added coincidence of also matching a char label from
        elsewhere in the corpus.

        'blank' (a corpus-confirmed rendered space, e.g. after a
        stand-alone '!' reaction mark - seen 108x across the corpus, as in
        dom3TrainingINT.mes "!<space>そんな、肺病がそこまで……") counts as a
        real-content follow-on token alongside full/half, since it's a
        rendered character, not raw ctrl noise.
        """
        v = values[i2]
        if kind_of(v) != "full":
            return False
        if v in _SENTINEL_STARTS:
            return True
        if i2 + 1 < len(values) and kind_of(values[i2 + 1]) in ("full", "half", "blank"):
            return True
        if i2 + 1 == t and CODES.get("%04X" % v, {}).get("char") is not None:
            return True
        return False

    blocks = []
    prev_term_end = 0
    for t in terms:
        start = None
        for i2 in range(prev_term_end, t):
            if is_real_glyph_start(i2, t):
                start = i2
                break
        if start is not None:
            while start - 1 >= prev_term_end and kind_of(values[start - 1]) == "half":
                start -= 1
            blocks.append((start, t))
        prev_term_end = t + 2
    return blocks


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/common.mes"
    values = load_values(path)
    print(f"{path}: {len(values)} u16 values")
    blocks = find_dialogue_blocks(values)
    print(f"dialogue blocks found: {len(blocks)}")
    for s, e in blocks[:5]:
        print(" ", render(values[s:e]))
    if not blocks:
        print(render(values))
