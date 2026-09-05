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


def detect_bpp(pal_buf):
    """Detect whether tiles paired with this palette are 4bpp or 8bpp.
    16-color palette (≤32 bytes decompressed) → 4bpp, else 8bpp.
    This is the reliable heuristic for NDS OBJ files whose palette size
    indicates how many bits index each pixel."""
    dec = lz10.decompress(pal_buf)
    return 4 if len(dec) <= 32 else 8


def load_tiles_4bpp(buf):
    """Decode LZ10-compressed 4bpp (16-color) tile data.
    Each 8×8 tile = 32 bytes (4 bits per pixel, two pixels per byte,
    low nibble = left pixel). Returns list of 64-byte expanded tiles
    (one byte per pixel, same indexing as 8bpp) for uniform rendering."""
    dec = lz10.decompress(buf)
    tiles = []
    for i in range(len(dec) // 32):
        tile = bytearray(64)
        for y in range(8):
            for x in range(4):
                b = dec[i * 32 + y * 4 + x]
                tile[y * 8 + x * 2] = b & 0x0F
                tile[y * 8 + x * 2 + 1] = (b >> 4) & 0x0F
        tiles.append(bytes(tile))
    return tiles


def encode_tiles_4bpp(tiles):
    """Pack a list of expanded 64-byte tiles back into 4bpp (32 bytes each)
    and LZ10-compress. Inverse of load_tiles_4bpp."""
    raw = bytearray()
    for tile in tiles:
        for y in range(8):
            for x in range(4):
                lo = tile[y * 8 + x * 2] & 0x0F
                hi = tile[y * 8 + x * 2 + 1] & 0x0F
                raw.append((hi << 4) | lo)
    return lz10.compress(bytes(raw))


def decode_tile_grid_4bpp_png(nbfc_buf, nbfp_buf, map_w=8, segments=None):
    """Like decode_tile_grid_png but for 4bpp tiles (auto-detected by the
    caller via detect_bpp). Palette index 0 → transparent, matching NDS OBJ
    convention.  Accepts the same ``segments`` parameter as the 8bpp variant
    for multi-row layouts (e.g. map*move nameplates: 48-tile cycles of
    big + small plate pairs)."""
    tiles = load_tiles_4bpp(nbfc_buf)
    palette = load_palette(nbfp_buf)

    def _render_range(start, end, w):
        sub = tiles[start:end]
        h = -(-len(sub) // w)
        img = Image.new("RGBA", (w * 8, h * 8))
        px = img.load()
        blank = bytes(64)
        for idx, tile in enumerate(sub):
            tx = idx % w
            ty = idx // w
            for py in range(8):
                for pcol in range(8):
                    cidx = tile[py * 8 + pcol]
                    if cidx == 0:
                        px[tx * 8 + pcol, ty * 8 + py] = (0, 0, 0, 0)
                    elif cidx < len(palette):
                        r, g, b = palette[cidx]
                        px[tx * 8 + pcol, ty * 8 + py] = (r, g, b, 255)
                    else:
                        px[tx * 8 + pcol, ty * 8 + py] = (0, 0, 0, 0)
        return img

    if segments:
        DEFAULT_GAP = 8
        pieces = []
        gaps_after = []
        for row in segments:
            if row[0] == "hstack":
                sub_ranges = row[1]
                pad_bottom = row[2] if len(row) > 2 else 0
                gap_after = row[3] if len(row) > 3 else DEFAULT_GAP
                sub_pieces = [_render_range(*r) for r in sub_ranges]
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
                piece = _render_range(start, end, w)
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

    img = _render_range(0, len(tiles), map_w)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def decode_nameplates_80x24(nbfc_buf, nbfp_buf, gap=8):
    """Decode map*move_name{on,off}_obj 4bpp OBJ nameplate files into a
    vertically stacked strip of complete 80x24 px (10x3 tiles) buttons.

    Hardware OAM layout per button (48 tiles total):
      - Chunk 1: 64x32 OAM sprite (tiles 0..31, 8x4 tiles). Top 64x24 px
        (tiles 0..23, 8x3) is the left portion of the button. Bottom 64x8 px
        (tiles 24..31) is transparent padding.
      - Chunk 2: 32x32 OAM sprite (tiles 32..47, 4x4 tiles). Top-left 16x24 px
        (tiles 32..47 cols 0..1, rows 0..2) is the right continuation + border.
        Remaining tiles are transparent padding.
      - Assembled button size: (64 + 16) x 24 = 80 x 24 px.
    """
    tiles = load_tiles_4bpp(nbfc_buf)
    pal = load_palette(nbfp_buf)
    n_tiles = len(tiles)
    n_plates = n_tiles // 48
    canvas_h = n_plates * 24 + (n_plates - 1) * gap
    img = Image.new("RGBA", (80, canvas_h), (0, 0, 0, 0))
    px = img.load()

    for p in range(n_plates):
        base = p * 48
        row_y = p * (24 + gap)
        # Left 64x24 px (tiles base + 0..23, 8 tiles wide)
        for ty in range(3):
            for tx in range(8):
                t = tiles[base + ty * 8 + tx]
                for py in range(8):
                    for px_x in range(8):
                        c = t[py * 8 + px_x]
                        if c != 0 and c < len(pal):
                            r, g, b = pal[c]
                            px[tx * 8 + px_x, row_y + ty * 8 + py] = (r, g, b, 255)
        # Right 16x24 px (tiles base + 32..47 at width 4, cols 0..1)
        for ty in range(3):
            for tx in range(2):
                t = tiles[base + 32 + ty * 4 + tx]
                for py in range(8):
                    for px_x in range(8):
                        c = t[py * 8 + px_x]
                        if c != 0 and c < len(pal):
                            r, g, b = pal[c]
                            px[64 + tx * 8 + px_x, row_y + ty * 8 + py] = (r, g, b, 255)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def pack_4bpp_nameplates(png_bytes, target_path, pal_path, gap=8):
    """Re-encode an 80x24 button strip PNG back into 4bpp OBJ nameplate tiles.
    Inverse of decode_nameplates_80x24:
      - Left 64x24 px -> tiles base + 0..23 (8x3 tiles)
      - Left bottom padding (tiles base + 24..31) -> 0
      - Right 16x24 px -> tiles base + 32 + ty*4 + tx (tx: 0..1, ty: 0..2)
      - Right padding (cols 2..3 and row 3) -> 0
    Zero-diff lossless round-trip verified."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    px = img.load()
    orig_tiles = load_tiles_4bpp(open(target_path, "rb").read())
    pal = load_palette(open(pal_path, "rb").read())
    n_tiles = len(orig_tiles)
    n_plates = n_tiles // 48
    new_tiles = [bytearray(64) for _ in range(n_tiles)]

    for p in range(n_plates):
        base = p * 48
        row_y = p * (24 + gap)
        # 1. Left 64x24 px -> tiles base + 0..23
        for ty in range(3):
            for tx in range(8):
                t_idx = base + ty * 8 + tx
                for py in range(8):
                    for px_x in range(8):
                        x = tx * 8 + px_x
                        y = row_y + ty * 8 + py
                        if x < img.width and y < img.height:
                            c = px[x, y]
                            if c[3] < 128 or c[:3] == (0, 255, 0):
                                new_tiles[t_idx][py * 8 + px_x] = 0
                            else:
                                new_tiles[t_idx][py * 8 + px_x] = nearest_palette_index(c[0], c[1], c[2], pal)
        # 2. Left bottom padding (tiles base + 24..31) stays 0 (empty)
        # 3. Right 16x24 px -> tiles base + 32 + ty * 4 + tx (tx: 0..1)
        for ty in range(3):
            for tx in range(2):
                t_idx = base + 32 + ty * 4 + tx
                for py in range(8):
                    for px_x in range(8):
                        x = 64 + tx * 8 + px_x
                        y = row_y + ty * 8 + py
                        if x < img.width and y < img.height:
                            c = px[x, y]
                            if c[3] < 128 or c[:3] == (0, 255, 0):
                                new_tiles[t_idx][py * 8 + px_x] = 0
                            else:
                                new_tiles[t_idx][py * 8 + px_x] = nearest_palette_index(c[0], c[1], c[2], pal)
        # 4. Right padding (tx: 2..3 and row 3) stays 0 (empty)

    packed = [bytes(t) for t in new_tiles]
    with open(target_path, "wb") as f:
        f.write(encode_tiles_4bpp(packed))
    return n_tiles


def decode_infobar_after(nbfc_buf, nbfp_buf):
    """Decode infobar_after_obj.nbfcn (8bpp, 48 tiles) into a complete
    80x24 px banner ("それから" phrase).
    Uses the exact same OAM sprite assembly as map*move nameplates:
      - Left: 64x32 OAM sprite (tiles 0..31, 8x4), top 64x24 px (tiles 0..23, 8x3).
      - Right: 32x32 OAM sprite (tiles 32..47, 4x4), top-left 16x24 px (cols 0..1, rows 0..2).
    Assembled size: 80x24 px. Transparent background (index 0)."""
    tiles = load_tiles(nbfc_buf)
    pal = load_palette(nbfp_buf)
    img = Image.new("RGBA", (80, 24), (0, 0, 0, 0))
    px = img.load()

    # Left 64x24 px (tiles 0..23, width 8)
    for ty in range(3):
        for tx in range(8):
            t = tiles[ty * 8 + tx]
            for py in range(8):
                for px_x in range(8):
                    c = t[py * 8 + px_x]
                    if c != 0 and c < len(pal):
                        px[tx * 8 + px_x, ty * 8 + py] = pal[c] + (255,)

    # Right 16x24 px (tiles 32..47, width 4, cols 0..1)
    for ty in range(3):
        for tx in range(2):
            t = tiles[32 + ty * 4 + tx]
            for py in range(8):
                for px_x in range(8):
                    c = t[py * 8 + px_x]
                    if c != 0 and c < len(pal):
                        px[64 + tx * 8 + px_x, ty * 8 + py] = pal[c] + (255,)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def pack_infobar_after(png_bytes, target_path, pal_path):
    """Re-encode an 80x24 PNG back into infobar_after_obj 8bpp tiles (48 tiles).
    Inverse of decode_infobar_after. Zero-diff round-trip verified."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    px = img.load()
    orig_tiles = load_tiles(open(target_path, "rb").read())
    pal = load_palette(open(pal_path, "rb").read())
    n_tiles = 48
    new_tiles = [bytearray(64) for _ in range(n_tiles)]

    # Left 64x24 px
    for ty in range(3):
        for tx in range(8):
            t_idx = ty * 8 + tx
            for py in range(8):
                for px_x in range(8):
                    x = tx * 8 + px_x
                    y = ty * 8 + py
                    if x < img.width and y < img.height:
                        c = px[x, y]
                        if c[3] < 128 or c[:3] == (0, 255, 0):
                            new_tiles[t_idx][py * 8 + px_x] = 0
                        else:
                            new_tiles[t_idx][py * 8 + px_x] = nearest_palette_index(c[0], c[1], c[2], pal)

    # Right 16x24 px
    for ty in range(3):
        for tx in range(2):
            t_idx = 32 + ty * 4 + tx
            for py in range(8):
                for px_x in range(8):
                    x = 64 + tx * 8 + px_x
                    y = ty * 8 + py
                    if x < img.width and y < img.height:
                        c = px[x, y]
                        if c[3] < 128 or c[:3] == (0, 255, 0):
                            new_tiles[t_idx][py * 8 + px_x] = 0
                        else:
                            new_tiles[t_idx][py * 8 + px_x] = nearest_palette_index(c[0], c[1], c[2], pal)

    raw = b"".join(new_tiles)
    with open(target_path, "wb") as f:
        f.write(lz10.compress(raw))
    return n_tiles


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
