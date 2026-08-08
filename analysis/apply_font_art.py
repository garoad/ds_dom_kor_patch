#!/usr/bin/env python3
"""
temp/apply_font_art.py  —  ★ 확정 한글 폰트 렌더링 스크립트 ★

Days of Memories (NDS) 한글화용 Font_DOM.nbfc 한글 글리프 렌더러.
Galmuri11.bdf에서 픽셀-퍼펙트 비트맵을 직접 읽어 Font_DOM.nbfc의 타일에 기록한다.

Key design decisions (see ANALYSIS_NOTES.md for rationale):
  - BDF (Bitmap Distribution Format) 직접 파싱: TTF 래스터라이즈는 작은 사이즈에서
    뭉개짐/안티앨리어싱 아티팩트를 만들어 v3~v12까지 전부 실패했음.
    BDF는 폰트 디자이너의 원본 비트맵 그대로이므로 래스터라이즈 과정 자체가 없음.
  - 원본 지오메트리 실측: pristine Font_DOM.nbfc의 일본어 히라가나/한자 글리프를 직접
    측정하여 잉크 영역 x:0..10, y:2..12 (11×11px), 잉크 인덱스 15만 사용을 확인.

Usage:
    cd /path/to/ds_dom_kor_patch
    .venv/bin/python3 analysis/apply_font_art.py

Inputs:
    - temp/fonts/Galmuri11.bdf          (BDF 비트맵 폰트, 한글 11,172자 수록)
    - unpack_origin/data/Font_DOM.nbfc  (pristine 원본, 매 실행마다 여기서 리셋)
    - analysis/font_map_full.json       (한글 코드 매핑)

Output:
    - unpack/data/Font_DOM.nbfc         (한글 글리프가 기록된 폰트 파일)
"""

import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
UNPACK_ORIGIN_NBFC = os.path.join(PROJECT_ROOT, "unpack_origin", "data", "Font_DOM.nbfc")
UNPACK_NBFC = os.path.join(PROJECT_ROOT, "unpack", "data", "Font_DOM.nbfc")
FONT_MAP_PATH = os.path.join(HERE, "font_map_kr.json")
BDF_PATH = os.path.join(HERE, "fonts", "Galmuri11.bdf")

# ── Measured from original Japanese glyphs in pristine Font_DOM.nbfc ──
GLYPH_X_MIN = 0
GLYPH_X_MAX = 10
GLYPH_Y_MIN = 2
GLYPH_Y_MAX = 12
GLYPH_W = GLYPH_X_MAX - GLYPH_X_MIN + 1  # 11
GLYPH_H = GLYPH_Y_MAX - GLYPH_Y_MIN + 1  # 11
INK_INDEX = 15


def parse_bdf(path):
    """Parse a BDF font file into a dict: codepoint -> {'bbx': (w,h,xoff,yoff), 'bitmap': [...]}"""
    glyphs = {}
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    i = 0
    encoding = None
    bbx = None
    bitmap = []
    in_bitmap = False

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('ENCODING '):
            encoding = int(line.split()[1])
        elif line.startswith('BBX '):
            parts = line.split()
            bbx = (int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]))
        elif line == 'BITMAP':
            in_bitmap = True
            bitmap = []
        elif line == 'ENDCHAR':
            if encoding is not None and bbx is not None:
                glyphs[encoding] = {'bbx': bbx, 'bitmap': bitmap}
            encoding = None
            bbx = None
            bitmap = []
            in_bitmap = False
        elif in_bitmap:
            bitmap.append(line)
        i += 1

    return glyphs


def bdf_glyph_to_pixel_grid(glyph_data):
    """Convert a BDF glyph into a list of (x, y) pixel coordinates (relative to glyph origin)."""
    w, h, xoff, yoff = glyph_data['bbx']
    pixels = []
    for row_idx, hex_str in enumerate(glyph_data['bitmap']):
        val = int(hex_str, 16)
        # BDF stores bits MSB-first, padded to byte boundary
        num_bits = len(hex_str) * 4
        for col in range(w):
            bit_pos = num_bits - 1 - col
            if (val >> bit_pos) & 1:
                pixels.append((col, row_idx))
    return pixels, w, h


def render_glyph_16x16(ch, bdf_glyphs):
    """Render a Korean character into a 16×16 grid using pixel-perfect BDF bitmap data,
    centred within the measured original art area (x:0..10, y:2..12)."""
    
    grid = [[0] * 16 for _ in range(16)]
    
    cp = ord(ch)
    if cp not in bdf_glyphs:
        return grid
    
    glyph = bdf_glyphs[cp]
    pixels, gw, gh = bdf_glyph_to_pixel_grid(glyph)
    
    if not pixels:
        return grid
    
    # Centre horizontally within the 11px canvas
    paste_x = GLYPH_X_MIN + (GLYPH_W - gw) // 2
    if paste_x < GLYPH_X_MIN:
        paste_x = GLYPH_X_MIN
    if paste_x + gw > GLYPH_X_MAX + 1:
        paste_x = GLYPH_X_MAX + 1 - gw
    
    # Align at bottom of the 11px vertical canvas
    paste_y = GLYPH_Y_MAX + 1 - gh
    if paste_y < GLYPH_Y_MIN:
        paste_y = GLYPH_Y_MIN
    
    for px, py in pixels:
        tx = paste_x + px
        ty = paste_y + py
        if GLYPH_X_MIN <= tx <= GLYPH_X_MAX and GLYPH_Y_MIN <= ty <= GLYPH_Y_MAX:
            grid[ty][tx] = INK_INDEX
    
    return grid


def glyph_to_4_tiles(grid):
    tiles = []
    for sub_y in range(2):
        for sub_x in range(2):
            tile_bytes = bytearray(64)
            for y in range(8):
                for x in range(8):
                    tile_bytes[y * 8 + x] = grid[sub_y * 8 + y][sub_x * 8 + x]
            tiles.append(bytes(tile_bytes))
    return tiles


def main():
    assert os.path.exists(UNPACK_ORIGIN_NBFC), f"Missing pristine origin: {UNPACK_ORIGIN_NBFC}"
    assert os.path.exists(BDF_PATH), f"Missing BDF font: {BDF_PATH}"

    # Parse BDF font (pixel-perfect bitmap data, no rasterization needed)
    print(f"Parsing BDF font: {BDF_PATH}")
    bdf_glyphs = parse_bdf(BDF_PATH)
    kr_count = sum(1 for cp in bdf_glyphs if 0xAC00 <= cp <= 0xD7A3)
    print(f"  Total glyphs: {len(bdf_glyphs)}, Korean syllables: {kr_count}")

    # Always reset unpack/data/Font_DOM.nbfc from pristine unpack_origin
    shutil.copy2(UNPACK_ORIGIN_NBFC, UNPACK_NBFC)
    print(f"Reset {UNPACK_NBFC} from pristine origin")

    with open(UNPACK_NBFC, "rb") as f:
        nbfc = bytearray(f.read())
    orig_size = len(nbfc)

    with open(FONT_MAP_PATH, encoding="utf-8") as f:
        font_map = json.load(f)
    codes = font_map["codes"]

    # Re-render all mapped Hangul glyphs using BDF bitmap data
    count = 0
    missing = 0
    for k, v in codes.items():
        ch = v.get("char")
        if not ch or not ("가" <= ch <= "힣"):
            continue

        t_idx = v.get("real_tile")
        if t_idx is None:
            continue

        grid = render_glyph_16x16(ch, bdf_glyphs)
        sub_tiles = glyph_to_4_tiles(grid)

        fp = [t_idx, t_idx + 1, t_idx + 32, t_idx + 33]
        for sub_i, tile_id in enumerate(fp):
            nbfc[tile_id * 64 : (tile_id + 1) * 64] = b"\x00" * 64
            nbfc[tile_id * 64 : (tile_id + 1) * 64] = sub_tiles[sub_i]
        
        # Check if glyph was actually found in BDF
        if ord(ch) not in bdf_glyphs:
            missing += 1
        count += 1

    # Zero out space tiles
    for space_t in (10242, 390):
        nbfc[space_t * 64 : (space_t + 1) * 64] = b"\x00" * 64
        nbfc[(space_t + 1) * 64 : (space_t + 2) * 64] = b"\x00" * 64
        if space_t == 10242:
            nbfc[(space_t + 32) * 64 : (space_t + 33) * 64] = b"\x00" * 64
            nbfc[(space_t + 33) * 64 : (space_t + 34) * 64] = b"\x00" * 64

    assert len(nbfc) == orig_size, "File size must remain unchanged"

    with open(UNPACK_NBFC, "wb") as f:
        f.write(nbfc)
    print(f"Successfully rendered {count} Hangul glyphs ({missing} missing from BDF) into {UNPACK_NBFC}")


if __name__ == "__main__":
    main()
