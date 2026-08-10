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

// Full-width blank tile. Kept for reference/back-compat only - no longer used
// to encode literal spaces or padding (see HALF_SPACE_TOKEN below).
const SPACE_TOKEN = 0xa002;

// Half-width blank tile (bank=0, low=0xCA -> tile 2*0xCA-14=390). Shares its
// physical tile with 0x0606 (a 'full' code with no char label, confirmed
// unused in real dialogue content) - see analysis/ANALYSIS_NOTES.md "0x00A4
// 반각 공백 오식별" (2026-08-06) for the full derivation; restored to
// font_map_full.json/font_map_kr.json 2026-08-10 after an earlier regen
// dropped it. Used both to encode literal ' ' and to pad translations that
// encode shorter than the original block's fixed token count (see
// pipeline.js) - switched from full-width SPACE_TOKEN per user request.
const HALF_SPACE_TOKEN = 0x00ca;

const _CHAR_TO_CODE = new Map();
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
// Force space to the half-width blank tile - this used to force full-width,
// contradicting the half-width preference above for other ASCII-style
// characters (fixed 2026-08-10).
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
  HALF_SPACE_TOKEN,
  isLiteralGlyph,
  tokensToText,
  textToTokens,
  validatePlaceholders,
};
