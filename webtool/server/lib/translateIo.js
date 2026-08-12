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
};
