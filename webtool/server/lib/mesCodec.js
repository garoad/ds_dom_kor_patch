"use strict";

// Port of analysis/mes_codec.py - .mes token stream decode/encode and
// dialogue block boundary detection. Reads the curated font_map_full.json
// directly from analysis/ (single source of truth, not duplicated here).
//
// decode_value()/NUM_TILES from the Python original are intentionally NOT
// ported - they are unused by find_dialogue_blocks() (which relies only on
// CODES[...].kind) and by the rest of the extract/reinsert pipeline.

const fs = require("fs");
const path = require("path");
const lz10 = require("./lz10");

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const FONT_MAP_FULL_PATH = path.join(REPO_ROOT, "analysis", "font_map_full.json");
const FONT_MAP_KR_PATH = path.join(REPO_ROOT, "analysis", "font_map_kr.json");

const _fmFull = JSON.parse(fs.readFileSync(FONT_MAP_FULL_PATH, "utf-8"));
const _fmKr = JSON.parse(fs.readFileSync(FONT_MAP_KR_PATH, "utf-8"));

const CODES_FULL = _fmFull.codes;
const CODES_KR = _fmKr.codes;
const CODES = CODES_KR;

function hex4(v) {
  return v.toString(16).toUpperCase().padStart(4, "0");
}

function loadValues(filePath) {
  const raw = fs.readFileSync(filePath);
  const dec = raw.length > 0 && raw[0] === 0x10 ? lz10.decompress(raw) : raw;
  const n = Math.floor(dec.length / 2);
  const values = new Array(n);
  for (let i = 0; i < n; i++) {
    values[i] = dec.readUInt16LE(i * 2);
  }
  return values;
}

function dumpValues(values, filePath, compress = true) {
  const body = Buffer.alloc(values.length * 2);
  for (let i = 0; i < values.length; i++) {
    body.writeUInt16LE(values[i] & 0xffff, i * 2);
  }
  const out = compress ? lz10.compress(body) : body;
  fs.writeFileSync(filePath, out);
}

function kindOf(v) {
  const e = CODES[hex4(v)];
  return e ? e.kind : undefined;
}

/**
 * Return list of [start, end) index ranges (content only, box-boundary
 * marker excluded) for real dialogue/text boxes. Direct port of
 * mes_codec.find_dialogue_blocks() - see that function's docstring for the
 * full reverse-engineering rationale (double 0x6E5C boundary, CODES-kind-
 * based content start instead of a fixed opener value).
 */
function findDialogueBlocks(values) {
  const n = values.length;
  const terms = [];
  let i = 0;
  while (i < n - 1) {
    if (values[i] === 0x6e5c && values[i + 1] === 0x6e5c) {
      terms.push(i);
      i += 2;
    } else {
      i += 1;
    }
  }

  const blocks = [];
  let prevTermEnd = 0;
  for (const t of terms) {
    let start = null;
    for (let i2 = prevTermEnd; i2 < t; i2++) {
      if (kindOf(values[i2]) === "full") {
        start = i2;
        break;
      }
    }
    if (start !== null) {
      while (start - 1 >= prevTermEnd && kindOf(values[start - 1]) === "half") {
        start -= 1;
      }
      blocks.push([start, t]);
    }
    prevTermEnd = t + 2;
  }
  return blocks;
}

module.exports = { CODES, CODES_FULL, CODES_KR, hex4, loadValues, dumpValues, findDialogueBlocks };
