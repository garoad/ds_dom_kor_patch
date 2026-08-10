"use strict";

// Port of analysis/speaker_map.py - see that file's module docstring for the
// full empirical derivation (header ID at values[start-1], per-character
// dominant ID, 0x0/0xFFFF special-cased as non-character lines).
//
// 2026-08-10 catalog expansion (synced from analysis/speaker_map.py): added
// 7 crossover-cast IDs resolved via direct in-text addressing (a nearby line
// calling the speaker by name/title) rather than per-file dominance - see
// the Python module's docstring for each ID's evidence. 0xf has a known
// residual scope collision (3/107 occurrences are an unrelated garbled-
// prefix artifact, not Leona's father) - left mapped anyway (104/107
// correct) pending investigation of that artifact.

const SPEAKER_NAMES = {
  0x2: "주인공",
  0x3: "Athena",
  0x37: "Shizuku",
  0x3b: "Chizuru",
  0xb: "Kula",
  0x6e: "Mina",
  0x6f: "Rinka",
  0x3c: "Mary",
  0x72: "Shiki",
  0x5: "Mai",
  0x6b: "Nakoruru",
  0x38: "Hotaru",
  0x71: "Mikoto",
  0x8: "Kasumi",
  0x39: "Kisarah",
  0x6c: "Shino",
  0x6: "Yuri",
  0x70: "Saya",
  0x73: "Iroha",
  0x9: "Jenny",
  0x3a: "Fio",
  0x3d: "Mature",
  0x4: "Leona",
  0x7: "King",
  0xa: "Kaidou",
  0xf: "레오나 아버지",
  0x3f: "Kyo",
  0x41: "Iori",
  0x48: "Goenitz",
  0x52: "Kagura Maya",
  0x76: "Ukyo",
};

const SPECIAL_NAMES = {
  0x0: "[선택지]",
  0xffff: "[효과음/내레이션]",
  0x44: "[마리의 개]",
};

/** Return a display label for a block's header ID, or null if unrecognized. */
function speakerOf(headerValue) {
  if (headerValue in SPECIAL_NAMES) return SPECIAL_NAMES[headerValue];
  if (headerValue in SPEAKER_NAMES) return SPEAKER_NAMES[headerValue];
  return null;
}

module.exports = { SPEAKER_NAMES, SPECIAL_NAMES, speakerOf };
