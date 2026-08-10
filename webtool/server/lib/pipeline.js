"use strict";

// CSV extract/save/reinsert pipeline - JS port of mes_translate_extract.py +
// mes_translate_reinsert.py's build_file(), adapted to per-project
// workspaces instead of the fixed analysis/ paths the Python scripts use.

const fs = require("fs");
const path = require("path");
const { parse: csvParse } = require("csv-parse/sync");
const { stringify: csvStringify } = require("csv-stringify/sync");

const mc = require("./mesCodec");
const tio = require("./translateIo");
const speakerMap = require("./speakerMap");
const { isDebugMenuBlock } = require("./debugFilter");
const proj = require("./project");

const FIELDS = ["file", "rel_path", "block", "n_tokens", "speaker", "source", "ai_draft", "translation"];

// playername.mes stores default preset names (surname/given name entries),
// each capped at 3 displayed characters by the in-game name UI itself -
// unlike dialogue blocks, an entry's length isn't tied to a fixed ROM slot,
// so it doesn't need to match the original token count exactly (2026-08-10).
const PLAYERNAME_FILE = "playername.mes";
const PLAYERNAME_MAX_TOKENS = 3;

// 2026-08-10: single 0x485C ("page turn/wait for input") sits as the very
// last in-block token in ~97% of all dialogue blocks (37417/38495, corpus-
// wide scan of unpack/data/Script), immediately followed (just outside the
// block, untouched by this function) by the real box-closing double-0x6E5C
// terminator. Padding filler must never land AFTER this marker - doing so
// displays an extra blank "page" the player has to tap through after the
// dialogue already visually ended, matching the "대사가 끝나도 빈칸이 나오고
// 안 넘어간다" symptom reported 2026-08-10. Experimental fix: insert filler
// BEFORE a trailing page-turn marker instead of after it.
const PAGE_TURN_TOKEN = 0x485c;

const OUTSIDE_MES_FILES = [
  "soundnamedom1.mes",
  "soundnamedom2.mes",
  "soundnamedom3.mes",
  "dom3chara.mes",
  "dom2chara.mes",
  "playername.mes",
  "extraopen.mes",
  "common.mes",
  "strindex.mes",
  "endtitledom3.mes",
  "endtitledom2.mes",
  "endtitledom1.mes",
];

function getCategory(filePath, unpackDataDir) {
  const fname = path.basename(filePath);
  const scriptDir = path.join(unpackDataDir, "Script");
  if (!filePath.startsWith(scriptDir)) {
    return "system_common";
  }

  let dom = "other";
  let rest = fname;
  if (fname.startsWith("dom1")) {
    dom = "dom1";
    rest = fname.slice(4);
  } else if (fname.startsWith("dom2")) {
    dom = "dom2";
    rest = fname.slice(4);
  } else if (fname.startsWith("dom3")) {
    dom = "dom3";
    rest = fname.slice(4);
  }

  let charName = "";
  for (const ch of rest) {
    if (/[a-zA-Z]/.test(ch)) {
      charName += ch;
    } else {
      break;
    }
  }

  const commonList = ["OP", "DefScn", "ENC", "HZR", "ED", "CHOICE", "MEZ", "Ed"];
  if (!charName || commonList.includes(charName)) {
    return `${dom}_common`;
  }
  return `${dom}_${charName}`;
}

/** Real (non-debug-menu) dialogue blocks for one .mes file, in CSV row order. */
function realBlocksOf(values) {
  const all = mc.findDialogueBlocks(values);
  return all.filter(([s, e]) => !isDebugMenuBlock(values.slice(s, e)));
}

function readCsv(name) {
  const transDir = proj.csvDir(name);
  let rows = [];

  if (fs.existsSync(transDir)) {
    const csvFiles = fs.readdirSync(transDir).filter((f) => f.endsWith(".csv"));
    for (const file of csvFiles) {
      const p = path.join(transDir, file);
      const text = fs.readFileSync(p, "utf-8");
      if (text.trim()) {
        const fileRows = csvParse(text, { columns: true, skip_empty_lines: true });
        rows.push(...fileRows);
      }
    }
  }

  // 폴백/하위호환: master translation_export.csv 도 여전히 존재한다면 함께 로드
  const oldMasterPath = proj.csvPath(name);
  if (!rows.length && fs.existsSync(oldMasterPath)) {
    const text = fs.readFileSync(oldMasterPath, "utf-8");
    if (text.trim()) {
      rows = csvParse(text, { columns: true, skip_empty_lines: true });
    }
  }

  return rows;
}

function writeCsv(name, rows) {
  const transDir = proj.csvDir(name);
  const unpackDataDir = path.join(proj.unpackDir(name), "data");

  fs.mkdirSync(transDir, { recursive: true });

  const catMap = new Map();
  for (const r of rows) {
    const filePath = path.join(unpackDataDir, r.rel_path || r.file);
    const cat = getCategory(filePath, unpackDataDir);
    if (!catMap.has(cat)) catMap.set(cat, []);
    catMap.get(cat).push(r);
  }

  for (const [cat, catRows] of catMap.entries()) {
    const text = csvStringify(catRows, { header: true, columns: FIELDS });
    fs.writeFileSync(path.join(transDir, `${cat}.csv`), text);
  }

  // 마스터 통짜 CSV도 호환성을 위해 업데이트
  const masterText = csvStringify(rows, { header: true, columns: FIELDS });
  fs.writeFileSync(proj.csvPath(name), masterText);
}

/**
 * Scan every .mes file in the project's unpack/data/Script, extract real
 * dialogue blocks, and merge with any existing CSV - rows matching on
 * (file, block, n_tokens, source) keep their existing translation, since the
 * CSV is the translator's save file and re-extraction must never wipe work.
 */
function extractProject(name) {
  const unpackDir = proj.unpackDir(name);
  const unpackDataDir = path.join(unpackDir, "data");
  const scriptDir = path.join(unpackDataDir, "Script");

  let scriptFiles = [];
  if (fs.existsSync(scriptDir)) {
    scriptFiles = fs.readdirSync(scriptDir).filter((f) => f.toLowerCase().endsWith(".mes")).sort().map((f) => path.join(scriptDir, f));
  }

  const outsideFiles = OUTSIDE_MES_FILES.map((f) => path.join(unpackDataDir, f)).filter((p) => fs.existsSync(p));
  const allFiles = [...scriptFiles, ...outsideFiles];

  const existing = readCsv(name);
  const existingByKey = new Map();
  for (const row of existing) {
    const key = `${row.file} ${row.block} ${row.n_tokens} ${row.source}`;
    existingByKey.set(key, {
      ai_draft: row.ai_draft || "",
      translation: row.translation || "",
    });
  }

  const rows = [];
  let filesWithBlocks = 0;
  let skippedDebug = 0;

  for (const filePath of allFiles) {
    const fname = path.basename(filePath);
    const relPath = path.relative(unpackDataDir, filePath);
    const values = mc.loadValues(filePath);
    const blocks = mc.findDialogueBlocks(values);
    const isScript = filePath.startsWith(scriptDir);

    const realBlocks = [];
    for (const [s, e] of blocks) {
      if (isScript && isDebugMenuBlock(values.slice(s, e))) {
        skippedDebug += 1;
      } else {
        realBlocks.push([s, e]);
      }
    }
    if (realBlocks.length) filesWithBlocks += 1;

    realBlocks.forEach(([s, e], i) => {
      const text = tio.tokensToText(values.slice(s, e), mc.CODES_FULL);
      const headerVal = s - 1 >= 0 ? values[s - 1] : null;
      const speaker = headerVal !== null ? speakerMap.speakerOf(headerVal) : null;
      const nTokens = e - s;
      const key = `${fname} ${i} ${nTokens} ${text}`;
      const saved = existingByKey.get(key) || { ai_draft: "", translation: "" };

      rows.push({
        file: fname,
        rel_path: relPath,
        block: i,
        n_tokens: nTokens,
        speaker: speaker !== null ? speaker : headerVal !== null ? `UNKNOWN_${headerVal.toString(16).padStart(2, "0")}` : "",
        source: text,
        ai_draft: saved.ai_draft,
        translation: saved.translation,
      });
    });
  }

  writeCsv(name, rows);
  return {
    filesScanned: allFiles.length,
    filesWithBlocks,
    totalBlocks: rows.length,
    skippedDebug,
    translatedCount: rows.filter((r) => r.translation && r.translation.trim()).length,
  };
}

function fileSummaries(name) {
  const rows = readCsv(name);
  const byFile = new Map();
  for (const row of rows) {
    if (!byFile.has(row.file)) byFile.set(row.file, { file: row.file, blockCount: 0, translatedCount: 0 });
    const s = byFile.get(row.file);
    s.blockCount += 1;
    if (row.translation && row.translation.trim()) s.translatedCount += 1;
  }
  return Array.from(byFile.values());
}

function rowsForFile(name, fname) {
  return readCsv(name).filter((r) => r.file === fname);
}

/**
 * Validate one row's translation without writing anything. If the encoded
 * translation is shorter than expectedTokenCount, it is padded with trailing
 * space tokens to match exactly (a translation encoding longer than the
 * original is still reported as a mismatch - trimming would drop content).
 *
 * playername.mes is exempt from the expectedTokenCount match (see
 * PLAYERNAME_FILE comment above) - it only enforces the in-game 3-character
 * name cap.
 */
function validateRow(srcText, dstTextRaw, expectedTokenCount, fname) {
  const dstText = dstTextRaw && dstTextRaw.length > 0 ? dstTextRaw : srcText;
  const problems = tio.validatePlaceholders(srcText, dstText);
  if (problems.length) return { ok: false, error: problems.join("; ") };
  let tokens;
  try {
    tokens = tio.textToTokens(dstText);
  } catch (ex) {
    return { ok: false, error: ex.message };
  }

  if (fname === PLAYERNAME_FILE) {
    if (tokens.length > PLAYERNAME_MAX_TOKENS) {
      return {
        ok: false,
        error: `player name too long - encodes to ${tokens.length} characters, but names are capped at ${PLAYERNAME_MAX_TOKENS} in-game`,
      };
    }
    return { ok: true, tokenCount: tokens.length };
  }

  if (expectedTokenCount !== undefined && tokens.length < expectedTokenCount) {
    tokens = tokens.concat(Array(expectedTokenCount - tokens.length).fill(tio.SPACE_TOKEN));
  }
  return { ok: true, tokenCount: tokens.length };
}

/**
 * Save a batch of {block, translation} edits for one file, validating each
 * row against its original n_tokens. Validation failures do not block
 * saving (drafts are allowed) - the caller gets a per-row report.
 */
function saveFile(name, fname, edits) {
  const rows = readCsv(name);
  const editByBlock = new Map(edits.map((e) => [String(e.block), e]));
  const report = [];

  for (const row of rows) {
    if (row.file !== fname) continue;
    if (!editByBlock.has(String(row.block))) continue;
    const item = editByBlock.get(String(row.block));
    if (item.translation !== undefined) row.translation = item.translation;
    if (item.ai_draft !== undefined) row.ai_draft = item.ai_draft;

    const v = validateRow(row.source, row.translation, Number(row.n_tokens), fname);
    if (!v.ok) {
      report.push({ block: Number(row.block), ok: false, error: v.error });
    } else if (fname !== PLAYERNAME_FILE && v.tokenCount !== Number(row.n_tokens)) {
      // Shorter translations are already padded to match inside validateRow,
      // so only "longer" (which would drop content if trimmed) reaches here.
      // playername.mes doesn't enforce this match at all (see validateRow).
      report.push({
        block: Number(row.block),
        ok: false,
        error: `token count mismatch - original has ${row.n_tokens} tokens, translation encodes to ${v.tokenCount} (longer)`,
      });
    } else {
      report.push({ block: Number(row.block), ok: true });
    }
  }

  writeCsv(name, rows);
  return report;
}

/**
 * Re-derive blocks from the pristine unpack/ file (never from stale CSV
 * offsets) and build the translated token stream. Returns
 * {tokens, problems}. `problems` non-empty => caller must skip this file
 * entirely (matches mes_translate_reinsert.py's all-or-nothing per file
 * behavior).
 */
function buildFileTokens(name, fname, rowsByBlock) {
  const unpackDataDir = path.join(proj.unpackDir(name), "data");
  let relPath = null;
  for (const r of rowsByBlock.values()) {
    if (r.rel_path) {
      relPath = r.rel_path;
      break;
    }
  }

  let srcPath = relPath ? path.join(unpackDataDir, relPath) : path.join(proj.scriptDir(name), fname);
  if (!fs.existsSync(srcPath)) {
    srcPath = path.join(unpackDataDir, fname);
  }
  if (!fs.existsSync(srcPath)) {
    return { tokens: null, problems: [`source file not found: ${srcPath}`] };
  }

  const values = mc.loadValues(srcPath);
  const isScript = srcPath.startsWith(path.join(unpackDataDir, "Script"));
  const blocks = isScript ? realBlocksOf(values) : mc.findDialogueBlocks(values);

  if (blocks.length !== rowsByBlock.size) {
    return {
      tokens: null,
      problems: [
        `block count mismatch: CSV has ${rowsByBlock.size} rows for ${fname}, ` +
          `current file has ${blocks.length} real dialogue blocks (CSV is stale - re-run extract)`,
      ],
    };
  }

  const problems = [];
  const out = [];
  let last = 0;

  blocks.forEach(([s, e], i) => {
    const row = rowsByBlock.get(i);
    const srcText = row.source;
    const dstText = row.translation && row.translation.length > 0 ? row.translation : srcText;
    const expectedLen = e - s;

    if (!row.translation || row.translation === srcText) {
      out.push(...values.slice(last, s));
      out.push(...values.slice(s, e));
      last = e;
      return;
    }

    const placeholderProblems = tio.validatePlaceholders(srcText, dstText);
    if (placeholderProblems.length) {
      problems.push(`block ${i}: ${placeholderProblems.join("; ")}`);
      return;
    }

    let newTokens;
    try {
      newTokens = tio.textToTokens(dstText);
    } catch (ex) {
      problems.push(`block ${i}: ${ex.message}`);
      return;
    }

    if (fname === PLAYERNAME_FILE) {
      // No fixed-slot constraint here - just the in-game 3-character name
      // cap (see PLAYERNAME_FILE comment above).
      if (newTokens.length > PLAYERNAME_MAX_TOKENS) {
        problems.push(
          `block ${i}: player name too long - encodes to ${newTokens.length} characters, ` +
            `but names are capped at ${PLAYERNAME_MAX_TOKENS} in-game`
        );
        return;
      }
      out.push(...values.slice(last, s));
      out.push(...newTokens);
      last = e;
      return;
    }

    if (newTokens.length < expectedLen) {
      // Pad with trailing space tokens rather than failing the block - a
      // shorter translation is safe to pad, unlike a longer one (which
      // would have to drop content to fit and is still reported below). If
      // the encoded text ends in the page-turn marker (true for ~97% of
      // blocks), insert the filler BEFORE it, not after - see
      // PAGE_TURN_TOKEN above. Uses tio.SPACE_TOKEN (full-width) - see its
      // comment for why the half-width blank is not used.
      const pad = Array(expectedLen - newTokens.length).fill(tio.SPACE_TOKEN);
      if (newTokens.length && newTokens[newTokens.length - 1] === PAGE_TURN_TOKEN) {
        newTokens = newTokens.slice(0, -1).concat(pad, newTokens[newTokens.length - 1]);
      } else {
        newTokens = newTokens.concat(pad);
      }
    }

    if (newTokens.length !== expectedLen) {
      problems.push(
        `block ${i}: token count mismatch - original has ${expectedLen} tokens, ` +
          `translation encodes to ${newTokens.length} (longer). Dialogue blocks ` +
          "must keep an identical token count or the game hangs on real hardware/melonDS."
      );
      return;
    }

    out.push(...values.slice(last, s));
    out.push(...newTokens);
    last = e;
  });

  if (problems.length) return { tokens: null, relPath, problems };

  out.push(...values.slice(last));
  return { tokens: out, relPath, problems: [] };
}

/**
 * Port of apply_font_art.py for NodeJS webtool.
 * Renders 1,559 Galmuri11 BDF Hangul glyphs into build/data/Font_DOM.nbfc.
 */
function applyFontArt(name) {
  const buildDir = proj.buildDir(name);
  const nbfcPath = path.join(buildDir, "data", "Font_DOM.nbfc");
  if (!fs.existsSync(nbfcPath)) return;

  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const bdfPath = path.join(repoRoot, "analysis", "fonts", "Galmuri11.bdf");
  if (!fs.existsSync(bdfPath)) return;

  const bdfContent = fs.readFileSync(bdfPath, "utf-8");
  const glyphs = parseBdf(bdfContent);

  const nbfcBuf = fs.readFileSync(nbfcPath);
  const numTiles = Math.floor(nbfcBuf.length / 64);

  for (const [k, v] of Object.entries(mc.CODES_KR)) {
    if (v.kind !== "full" || !v.char) continue;
    const realTile = v.real_tile;
    if (realTile === null || realTile === undefined) continue;
    const glyph = glyphs.get(v.char);
    if (!glyph) continue;

    renderGlyphToTiles(nbfcBuf, numTiles, realTile, glyph);
  }

  // Zero out the blank space tiles (mirrors analysis/apply_font_art.py) - the
  // pristine Font_DOM.nbfc has real Japanese glyph ink baked into these tile
  // slots (they were only ever "blank" by font-code convention, not by
  // pixel data), so without this the space character shows leftover
  // original artwork instead of a blank (2026-08-10, confirmed via melonDS
  // screenshots showing 幡 in place of every space).
  //
  // Both full-width (0xA002) and half-width (0x00CA) space codes need all 4
  // sub-tiles of their 2x2 block cleared, not just the top row - 0x00CA
  // shares its base tile with the unused full-width code 0x0606, which
  // occupies all 4 sub-tiles (base, base+1, base+32, base+33). Clearing only
  // (base, base+1) left the bottom row with leftover pristine glyph ink,
  // confirmed 2026-08-10 via melonDS showing garbage where spaces/padding
  // should be blank.
  const FULL_SPACE_TILE = 10242;
  const HALF_SPACE_TILE = 390;
  for (const base of [FULL_SPACE_TILE, HALF_SPACE_TILE]) {
    for (const off of [base * 64, (base + 1) * 64, (base + 32) * 64, (base + 33) * 64]) {
      if (off + 64 <= nbfcBuf.length) nbfcBuf.fill(0, off, off + 64);
    }
  }

  fs.writeFileSync(nbfcPath, nbfcBuf);
}

function parseBdf(content) {
  const glyphs = new Map();
  const lines = content.split(/\r?\n/);
  let curChar = null;
  let curBbox = null;
  let inBitmap = false;
  let bitmapHex = [];

  for (const line of lines) {
    if (line.startsWith("ENCODING ")) {
      const code = parseInt(line.split(/\s+/)[1], 10);
      curChar = String.fromCharCode(code);
    } else if (line.startsWith("BBX ")) {
      const parts = line.split(/\s+/).slice(1).map(Number);
      curBbox = { w: parts[0], h: parts[1], xoff: parts[2], yoff: parts[3] };
    } else if (line === "BITMAP") {
      inBitmap = true;
      bitmapHex = [];
    } else if (line === "ENDCHAR") {
      if (curChar && curBbox && bitmapHex.length) {
        glyphs.set(curChar, { bbox: curBbox, hex: bitmapHex });
      }
      curChar = null;
      curBbox = null;
      inBitmap = false;
      bitmapHex = [];
    } else if (inBitmap) {
      bitmapHex.push(line.trim());
    }
  }
  return glyphs;
}

function renderGlyphToTiles(nbfcBuf, numTiles, startTile, glyph) {
  const tileOffsets = [
    startTile * 64,
    (startTile + 1) * 64,
    (startTile + 32) * 64,
    (startTile + 33) * 64,
  ];

  for (const off of tileOffsets) {
    if (off + 64 <= nbfcBuf.length) {
      nbfcBuf.fill(0, off, off + 64);
    }
  }

  const { bbox, hex } = glyph;
  const canvasW = 11;
  const canvasH = 11;
  const targetX0 = Math.floor((canvasW - bbox.w) / 2);
  const targetY0 = Math.floor((canvasH - bbox.h) / 2);

  for (let r = 0; r < bbox.h; r++) {
    const rowHex = hex[r] || "00";
    const rowVal = parseInt(rowHex, 16);
    const rowBits = hex[r].length * 4;

    for (let c = 0; c < bbox.w; c++) {
      const bitIndex = rowBits - 1 - c;
      const pixel = (rowVal >> bitIndex) & 1;
      if (!pixel) continue;

      const px = targetX0 + c;
      const py = targetY0 + r + 2;

      if (px < 0 || px >= 16 || py < 0 || py >= 16) continue;

      const subTileX = Math.floor(px / 8);
      const subTileY = Math.floor(py / 8);
      const localX = px % 8;
      const localY = py % 8;

      const subTileIndex = subTileY * 2 + subTileX;
      const tileOffset = tileOffsets[subTileIndex];
      const pixelOffset = tileOffset + localY * 8 + localX;

      if (pixelOffset < nbfcBuf.length) {
        nbfcBuf[pixelOffset] = 15;
      }
    }
  }
}

module.exports = {
  FIELDS,
  readCsv,
  writeCsv,
  extractProject,
  fileSummaries,
  rowsForFile,
  saveFile,
  buildFileTokens,
  applyFontArt,
};
