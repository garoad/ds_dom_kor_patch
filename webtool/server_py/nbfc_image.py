"""
.nbfc(tile)+.nbfp(palette)+.nbfs(screenmap) triplet <-> PNG codec. Python port
of webtool/server/lib/nbfcImage.js - see that file's header comment for the
on-disk format (LZ10-compressed 8bpp tiles / RGB555 palette / u16 screenmap
entries), verified against real ROM data in
analysis/ANALYSIS_NOTES.md "그래픽 리소스 추출/삽입 검증".

Uses analysis/lz10.py directly (byte-identical LZ10 codec to lz10.js - no
separate JS reimplementation existed for this one, so nothing to reconcile).
"""
import io
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "analysis"))
if ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, ANALYSIS_DIR)

import lz10  # noqa: E402


def load_palette(buf):
    dec = lz10.decompress(buf)
    n = len(dec) // 2
    pal = []
    for i in range(n):
        v = dec[i * 2] | (dec[i * 2 + 1] << 8)
        pal.append((
            round(((v & 0x1F) * 255) / 31),
            round((((v >> 5) & 0x1F) * 255) / 31),
            round((((v >> 10) & 0x1F) * 255) / 31),
        ))
    return pal


def load_tiles(buf):
    dec = lz10.decompress(buf)
    n = len(dec) // 64
    return [dec[i * 64:i * 64 + 64] for i in range(n)]


def load_screen(buf):
    dec = lz10.decompress(buf)
    n = len(dec) // 2
    return [dec[i * 2] | (dec[i * 2 + 1] << 8) for i in range(n)]


def tilemap_dims(n):
    """Screenmap entry count -> tilemap width/height in tiles. Must match on
    both the decode and encode side for round-tripping."""
    if n == 289:
        return 17, 17
    if n == 768:
        return 32, 24
    if n == 960:
        return 32, 30
    if n == 1024:
        return 32, 32
    return 32, -(-n // 32)  # ceil division


def decode_tilemap_png(nbfc_buf, nbfp_buf, nbfs_buf):
    tiles = load_tiles(nbfc_buf)
    palette = load_palette(nbfp_buf)
    entries = load_screen(nbfs_buf)

    n = len(entries)
    map_w, map_h = tilemap_dims(n)

    img = Image.new("RGBA", (map_w * 8, map_h * 8))
    px = img.load()
    blank_tile = bytes(64)

    for i, e in enumerate(entries):
        tile_idx = e & 0x3FF
        hflip = (e >> 10) & 1
        vflip = (e >> 11) & 1
        tx = i % map_w
        ty = i // map_w
        tile = tiles[tile_idx] if tile_idx < len(tiles) else blank_tile
        for py in range(8):
            for pcol in range(8):
                sx = 7 - pcol if hflip else pcol
                sy = 7 - py if vflip else py
                color_idx = tile[sy * 8 + sx]
                rgb = palette[color_idx] if color_idx < len(palette) else (0, 0, 0)
                px[tx * 8 + pcol, ty * 8 + py] = (rgb[0], rgb[1], rgb[2], 255)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def nearest_palette_index(r, g, b, palette):
    best = 0
    best_dist = None
    for i, p in enumerate(palette):
        dr, dg, db = r - p[0], g - p[1], b - p[2]
        dist = dr * dr + dg * dg + db * db
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = i
            if dist == 0:
                break
    return best


def encode_tilemap_png(png_buf, nbfp_buf, orig_entry_count):
    """Re-encode a PNG into tile (.nbfc)+screenmap (.nbfs) compressed
    binaries. The palette is reused as-is (nearest-color matched per pixel,
    not regenerated) and the screenmap is emitted as a plain sequential index
    (no hflip/vflip, no tile dedup) - correctness over compactness, since
    NitroPacker's pack step tolerates variable-size files."""
    if orig_entry_count > 1024:
        raise ValueError(
            f"타일 개수({orig_entry_count})가 1024개를 초과해 인코딩할 수 없습니다 "
            "(스크린맵 타일 인덱스 필드는 10비트)"
        )
    palette = load_palette(nbfp_buf)
    map_w, map_h = tilemap_dims(orig_entry_count)
    expected_w, expected_h = map_w * 8, map_h * 8

    img = Image.open(io.BytesIO(png_buf)).convert("RGBA")
    if img.width != expected_w or img.height != expected_h:
        raise ValueError(
            f"이미지 크기가 원본과 다릅니다 (원본 {expected_w}x{expected_h}, "
            f"업로드 {img.width}x{img.height}) - 리팩은 원본과 정확히 같은 픽셀 크기만 지원합니다"
        )
    px = img.load()

    n = orig_entry_count
    tiles = bytearray(n * 64)
    screen = bytearray(n * 2)
    for i in range(n):
        tx = i % map_w
        ty = i // map_w
        tile_off = i * 64
        for py in range(8):
            for pcol in range(8):
                r, g, b = px[tx * 8 + pcol, ty * 8 + py][:3]
                tiles[tile_off + py * 8 + pcol] = nearest_palette_index(r, g, b, palette)
        screen[i * 2] = i & 0xFF
        screen[i * 2 + 1] = (i >> 8) & 0xFF

    return {"nbfc": lz10.compress(bytes(tiles)), "nbfs": lz10.compress(bytes(screen))}
