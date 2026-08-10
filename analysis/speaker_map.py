"""
Speaker-ID map for .mes dialogue blocks.

Every dialogue block is preceded by a variable-length header whose last u16
token is a speaker/line-type ID (see find_dialogue_blocks() in mes_codec.py -
that ID sits at values[start-1] for a block returned as (start, end)).

This map was derived empirically (2026-08-06) by cross-referencing script
filenames (which embed a character name, e.g. dom1Athena_L01.mes) against the
header ID distribution across all 865 .mes files: for each named character,
one non-special ID value dominates the overwhelming majority of that
character's own files (confirmed both by aggregate frequency and by how many
individual files it "wins" as the top value), while 0x2 is the universal top
value in literally every file (the protagonist, who responds in nearly every
scene). Spot-checked against actual rendered dialogue text (dom1Mai_L02.mes)
to confirm the ID switches line-by-line exactly where the speaker changes in
a back-and-forth conversation.

Three IDs are NOT character speakers:
  0x0    - choice/selection prompt (block content is two options concatenated,
           e.g. "ミニスカートチャイナ服", "4月13日3月14日" - not spoken text)
  0xffff - narration/sound effect with no speaker (e.g. "ガチャッ", "ピッ",
           "バタンッ" - onomatopoeia, confirmed corpus-wide)
  0x6e5c - NOT a real header value. find_dialogue_blocks() in mes_codec.py starts
           scanning for the next block's header right after the previous block's
           closing 0x6E5C 0x6E5C marker; in flat name/label list files
           (soundnamedom*.mes, dom2chara.mes, dom3chara.mes, strindex.mes,
           endtitledom*.mes, some playername.mes entries - confirmed 2026-08-10 by
           inspecting raw token context around every zero-header-gap block in
           those files) entries sit back-to-back with zero header tokens between
           the previous marker and the next entry's first glyph, so
           values[start-1] lands on the marker's own second 0x6E5C token instead
           of a real per-entry ID. Confirmed Script/*.mes dialogue files never
           produce a zero header gap (every real dialogue box has >=1 header
           token), so this case is specific to headerless list files, not a
           coincidental real speaker ID. Treated the same as the "no header data"
           case (header_value is None, e.g. a file's very first block).

"Orochi"-prefixed files were excluded from the 2026-08-06 pass: unlike every
other named character, they show no single dominant ID (each file's top
value differs), meaning this label groups crossover/multi-character scenes
rather than one heroine's route. 2026-08-10 catalog expansion resolved most
of these by identifying individual crossover-cast IDs from direct in-text
addressing (a nearby line calling the speaker by name/title) instead of
per-file dominance: 0x3f (草薙/Kyo - addressed "草薙先輩" immediately before
his lines, 56 corpus occurrences), 0x41 (八神/Iori - addressed "八神先輩!",
35 occurrences, self-references "神楽" i.e. Chizuru's clan by name), 0x48
(Goenitz - addressed "ゲーニッツ先生", self-references starting-the-wind
imagery), 0x52 (Kagura Maya, Chizuru's "姉様" - addresses her as "ちづる",
self-references "神楽の家の女"), 0xa (Kaidou - addressed "海堂……" directly
after his lines, recurring rough-speech friend character across multiple
dom1 heroine routes, not file-local), 0xf (Leona's father, unnamed by proper
noun - self-identifies "レオナの父だ" in dom1Leona_L06 and is referenced by
name-dropping Leona in dom1Mai_O0727_4), 0x76 (Ukyo [Tachibana] - addressed
"右京さん/右京先生" across both dom3Saya and dom3Mikoto files, archaic speech
"かまわぬ"), 0x44 ([마리의 개] - Mary's dog; content is always onomatopoeic
barking/growling, never real dialogue, so kept in SPECIAL_NAMES not
SPEAKER_NAMES).

0xf has a known residual scope collision: 3 of its 107 corpus occurrences
(dom1DefScn_Morning.mes block 0, dom3HZR.mes block 134, dom1King_M06.mes
block 0) are NOT Leona's father - they carry the same garbled-numeric-prefix
"header" artifact documented below for 0x29, so mapping 0xf globally
mislabels those 3 blocks. Left as-is (104/107 correct) pending investigation
of the artifact itself.

Separately, 2026-08-10 investigation surfaced a distinct unresolved
structural finding, NOT yet mapped to any speaker name: a cluster of blocks
(observed under header IDs 0x29, 0x01, 0x20a among others) whose content
begins with a run of 3+ raw undecoded "<XXXX>" tokens (small ints and zeros,
e.g. "<0148><0000><0000><0000><0000><0000><0030><0022><0002>...") before the
first real sentence. This is not confined to a file's first block (e.g.
dom2Athena_L01.mes block 33 shows it deep mid-file) and the trailing real
text reads as ordinary conversation (sometimes plausibly 주인공's own line,
reacted to by a heroine in the very next block) rather than one consistent
character's voice. Likely a conditional/affection-branch parameter sequence
that find_dialogue_blocks() is folding into the block's rendered content
rather than a genuine per-character header. Do NOT assign these IDs a
character name without further evidence - see ANALYSIS_NOTES.md 2026-08-10
entry for the corpus-wide scan (31/121 unknown block-0 rows alone match this
pattern) and next-step investigation notes.
"""

SPEAKER_NAMES = {
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
}

SPECIAL_NAMES = {
    0x0: "[선택지]",
    0xFFFF: "[효과음/내레이션]",
    0x6E5C: "",  # not a real header - see module docstring
    0x44: "[마리의 개]",
}


def speaker_of(header_value):
    """Return a display label for a block's header ID, or None if unrecognized."""
    if header_value in SPECIAL_NAMES:
        return SPECIAL_NAMES[header_value]
    if header_value in SPEAKER_NAMES:
        return SPEAKER_NAMES[header_value]
    return None
