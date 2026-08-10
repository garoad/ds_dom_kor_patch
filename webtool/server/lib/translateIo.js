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

// Full-width blank tile. Used to encode literal spaces and to pad
// translations that encode shorter than the original block's fixed token
// count (see pipeline.js).
//
// 2026-08-10: briefly switched to a half-width blank (HALF_SPACE_TOKEN =
// 0x00CA, tile 390 per font_map_full.json's half-width formula) for tighter
// Korean spacing, but real-hardware testing proved that tile address formula
// wrong for this code - overwriting tiles 390/391/422/423 with a solid,
// unmistakable marker had ZERO effect on what melonDS actually displayed,
// meaning the engine doesn't read that tile for 0x00CA at all
// (font_map_full.json's own stats confirm this: every OTHER half-width code
// except the manually-patched 0x00CA has real_tile=null). Reverted to
// SPACE_TOKEN, which IS validated - it's what the original 2026-08-05/06
// session used when the "block token count must match exactly" rule was
// first confirmed working on real hardware, and a direct A/B real-hardware
// test (2026-08-10) confirmed it still renders as a clean blank while
// 0x00CA renders as a repeating garbled glyph.
const SPACE_TOKEN = 0xa002;

const _CHAR_TO_CODE = new Map();
// Some characters (':', digits, 'A'/'B') have both a half-width and a
// full-width tile in the corpus. Prefer half-width for these. Space is
// deliberately excluded from this preference - see SPACE_TOKEN above.
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
// Force space to the validated full-width blank tile (see SPACE_TOKEN above).
_CHAR_TO_CODE.set(" ", SPACE_TOKEN);

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

/**
 * Every <HEX> control/formatting placeholder (and the <이름> marker) in the
 * source must appear the same number of times in the translation - order is
 * NOT enforced, only counts. Returns an array of human-readable problem
 * strings (empty = OK).
 */
function validatePlaceholders(srcText, dstText) {
  const sc = countPlaceholders(srcText);
  const dc = countPlaceholders(dstText);
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
  SPACE_TOKEN,
  isLiteralGlyph,
  tokensToText,
  textToTokens,
  validatePlaceholders,
};
