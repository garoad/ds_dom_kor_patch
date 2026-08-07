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
ROOT = os.path.abspath(os.path.join(HERE, "..", "unpack"))

with open(os.path.join(HERE, "font_map_full.json")) as f:
    _FM = json.load(f)
CODES = _FM["codes"]

with open(f"{ROOT}/data/Font_DOM.nbfc", "rb") as f:
    _NBFC = f.read()
NUM_TILES = len(_NBFC) // 64


def decode_value(v):
    bank = (v >> 8) & 0xFF
    low = v & 0xFF
    if bank == 0:
        if low >= 0x80:
            return ("half", 2 * low - 14)
        return ("ctrl", v)
    if v + 33 >= NUM_TILES:
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

    blocks = []
    prev_term_end = 0
    for t in terms:
        start = None
        for i2 in range(prev_term_end, t):
            if kind_of(values[i2]) == "full":
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
