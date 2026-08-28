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

# Full-width blank tile. Still used to pad translations that encode shorter
# than the original block's fixed token count (see mes_translate_reinsert.py)
# - block-length padding is a separate technical concern from visible
# word-spacing, and 0xA002 remains the validated choice there.
#
# 2026-08-10: briefly tried a half-width blank (HALF_SPACE_TOKEN = 0x00CA,
# assumed tile 390 under the OLD half-width formula tile=2*low-14) for
# tighter Korean word-spacing, but real-hardware testing proved that formula
# wrong for this code - overwriting tile 390 had ZERO effect on melonDS,
# meaning the engine doesn't read that tile for 0x00CA at all. Reverted to
# SPACE_TOKEN (0xA002, full-width) for both spacing and padding at the time.
SPACE_TOKEN = 0xA002

# 2026-08-10: single 0x485C ("page turn/wait for input") sits as the very
# last in-block token in ~97% of all dialogue blocks (37417/38495, corpus-
# wide scan of unpack/data/Script), immediately followed (just outside the
# block, untouched by mes_translate_reinsert.py) by the real box-closing
# double-0x6E5C terminator.
#
# 2026-08-12: per user request, when a block's LAST token is this marker,
# mes_translate_extract.py excludes it from the text handed to
# tokens_to_text() so the CSV 'source' column never shows a trailing
# <485C> for the translator to carry through. mes_translate_reinsert.py
# detects the same condition from the real on-disk block boundary and
# appends this token back onto the encoded translation automatically.
# Padding filler must never land AFTER this marker - doing so displays an
# extra blank "page" the player has to tap through after the dialogue
# already visually ended (matching the "대사가 끝나도 빈칸이 나오고 안 넘어간다"
# symptom from 2026-08-10) - since the marker is no longer part of the
# encoded translation tokens, padding is simply computed against the
# length excluding it, then the marker is appended last.
PAGE_TURN_TOKEN = 0x485C

# 2026-08-11: half-width formula corrected and hardware-confirmed to be
# tile=low-128 (see font_map_full.json's formula.description and
# ANALYSIS_NOTES.md "실기(melonDS) 검증 완료"). Under the CORRECT formula,
# 0x0080 (low=0x80 -> tile=0) is the real half-width blank - confirmed on
# real hardware to render as a true, invisible blank (tile 0 has zero ink
# in both the pristine and patched font). This is a different code from the
# disproven 0x00CA attempt above (0x00CA is actually 'P', tile 74). Now used
# for literal word-spacing (half the width of SPACE_TOKEN) since half-width
# character coverage has been fully verified on real hardware.
HALF_SPACE_TOKEN = 0x0080

_CHAR_TO_CODE = {}
# Some characters (':', digits, 'A'/'B') have both a half-width and a
# full-width tile in the corpus. Prefer half-width for these: Korean text
# uses these ASCII-style characters at half-width spacing convention. Space
# is deliberately excluded from this preference - see HALF_SPACE_TOKEN below.
for _pass_kinds in (("half",), ("full",)):
    for _k, _v in CODES_KR.items():
        if _v.get("kind") in _pass_kinds:
            _ch = _v.get("char")
            if _ch and len(_ch) == 1:
                _CHAR_TO_CODE.setdefault(_ch, int(_k, 16))

# Force space to the hardware-confirmed half-width blank for tighter Korean
# word-spacing (see HALF_SPACE_TOKEN above). Padding still uses SPACE_TOKEN.
_CHAR_TO_CODE[" "] = HALF_SPACE_TOKEN

# 2026-08-18: real-hardware bug report (melonDS) - 「/『 rendered as "!". Pixel-
# rendered both candidates directly from Font_DOM.nbfc (64B/tile, byte-per-
# pixel, 2x2 full-width block = offsets {0,1,32,33}): the auto-picked codes
# (0193 for 「, 0197 for 『) only have ink in their TR+BR quadrants (right
# half of the cell), while the original shipped script's codes (0314/0318)
# have ink in TL+BL (left half) - the correct side for a 「/『 corner stroke.
# This is the same densely-packed punctuation strip (tiles ~205-223) where
# adjacent glyphs' declared footprints share physical tiles by design; 0193/
# 0197 are simply the "wrong half" of that shared tile pair. User-confirmed
# fixed on real hardware after pinning to 0314/0318.
_CHAR_TO_CODE["「"] = 0x0314
_CHAR_TO_CODE["『"] = 0x0318

# 2026-08-18 (re-corrected, same session): went through TWO wrong turns on S
# before landing here - full history kept because the reasoning at each step
# looked sound at the time:
#   1) pinned S to 0x018C "match what vanilla used at this exact position" -
#      reported by user as still garbled (attributed to this override at the
#      time, but see step 3 - likely mis-attributed).
#   2) "fixed" by switching to 0x00CC (half-width) based on an offline pixel
#      render that showed 0x018C as fragmented pixels and 0x00CC as a clean
#      glyph - still reported garbled by user afterward.
#   3) ROOT CAUSE FOUND (user's own suggestion: "원본이 이미 이 문자열을 렌더링하니
#      그 코드를 그대로 쓰면 되잖아"): the vanilla corpus's OWN copy of the exact
#      string this bug is about - "『NO MUSIC NO LIFE!』" at
#      dom1OP_0701_1.mes block 228 (untranslated Japanese OP dialogue) -
#      already uses 0x018C for every 'S' in it, count=114 across the whole
#      corpus, real_tile=204. That block undeniably renders correctly on
#      real hardware right now, in the unpatched ROM, because it's SNK's own
#      shipped, tested text. That is strictly stronger evidence than the
#      offline pixel read from step 2, which is now understood to be
#      unreliable for this exact reason (see
#      temp/probe_all_half_codes_ingame.py's docstring / the F-Y retraction
#      above) - the "fragmented" verdict for 0x018C in step 2 was a
#      misapplication of the pixel-extraction formula, not a real defect.
#      0x00CC (kind=half, corpus count=1) has comparatively weak evidence -
#      it's barely used anywhere in the real script, so its "real-hardware
#      confirmed" status rests entirely on the 2026-08-11 synthetic
#      plant-test, not on actual shipped usage. Prefer 0x018C: it's the
#      code SNK's own text generator chose and is proven correct by the mere
#      fact that dialogue block still displays correctly today.
# General principle going forward for any Latin letter, established by this
# episode: trust corpus REAL_TILE/COUNT from font_map_full.json (i.e. what
# the vanilla game already renders somewhere) over any offline pixel
# analysis of a candidate tile. Do not re-litigate S without new evidence at
# least as strong as "vanilla renders this exact code in real, currently-
# working dialogue".
_CHAR_TO_CODE["S"] = 0x018C
# 'G' (0x00C1, half, corpus count=1) and 'P' (0x00CA, half, corpus count=0)
# remain on their half-width real-hardware-plant-tested codes (2026-08-11) -
# unlike S, no conflicting high-count vanilla usage undermines them (full-
# width alternatives 0x0181/0x018A do exist with much higher counts of 35/29
# respectively and would also be safe if G/P ever need re-litigating).
_CHAR_TO_CODE["G"] = 0x00C1
_CHAR_TO_CODE["P"] = 0x00CA

# 2026-08-18 (same session, RETRACTED): briefly assigned F,H,I,J,K,L,M,N,O,
# R,T,U,V,W,X,Y to 0x00C0/C2-C9/CB/CD-D2 on the theory that pixel-clean data
# at the {tile, tile+32} vertical-stack offset for each code meant the game
# would render it half-width, by analogy with G/P/S. User real-hardware
# re-test (melonDS) showed the alphabet STILL renders exactly as broken as
# before this "fix". Root cause: temp/probe_all_half_codes_ingame.py's own
# docstring records that this exact offline pixel-extraction method (incl.
# this same tile+32 formula) previously produced WRONG glyphs even for
# already-real-hardware-CONFIRMED half codes (0091/0084/008F/0086) - so
# "looks clean at the computed offset" never was a valid predictor of how
# the DS engine actually renders a given code. G/P/S only work because they
# were each individually planted and melonDS-observed on 2026-08-11 (see
# formula.description in font_map_full.json); F,H,I,J,K,L,M,N,O,R,T,U,V,W,
# X,Y were never planted/observed and the corpus offers ~0 real usages to
# infer "kind" from either - font_map_full.json's automatic classifier
# never labeled them "half" for a reason: whether the game engine treats an
# arbitrary code as half- or full-width is apparently NOT simply "does a
# half-width tile of clean pixel data exist at low-128" - there's a
# separate, still-unidentified mechanism (likely a fixed lookup table baked
# into the ROM's code, only populated for the handful of codes the original
# Japanese script actually used half-width). DO NOT reintroduce this class
# of fix without an actual in-game probe (plant the exact code into a real
# dialogue block via NitroPacker, screenshot melonDS) - offline pixel
# reads, no matter how clean-looking, are not evidence for kind="half".
# These letters remain on their setdefault-selected full-width codes below
# (same as before this attempt - known-broken, but not a NEW regression).


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


# 2026-08-12: a translation that's meaningfully shorter or longer than the
# source naturally needs a different number of line breaks (0x6E5C, used
# mid-block as an internal page/line break - see mes_codec.py's box-boundary
# comment for the separate double-0x6E5C box-closing use outside blocks) or
# page-turns (tio.PAGE_TURN_TOKEN / 0x485C). Requiring an exact count match
# for these two forced translators to pad/trim text just to keep the count
# identical instead of writing natural Korean. Exempted from the count check
# below per user request - every other placeholder (name variables, unknown
# control codes, etc.) still must match exactly.
IGNORED_PLACEHOLDER_CODES = {"485C", "6E5C"}


def validate_placeholders(src_text, dst_text):
    """Every <HEX> control/formatting placeholder in the source must appear
    the same number of times in the translation - these encode control flow
    (line breaks, variable substitution, timing, etc.) the translator must
    not drop, duplicate, or invent. Order is NOT enforced (a translator may
    need to reorder a name-substitution placeholder for grammar), only
    counts. Exception: see IGNORED_PLACEHOLDER_CODES above."""
    def counts(text):
        c = Counter(PLACEHOLDER_RE.findall(text))
        for m in NAME_VAR_RE.finditer(text):
            c["이름:" + (m.group(1) or "")] += 1
        for code in IGNORED_PLACEHOLDER_CODES:
            c.pop(code, None)
            c.pop(code.lower(), None)
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


def split_units(text):
    """Split text into the same atomic units tokens_to_text()/text_to_tokens()
    treat as indivisible: a <이름>/<이름:XXXX> marker, a <HEX> placeholder, or a
    single literal character. Used by pipeline.py's header-splice safety
    check (see its compute_header_splice comment) to find how much of a
    translated block's leading text is UNCHANGED from the source,
    unit-for-unit. Ported from webtool/server/lib/translateIo.js's
    splitUnits(), which had no Python equivalent until this rewrite needed
    one too - added here instead of a third copy."""
    units = []
    i, n = 0, len(text)
    while i < n:
        m = NAME_VAR_RE.match(text, i)
        if m:
            units.append(text[i:m.end()])
            i = m.end()
            continue
        m = PLACEHOLDER_RE.match(text, i)
        if m:
            units.append(text[i:m.end()])
            i = m.end()
            continue
        units.append(text[i])
        i += 1
    return units


_UNIT_NAME_VAR_RE = re.compile(r"^<이름(?::([0-9A-Fa-f]{4}))?>$")


def unit_token_length(unit):
    """How many raw u16 tokens one split_units() unit represents: 2 for a
    <이름:XXXX> marker (prefix + suffix token), 1 for everything else (a bare
    <이름> marker, a <HEX> placeholder, or a single literal character)."""
    m = _UNIT_NAME_VAR_RE.match(unit)
    if m:
        return 2 if m.group(1) else 1
    return 1
