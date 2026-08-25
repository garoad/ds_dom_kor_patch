"""
Build a corrected font_map_full.json from:
  1. full_code_tile_map.json - authoritative {count, kind, real_tile} for every
     code seen across all 883 .mes files (superset of the old 340-file scan).
  2. FULL_CHARS below - manual visual re-transcription of all 'full'-kind
     codes, read from fullcodes_correct_batch_*.png (rendered at the
     CONFIRMED real_tile address, not the old/wrong tile==code assumption).
  3. HALF_CHARS below - carried over verbatim from the OLD font_map_full.json,
     since half-width addressing (tile=2*low-14) was never wrong and is
     unaffected by the real_tile bug.

Codes with kind in ('ctrl', 'ctrl_or_unknown') or 'full'-kind codes not in
FULL_CHARS (deliberately skipped as ambiguous) get no 'char' key at all, so
translate_io.is_literal_glyph() safely falls back to <HEX> rendering.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "full_code_tile_map.json"), encoding="utf-8") as f:
    FULL_MAP = json.load(f)

with open(os.path.join(HERE, "font_map_full.json"), encoding="utf-8") as f:
    OLD = json.load(f)

HALF_CHARS = {}
for k, v in OLD["codes"].items():
    if v.get("kind") == "half":
        HALF_CHARS[k] = v

# 2026-08-06 half-width re-verification (context-based, same method as
# full-width): the old "?(punct, unresolved)" string was a leftover debug
# note being rendered as literal text. 0083/0084 confirmed via unambiguous
# raw-token context (see below); the rest are cleared to a clean <HEX>
# fallback since context shows them used inconsistently (mixed with block
# header/control bytes) and pixel re-derivation was inconclusive.
#   0083 = "・" - context: "サイコ<0083>ソルジャー" (サイコ・ソルジャー),
#     "トゥルー<0083>ハート" (トゥルー・ハート), "イリュージョン<0083>ダンス",
#     "オリジナル<0083>カクテル" - all katakana compound words joined by nakaguro.
#   0084 = ":" - context: "8<0084>30" (time notation "8:30"), the exact case
#     that surfaced this whole investigation. Only 1 occurrence in the corpus
#     but it is unambiguous.
for _hex in ("0080", "0082", "009D", "009E"):
    HALF_CHARS.pop(_hex, None)
HALF_CHARS["0083"] = {"char": "・"}
HALF_CHARS["0084"] = {"char": ":"}
# 2026-08-06: 009B/009C confirmed via unambiguous school-class context -
# "3年<009B>組" (3rd-year Class A) repeated across many files, and the
# decisive paired occurrence "<009B>組も<009C>組も無事に" ("both Class A and
# Class B safely...", dom2Kisarah_L06.mes) - directly parallel to the
# already-known full-width "年A組<...>年B組<...>年C組" sequence
# (dom1Leona_O0731_1.mes, codes 0508/050A/050C). User flagged 009C from
# "<009C>ジェニーのテーマ" (a lettered BGM track-list entry, "B. Jenny's
# Theme") and independently guessed "B" - confirmed by the corpus-wide scan.
HALF_CHARS["009B"] = {"char": "A"}
HALF_CHARS["009C"] = {"char": "B"}
# 2026-08-06: 009A="9" - completes the digit table (0091='0'..0099='8' were
# already confirmed; 009A is the linearly-next slot). Confirmed via numeric
# context: "身長16<009A>センチ"(height 169cm), "1<009A>時から"(from 19:00),
# "5月2<009A>日"(May 29), "2<009A>秒"(29 seconds) - all read correctly as "9".
# NOTE: extending this same linear-table hypothesis past B (predicting
# 009D=C, 009E=D, 009F=E, 00A4=J, 00A6=L, 00B4=Z, ...) was checked against
# full corpus context and does NOT hold - every one of those codes appears
# almost exclusively as a block-header/speaker-ID field (immediately after
# a 0x6E5C 0x6E5C terminator, immediately before real dialogue text) with
# zero clean in-content usage as a printed letter. Left unlabeled.
HALF_CHARS["009A"] = {"char": "9"}

# 2026-08-06: full-width codes that NEVER once appeared inside a detected
# dialogue block in the entire corpus (absent from full_code_tile_map.json
# entirely) - the same self-referential blind spot that hid 0x412 (♪):
# find_dialogue_blocks() only recognizes a code as a content-start candidate
# via CODES, but CODES is built by scanning content THROUGH
# find_dialogue_blocks() itself, so a code that's never once been recognized
# can never be discovered by rescanning alone. Found instead by directly
# auditing every block's header value (values[start-1]) for ones that are
# structurally full/half-shaped per decode_value() (real speaker IDs are
# always small ctrl-range ints, per speaker_map.py) - 4 candidates turned up,
# 3 confirmed real via a consistent raw-context signature (immediately after
# 0xFFFF, the "sound effect/no speaker" ID, and immediately before a short
# onomatopoeia/word) plus visual tile confirmation:
#   0402 (tile 258, alias of already-confirmed 0282) = "<"
#   0404 (tile 260, alias of already-confirmed 0284) = ">"
#     -- context: "<アイントリガー>", "<クロウバイツ>", "<ヒートドライブ>" etc,
#     KOF-style special-move names bracketed for a move-list/debug screen.
#   0410 (tile 272) = "◎" -- context: "◎ピンポーン" (correct-answer chime)
#   031E (tile 222) = "×" -- context: "×ブー" (buzzer/wrong-answer sound)
#     ◎/× is the standard Japanese correct/incorrect quiz pair, matching
#     ピンポーン(ding-dong)/ブー(buzzer) perfectly.
# A 4th candidate, 010C (tile 76 = "S"), was NOT confirmed: it recurs with a
# byte-identical header across many unrelated character files right before
# the shared line "藤堂です" (a common cross-route phone-call scene), which
# looks like a reused scene/event-ID header field, not a printed letter -
# left unresolved as <010C>.
MANUAL_FULL_CODES = {
    "0402": "<",
    "0410": "◎",  # ◎
    "031E": "×",  # ×
}
# 0404 (">") is NOT in MANUAL_FULL_CODES like its "<" partner 0402 - it
# already had a full_code_tile_map.json entry (kind=full, count=8, seen
# elsewhere mid-content as the closing bracket), just no FULL_CHARS label,
# so it goes through the normal FULL_CHARS path below instead.

# code(hex, no 0x prefix, uppercase) -> char, from visual re-transcription of
# fullcodes_correct_batch_0000.png .. _1500.png (16 batches, ~1591 codes).
#
# 2026-08-25 correction: 0193/0197/0198/0282/0283/0284 were originally
# mistranscribed as Japanese brackets/punctuation (「/『/』/</:/>) during the
# manual visual batch pass. Corpus cross-checks (`GAME START!!`, `MER06`,
# `AMP wi<0284>h HIROKI`, `Show m<0197> Cou<0282>a<0199>e~`/"Courage",
# `<0189><0198> Figh<0284><0197><0282><0283>`/"Of Fighters", and namelist1.mes's
# `M<0282>.ビッグ`/"Mr.ビッグ") show these are actually lowercase Latin
# a/e/f/r/s/t (real_tile 211/215/216/258/259/260 - part of the same lowercase
# alphabet run as already-confirmed 0195=c/0199=g/019A=h/019B=i/019E=m/0280=o/
# 0285=u/0286=w). See ANALYSIS_NOTES.md for the reversed "40 aliases" false
# lead this superseded.
#
# 2026-08-25 second pass: orochiendroll.mes (DS staff credits roll, dense
# clean English text) resolved the remaining gaps in this same run via whole
# -word corpus matches: "Debug"->0194=b, "Sound"/"Design"/"Background"/
# "Produce"->0196=d, "Planning"/"Original"->019D=l, "Nintendo"/"Design"/
# "Main"->019F=n, "Graphic"/"program"->0281=p, "EXECUTIVE"->0191=X/018F=V,
# "PLAYMORE"/"ECSTACY"/"Yuka"->0192=Y, "Thanks for playing you!"/"R.E.D.Days"
# (endtitledom2.mes)->0287=y. 0194/0196 were previously (wrongly) believed to
# be genuine 「/」 brackets - re-checked corpus-wide, those two codes ONLY ever
# appear in orochiendroll.mes, never in dialogue files, so that belief was a
# mix-up with the visually-identical but distinct bank-03 codes 0314/0316
# (confirmed real brackets/punctuation via common.mes's glyph-catalog block).
# 019C/9D02 remain resolved separately (9D02='盃' via strindex.mes kanji-index
# adjacency + visual tile match); 0288 ("yu#uko" in orochiendroll.mes, single
# context only) is still UNRESOLVED - do not guess from one occurrence.
FULL_CHARS = {
# --- batch 0000: punctuation / digits / letters / hiragana start ---
"0412": "♪",
"0404": ">",
"0182": "/", "0191": "X", "0192": "Y", "0193": "a", "0194": "b", "0196": "d",
"0197": "e", "0198": "f", "018F": "V", "019D": "l", "019F": "n", "0214": "。",
"0218": "?", "021A": "!", "0281": "p", "0282": "r", "0283": "s", "0284": "t",
"0287": "y", "9D02": "盃", "0304": "~",
"0306": "…", "0310": "(", "0312": ")", "020E": ".", "0406": "%", "0408": "#",
"020C": "、", "021E": "ー", "021C": "々", "0300": "―", "030C": "“", "030E": "”",
"0314": "「", "0316": "」",
"041E": "5", "0500": "6", "0502": "7", "0508": "A", "050A": "B", "050C": "C",
"0512": "F", "0514": "G", "0516": "H", "051E": "L", "0600": "M", "0604": "O",
"060A": "R", "0714": "m",
"0810": "ぁ", "0812": "あ", "0814": "い", "0816": "ぃ", "0818": "う", "081A": "ぅ",
"081C": "え", "081E": "ぇ", "0900": "お", "0902": "ぉ", "0904": "か", "0906": "が",
"0908": "き", "090A": "ぎ", "090C": "く", "090E": "ぐ", "0910": "け", "0912": "げ",
"0914": "こ", "0916": "ご", "0918": "さ", "091A": "ざ", "091C": "し", "091E": "じ",
"0A00": "す", "0A02": "ず", "0A04": "せ", "0A06": "ぜ", "0A08": "そ", "0A0A": "ぞ",
"0A0C": "た", "0A0E": "だ", "0A10": "ち", "0A14": "っ", "0A16": "つ", "0A18": "づ",
"0A1A": "て", "0A1C": "で", "0A1E": "と", "0B00": "ど", "0B02": "な", "0B04": "に",

# --- batch 0100: hiragana/katakana ---
"0B06": "ぬ", "0B08": "ね", "0B0A": "の", "0B0C": "は", "0B0E": "ば", "0B10": "ぱ",
"0B12": "ひ", "0B14": "び", "0B16": "ぴ", "0B18": "ふ", "0B1A": "ぶ", "0B1C": "ぷ",
"0B1E": "へ", "0C00": "べ", "0C02": "ぺ", "0C04": "ほ", "0C06": "ぼ", "0C08": "ぽ",
"0C0A": "ま", "0C0C": "み", "0C0E": "む", "0C10": "め", "0C12": "も", "0C14": "や",
"0C16": "ゃ", "0C18": "ゆ", "0C1A": "ゅ", "0C1C": "よ", "0C1E": "ょ", "0D00": "ら",
"0D02": "り", "0D04": "る", "0D06": "れ", "0D08": "ろ", "0D0A": "わ", "0D0C": "を",
"0D0E": "ん", "0D10": "ア", "0D12": "ァ", "0D14": "イ", "0D16": "ィ", "0D18": "ウ",
"0D1A": "ゥ", "0D1C": "エ", "0D1E": "ェ", "0E00": "オ", "0E02": "ォ", "0E04": "カ",
"0E06": "ガ", "0E08": "キ", "0E0A": "ギ", "0E0C": "ク", "0E0E": "グ", "0E10": "ケ",
"0E12": "ゲ", "0E14": "コ", "0E16": "ゴ", "0E18": "サ", "0E1A": "ザ", "0E1C": "シ",
"0E1E": "ジ", "0F00": "ス", "0F02": "ズ", "0F04": "セ", "0F06": "ゼ", "0F08": "ソ",
"0F0C": "タ", "0F0E": "ダ", "0F10": "チ", "0F12": "ヂ", "0F14": "ツ", "0F16": "ッ",
"0F1A": "テ", "0F1C": "デ", "0F1E": "ト", "1000": "ド", "1002": "ナ", "1004": "ニ",
"1006": "ヌ", "1008": "ネ", "100A": "ノ", "100C": "ハ", "100E": "バ", "1010": "パ",
"1012": "ヒ", "1014": "ビ", "1016": "ピ", "1018": "フ", "101A": "ブ", "101C": "プ",
"101E": "ヘ", "1100": "ベ", "1102": "ペ", "1104": "ホ", "1106": "ボ", "1108": "ポ",
"110A": "マ", "110C": "ミ", "110E": "ム", "1110": "メ",

# --- batch 0200: katakana continuation + kanji ---
"1112": "モ", "1114": "ャ", "1116": "ヤ", "1118": "ュ", "111A": "ユ", "111C": "ョ",
"111E": "ヨ", "1200": "ラ", "1202": "リ", "1204": "ル", "1206": "レ", "1208": "ロ",
"120A": "ワ", "120C": "ヲ", "120E": "ン", "1212": "ヶ",
"121E": "愛", "1300": "挨", "130C": "悪", "130E": "握", "131C": "圧", "1400": "扱",
"1402": "宛", "1408": "飴", "140A": "絢", "1416": "安", "141C": "暗", "141E": "案",
"1500": "闇", "1506": "以", "150A": "位", "150C": "依", "150E": "偉", "1510": "囲",
"1516": "威", "151C": "意", "151E": "慰", "1608": "異", "160A": "移", "1610": "胃",
"1614": "衣", "1618": "違", "161A": "遺", "161E": "井", "1704": "育", "170A": "一",
"1710": "逸", "171C": "印", "1800": "員", "1802": "因", "1806": "引", "1808": "飲",
"1810": "院", "1812": "陰", "1814": "隠", "181A": "右", "181C": "宇", "1900": "羽",
"1904": "雨", "1914": "嘘", "1A08": "噂", "1A0C": "運", "1A0E": "雲", "1A16": "営",
"1A1A": "影", "1A1C": "映", "1B00": "栄", "1B02": "永", "1B04": "泳", "1B10": "英",
"1B12": "衛", "1B16": "鋭", "1C04": "越", "1C0C": "円", "1C0E": "園", "1C16": "延",
"1C18": "怨", "1C1C": "援", "1C1E": "沿", "1D00": "演", "1D02": "淡", "1D06": "煙",
"1D0C": "縁", "1D0E": "鮑", "1D14": "遠", "1D1A": "塩", "1D1E": "汚", "1E06": "奥",
"1E0A": "応", "1E0C": "押", "1E10": "横", "1E14": "殴", "1E16": "王", "1F00": "黄",
"1F0A": "屋", "1F0C": "憶", "1F0E": "臆", "1F14": "乙", "1F16": "俺", "1F1A": "恩",

# --- batch 0300 ---
"1F1C": "温", "1F1E": "穏", "2000": "音", "2002": "下", "2004": "化", "2008": "何",
"200A": "伽", "200C": "価", "2010": "加", "2012": "可", "2016": "夏", "2018": "嫁",
"201A": "家", "201E": "科", "2100": "暇", "2102": "果", "2106": "歌", "2108": "河",
"210A": "火", "2112": "稼", "2116": "花", "211C": "荷", "211E": "華", "2204": "課",
"2206": "嘩", "2208": "貨", "220C": "過", "2210": "蚊", "2216": "我", "2218": "牙",
"221A": "画", "230A": "介", "230C": "会", "230E": "解", "2310": "回", "2314": "壊",
"2318": "快", "231A": "怪", "231C": "悔", "2400": "懐", "2402": "戒", "2404": "拐",
"2406": "改", "240E": "海", "2412": "界", "2414": "皆", "2416": "絵", "241C": "開",
"241E": "階", "2506": "外", "2508": "咳", "250A": "害", "250C": "崖", "2512": "涯",
"2518": "街", "2606": "垣", "261A": "格", "261C": "核", "261E": "殻", "2700": "獲",
"2702": "確", "2706": "覚", "2708": "角", "2716": "学", "271A": "楽", "271C": "額",
"2800": "掛", "2802": "笠", "280E": "割", "2816": "活", "2818": "渇", "281C": "葛",
"2906": "叶", "291A": "噛", "2A0C": "乾", "2A12": "寒", "2A16": "勘", "2A18": "勧",
"2A1A": "巻", "2B02": "完", "2B08": "干", "2B0E": "感", "2B10": "慣", "2C00": "歓",
"2C02": "汗", "2C0A": "環", "2C0C": "甘", "2C10": "看", "2C14": "管", "2C16": "簡",
"2C18": "緩", "2C1E": "肝", "2D04": "観", "2D08": "貫", "2D0A": "還", "2D0E": "間",
"2D10": "閑", "2D12": "関", "2D18": "館", "2D1C": "丸",

# --- batch 0400 ---
"2E08": "眼", "2E12": "頑", "2E14": "顔", "2E16": "願", "2E18": "企", "2E1A": "伎",
"2E1C": "危", "2E1E": "喜", "2F00": "器", "2F04": "奇", "2F06": "嬉", "2F08": "寄",
"2F0C": "希", "2F14": "机", "2F1A": "期", "2F1E": "棄", "3000": "機", "3002": "帰",
"3006": "気", "300C": "祈", "300E": "季", "3016": "規", "3018": "記", "301A": "貴",
"301C": "起", "301E": "軌", "3100": "輝", "3106": "鬼", "310A": "偽", "310C": "儀",
"310E": "妓", "3114": "技", "3116": "擬", "311A": "犠", "311C": "疑",
"3200": "義", "3206": "議", "3212": "喫", "3216": "橘", "3218": "詰",
"3302": "客", "3304": "脚", "3308": "逆", "330C": "久", "330E": "仇", "3310": "休",
"3316": "宮", "3318": "弓", "331A": "急", "331C": "救", "331E": "朽", "3400": "求",
"3404": "泣", "3408": "球", "340A": "究", "340C": "窮", "3410": "級", "3416": "旧",
"341A": "去", "341C": "居", "341E": "巨", "3500": "拒", "3502": "拠", "3504": "挙",
"3508": "虚", "350A": "許", "3514": "魚", "351A": "京", "351C": "供", "3604": "競",
"3606": "共", "3608": "凶", "360A": "協", "3610": "叫", "3614": "境", "3618": "強",
"361C": "怯", "361E": "恐", "3702": "挟", "3704": "教", "3708": "況", "370A": "狂",
"370C": "狭", "3710": "胸", "3712": "脅", "3714": "興", "3718": "郷", "371A": "鏡",
"3800": "驚", "380A": "業", "380C": "局", "380E": "曲", "3810": "極", "3812": "玉",
"381A": "勤", "381E": "巾", "390E": "筋", "3910": "緊",

# --- batch 0500 ---
"391A": "謹", "391C": "近", "391E": "金", "3A08": "句", "3A0C": "狗", "3A12": "苦",
"3A16": "駆", "3A1C": "具", "3A1E": "愚", "3B04": "空", "3B06": "偶", "3B0A": "遇",
"3B16": "屈", "3B18": "掘", "3B1A": "窟", "3B1E": "靴", "3C0C": "繰", "3C14": "君",
"3C18": "訓", "3C1C": "軍", "3D06": "係", "3D0C": "兄", "3D14": "型", "3D16": "契",
"3D18": "形", "3E02": "憩", "3E06": "携", "3E08": "敬", "3E12": "稽", "3E16": "経",
"3E18": "維", "3F04": "計", "3F08": "警", "3F0A": "軽", "3F10": "芸", "3F12": "迎",
"3F1A": "撃", "3F1C": "激", "3F1E": "隙", "4006": "決", "400A": "穴", "400C": "結",
"400E": "血", "4012": "月", "4014": "件", "401A": "健", "401E": "券", "4100": "剣",
"4102": "喧", "4108": "嫌", "410E": "懸", "4110": "拳", "4116": "権", "411A": "犬",
"411C": "献", "411E": "研", "4206": "肩", "4208": "見", "4210": "遣", "4212": "鍵",
"4214": "険", "4218": "験", "421C": "元", "421E": "原", "4300": "厳", "4302": "幻",
"4306": "減", "430C": "現", "4312": "言", "4316": "限", "431A": "個", "431C": "古",
"431E": "呼", "4400": "固", "4404": "孤", "4406": "己", "440C": "戸", "440E": "故",
"4410": "枯", "4502": "誇", "4508": "雇", "4510": "互", "4514": "午", "4518": "吾",
"451C": "後", "451E": "御", "4600": "悟", "460A": "語", "460C": "誤", "460E": "護",
"4610": "酬", "4616": "交", "461C": "候", "4700": "光", "4702": "公", "4704": "功",
"4706": "効", "4708": "勾", "470A": "厚", "470C": "口",

# --- batch 0600 ---
"470E": "向", "4718": "好", "471C": "孝", "4800": "工", "4806": "幸", "4808": "広",
"480C": "康", "4814": "抗", "481A": "攻", "4900": "更", "4904": "校",
"4908": "構", "490A": "江", "4910": "港", "4914": "甲", "4A08": "考", "4A0A": "肯",
"4A12": "航", "4A14": "荒", "4A16": "行", "4A1A": "講", "4A1E": "購", "4B0C": "降",
"4B0E": "項", "4B10": "香", "4B12": "高", "4B1A": "号", "4B1C": "合", "4C04": "豪",
"4C0A": "克", "4C0C": "刻", "4C0E": "告", "4C10": "国", "4C14": "酷", "4C18": "黒",
"4C1A": "獄", "4C1E": "腰", "4D04": "惚", "4D0A": "込", "4D0E": "頃", "4D10": "今",
"4D12": "困", "4D18": "婚", "4D1A": "恨", "4E02": "根", "4E06": "混", "4E0E": "魂",
"4E1A": "左", "4E1C": "差", "4F04": "砂", "4F0E": "座", "4F14": "催", "4F16": "再",
"4F18": "最", "4F1A": "哉", "5004": "才", "5006": "採", "500A": "歳", "500C": "済",
"500E": "災", "5018": "祭", "501C": "細", "501E": "菜", "5100": "裁", "5102": "載",
"5104": "際", "5108": "在", "510A": "材", "510C": "罪", "510E": "財", "5110": "冴",
"5112": "坂", "5206": "作", "520E": "昨", "5216": "策", "5218": "索", "521A": "錯",
"5300": "笹", "5304": "冊", "5308": "察", "530A": "拶", "5310": "札", "5312": "殺",
"5316": "雑", "5402": "皿", "5406": "三", "5408": "傘", "540A": "参", "540C": "山",
"5412": "散", "541A": "産", "541C": "算", "5504": "賛", "5508": "餐", "550A": "斬",
"550E": "残", "5510": "仕",

# --- batch 0700 ---
"5516": "使", "5518": "刺", "551C": "史", "5602": "士", "5604": "始", "5606": "姉",
"5608": "姿", "560A": "子", "560E": "市", "5610": "師", "5612": "志", "5614": "思",
"5616": "指", "5618": "支", "561E": "施", "5704": "止", "5706": "死", "5708": "氏",
"570A": "獅", "570E": "私", "5712": "紙", "571C": "視", "571E": "詞", "575C": "寺",
"5800": "詩", "5802": "試", "5808": "資", "580E": "飼", "5812": "事", "5814": "似",
"5816": "侍", "5818": "児", "581A": "字", "581C": "寺", "5900": "持", "5902": "時",
"5904": "次", "5908": "治", "5912": "示", "5916": "耳", "5918": "自", "591C": "辞",
"5A02": "式", "5A04": "識", "5A0E": "雫", "5A10": "七", "5A12": "叱", "5A14": "執",
"5A16": "失", "5A1A": "室", "5B04": "質", "5B06": "実", "5B18": "舎", "5B1A": "写",
"5B1E": "捨", "5C04": "煮", "5C06": "社", "5C0A": "者", "5C0C": "謝", "5C0E": "車",
"5C14": "邪", "5C16": "借", "5C1A": "尺", "5D08": "若", "5D0A": "寂", "5D0C": "弱",
"5D0E": "惹", "5D10": "主", "5D12": "取", "5D14": "守", "5D16": "手", "5D1A": "殊",
"5D1C": "狩", "5E00": "種", "5E04": "趣", "5E06": "酒", "5E08": "首", "5E0C": "受",
"5E0E": "呪", "5E12": "授", "5E1A": "囚", "5E1C": "収", "5E1E": "周", "5F06": "修",
"5F0A": "拾", "5F0E": "秀", "5F12": "終", "5F16": "習", "5F18": "臭", "6000": "襲",
"6008": "週", "600E": "集", "6014": "住", "6018": "十", "601A": "従", "601E": "柔",
"6100": "汁", "6104": "獣", "6108": "重", "610A": "銃",

# --- batch 0800 ---
"6110": "宿", "6114": "祝", "6116": "縮", "611C": "熟", "611E": "出", "6200": "術",
"6208": "春", "620A": "瞬", "621E": "準", "6304": "純", "6306": "巡", "630E": "処",
"6310": "初", "6312": "所", "6314": "暑", "631C": "緒", "6400": "書", "6408": "助",
"640C": "女", "640E": "序", "6418": "傷", "641C": "勝", "641E": "匠", "6506": "商",
"6512": "宵", "6514": "将", "6516": "小", "6518": "少", "651E": "床", "6604": "承",
"6614": "晶", "6700": "消", "6706": "焼", "6708": "焦", "670A": "照", "670E": "省",
"671A": "笑", "671E": "紹", "6808": "衝", "680E": "証", "6812": "詳", "6814": "象",
"6818": "醤", "6900": "障", "6902": "鞘", "6904": "上", "6906": "丈", "690A": "乗",
"690C": "冗", "6912": "場", "6916": "嬢", "6918": "常", "691A": "情", "691E": "桑",
"6A00": "杖", "6A04": "状", "6A0C": "譲", "6A16": "飾", "6A18": "拭", "6A1C": "殖",
"6B00": "織", "6B02": "職", "6B04": "色", "6B06": "触", "6B08": "食", "6B0E": "尻",
"6B10": "伸", "6B12": "信", "6B14": "侵", "6B16": "唇", "6B1A": "寝", "6B1C": "審",
"6B1E": "心", "6C00": "慎", "6C02": "振", "6C04": "新", "6C08": "森", "6C0C": "浸",
"6C0E": "深", "6C10": "申", "6C14": "真", "6C16": "神", "6C1E": "芯", "6D00": "薪",
"6D02": "親", "6D06": "身", "6D08": "辛", "6D0A": "進", "6D0E": "震", "6D10": "人",
"6D16": "塵", "6D1E": "尽", "6E12": "図", "6E14": "厨", "6E18": "吹", "6E1E": "推",
"6F00": "水", "6F02": "炊", "6F04": "睡", "6F06": "粋",

# --- batch 0900 ---
"6F0A": "衰", "6F0C": "遂", "6F0E": "酔", "6F14": "随", "6F16": "瑞", "6F1A": "崇",
"6F1E": "数", "7010": "雀", "7014": "澄", "701A": "世", "701C": "瀬", "7100": "是",
"7102": "凄", "7104": "制", "7106": "勢", "710C": "性", "710E": "成", "7112": "整",
"7114": "星", "7116": "晴", "711C": "正", "711E": "清", "7200": "牲", "7202": "生",
"7204": "盛", "7206": "精", "7208": "聖", "720A": "声", "720C": "製", "7212": "誓",
"7214": "諸", "721A": "青", "721C": "静", "7306": "席", "7308": "惜", "730E": "昔",
"7312": "石", "7314": "積", "7318": "績", "731C": "責", "731E": "赤", "7400": "跡",
"7406": "切", "740A": "接", "740E": "折", "7414": "節", "7416": "説", "7418": "雪",
"741A": "絶", "7502": "先", "7504": "千", "7508": "宣", "750A": "専", "750E": "川",
"7510": "戦", "7512": "扇", "751A": "泉", "751C": "浅", "751E": "洗", "7600": "染",
"760E": "線", "7610": "繊", "761C": "詮", "7700": "践", "7702": "選", "7706": "銭",
"770A": "閃", "770C": "鮮", "770E": "前", "7710": "善", "7714": "然", "7716": "全",
"7800": "喘", "780C": "楚", "780E": "狙", "7816": "祖", "781C": "素", "781E": "組",
"790E": "双", "7914": "喪", "7918": "葬", "791A": "爽", "791E": "層", "7A04": "想",
"7A06": "捜", "7A0E": "操", "7A10": "早", "7A1A": "漕", "7A1E": "争", "7B02": "相",
"7B04": "窓", "7B0E": "草", "7B18": "装", "7B1A": "走", "7B1C": "送", "7B1E": "遭",
"7C04": "騒", "7C06": "像", "7C08": "増", "7C0C": "臓",

# --- batch 1000 ---
"7C12": "造", "7C14": "促", "7C16": "側", "7C18": "則", "7C1A": "即", "7C1C": "息",
"7D00": "束", "7D04": "足", "7D06": "速", "7D08": "俗", "7D0A": "属", "7D0E": "族",
"7D10": "続", "7D12": "卒", "7D14": "袖", "7D18": "揃", "7D1A": "存", "7D1E": "尊",
"7E00": "損", "7E02": "村", "7E06": "他", "7E08": "多", "7E0A": "太", "7E12": "堕",
"7E18": "打", "7F02": "駄", "7F06": "体", "7F0A": "対", "7F0C": "耐", "7F10": "帯",
"7F12": "待", "7F16": "態", "7F18": "戴", "7F1A": "替", "7F1E": "滞", "8008": "貸",
"800A": "退", "800E": "隊", "8014": "代", "8016": "台", "8018": "大", "801A": "第",
"801C": "醒", "801E": "題", "8100": "鷹", "810E": "択", "8112": "沢", "8208": "叩",
"820C": "達", "8210": "奪", "8212": "脱", "8304": "誰", "8306": "丹", "8308": "単",
"830E": "担", "8310": "探", "8312": "旦", "831C": "短", "831E": "端", "8406": "胆",
"840A": "誕", "840C": "鍛", "840E": "団", "8412": "弾", "8414": "断", "841A": "段",
"841C": "男", "841E": "談", "8502": "知", "8504": "地", "8508": "恥", "850E": "痴",
"8512": "置", "8518": "遅", "851A": "馳", "8608": "秩", "860C": "茶", "860E": "嫡",
"8610": "着", "8612": "中", "8614": "仲", "861A": "抽", "861C": "昼", "861E": "柱",
"8700": "注", "8702": "虫", "871A": "丁", "8806": "帳", "880C": "張", "8810": "徴",
"8814": "挑", "8818": "朝", "881E": "町", "8900": "眺", "8902": "聴", "8908": "蝶",
"890A": "調", "890E": "超", "8914": "長", "8916": "頂",

# --- batch 1100 ---
"8918": "鳥", "891E": "直", "8A02": "沈", "8A04": "珍", "8A12": "槌", "8A14": "追",
"8A18": "痛", "8A1A": "通", "8B06": "漬", "8B14": "潰", "8C02": "釣", "8C04": "鶴",
"8C08": "低", "8C0A": "停", "8C0C": "値", "8C16": "定", "8C1A": "底", "8C1C": "庭",
"8D00": "弟", "8D08": "提", "8D12": "程", "8D14": "締", "8D1A": "諦", "8E08": "泥",
"8E0E": "敵", "8E12": "的", "8E16": "適", "8E1E": "徹", "8F06": "鉄", "8F08": "典",
"8F0C": "天", "8F0E": "展", "8F10": "店", "8F12": "添", "8F1A": "転", "8F1E": "点",
"9000": "伝", "9002": "殿", "9006": "田", "9008": "電", "900C": "吐", "9016": "徒",
"901C": "渡", "901E": "登", "9102": "賭", "9104": "途", "9106": "都", "910E": "努",
"9110": "度", "9112": "土", "9114": "奴", "9116": "怒", "9118": "倒", "911A": "党",
"911C": "冬", "911E": "凍", "9200": "刀", "9202": "唐", "920C": "島", "9212": "投",
"9216": "東", "921E": "盗", "9302": "湯", "9306": "灯", "930A": "当", "9310": "等",
"9312": "答", "9316": "糖", "9318": "統", "9400": "藤", "9402": "討", "9406": "豆",
"940A": "逃", "940B": "踏", "9412": "頭", "9416": "闘", "9418": "働", "941A": "動",
"941C": "同", "941E": "堂", "9500": "導", "9502": "憧", "9506": "洞", "9508": "瞳",
"9510": "道", "9512": "銅", "951A": "得", "9600": "特", "9608": "毒", "960A": "独",
"960C": "読", "9614": "突", "9618": "届", "9716": "曇", "9718": "鈍", "971C": "那",
"971E": "内", "9804": "薙", "9806": "謎", "980C": "鍋",

# --- batch 1200 ---
"9810": "馴", "9816": "南", "981C": "難", "981E": "汝", "9900": "二", "9908": "匂",
"990A": "賑", "990C": "肉", "9912": "日", "9916": "入", "991E": "任", "9A02": "忍",
"9A04": "認", "9A06": "濡", "9A0C": "寧", "9A10": "猫", "9A12": "熱", "9A14": "年",
"9A16": "念", "9A18": "捻", "9B00": "乃", "9B04": "之", "9B0A": "悩", "9B0E": "納",
"9B10": "能", "9B12": "脳", "9B18": "覗", "9C02": "覇", "9C06": "波", "9C08": "派",
"9C0C": "破", "9C14": "馬", "9C1E": "敗", "9D00": "杯", "9D06": "背", "9D08": "肺",
"9D0A": "輩", "9D0C": "配", "9D0E": "倍", "9D1C": "買", "9D1E": "売", "9E12": "博",
"9E14": "拍", "9E18": "泊", "9E1A": "白", "9F02": "薄", "9F04": "迫", "9F0A": "爆",
"9F0C": "縛", "9F16": "箱", "A004": "肌", "A00A": "八", "A010": "発", "A014": "髪",
"A01A": "抜", "A01E": "閥", "A100": "鳩", "A102": "嘴", "A10C": "判", "A10E": "半",
"A110": "反", "A11A": "板", "A202": "犯", "A208": "繁", "A20A": "般", "A20C": "藩",
"A20E": "販", "A210": "範", "A218": "飯", "A21C": "晩", "A21E": "番", "A30A": "卑",
"A30C": "否", "A312": "被", "A314": "悲", "A316": "扉", "A31C": "斐", "A31E": "比",
"A402": "疲", "A404": "皮", "A408": "秘", "A414": "費", "A418": "非", "A41A": "飛",
"A500": "備", "A502": "尾", "A504": "微", "A50E": "美", "A510": "鼻", "A51E": "膝",
"A606": "必", "A610": "姫", "A614": "紐", "A616": "百", "A61E": "標", "A700": "氷",
"A702": "漂", "A708": "表", "A70A": "評", "A710": "描",

# --- batch 1300 ---
"A712": "病", "A714": "秒", "A802": "品", "A808": "浜", "A80C": "貧", "A812": "敏",
"A814": "瓶", "A816": "不", "A818": "付", "A81C": "夫", "A81E": "婦", "A904": "布",
"A908": "怖", "A90C": "敷", "A910": "普", "A912": "浮", "A914": "父", "A918": "腐",
"AA00": "負", "AA0E": "武", "AA10": "舞", "AA16": "部", "AA18": "封", "AA1C": "風",
"AB04": "副", "AB06": "復", "AB08": "幅", "AB0A": "服", "AB0C": "福", "AB0E": "腹",
"AB10": "複", "AB18": "払", "AB1E": "物", "AC02": "分", "AC04": "吻", "AC10": "奮",
"AC18": "雰", "AC1A": "文", "AC1C": "閉", "AD02": "兵", "AD08": "平", "AD0C": "柄",
"AD0E": "並", "AD1C": "壁", "AD1E": "癖", "AE02": "別", "AE0C": "変", "AE0E": "片",
"AE12": "編", "AE14": "辺", "AE16": "返", "AE1A": "便", "AE1C": "勉", "AF00": "弁",
"AF04": "保", "AF0C": "捕", "AF0E": "歩", "AF12": "補", "AF16": "穂", "AF1C": "慕",
"B000": "募", "B002": "母", "B004": "簿", "B00C": "包", "B00E": "呆", "B010": "報",
"B014": "宝", "B01A": "崩", "B01E": "抱", "B100": "捧", "B102": "放", "B104": "方",
"B108": "法", "B10E": "砲", "B11A": "蜂", "B11E": "訪", "B200": "豊", "B206": "飽",
"B208": "鳳", "B20C": "乏", "B20E": "亡", "B214": "坊", "B216": "妨", "B218": "帽",
"B21A": "忘", "B21C": "忙", "B21E": "房", "B300": "暴", "B302": "望", "B306": "棒",
"B310": "謀", "B318": "防", "B31A": "吠", "B31C": "頬", "B31E": "北", "B400": "僕",
"B418": "堀", "B41E": "本", "B504": "盆",

# --- batch 1400 ---
"B508": "磨", "B50A": "魔", "B50C": "麻", "B50E": "埋", "B510": "妹", "B514": "枚",
"B516": "毎", "B51C": "幕", "B600": "枕", "B612": "末", "B61E": "万", "B700": "慢",
"B702": "満", "B708": "味", "B70A": "未", "B70C": "魅", "B70E": "巳", "B714": "密",
"B716": "蜜", "B800": "妙", "B804": "民", "B806": "眠", "B808": "務", "B80A": "夢",
"B80C": "無", "B812": "霧", "B818": "婿", "B81A": "娘", "B81C": "冥", "B81E": "名",
"B900": "命", "B902": "明", "B906": "迷", "B908": "銘", "B90A": "鳴", "B910": "滅",
"B912": "免", "B91A": "面", "BA00": "摸", "BA08": "毛", "BA0A": "猛", "BA0C": "盲",
"BA0E": "網", "BA16": "木", "BA18": "黙", "BA1A": "目", "BB00": "餅", "BB04": "戻",
"BB0A": "問", "BB10": "門", "BB18": "夜", "BB1E": "野", "BC02": "矢", "BC04": "厄",
"BC06": "役", "BC08": "約", "BC0A": "薬", "BC0C": "訳", "BC0E": "躍", "BC12": "柳",
"BC18": "愉", "BC1C": "油", "BC1E": "癒", "BD04": "唯", "BD08": "優", "BD0A": "勇",
"BD0C": "友", "BD10": "幽", "BD12": "悠", "BD18": "有", "BD1C": "湧", "BE04": "由",
"BE08": "裕", "BE0A": "誘", "BE0C": "遊", "BE16": "夕", "BE18": "予", "BE1A": "余",
"BE1C": "与", "BE1E": "誉", "BF06": "幼", "BF08": "妖", "BF0A": "容", "BF0E": "揚",
"BF10": "揺", "BF14": "曜", "BF18": "様", "C000": "用", "C008": "葉", "C00C": "要",
"C010": "踊", "C014": "陽", "C016": "養", "C01A": "抑", "C01C": "欲", "C100": "浴",
"C102": "翌", "C10E": "来", "C112": "頼", "C114": "雷",

# --- batch 1500 (last, 91 codes) ---
"C118": "絡", "C11A": "落", "C11E": "乱", "C20C": "覧", "C20E": "利", "C218": "理",
"C21E": "裏", "C304": "離", "C30C": "立", "C312": "略", "C316": "流", "C31A": "琉",
"C31C": "留", "C404": "竜", "C40A": "慮", "C40C": "旅", "C410": "了", "C416": "両",
"C41C": "料", "C500": "涼", "C50C": "良", "C512": "量", "C516": "領", "C518": "力",
"C51A": "緑", "C602": "淋", "C608": "臨", "C60A": "輪", "C60C": "隣", "C616": "涙",
"C61A": "類", "C61C": "令", "C700": "例", "C702": "冷", "C704": "励", "C70C": "礼",
"C716": "霊", "C718": "麗", "C71A": "齢", "C71E": "歴", "C800": "列", "C804": "烈",
"C80A": "恋", "C814": "練", "C81A": "連", "C81C": "錬", "C81E": "呂", "C908": "路",
"C90A": "露", "C90C": "労", "C91A": "浪", "CA00": "狼", "CA0A": "郎", "CA0C": "六",
"CA10": "禄", "CA14": "録", "CA1A": "和", "CA1C": "話", "CB02": "脇", "CB04": "惑",
"CB1C": "腕", "CB1E": "丼", "CC06": "凛", "CC08": "凰", "CC0A": "刹", "CC12": "咎",
"CD04": "巫", "CD06": "悴", "CD0A": "愕", "CD1C": "朦", "CD1E": "朧", "CE08": "渾",
"CE10": "爛", "CE14": "璧", "CE16": "瓊", "CE1C": "眩", "CF00": "祟", "CF02": "祓",
"CF04": "穢", "CF08": "絆", "CF0C": "罠", "CF10": "翔", "CF14": "裔", "CF18": "賽",
"CF1C": "踪", "D002": "騙",
}

# Ground-truth cross-check against /tmp/orig_unpack (pristine ROM) dialogue
# text showed the small/big-kana member of several vowel/glide pairs were
# transcribed backwards (e.g. "いま" decoded as "ぃま", "ちょっと" as "ちよっと",
# "アテナ" as "ァテナ") - this font's bank/low layout mirrors real JIS X0208
# codepoint order, where the SMALL kana always has the lower codepoint
# (compare kana pairs い/ぃ,や/ゃ vs. real JIS 3043/3044, 3083/3084). These
# pairs were read with the labels swapped; つ/っ and katakana ャ/ュ/ョ were
# already correctly small-first and are left untouched.
SWAP_PAIRS = [
    ("0814", "0816"),  # い / ぃ
    ("0818", "081A"),  # う / ぅ
    ("081C", "081E"),  # え / ぇ
    ("0900", "0902"),  # お / ぉ
    ("0C14", "0C16"),  # や / ゃ
    ("0C18", "0C1A"),  # ゆ / ゅ
    ("0C1C", "0C1E"),  # よ / ょ
    ("0D10", "0D12"),  # ア / ァ
    ("0D14", "0D16"),  # イ / ィ
    ("0D18", "0D1A"),  # ウ / ゥ
    ("0D1C", "0D1E"),  # エ / ェ
    ("0E00", "0E02"),  # オ / ォ
    ("0F14", "0F16"),  # ツ / ッ
]
for a, b in SWAP_PAIRS:
    FULL_CHARS[a], FULL_CHARS[b] = FULL_CHARS[b], FULL_CHARS[a]

# codes explicitly proven blank (rendered no ink) - mark kind 'blank', no char
BLANK_CODES = {"020A"}

# 2026-08-06: 0x485C ("糠") removed from FULL_CHARS. Corpus-wide context scan
# shows it is not printed text: it ends ~98.5% of all dialogue blocks
# (17498/17760) and, mid-block, is immediately followed by the 0x6E5C
# newline code 75% of the time (2002/2661) - the signature of a page-break/
# wait-for-input marker reusing a spare font tile as a sentinel, the same
# trick the 0x6E5C 0x6E5C 0x0000 terminator uses. The tile itself does
# render as 糠 (confirmed by visual transcription), but the game's text
# engine never draws it - it intercepts the code as control. Left with no
# 'char' key so it falls back to the safe <485C> hex placeholder.

# 2026-08-06: full_code_tile_map.json regenerated by rerunning
# temp/scan_all_codes_v8.py (find_dialogue_blocks() v8 + unpack_origin) after
# the boundary-detection fix - the OLD full_code_tile_map.json was built
# before that fix and only ever saw content inside the narrower/buggy block
# boundaries, so any code that happened to sit at the very start of a box
# under v8 but was absent from that older, incomplete scan was invisible to
# CODES (kind=None). find_dialogue_blocks() requires kind=='full' to mark
# content-start, so such a code was silently excluded from the block and
# miscounted as part of the variable header instead - this is how the user
# caught it: 0x412 sat right before "ピンポ~ン" and looked like a speaker-ID
# header value, but it's actually a leading "!" (music note, confirmed via
# tile render at real_tile=274 - visually a clean 8th-note glyph) that
# should have been the first character of the block. Rescanning roughly
# doubled the code universe (1612 -> 3514 unique codes, full: 1591 -> 3387),
# recovering many more real leading glyphs the same way. See
# [[project_dom_hangulization]] for the speaker-ID investigation this bug
# was found during. (0x412 -> "♪" added to FULL_CHARS above.)


def build():
    codes_out = {}
    kind_counts = {}
    for k, v in FULL_MAP.items():
        khex = k[2:].upper() if k.lower().startswith("0x") else k.upper()
        kind = v.get("kind")
        entry = {"kind": kind}
        if "count" in v:
            entry["count"] = v["count"]
        if "real_tile" in v:
            entry["real_tile"] = v["real_tile"]

        if khex in BLANK_CODES:
            entry["kind"] = "blank"
        elif kind == "full":
            ch = FULL_CHARS.get(khex)
            if ch is not None:
                entry["char"] = ch
        elif kind == "half":
            old_entry = HALF_CHARS.get(khex)
            if old_entry:
                if "char" in old_entry:
                    entry["char"] = old_entry["char"]
                if "note" in old_entry:
                    entry["note"] = old_entry["note"]

        codes_out[khex] = entry
        kind_counts[entry["kind"]] = kind_counts.get(entry["kind"], 0) + 1

    for khex, ch in MANUAL_FULL_CODES.items():
        if khex not in codes_out:
            codes_out[khex] = {"kind": "full", "char": ch}
            kind_counts["full"] = kind_counts.get("full", 0) + 1

    full_total = sum(1 for k, v in codes_out.items() if v["kind"] == "full")
    full_labeled = sum(1 for k, v in codes_out.items() if v["kind"] == "full" and "char" in v)

    new_map = {
        "formula": OLD["formula"],
        "stats": {
            "total_distinct_codes": len(codes_out),
            "kind_counts": kind_counts,
            "full_width_total": full_total,
            "full_width_labeled": full_labeled,
            "full_width_unlabeled": full_total - full_labeled,
        },
        "codes": codes_out,
    }

    out_path = os.path.join(HERE, "font_map_full.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(new_map, f, ensure_ascii=False, indent=1)

    print(f"wrote {out_path}")
    print("kind counts:", kind_counts)
    print(f"full-width: {full_labeled}/{full_total} labeled ({full_total - full_labeled} left as <HEX> fallback)")


if __name__ == "__main__":
    build()
