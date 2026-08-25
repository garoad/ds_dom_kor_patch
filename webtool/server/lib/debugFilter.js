"use strict";

// Port of mes_translate_extract.py's is_debug_menu_block().
// Leftover dev QA menu entries that match the real dialogue box shape but
// aren't player-facing text. Two known shapes:
// (1) "<name><0087><costume><0087><emotion>" portrait/costume test entries -
//     every confirmed instance contains a literal 0x0087 separator; no
//     confirmed real dialogue block does.
// (2) sound/BGM/emotion test-menu screens - every confirmed instance ends
//     with the literal phrase "次のページ" ("next page"), which does not
//     occur in any real dialogue line in the corpus.
//
// Exception to (2): real "who do you want to call?" / character-select
// choice menus also legitimately end with a "次のページ" (next page) option
// to page through more names when there are more than fit on one screen -
// the exact same trailing signature as the dev sound-test menus. A block
// whose text (minus the trailer) ENDS WITH a concatenation of known
// character names (or the standalone "1人で行く"/"go it alone" option) is a
// real choice menu, not a debug leftover (see ANALYSIS_NOTES.md 2026-08-25).
//
// Matching is done from the END of the text, not the start: some real
// choice-menu blocks (dom1MEZ01.mes's page-2/page-3 continuations,
// dom3Festival.mes/dom3OP_0701.mes's page-2) have a binary icon-assignment
// preamble before the plain-text option list, which decodes to stray glyph
// artifacts that would break a from-the-start match. Verified corpus-wide
// this doesn't misclassify any genuine dev sound/BGM-test menu, whose junk
// text (e.g. "のテーマ") breaks the match at the first non-name character.

const tio = require("./translateIo");

const NEXT_PAGE_TEXT = "次のページ";

// Sorted longest-first so segmentation can't short-match a name that's a
// prefix of a longer one.
const CHOICE_OPTION_TEXTS = [
  "アテナ", "舞", "ユリ", "キング", "香澄", "ジェニー", "クーラ", "レオナ",
  "雫", "ほたる", "キサラ", "フィオ", "ちづる", "マリー", "マチュア",
  "ナコルル", "詩乃", "ミナ", "凛花", "サヤ", "命", "色", "いろは",
  "1人で行く",
].sort((a, b) => b.length - a.length);

function isHeroineNameChoice(text) {
  let remaining = text;
  let matched = false;
  while (remaining) {
    const name = CHOICE_OPTION_TEXTS.find((n) => remaining.endsWith(n));
    if (!name) break;
    remaining = remaining.slice(0, remaining.length - name.length);
    matched = true;
  }
  return matched;
}

function isDebugMenuBlock(values) {
  if (values.includes(0x0087)) return true;
  const text = tio.tokensToText(values);
  if (text.endsWith(NEXT_PAGE_TEXT)) {
    const prefix = text.slice(0, text.length - NEXT_PAGE_TEXT.length);
    if (isHeroineNameChoice(prefix)) return false;
    return true;
  }
  return false;
}

module.exports = { isDebugMenuBlock };
