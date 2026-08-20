"use strict";

// 1:1 port of analysis/translate_io.py - lossless text<->token conversion.
// See the Python source's module docstring for the full rationale (why
// every non-literal code becomes an explicit <HEX> placeholder instead of
// being collapsed to a space, etc).

const mc = require("./mesCodec");

const PLACEHOLDER_RE = /<([0-9A-Fa-f]{1,4})>/y;

// 0x505C = player-inputted protagonist name marker, optionally followed by
// 0x3131/0x3232 (undecoded suffix, preserved losslessly but never
// interpreted). See translate_io.py's NAME_VAR_PREFIX comment for the full
// reverse-engineering evidence (2786 corpus occurrences, 99.7% followed by
// one of these two suffixes which never occur standalone anywhere else).
const NAME_VAR_PREFIX = 0x505c;
const NAME_VAR_SUFFIXES = new Set([0x3131, 0x3232]);
const NAME_VAR_RE = /<이름(?::([0-9A-Fa-f]{4}))?>/y;

// See analysis/translate_io.py's PAGE_TURN_TOKEN comment for the full
// rationale: when a block's last token is this marker, pipeline.js's
// extractProject() excludes it from the CSV 'source' text entirely (no
// trailing <485C> for the translator to carry through), and
// buildFileTokens()/validateRow() append it back automatically.
const PAGE_TURN_TOKEN = 0x485c;

// Full-width blank tile. Still used to pad translations that encode shorter
// than the original block's fixed token count (see pipeline.js) -
// block-length padding is a separate technical concern from visible
// word-spacing, and 0xA002 remains the validated choice there.
//
// 2026-08-10: briefly tried a half-width blank (HALF_SPACE_TOKEN = 0x00CA,
// assumed tile 390 under the OLD half-width formula tile=2*low-14) for
// tighter Korean word-spacing, but real-hardware testing proved that formula
// wrong for this code - overwriting tile 390 had ZERO effect on melonDS,
// meaning the engine doesn't read that tile for 0x00CA at all. Reverted to
// SPACE_TOKEN (0xA002, full-width) for both spacing and padding at the time.
const SPACE_TOKEN = 0xa002;

// 2026-08-11: half-width formula corrected and hardware-confirmed to be
// tile=low-128 (see font_map_full.json's formula.description and
// ANALYSIS_NOTES.md "실기(melonDS) 검증 완료"). Under the CORRECT formula,
// 0x0080 (low=0x80 -> tile=0) is the real half-width blank - confirmed on
// real hardware to render as a true, invisible blank (tile 0 has zero ink
// in both the pristine and patched font). This is a different code from the
// disproven 0x00CA attempt above (0x00CA is actually 'P', tile 74). Now used
// for literal word-spacing (half the width of SPACE_TOKEN) since half-width
// character coverage has been fully verified on real hardware.
const HALF_SPACE_TOKEN = 0x0080;

const _CHAR_TO_CODE = new Map();
// Some characters (':', digits, 'A'/'B') have both a half-width and a
// full-width tile in the corpus. Prefer half-width for these. Space is
// deliberately excluded from this preference - see HALF_SPACE_TOKEN below.
for (const passKinds of [["half"], ["full"]]) {
  for (const [k, v] of Object.entries(mc.CODES_KR)) {
    if (passKinds.includes(v.kind)) {
      const ch = v.char;
      if (ch && Array.from(ch).length === 1 && !_CHAR_TO_CODE.has(ch)) {
        _CHAR_TO_CODE.set(ch, parseInt(k, 16));
      }
    }
  }
}
// Force space to the hardware-confirmed half-width blank for tighter Korean
// word-spacing (see HALF_SPACE_TOKEN above). Padding still uses SPACE_TOKEN.
_CHAR_TO_CODE.set(" ", HALF_SPACE_TOKEN);

// 2026-08-18: real-hardware bug report (melonDS) - 「/『 rendered as "!".
// Pixel-rendered both candidates directly from Font_DOM.nbfc (64B/tile,
// byte-per-pixel, 2x2 full-width block = offsets {0,1,32,33}): the
// auto-picked codes (0193 for 「, 0197 for 『) only have ink in their TR+BR
// quadrants (right half of the cell), while the original shipped script's
// codes (0314/0318) have ink in TL+BL (left half) - the correct side for a
// 「/『 corner stroke. This is the same densely-packed punctuation strip
// (tiles ~205-223) where adjacent glyphs' declared footprints share
// physical tiles by design; 0193/0197 are simply the "wrong half" of that
// shared tile pair. User-confirmed fixed on real hardware after pinning to
// 0314/0318.
_CHAR_TO_CODE.set("「", 0x0314);
_CHAR_TO_CODE.set("『", 0x0318);

// 2026-08-18 (re-corrected, same session): went through TWO wrong turns on S
// before landing here - full history kept because the reasoning at each step
// looked sound at the time:
//   1) pinned S to 0x018C "match what vanilla used at this exact position" -
//      reported by user as still garbled (attributed to this override at the
//      time, but see step 3 - likely mis-attributed).
//   2) "fixed" by switching to 0x00CC (half-width) based on an offline pixel
//      render that showed 0x018C as fragmented pixels and 0x00CC as a clean
//      glyph - still reported garbled by user afterward.
//   3) ROOT CAUSE FOUND (user's own suggestion: "원본이 이미 이 문자열을 렌더링하니
//      그 코드를 그대로 쓰면 되잖아"): the vanilla corpus's OWN copy of the exact
//      string this bug is about - "『NO MUSIC NO LIFE!』" at
//      dom1OP_0701_1.mes block 228 (untranslated Japanese OP dialogue) -
//      already uses 0x018C for every 'S' in it, count=114 across the whole
//      corpus, real_tile=204. That block undeniably renders correctly on
//      real hardware right now, in the unpatched ROM, because it's SNK's own
//      shipped, tested text. That is strictly stronger evidence than the
//      offline pixel read from step 2, which is now understood to be
//      unreliable for this exact reason (see
//      temp/probe_all_half_codes_ingame.py's docstring / the F-Y retraction
//      above) - the "fragmented" verdict for 0x018C in step 2 was a
//      misapplication of the pixel-extraction formula, not a real defect.
//      0x00CC (kind=half, corpus count=1) has comparatively weak evidence -
//      it's barely used anywhere in the real script, so its "real-hardware
//      confirmed" status rests entirely on the 2026-08-11 synthetic
//      plant-test, not on actual shipped usage. Prefer 0x018C: it's the
//      code SNK's own text generator chose and is proven correct by the mere
//      fact that dialogue block still displays correctly today.
// General principle going forward for any Latin letter, established by this
// episode: trust corpus REAL_TILE/COUNT from font_map_full.json (i.e. what
// the vanilla game already renders somewhere) over any offline pixel
// analysis of a candidate tile. Do not re-litigate S without new evidence at
// least as strong as "vanilla renders this exact code in real, currently-
// working dialogue".
_CHAR_TO_CODE.set("S", 0x018c);
// 'G' (0x00C1, half, corpus count=1) and 'P' (0x00CA, half, corpus count=0)
// remain on their half-width real-hardware-plant-tested codes (2026-08-11) -
// unlike S, no conflicting high-count vanilla usage undermines them (full-
// width alternatives 0x0181/0x018A do exist with much higher counts of 35/29
// respectively and would also be safe if G/P ever need re-litigating).
_CHAR_TO_CODE.set("G", 0x00c1);
_CHAR_TO_CODE.set("P", 0x00ca);

// 2026-08-18 (same session, RETRACTED): briefly assigned F,H,I,J,K,L,M,N,O,
// R,T,U,V,W,X,Y to 0x00C0/C2-C9/CB/CD-D2 on the theory that pixel-clean data
// at the {tile, tile+32} vertical-stack offset for each code meant the game
// would render it half-width, by analogy with G/P/S. User real-hardware
// re-test (melonDS) showed the alphabet STILL renders exactly as broken as
// before this "fix". Root cause: temp/probe_all_half_codes_ingame.py's own
// docstring records that this exact offline pixel-extraction method (incl.
// this same tile+32 formula) previously produced WRONG glyphs even for
// already-real-hardware-CONFIRMED half codes (0091/0084/008F/0086) - so
// "looks clean at the computed offset" never was a valid predictor of how
// the DS engine actually renders a given code. G/P/S only work because they
// were each individually planted and melonDS-observed on 2026-08-11 (see
// formula.description in font_map_full.json); F,H,I,J,K,L,M,N,O,R,T,U,V,W,
// X,Y were never planted/observed and the corpus offers ~0 real usages to
// infer "kind" from either - font_map_full.json's automatic classifier
// never labeled them "half" for a reason: whether the game engine treats an
// arbitrary code as half- or full-width is apparently NOT simply "does a
// half-width tile of clean pixel data exist at low-128" - there's a
// separate, still-unidentified mechanism (likely a fixed lookup table baked
// into the ROM's code, only populated for the handful of codes the original
// Japanese script actually used half-width). DO NOT reintroduce this class
// of fix without an actual in-game probe (plant the exact code into a real
// dialogue block via NitroPacker, screenshot melonDS) - offline pixel
// reads, no matter how clean-looking, are not evidence for kind="half".
// These letters remain on their setdefault-selected full-width codes below
// (same as before this attempt - known-broken, but not a NEW regression).

function isLiteralGlyph(v, codesMap = mc.CODES_FULL) {
  const e = codesMap[mc.hex4(v)];
  return Boolean(e) && (e.kind === "full" || e.kind === "half") && Boolean(e.char) && Array.from(e.char).length === 1;
}

function tokensToText(values, codesMap = mc.CODES_FULL) {
  const out = [];
  const n = values.length;
  let i = 0;
  while (i < n) {
    const v = values[i];
    if (v === NAME_VAR_PREFIX) {
      if (i + 1 < n && NAME_VAR_SUFFIXES.has(values[i + 1])) {
        out.push(`<이름:${mc.hex4(values[i + 1])}>`);
        i += 2;
        continue;
      }
      out.push("<이름>");
      i += 1;
      continue;
    }
    if (isLiteralGlyph(v, codesMap)) {
      out.push(codesMap[mc.hex4(v)].char);
    } else {
      out.push(`<${mc.hex4(v)}>`);
    }
    i += 1;
  }
  return out.join("");
}

/**
 * Inverse of tokensToText. Throws on any character with no assigned font
 * code (untranslated glyph, unassigned punctuation/space, or a malformed
 * <HEX> placeholder).
 */
function textToTokens(text) {
  const tokens = [];
  // Hangul/CJK/ASCII/hex-digit placeholders are all in the BMP, so plain
  // UTF-16 string indices (no surrogate-pair handling) are safe here.
  let strPos = 0;
  const str = text;
  while (strPos < str.length) {
    NAME_VAR_RE.lastIndex = strPos;
    let m = NAME_VAR_RE.exec(str);
    if (m && m.index === strPos) {
      tokens.push(NAME_VAR_PREFIX);
      if (m[1]) {
        tokens.push(parseInt(m[1], 16));
      }
      strPos = NAME_VAR_RE.lastIndex;
      continue;
    }
    PLACEHOLDER_RE.lastIndex = strPos;
    m = PLACEHOLDER_RE.exec(str);
    if (m && m.index === strPos) {
      tokens.push(parseInt(m[1], 16));
      strPos = PLACEHOLDER_RE.lastIndex;
      continue;
    }
    const ch = str[strPos];
    if (!_CHAR_TO_CODE.has(ch)) {
      throw new Error(`no font code assigned for character ${JSON.stringify(ch)} at position ${strPos} in: ${JSON.stringify(str)}`);
    }
    tokens.push(_CHAR_TO_CODE.get(ch));
    strPos += 1;
  }
  return tokens;
}

function countPlaceholders(text) {
  const counts = new Map();
  const bump = (key) => counts.set(key, (counts.get(key) || 0) + 1);

  let pos = 0;
  while (pos < text.length) {
    NAME_VAR_RE.lastIndex = pos;
    const nameMatch = NAME_VAR_RE.exec(text);
    if (nameMatch && nameMatch.index === pos) {
      bump("이름:" + (nameMatch[1] || ""));
      pos = NAME_VAR_RE.lastIndex;
      continue;
    }
    PLACEHOLDER_RE.lastIndex = pos;
    const phMatch = PLACEHOLDER_RE.exec(text);
    if (phMatch && phMatch.index === pos) {
      bump(phMatch[1]);
      pos = PLACEHOLDER_RE.lastIndex;
      continue;
    }
    pos += 1;
  }
  return counts;
}

// 2026-08-12: a translation that's meaningfully shorter or longer than the
// source naturally needs a different number of line breaks (0x6E5C, used
// mid-block as an internal page/line break) or page-turns (PAGE_TURN_TOKEN /
// 0x485C). Requiring an exact count match for these two forced translators
// to pad/trim text just to keep the count identical instead of writing
// natural Korean. Exempted from the count check below per user request -
// every other placeholder (name variables, unknown control codes, etc.)
// still must match exactly.
const IGNORED_PLACEHOLDER_CODES = new Set(["485C", "485c", "6E5C", "6e5c"]);

/**
 * Every <HEX> control/formatting placeholder (and the <이름> marker) in the
 * source must appear the same number of times in the translation - order is
 * NOT enforced, only counts (except IGNORED_PLACEHOLDER_CODES above).
 * Returns an array of human-readable problem strings (empty = OK).
 */
function validatePlaceholders(srcText, dstText) {
  const sc = countPlaceholders(srcText);
  const dc = countPlaceholders(dstText);
  for (const code of IGNORED_PLACEHOLDER_CODES) {
    sc.delete(code);
    dc.delete(code);
  }
  const missing = {};
  const extra = {};
  for (const [k, v] of sc) {
    const d = dc.get(k) || 0;
    if (v > d) missing[k] = v - d;
  }
  for (const [k, v] of dc) {
    const s = sc.get(k) || 0;
    if (v > s) extra[k] = v - s;
  }
  const problems = [];
  if (Object.keys(missing).length) problems.push(`missing placeholders: ${JSON.stringify(missing)}`);
  if (Object.keys(extra).length) problems.push(`unexpected/extra placeholders: ${JSON.stringify(extra)}`);
  return problems;
}

/**
 * Split text into the same atomic units tokensToText()/textToTokens() treat
 * as indivisible: a <이름>/<이름:XXXX> marker, a <HEX> placeholder, or a single
 * literal character. Used by pipeline.js's header-splice safety check (see
 * its computeHeaderSplice comment) to find how much of a translated block's
 * leading text is UNCHANGED from the source, unit-for-unit.
 */
function splitUnits(text) {
  const units = [];
  let i = 0;
  while (i < text.length) {
    NAME_VAR_RE.lastIndex = i;
    let m = NAME_VAR_RE.exec(text);
    if (m && m.index === i) {
      units.push(text.slice(i, NAME_VAR_RE.lastIndex));
      i = NAME_VAR_RE.lastIndex;
      continue;
    }
    PLACEHOLDER_RE.lastIndex = i;
    m = PLACEHOLDER_RE.exec(text);
    if (m && m.index === i) {
      units.push(text.slice(i, PLACEHOLDER_RE.lastIndex));
      i = PLACEHOLDER_RE.lastIndex;
      continue;
    }
    units.push(text[i]);
    i += 1;
  }
  return units;
}

/**
 * How many raw u16 tokens one splitUnits() unit represents: 2 for a
 * <이름:XXXX> marker (prefix + suffix token), 1 for everything else (a bare
 * <이름> marker, a <HEX> placeholder, or a single literal character - every
 * literal glyph is exactly one token both directions, see tokensToText).
 */
function unitTokenLength(unit) {
  const m = unit.match(/^<이름(?::([0-9A-Fa-f]{4}))?>$/);
  if (m) return m[1] ? 2 : 1;
  return 1;
}

module.exports = {
  NAME_VAR_PREFIX,
  NAME_VAR_SUFFIXES,
  PAGE_TURN_TOKEN,
  SPACE_TOKEN,
  HALF_SPACE_TOKEN,
  isLiteralGlyph,
  tokensToText,
  textToTokens,
  validatePlaceholders,
  splitUnits,
  unitTokenLength,
};
