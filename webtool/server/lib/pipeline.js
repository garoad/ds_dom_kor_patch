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

// namelist1.mes (speaker/NPC display-name table, see speakerMap.js) - like
// playername.mes, entries here aren't dialogue-box text tied to a fixed ROM
// slot. Hardware-confirmed safe on melonDS 2026-08-12 (translated names of
// varying length render correctly, game runs normally, including the
// Athena nameplate - proving that scene reads names from here too rather
// than from its separate image-based nameplate asset).
//
// Extended 2026-08-12 to the other headerless-list-format files (see
// speaker_map.py's module docstring) that share the same structural
// signature - back-to-back entries with no per-entry header, found by
// scanning for 0x6E5C 0x6E5C markers rather than by jumping to a
// hardcoded byte offset - so the same "not tied to a fixed ROM slot"
// reasoning applies:
//   - dom1chara.mes/dom2chara.mes/dom3chara.mes: per-character profile
//     cards (birthday/age/hometown/blood type/height/weight)
//   - soundnamedom1/2/3.mes: sound-test music track name list
//   - endtitledom1/2/3.mes: unlockable ending title name list
// No max-tokens cap (unlike PLAYERNAME_FILE) since none of these have a
// known in-game character limit. This extension itself is still
// experimental pending its own real hardware/melonDS confirmation - only
// namelist1.mes has been confirmed so far.
//
// NOT included: extraopen.mes/common.mes (real per-entry headers, not the
// headerless-list pattern - structurally just normal one-off strings);
// strindex.mes (the font glyph index table itself, not player-facing
// text); orochiendroll.mes (staff credits - real people's names, must stay
// as-is, not translated); saveload.mes (save/load UI mixes translatable
// words with fixed-position date/time digit formatting via dense control
// codes - too fragile to blanket-exempt, left on strict matching if ever
// added to the pipeline).
const LIST_NO_LENGTH_CAP_FILES = new Set([
  "namelist1.mes",
  "dom1chara.mes",
  "dom2chara.mes",
  "dom3chara.mes",
  "soundnamedom1.mes",
  "soundnamedom2.mes",
  "soundnamedom3.mes",
  "endtitledom1.mes",
  "endtitledom2.mes",
  "endtitledom3.mes",
]);

// See translateIo.js's PAGE_TURN_TOKEN for how the trailing page-turn
// marker is hidden from the CSV text and re-appended automatically by
// buildFileTokens()/validateRow() below.
const PAGE_TURN_TOKEN = tio.PAGE_TURN_TOKEN;

const OUTSIDE_MES_FILES = [
  "soundnamedom1.mes",
  "soundnamedom2.mes",
  "soundnamedom3.mes",
  "dom3chara.mes",
  "dom2chara.mes",
  "playername.mes",
  "extraopen.mes",
  "common.mes",
  "endtitledom3.mes",
  "endtitledom2.mes",
  "endtitledom1.mes",
  // Master speaker/NPC name table - index N == the header ID used by
  // findDialogueBlocks() to tag a dialogue block's speaker (verified
  // 2026-08-12 against speaker_map's SPEAKER_NAMES/SPECIAL_NAMES). Headerless
  // list format like dom2chara.mes/playername.mes, so its own rows' speaker
  // labels come out as UNKNOWN_0x6e5c - same as those other list files.
  "namelist1.mes",
  // dom1chara.mes was missing entirely from this list until 2026-08-12
  // (dom2chara.mes/dom3chara.mes were already here) - same per-character
  // profile-card format, just for dom1's cast.
  "dom1chara.mes",
  // Short one-off UI prompt strings (map-move / name-confirm dialogs) -
  // real per-entry headers, NOT the headerless-list pattern, so they use
  // standard strict length matching, not LIST_NO_LENGTH_CAP_FILES.
  "mapmove.mes",
  "nameinput.mes",
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
      // Hide the trailing page-turn marker from the CSV text entirely (see
      // tio.PAGE_TURN_TOKEN) - buildFileTokens()/validateRow() restore it
      // automatically.
      const textEnd = values[e - 1] === tio.PAGE_TURN_TOKEN ? e - 1 : e;
      const text = tio.tokensToText(values.slice(s, textEnd), mc.CODES_FULL);
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
  const rows = readCsv(name).filter((r) => r.file === fname);
  const relPath = rows.find((r) => r.rel_path)?.rel_path;
  const pageTurnFlags = realBlockPageTurnFlags(name, fname, relPath);
  return rows.map((r) => ({
    ...r,
    max_len: maxLenOf(r, fname, pageTurnFlags ? pageTurnFlags[Number(r.block)] : undefined),
  }));
}

/**
 * Per-block "does this block's real on-disk token end with the hidden
 * PAGE_TURN_TOKEN" flags, read directly from the pristine unpack/ file -
 * the same authoritative source buildFileTokens() uses. Returns null if the
 * file can't be resolved (falls back to detectHasPageTurn's text-based
 * guess in that case).
 */
function realBlockPageTurnFlags(name, fname, relPath) {
  const unpackDataDir = path.join(proj.unpackDir(name), "data");
  let srcPath = relPath ? path.join(unpackDataDir, relPath) : path.join(proj.scriptDir(name), fname);
  if (!fs.existsSync(srcPath)) srcPath = path.join(unpackDataDir, fname);
  if (!fs.existsSync(srcPath)) return null;

  const values = mc.loadValues(srcPath);
  const isScript = srcPath.startsWith(path.join(unpackDataDir, "Script"));
  const blocks = isScript ? realBlocksOf(values) : mc.findDialogueBlocks(values);
  return blocks.map(([s, e]) => e > s && values[e - 1] === PAGE_TURN_TOKEN);
}

/**
 * Fallback used only when the real .mes file can't be resolved (e.g. a
 * stale/relocated project). Derives hasPageTurn from srcText alone:
 * tokensToText()/textToTokens() are a 1-token-in/1-symbol-out round trip for
 * everything except this one deliberate omission, so srcText re-encodes to
 * exactly expectedTokenCount tokens normally, or expectedTokenCount - 1 when
 * the marker was hidden. NOTE: tio.textToTokens() only knows the Korean
 * translation font map (mc.CODES_KR) - it throws on any kanji still present
 * in an untranslated srcText, which silently falls through to "no marker"
 * below. That's acceptable here only because this path is a last-resort
 * fallback; realBlockPageTurnFlags() above (reading the real file) is what
 * actually matters for the ~97% of blocks that do have the marker.
 */
function detectHasPageTurn(srcText, expectedTokenCount) {
  if (expectedTokenCount === undefined) return false;
  let srcTokenCount = expectedTokenCount;
  try {
    srcTokenCount = tio.textToTokens(srcText).length;
  } catch (ex) {
    // srcText contains a kanji (or other) character outside the Korean font
    // map and can't be re-encoded; fall back to treating it as the
    // no-marker case since we have no better signal here.
  }
  return srcTokenCount === expectedTokenCount - 1;
}

/**
 * The usable character budget for a row's translation, for display to the
 * translator. row.n_tokens is the raw ROM block span, which still includes
 * the hidden PAGE_TURN_TOKEN slot for ~97% of blocks (see
 * pipeline.js's extractProject) - showing that raw number as the length
 * limit is off by one for those rows. Returns null when the file has no
 * length cap at all (see LIST_NO_LENGTH_CAP_FILES).
 */
function maxLenOf(row, fname, hasPageTurnHint) {
  if (fname === PLAYERNAME_FILE) return PLAYERNAME_MAX_TOKENS;
  if (LIST_NO_LENGTH_CAP_FILES.has(fname)) return null;
  const nTokens = Number(row.n_tokens);
  const hasPageTurn = hasPageTurnHint !== undefined ? hasPageTurnHint : detectHasPageTurn(row.source, nTokens);
  return hasPageTurn ? nTokens - 1 : nTokens;
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
 *
 * hasPageTurnHint should come from realBlockPageTurnFlags() (the real file,
 * authoritative - same source buildFileTokens() uses); this only falls back
 * to detectHasPageTurn()'s srcText-based guess when the caller couldn't
 * resolve the real file.
 */
function validateRow(srcText, dstTextRaw, expectedTokenCount, fname, hasPageTurnHint) {
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

  if (LIST_NO_LENGTH_CAP_FILES.has(fname)) {
    return { ok: true, tokenCount: tokens.length };
  }

  const hasPageTurn = hasPageTurnHint !== undefined ? hasPageTurnHint : detectHasPageTurn(srcText, expectedTokenCount);
  const textExpected = hasPageTurn ? expectedTokenCount - 1 : expectedTokenCount;

  if (textExpected !== undefined && tokens.length < textExpected) {
    tokens = tokens.concat(Array(textExpected - tokens.length).fill(tio.SPACE_TOKEN));
  }
  return { ok: true, tokenCount: tokens.length + (hasPageTurn ? 1 : 0) };
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

  const fileRows = rows.filter((r) => r.file === fname);
  const relPath = fileRows.find((r) => r.rel_path)?.rel_path;
  const pageTurnFlags = realBlockPageTurnFlags(name, fname, relPath);

  for (const row of rows) {
    if (row.file !== fname) continue;
    if (!editByBlock.has(String(row.block))) continue;
    const item = editByBlock.get(String(row.block));
    if (item.translation !== undefined) row.translation = item.translation;
    if (item.ai_draft !== undefined) row.ai_draft = item.ai_draft;

    const hasPageTurnHint = pageTurnFlags ? pageTurnFlags[Number(row.block)] : undefined;
    const v = validateRow(row.source, row.translation, Number(row.n_tokens), fname, hasPageTurnHint);
    if (!v.ok) {
      report.push({ block: Number(row.block), ok: false, error: v.error });
    } else if (fname !== PLAYERNAME_FILE && !LIST_NO_LENGTH_CAP_FILES.has(fname) && v.tokenCount !== Number(row.n_tokens)) {
      // Shorter translations are already padded to match inside validateRow,
      // so only "longer" (which would drop content if trimmed) reaches here.
      // playername.mes/LIST_NO_LENGTH_CAP_FILES don't enforce this match at all (see validateRow).
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

function isDangerousOpcodeBlock(srcText) {
  if (!srcText) return false;
  return (
    srcText.includes("<000") ||
    srcText.includes("<001") ||
    srcText.includes("<002") ||
    srcText.includes("<003") ||
    srcText.includes("<004") ||
    srcText.includes("<005") ||
    srcText.includes("<006") ||
    srcText.includes("<007") ||
    srcText.includes("<008") ||
    srcText.includes("<009") ||
    srcText.includes("<00A") ||
    srcText.includes("<00B") ||
    srcText.includes("<00C") ||
    srcText.includes("<00D") ||
    srcText.includes("<00E") ||
    srcText.includes("<00F") ||
    srcText.includes("<FF") ||
    srcText.includes("<FC") ||
    srcText.startsWith("<0") ||
    Boolean(srcText.match(/^[a-zA-Z0-9~,.<>]{1,5}<00/))
  );
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
    const hasPageTurn = expectedLen > 0 && values[e - 1] === PAGE_TURN_TOKEN;
    const textExpectedLen = hasPageTurn ? expectedLen - 1 : expectedLen;

    if (!row.translation || row.translation === srcText || isDangerousOpcodeBlock(srcText)) {
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

    if (LIST_NO_LENGTH_CAP_FILES.has(fname)) {
      // No length constraint at all (see LIST_NO_LENGTH_CAP_FILES comment
      // above) - hardware-confirmed for namelist1.mes only so far; the
      // other files here are the same experiment, pending their own
      // real hardware/melonDS confirmation.
      out.push(...values.slice(last, s));
      out.push(...newTokens);
      last = e;
      return;
    }

    if (newTokens.length < textExpectedLen) {
      // Pad with trailing space tokens rather than failing the block - a
      // shorter translation is safe to pad, unlike a longer one (which
      // would have to drop content to fit and is still reported below).
      // Padded against textExpectedLen (excluding the page-turn marker, if
      // any) so the marker appended below always ends up last - see
      // tio.PAGE_TURN_TOKEN for why it must never be pushed off the end by
      // padding. Uses tio.SPACE_TOKEN (full-width) - see its comment for
      // why the half-width blank is not used.
      newTokens = newTokens.concat(Array(textExpectedLen - newTokens.length).fill(tio.SPACE_TOKEN));
    }

    if (newTokens.length !== textExpectedLen) {
      problems.push(
        `block ${i}: token count mismatch - original has ${textExpectedLen} tokens, ` +
          `translation encodes to ${newTokens.length} (longer). Dialogue blocks ` +
          "must keep an identical token count or the game hangs on real hardware/melonDS."
      );
      return;
    }

    if (hasPageTurn) {
      newTokens = newTokens.concat(PAGE_TURN_TOKEN);
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
 * Renders the Galmuri11 BDF Hangul glyphs (per font_map_kr.json) into
 * build/data/Font_DOM.nbfc.
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
    // Only re-render actual Hangul syllables. Without this range check, any
    // non-Hangul char (Japanese punctuation like '、'/'「', kanji, kana) that
    // font_map_kr.json still carries from font_map_full.json but which also
    // happens to exist in Galmuri11.bdf's glyph set gets incorrectly
    // overwritten with the Korean bitmap font's version, corrupting glyphs
    // that were never meant to be touched (2026-08-11, confirmed via melonDS
    // screenshots showing garbled '、'/「' in place of untouched punctuation).
    // analysis/apply_font_art.py already has this same check - this brings
    // the JS mirror in line with it.
    const cp = v.char.codePointAt(0);
    if (v.char.length !== 1 || cp < 0xac00 || cp > 0xd7a3) continue;
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

  // Canvas is x:[0,10] (11 wide, centred horizontally) y:[2,12] (11 tall,
  // BOTTOM-aligned - not centred). This must match analysis/apply_font_art.py's
  // render_glyph_16x16 exactly (GLYPH_X_MIN/MAX/Y_MIN/MAX, paste_x/paste_y) -
  // that Python renderer is the one validated against real hardware/melonDS.
  // This JS port previously centred vertically (targetY0 + r + 2), which
  // put every hangul glyph ~2px higher than the validated Python output -
  // usually invisible, but for glyphs whose ink straddles the y=8 tile
  // boundary (e.g. 스/소/쇼, short vowel strokes) it moves pixels into the
  // wrong sub-tile entirely (2026-08-18, found while diffing a webtool
  // build's Font_DOM.nbfc against analysis/unpack's after the half-width
  // danger-zone fix - the two should have been byte-identical for hangul
  // tiles and weren't).
  const GLYPH_X_MIN = 0;
  const GLYPH_X_MAX = 10;
  const GLYPH_Y_MIN = 2;
  const GLYPH_Y_MAX = 12;
  const GLYPH_W = GLYPH_X_MAX - GLYPH_X_MIN + 1;

  const { bbox, hex } = glyph;
  let targetX0 = GLYPH_X_MIN + Math.floor((GLYPH_W - bbox.w) / 2);
  if (targetX0 < GLYPH_X_MIN) targetX0 = GLYPH_X_MIN;
  if (targetX0 + bbox.w > GLYPH_X_MAX + 1) targetX0 = GLYPH_X_MAX + 1 - bbox.w;
  let targetY0 = GLYPH_Y_MAX + 1 - bbox.h;
  if (targetY0 < GLYPH_Y_MIN) targetY0 = GLYPH_Y_MIN;

  for (let r = 0; r < bbox.h; r++) {
    const rowHex = hex[r] || "00";
    const rowVal = parseInt(rowHex, 16);
    const rowBits = hex[r].length * 4;

    for (let c = 0; c < bbox.w; c++) {
      const bitIndex = rowBits - 1 - c;
      const pixel = (rowVal >> bitIndex) & 1;
      if (!pixel) continue;

      const px = targetX0 + c;
      const py = targetY0 + r;
      if (px < GLYPH_X_MIN || px > GLYPH_X_MAX || py < GLYPH_Y_MIN || py > GLYPH_Y_MAX) continue;

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

function searchCsv(name, query, options = {}) {
  const { target = "all", limit = 200 } = options;
  const rows = readCsv(name);
  if (!rows || rows.length === 0) {
    return { total: 0, results: [] };
  }

  const qLower = query.toLowerCase();
  const matched = [];

  for (const r of rows) {
    let isMatch = false;
    const source = (r.source || "").toLowerCase();
    const translation = (r.translation || "").toLowerCase();
    const aiDraft = (r.ai_draft || "").toLowerCase();
    const speaker = (r.speaker || "").toLowerCase();
    const file = (r.file || "").toLowerCase();

    if (target === "source") {
      isMatch = source.includes(qLower);
    } else if (target === "translation") {
      isMatch = translation.includes(qLower) || aiDraft.includes(qLower);
    } else if (target === "speaker") {
      isMatch = speaker.includes(qLower);
    } else if (target === "file") {
      isMatch = file.includes(qLower);
    } else {
      isMatch =
        source.includes(qLower) ||
        translation.includes(qLower) ||
        aiDraft.includes(qLower) ||
        speaker.includes(qLower) ||
        file.includes(qLower);
    }

    if (isMatch) {
      matched.push(r);
    }
  }

  const total = matched.length;
  const sliced = limit > 0 ? matched.slice(0, limit) : matched;

  return {
    total,
    query,
    results: sliced,
  };
}

module.exports = {
  FIELDS,
  readCsv,
  writeCsv,
  extractProject,
  fileSummaries,
  rowsForFile,
  searchCsv,
  saveFile,
  buildFileTokens,
  applyFontArt,
};

