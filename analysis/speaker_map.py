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

Two IDs are NOT character speakers:
  0x0    - choice/selection prompt (block content is two options concatenated,
           e.g. "ミニスカートチャイナ服", "4月13日3月14日" - not spoken text)
  0xffff - narration/sound effect with no speaker (e.g. "ガチャッ", "ピッ",
           "バタンッ" - onomatopoeia, confirmed corpus-wide)

"Orochi"-prefixed files were excluded: unlike every other named character,
they show no single dominant ID (each file's top value differs), meaning
this label groups crossover/multi-character scenes rather than one heroine's
route - a per-file ID guess would be unreliable there.
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
}

SPECIAL_NAMES = {
    0x0: "[선택지]",
    0xFFFF: "[효과음/내레이션]",
}


def speaker_of(header_value):
    """Return a display label for a block's header ID, or None if unrecognized."""
    if header_value in SPECIAL_NAMES:
        return SPECIAL_NAMES[header_value]
    if header_value in SPEAKER_NAMES:
        return SPEAKER_NAMES[header_value]
    return None
