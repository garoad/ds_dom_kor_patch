"""
Lossless text<->token conversion for the translation pipeline.

Unlike mes_codec.render() (a quick skim/debug view that collapses 'blank'
codes to a space and prints malformed multi-char debug labels like
'?(punct, unresolved)' inline), tokens_to_text()/text_to_tokens() here must
round-trip exactly, because translators edit the text form and we re-encode
it back to u16 codes for repacking.

Rule: a token is rendered as its literal character ONLY if font_map_full.json
maps it to kind in ('full','half') AND that mapping is a single real
character. Everything else (ctrl codes, blank/formatting codes, and the
handful of still-unresolved debug-labeled codes) is rendered as an explicit
<HEX> placeholder that the translator must carry through untouched. This
avoids the ambiguity of collapsing 22 different 'blank' codes to one space
character, which would make the reverse mapping (space -> which blank code?)
impossible.
"""
import json
import os
import re
from collections import Counter

import mes_codec as mc

# Load Korean font map for text_to_tokens re-encoding
with open(os.path.join(mc.HERE, "font_map_kr.json")) as _f:
    _FM_KR = json.load(_f)
CODES_KR = _FM_KR["codes"]

PLACEHOLDER_RE = re.compile(r"<([0-9A-Fa-f]{1,4})>")

# 2026-08-06: player-inputted protagonist name marker. 0x505C appears 2786x
# corpus-wide, 99.7% of the time immediately followed by 0x3131 or 0x3232
# (2777x) - both of which NEVER appear anywhere else in the entire corpus
# (0 standalone occurrences). Confirmed via raw context scan: every instance
# (with or without the 3131/3232 suffix) sits exactly where a character
# addresses the protagonist by name or the protagonist refers to themselves
# ("<505C>君、遅くなって" = "<name>-kun, sorry I'm late", "どうも<505C>です" =
# "hi, I'm <name>"), never as a real word. 0x505C's own real_tile (5212) does
# render as a legitimate kanji (咲) if drawn literally, but that glyph is
# never what's on screen here - like <485C> reusing 糠's tile as a page-turn
# control code, this is the same "valid tile address repurposed as a
# sentinel" trick. The 3131/3232 suffix's exact meaning (honorific/case
# variant?) is NOT decoded - only its presence and identity is preserved
# losslessly, per this project's "no fix is better than a wrong fix" policy.
# Rendered distinctly as <이름> / <이름:3131> / <이름:3232> so a translator
# never mistakes it for an unresolved font code or literal text, and so
# validate_placeholders() can enforce it's never dropped/duplicated - the
# block-length-fixed constraint means losing or adding a token here corrupts
# the whole file.
NAME_VAR_PREFIX = 0x505C
NAME_VAR_SUFFIXES = {0x3131, 0x3232}
NAME_VAR_RE = re.compile(r"<이름(?::([0-9A-Fa-f]{4}))?>")

_CHAR_TO_CODE = {}
# Some characters (space, ':', digits, 'A'/'B') have both a half-width and a
# full-width tile in the corpus. Prefer half-width for these: Korean text
# uses these ASCII-style characters at half-width spacing convention, and a
# handful of full-width duplicates (e.g. the ' ' at 0xA002, a brand-new
# blank tile added by an earlier repaint pass) render nearly 2x as wide as
# intended, making translated lines look oddly spaced out (2026-08-06).
for _pass_kinds in (("half",), ("full",)):
    for _k, _v in CODES_KR.items():
        if _v.get("kind") in _pass_kinds:
            _ch = _v.get("char")
            if _ch and len(_ch) == 1:
                _CHAR_TO_CODE.setdefault(_ch, int(_k, 16))

# Force space to use 0xA002 (full-width 16x16 blank tile) for dialogue text
_CHAR_TO_CODE[" "] = 0xA002


def is_literal_glyph(v):
    e = mc.CODES.get("%04X" % v)
    return bool(e) and e.get("kind") in ("full", "half") and e.get("char") and len(e["char"]) == 1


def tokens_to_text(values):
    out = []
    i, n = 0, len(values)
    while i < n:
        v = values[i]
        if v == NAME_VAR_PREFIX:
            if i + 1 < n and values[i + 1] in NAME_VAR_SUFFIXES:
                out.append("<이름:%04X>" % values[i + 1])
                i += 2
                continue
            out.append("<이름>")
            i += 1
            continue
        if is_literal_glyph(v):
            out.append(mc.CODES["%04X" % v]["char"])
        else:
            out.append("<%04X>" % v)
        i += 1
    return "".join(out)


def text_to_tokens(text):
    """Inverse of tokens_to_text. Raises ValueError on any character with no
    assigned font code (untranslated glyph, unassigned punctuation/space,
    or a malformed <HEX> placeholder)."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        m = NAME_VAR_RE.match(text, i)
        if m:
            tokens.append(NAME_VAR_PREFIX)
            if m.group(1):
                tokens.append(int(m.group(1), 16))
            i = m.end()
            continue
        m = PLACEHOLDER_RE.match(text, i)
        if m:
            tokens.append(int(m.group(1), 16))
            i = m.end()
            continue
        ch = text[i]
        if ch not in _CHAR_TO_CODE:
            raise ValueError(
                f"no font code assigned for character {ch!r} at position {i} in: {text!r}"
            )
        tokens.append(_CHAR_TO_CODE[ch])
        i += 1
    return tokens


def validate_placeholders(src_text, dst_text):
    """Every <HEX> control/formatting placeholder in the source must appear
    the same number of times in the translation - these encode control flow
    (line breaks, variable substitution, timing, etc.) the translator must
    not drop, duplicate, or invent. Order is NOT enforced (a translator may
    need to reorder a name-substitution placeholder for grammar), only
    counts."""
    def counts(text):
        c = Counter(PLACEHOLDER_RE.findall(text))
        for m in NAME_VAR_RE.finditer(text):
            c["이름:" + (m.group(1) or "")] += 1
        return c

    sc = counts(src_text)
    dc = counts(dst_text)
    problems = []
    missing = sc - dc
    extra = dc - sc
    if missing:
        problems.append(f"missing placeholders: {dict(missing)}")
    if extra:
        problems.append(f"unexpected/extra placeholders: {dict(extra)}")
    return problems
