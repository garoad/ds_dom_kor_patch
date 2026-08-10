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

const tio = require("./translateIo");

function isDebugMenuBlock(values) {
  if (values.includes(0x0087)) return true;
  const text = tio.tokensToText(values);
  if (text.endsWith("次のページ")) return true;
  return false;
}

module.exports = { isDebugMenuBlock };
