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
    if n == 30:
        return 10, 3
    if n == 289:
        return 17, 17
    if n == 768:
        return 32, 24
    if n == 960:
        return 32, 30
    if n == 1024:
        return 32, 32
    return 32, -(-n // 32)  # ceil division


def render_tilemap(tiles, palette, entries, map_w, map_h):
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


def decode_tilemap_png(nbfc_buf, nbfp_buf, nbfs_buf, map_w=None):
    """map_w overrides tilemap_dims()'s guess (NDS-hardware-BG's standard
    32-tile row width) for small standalone UI graphics that were never an
    actual hardware background and so aren't bound by that convention - e.g.
    infodom*/eplace_NN name-tag banners, confirmed 2026-09-02 to be 10 tiles
    wide (real Japanese place-name text only forms correctly at that width,
    see files.py's KNOWN_WIDTH_OVERRIDES and ANALYSIS_NOTES.md)."""
    tiles = load_tiles(nbfc_buf)
    palette = load_palette(nbfp_buf)
    entries = load_screen(nbfs_buf)
    if map_w is not None:
        map_h = -(-len(entries) // map_w)
    else:
        map_w, map_h = tilemap_dims(len(entries))
    return render_tilemap(tiles, palette, entries, map_w, map_h)


def decode_tile_grid_png(nbfc_buf, nbfp_buf, map_w=32, segments=None):
    """Reference-only preview for tile sheets with no paired screenmap (OAM
    sprite fragments like infobarobj.nbfcn/map*move*_obj.nbfcn - digit/name
    tag pieces the game assembles at runtime, not a fixed tilemap). Renders
    tiles as a plain sequential raster at the NDS-standard 32-tile row width,
    the same on-disk row width Font_DOM.nbfc's glyphs use
    (apply_font_art.py's [t, t+1, t+32, t+33] 2x2 footprint) - confirmed
    visually legible (digits/name-tag text readable) for infobarobj/
    map1moveobj/map1move_nameon_obj on 2026-09-02, see ANALYSIS_NOTES.md.
    Actual in-game placement of these fragments is still unknown, so this is
    for reference/inspection only - not pixel-accurate, and not meant to
    round-trip (no encode counterpart).

    segments: optional list of rows, each row either:
    - a plain (start_tile, end_tile, width) tuple, or
    - ("hstack", [(start_tile, end_tile, width), ...]) to render several
      sub-ranges independently (each at its own width) and place them SIDE
      BY SIDE (top-aligned) into a single combined piece for this row -
      e.g. titleobj's tiles[0:56] (its speech-bubble text, width 8) and
      tiles[64:84] (a second width-4 chunk) are not a separate box stacked
      below - hstack-ing them reveals they're the missing right half of the
      SAME two text lines ("タイトルを" / "選んでね。", the bubble's own
      right border completing on the second piece) and closes the bubble
      that otherwise looked "cut off" on the right, 2026-09-02.

    Rows exist because some files splice together multiple differently-
    arranged sprite sheets with no single width/layout that renders the
    whole file cleanly (e.g. infobarobj: a digit font 0-9 at width 2 in
    tiles[0:80], then weekday badges 月火水木金土日 at width 4 in
    tiles[80:136], confirmed 2026-09-02, see ANALYSIS_NOTES.md). Rows stack
    vertically with a default 8px gap between them (narrower rows
    horizontally centered on a canvas as wide as the widest one -
    left-aligning them reads as the narrower piece being shoved to one
    side, confirmed visually confusing 2026-09-02).

    A plain tuple may optionally carry a 4th value, pad_bottom_px (extra
    blank pixels appended to the bottom of that row's render, before the
    inter-row gap - e.g. matching a shorter row's total height to a taller
    one that includes a tail/decoration of its own) and a 5th,
    gap_after_px (overrides the default 8px gap that follows that row - 0
    butts the next row right up against it when they read as one continuous
    element, while the default gap still separates an unrelated row like a
    separate icon). An ("hstack", ...) row does not itself take these -
    wrap it as a 3rd/4th list element instead: ("hstack", [...],
    pad_bottom_px, gap_after_px)."""
    tiles = load_tiles(nbfc_buf)
    palette = load_palette(nbfp_buf)
    if segments:
        DEFAULT_GAP = 8

        def render_range(start, end, w):
            sub = tiles[start:end]
            entries = list(range(len(sub)))
            h = -(-len(sub) // w)
            png = render_tilemap(sub, palette, entries, w, h)
            return Image.open(io.BytesIO(png))

        pieces = []
        gaps_after = []
        for row in segments:
            if row[0] == "hstack":
                sub_ranges = row[1]
                pad_bottom = row[2] if len(row) > 2 else 0
                gap_after = row[3] if len(row) > 3 else DEFAULT_GAP
                sub_pieces = [render_range(*r) for r in sub_ranges]
                piece_w = sum(im.width for im in sub_pieces)
                piece_h = max(im.height for im in sub_pieces)
                piece = Image.new("RGBA", (piece_w, piece_h))
                x = 0
                for im in sub_pieces:
                    piece.paste(im, (x, 0))
                    x += im.width
            else:
                start, end, w = row[0], row[1], row[2]
                pad_bottom = row[3] if len(row) > 3 else 0
                gap_after = row[4] if len(row) > 4 else DEFAULT_GAP
                piece = render_range(start, end, w)
            if pad_bottom:
                padded = Image.new("RGBA", (piece.width, piece.height + pad_bottom))
                padded.paste(piece, (0, 0))
                piece = padded
            pieces.append(piece)
            gaps_after.append(gap_after)
        canvas_w = max(im.width for im in pieces)
        canvas_h = sum(im.height for im in pieces) + sum(gaps_after[:-1])
        canvas = Image.new("RGBA", (canvas_w, canvas_h))
        y = 0
        for i, im in enumerate(pieces):
            x = (canvas_w - im.width) // 2
            canvas.paste(im, (x, y))
            y += im.height
            if i < len(pieces) - 1:
                y += gaps_after[i]
        out = io.BytesIO()
        canvas.save(out, format="PNG")
        return out.getvalue()
    n = len(tiles)
    entries = list(range(n))
    map_h = -(-n // map_w)
    return render_tilemap(tiles, palette, entries, map_w, map_h)


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
    not regenerated) with tile deduplication so decompressed tile data fits
    within NDS BG character VRAM blocks (preventing VRAM buffer overflow)."""
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
    tiles = []
    tile_dict = {}
    screen = bytearray(n * 2)

    for i in range(n):
        tx = i % map_w
        ty = i // map_w
        tile_bytes = bytearray(64)
        for py in range(8):
            for pcol in range(8):
                r, g, b = px[tx * 8 + pcol, ty * 8 + py][:3]
                tile_bytes[py * 8 + pcol] = nearest_palette_index(r, g, b, palette)

        t_key = bytes(tile_bytes)
        if t_key not in tile_dict:
            tile_dict[t_key] = len(tiles)
            tiles.append(t_key)

        tile_idx = tile_dict[t_key]
        screen[i * 2] = tile_idx & 0xFF
        screen[i * 2 + 1] = (tile_idx >> 8) & 0xFF

    raw_tiles = b"".join(tiles)
    return {"nbfc": lz10.compress(raw_tiles), "nbfs": lz10.compress(bytes(screen))}
