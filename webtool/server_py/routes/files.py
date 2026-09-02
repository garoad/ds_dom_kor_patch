"""Python port of webtool/server/routes/files.js - see that file for the
original route contract (path-traversal guard, .nbfc/.bin sibling-matching
logic) this mirrors exactly."""
import os
import re

from flask import Blueprint, jsonify, request, send_file, Response

import nbfc_image
import project as proj

bp = Blueprint("files", __name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}

# See files.js's BIN_TILE_RE comment: many data/ background graphics use
# .bin-extension "<A>_bg_<B>c.bin"(tiles)/"<A>_bg_<B>s.bin"(screenmap)/
# "<A>_p_<C>.bin"(palette) naming instead of .nbfc/.nbfp/.nbfs, but are the
# same LZ10+tile/palette/screenmap format byte-for-byte.
#
# The palette's own suffix <C> is NOT always the same string as the tile
# file's <B> - confirmed 2026-09-02 by dumping every top-level _bg_*c.bin/
# _p_*.bin pair (see ANALYSIS_NOTES.md): e.g. tile
# "soundmode_u02_bg_soundmode_u01c.bin" (a=soundmode_u02, b=soundmode_u01)
# pairs with palette "soundmode_u02_p_soundmode_u.bin" (b truncated to
# "soundmode_u"), and "title04_bg_title0c.bin" (b=title0, itself truncated)
# pairs with "title04_p_title04.bin". What's actually stable across every
# case checked (soundmode/title/ending/name_screen/load_save plus all the
# ones that already matched) is the <A> prefix: the correct palette is
# whichever "<A>_p_....bin" file lives in the same directory - so <C> is
# ignored entirely and only <A> is matched.
BIN_TILE_RE = re.compile(r"^(.+)_bg_(.+)c\.bin$", re.IGNORECASE)
# Any "..._p_....bin" is a candidate standalone palette file, used below to
# borrow a directory's one-and-only palette for tile+screen pairs that have
# no "<A>_p_...bin" of their own at all (e.g. infodom*/eplace_NN, which all
# share infodom*/map_ue's palette - confirmed visually 2026-09-02, see
# ANALYSIS_NOTES.md). Only borrowed when exactly one such file exists in the
# directory - if there's more than one, which one applies is genuinely
# ambiguous and guessing risks a silently-wrong preview.
BIN_PALETTE_RE = re.compile(r"^.+_p_.+\.bin$", re.IGNORECASE)

# The 32-tile row width both nbfc_image.tilemap_dims() (real screenmap) and
# decode_tile_grid_png()'s default (no screenmap at all) fall back to is the
# NDS hardware BG convention - only correct for files that are actual
# hardware backgrounds (1024-entry 256x256 screens like movemap/title/
# soundmode). Small standalone UI-label/icon
# graphics were never a hardware BG and aren't bound by that width at all -
# confirmed by rendering each candidate divisor of the tile/entry count and
# checking which one stops icons/text from being cut mid-shape, 2026-09-02
# (see ANALYSIS_NOTES.md):
# - infodom*/eplace_NN name-tag banners (30 screenmap entries, full/
#   borrowed_palette mode): garbled/solid at 32 wide, clean Japanese text
#   (e.g. "通学路", "清嶺学園") at 10 wide.
# - extra_par/extra_T_par (44 tiles, grid mode): digit+"%" glyph strip,
#   clean at 2 wide (each glyph is a 2-tile column), garbled otherwise.
# - extra_topu_obj (256 tiles, grid mode): dialog-box UI text, clean at 2.
# - extra_b_icon (432 tiles, grid mode): icon list, clean at 2.
# - extra_objkiso (64 tiles, grid mode): R/L button + arrow icon cluster,
#   cleanest at 4 (2 or 8+ cut icons apart or interleave unrelated ones).
# - extra_menusub (1152 tiles, grid mode): see its own KNOWN_WIDTH_OVERRIDES
#   entry below - tiles[0:768] (12 pill-shaped menu buttons) are clean plain
#   rows at width 8, but tiles[768:1152] needed the hstack technique found
#   for titleobj/extra_afdom* (three "Days of Memories" logo cards split
#   across an 8-wide + 4-wide chunk each) plus two more plain width-8 rows.
# extra_b_waku/extra_ending_waku/extra_menuwaku ("waku" = frame/border) and
# infobarobj/infobar3obj/infobar_after_obj/map*move*_obj were checked too but
# no candidate width made them fully coherent - they're most likely
# runtime-assembled UI chrome (corner/edge border pieces, digit/name-tag
# fragments drawn individually rather than as one picture), so they stay on
# decode_tile_grid_png()'s 32-wide default (best-effort reference preview,
# not a claim of correctness).
#
def _repeating_hstack_rows(cycle_len, chunk1_end, chunk2_start, chunk2_end, w1, w2, n_cycles, base_offset=0):
    """Build `n_cycles` ("hstack", [(...)]) rows for a file made of repeated
    fixed-size cycles, each cycle itself needing tiles[chunk1_start:chunk1_end]
    at width w1 placed left of tiles[chunk2_start:chunk2_end] at width w2
    (offsets relative to the start of that cycle) - see extra_afdom*_onsub
    below for why this shape shows up (a name split across two chunks).
    base_offset shifts every tile index by a fixed amount, for a repeating
    region that doesn't start at tile 0 (e.g. extra_dom*_albumsub's name
    cycles start after a leading block of portrait icons)."""
    rows = []
    for i in range(n_cycles):
        base = base_offset + i * cycle_len
        rows.append(("hstack", [(base, base + chunk1_end, w1), (base + chunk2_start, base + chunk2_end, w2)]))
    return rows


# Each entry is (filename pattern, confirmed width); only applied when the
# tile/entry count is evenly divisible by that width.
KNOWN_WIDTH_OVERRIDES = [
    (re.compile(r"^eplace_\d+_bg_eplace_\d+c\.bin$", re.IGNORECASE), 10),
    (re.compile(r"^extra_(T_)?par\.nbfcn$", re.IGNORECASE), 2),
    (re.compile(r"^extra_topu_obj\.nbfcn$", re.IGNORECASE), 2),
    (re.compile(r"^extra_b_icon\.nbfcn$", re.IGNORECASE), 2),
    (re.compile(r"^extra_objkiso\.nbfcn$", re.IGNORECASE), 4),
    # extra_menusub (1152 tiles): tiles[0:768] originally treated as one
    # plain width-8 row of 12 pill-shaped buttons (each 64 tiles looked like
    # a complete, self-closed pill on its own - rounded top AND bottom -
    # which is what made the illusion so convincing). Re-checked 2026-09-02
    # after the user noticed only 3 button labels in 2 colors (6 buttons)
    # should exist, not 12: hstack-ing tiles[+0:+64]@8 with tiles[+64:+128]@8
    # (128-tile cycles) reveals each PAIR of "complete-looking" 64-tile
    # blocks is actually the left/right halves of ONE wider button -
    # 6 buttons total, "アルバム"/"エンディング"/"サウンド" each in pink then
    # yellow. tiles[768:1152]: three "Days of Memories"(-branded logo card
    # graphics, each split tiles[+0:+48]@8 (main card, text cut at the
    # right) + tiles[+64:+88]@4 (the missing right side - a swirl/"2" on the
    # 2nd one) - repeating every 96 tiles for 3 cycles (768, 864, 960), then
    # tiles[1056:1088]@8 (4 small return/save icon buttons) and
    # tiles[1088:1136]@8 (one more "Days of Memories" card, complete on its
    # own this time, no hstack needed) - trailing tiles[1136:1152] unused.
    (re.compile(r"^extra_menusub\.nbfcn$", re.IGNORECASE),
     _repeating_hstack_rows(cycle_len=128, chunk1_end=64, chunk2_start=64, chunk2_end=128, w1=8, w2=8, n_cycles=6)
     + _repeating_hstack_rows(cycle_len=96, chunk1_end=48, chunk2_start=64, chunk2_end=88,
                               w1=8, w2=4, n_cycles=3, base_offset=768)
     + [(1056, 1088, 8), (1088, 1136, 8)]),
    # talkobj (304 tiles): re-verified 2026-09-02 into a two-segment splice
    # (same "double-width coincidence" trap as infobar3obj/titleobj) - the
    # original single-width-4 guess only actually rendered tiles[0:80]
    # correctly; tiles[80:304] just *looked* plausible at 4 (an apparent
    # "scrollbar") but is really two pink log-bar backgrounds + 4 blue
    # up/up/down/down scroll buttons + 2 confirm-arrow icon pairs, all only
    # complete (rounded corners closing on both sides, arrows unsplit) at 8.
    # tiles[0:80] at width 4: "!"/"!"/glasses/glasses/pen icon set.
    (re.compile(r"^talkobj\.nbfcn$", re.IGNORECASE), [(0, 80, 4), (80, 304, 8)]),
    # titleobj (112 tiles): tiles[0:56]@8 and tiles[64:84]@4 are NOT two
    # stacked boxes - hstack-ing them side by side (2026-09-02, after user
    # pushed back on a vertical stack and asked for left-right instead)
    # reveals they're two chunks of the SAME two-line speech bubble: the
    # width-8 piece alone reads "タイトル"/"選んでね" looking cut off at its
    # right edge, and the width-4 piece supplies exactly the missing
    # continuation - "タイトルを" / "選んでね。" - with the small piece's own
    # rounded corner completing the bubble's right border. This also
    # explains why the small piece looked "open on the left" at every width
    # tried: it was never a separate box, so it never had its own left
    # border to begin with. tiles[96:112]@4 is a separate, fully-closed
    # shuriken (ninja star) icon - kept as its own row after the combined
    # bubble, with the default 8px gap before it since it's unrelated.
    (re.compile(r"^titleobj\.nbfcn$", re.IGNORECASE), [("hstack", [(0, 56, 8), (64, 84, 4)]), (96, 112, 4)]),
    # infobarobj (136 tiles): NOT one uniform sheet - splices together two
    # differently-arranged sub-assets, confirmed by finding a blank-tile-row
    # boundary at tile 80 (see analyze() runs in ANALYSIS_NOTES.md) and
    # checking each half independently: tiles[0:80] are a digit font 0-9 at
    # width 2 (same pattern as extra_par), tiles[80:136] are weekday badges
    # 月火水木金土日(月=Mon..日=Sun, Sun in red) at width 4. No single width
    # renders both halves cleanly, so this is a segments list, not a width -
    # see decode_tile_grid_png()'s `segments` param.
    (re.compile(r"^infobarobj\.nbfcn$", re.IGNORECASE), [(0, 80, 2), (80, 136, 4)]),
    # infobar3obj (112 tiles): also a two-segment splice (like infobarobj) -
    # corrected 2026-09-02 after user caught the earlier single-width-8 guess
    # rendering the kanji broken. tiles[0:80] are 5 zodiac-hour kanji
    # (辰/午/未/申/戌) at width 4 - each one clean and evenly separated by a
    # blank tile-row; the width-8 render used before was actually just this
    # same data double-wide, which interleaves each kanji's own rows and
    # only *looked* like a plausible "icon+kanji column" pattern by
    # coincidence. tiles[80:112] are the shared "の刻" suffix
    # ("Hour of the ___") at width 8, confirmed still correct standalone.
    (re.compile(r"^infobar3obj\.nbfcn$", re.IGNORECASE), [(0, 80, 4), (80, 112, 8)]),
    # infobar_after_obj (48 tiles): "それから"(그러고 나서/그 후) phrase +
    # a small arrow/transition icon, clean at 8.
    (re.compile(r"^infobar_after_obj\.nbfcn$", re.IGNORECASE), 8),
    # saveloadobj (656 tiles): save/load menu buttons - return-arrow icons,
    # "タイトルにもどる"(타이틀로 돌아가기), "はい"/"いいえ"(예/아니오),
    # "1ページ"/"2ページ"/"3ページ"(페이지 탭) in multiple color states.
    # Same failure mode as extra_menusub: at 32 a multi-row label's rows land
    # in different quadrants of one wide display row instead of stacking, so
    # it reads as scattered fragments; at 8 each label's rows stack correctly.
    (re.compile(r"^saveloadobj\.nbfcn$", re.IGNORECASE), 8),
    # extra_afdom1/2/3_onsub (864 tiles each): character-select folder tabs
    # - looked fine at the 32-wide default (a plausible multi-column folder
    # grid), but re-verified 2026-09-02 with the hstack technique found for
    # titleobj: each of the 9 tabs is itself split into tiles[+0:+48]@8 (the
    # tab body, name cut off at its right edge) and tiles[+64:+88]@4 (the
    # missing right side of the name), repeating every 96 tiles. hstack-ing
    # each pair completes full names - afdom1: 麻宮アテナ/不知火舞/ユリ・サカザキ/
    # キング/藤堂香澄/B・ジェニー/クーラ・ダイアモンド/レオナ・ハイデルン/その他;
    # afdom2 and afdom3 are different character rosters (confirmed same
    # 96-tile cycle structure, all 9 names read cleanly) - all SNK crossover
    # cast for what looks like an "extra mode" character list.
    (re.compile(r"^extra_afdom[123]_onsub\.nbfcn$", re.IGNORECASE),
     _repeating_hstack_rows(cycle_len=96, chunk1_end=48, chunk2_start=64, chunk2_end=88, w1=8, w2=4, n_cycles=9)),
    # extra_dom1/2/3_albumsub (992 tiles each): tiles[0:128] at width 4 are
    # 8 clean, fully-closed character face portraits (matching the first 8
    # named tabs of the corresponding extra_afdomN_onsub, "その他" excluded
    # since it has no single character face) - already fine at width 4 with
    # no hstack needed. tiles[128:992] (864 tiles) are the exact same
    # 96-tile hstack-cycle name structure as extra_afdomN_onsub (same
    # per-tab split, same 9 names, now with the character art visible
    # behind the folder tab instead of a plain color) - confirmed
    # 2026-09-02 immediately after finding that pattern in extra_afdom*.
    (re.compile(r"^extra_dom[123]_albumsub\.nbfcn$", re.IGNORECASE),
     [(0, 128, 4)] + _repeating_hstack_rows(cycle_len=96, chunk1_end=48, chunk2_start=64, chunk2_end=88,
                                             w1=8, w2=4, n_cycles=9, base_offset=128)),
]


def _row_max_end(row):
    """Highest tile index a segments row reads up to - a plain
    (start,end,width,...) tuple's own `end`, or the max `end` across an
    ("hstack", [(start,end,width), ...]) row's sub-ranges."""
    if row[0] == "hstack":
        return max(r[1] for r in row[1])
    return row[1]


def known_width_override(fname, n_entries):
    """Returns an int (single width, applies to grid mode's map_w or
    decode_tilemap_png's map_w) or a list of segment rows (grid mode only,
    see decode_tile_grid_png's `segments` param) - or None if nothing
    matches or the tile/entry count doesn't line up."""
    for pat, val in KNOWN_WIDTH_OVERRIDES:
        if not pat.match(fname):
            continue
        if isinstance(val, list):
            if _row_max_end(val[-1]) <= n_entries:
                return val
        elif n_entries % val == 0:
            return val
    return None


def bin_image_parts(fname):
    m = BIN_TILE_RE.match(fname)
    if not m:
        return None
    return {"a": m.group(1), "b": m.group(2)}


def bin_sibling_names(parts):
    return {
        "screen": f"{parts['a']}_bg_{parts['b']}s.bin",
        "palette": f"{parts['a']}_p_{parts['b']}.bin",
    }


def find_bin_palettes_by_prefix(dir_names, a_prefix):
    pat = re.compile(r"^" + re.escape(a_prefix) + r"_p_.+\.bin$", re.IGNORECASE)
    return sorted(n for n in dir_names if pat.match(n))


def find_single_other_bin_palette(dir_names, exclude_name):
    candidates = [n for n in dir_names if n != exclude_name and BIN_PALETTE_RE.match(n)]
    return candidates[0] if len(candidates) == 1 else None


def resolve_triplet_paths(target):
    """Given a tile-file path (.nbfc/.nbfcn/_bg_*c.bin), resolve its
    palette/screenmap sibling absolute paths. Returns {"error": ...} if the
    format isn't recognized or no palette can be found at all, else
    {"tilePath", "palettePath", "screenPath", "mode"} where mode is:
    - "full": real screenmap + dedicated palette, decodes/encodes normally.
    - "grid": .nbfc(n) tile sheet with a palette but no .nbfs sibling (OAM
      sprite fragments) - screenPath is None, preview-only (no encode).
    - "borrowed_palette": .bin tile+screen pair with no "<A>_p_...bin" of its
      own at all, using the directory's one unambiguous leftover palette -
      preview-only (encode would need to prove that palette is
      byte-identical to what the game actually uses, which hasn't been
      verified)."""
    ext = os.path.splitext(target)[1].lower()
    dir_ = os.path.dirname(target)
    fname = os.path.basename(target)

    if ext in (".nbfc", ".nbfcn"):
        is_nn = ext == ".nbfcn"
        base = target[: -len(ext)]
        palette_path = base + (".nbfpn" if is_nn else ".nbfp")
        screen_path = base + ".nbfs"
        if not os.path.exists(palette_path):
            return {"error": f"짝이 되는 {'.nbfpn' if is_nn else '.nbfp'} 파일이 없어 처리할 수 없습니다"}
        if os.path.exists(screen_path):
            return {"tilePath": target, "palettePath": palette_path, "screenPath": screen_path, "mode": "full"}
        return {"tilePath": target, "palettePath": palette_path, "screenPath": None, "mode": "grid"}

    if ext == ".bin":
        parts = bin_image_parts(fname)
        if not parts:
            return {"error": "이미지로 인식되지 않는 .bin 파일입니다"}
        names = bin_sibling_names(parts)
        screen_path = os.path.join(dir_, names["screen"])
        if not os.path.exists(screen_path):
            return {"error": f"짝이 되는 스크린 파일이 없어 처리할 수 없습니다 (필요: {names['screen']})"}

        dir_names = set(os.listdir(dir_))
        own_prefix = find_bin_palettes_by_prefix(dir_names, parts["a"])
        if len(own_prefix) == 1:
            return {
                "tilePath": target,
                "palettePath": os.path.join(dir_, own_prefix[0]),
                "screenPath": screen_path,
                "mode": "full",
            }
        if len(own_prefix) > 1:
            return {"error": f"팔레트 후보가 여러 개라 특정할 수 없습니다: {', '.join(own_prefix)}"}

        borrowed = find_single_other_bin_palette(dir_names, fname)
        if borrowed:
            return {
                "tilePath": target,
                "palettePath": os.path.join(dir_, borrowed),
                "screenPath": screen_path,
                "mode": "borrowed_palette",
            }
        return {"error": f"짝이 되는 팔레트 파일이 없고, 같은 폴더에서 대신 빌릴 팔레트도 특정할 수 없습니다 (필요: {names['palette']} 계열)"}
    return {"error": f"타일맵 이미지로 인식되지 않는 형식입니다: {ext}"}


def walk_image_files(dir_path, root, out):
    for entry in os.scandir(dir_path):
        if entry.is_dir():
            walk_image_files(entry.path, root, out)
            continue
        ext = os.path.splitext(entry.name)[1].lower()
        if ext not in (".nbfc", ".nbfcn", ".bin"):
            continue
        resolved = resolve_triplet_paths(entry.path)
        if resolved.get("mode") != "full":
            continue
        out.append({
            "base": os.path.splitext(entry.name)[0].lower(),
            "rel": os.path.relpath(entry.path, root),
        })


def find_images_by_basename(name, target_base):
    root = proj.unpack_dir(name)
    all_files = []
    walk_image_files(root, root, all_files)
    return [f for f in all_files if f["base"] == target_base.lower()]


def resolve_in_unpack(name, rel):
    root = proj.unpack_dir(name)
    resolved = os.path.abspath(os.path.join(root, rel or ""))
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError("잘못된 경로입니다")
    return resolved


@bp.get("/tree")
def tree():
    name = request.args.get("name")
    dir_ = request.args.get("dir") or ""
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400

    try:
        target = resolve_in_unpack(name, dir_)
        if not os.path.exists(target):
            return jsonify({"error": "디렉터리를 찾을 수 없습니다"}), 404

        entries_raw = list(os.scandir(target))
        entries = []
        for e in entries_raw:
            rel_path = os.path.join(dir_, e.name)
            if e.is_dir():
                entries.append({"name": e.name, "type": "dir", "path": rel_path})
                continue
            ext = os.path.splitext(e.name)[1].lower()
            size = e.stat().st_size
            is_std_image = ext in IMAGE_EXTS
            is_tile_image = ext in (".nbfc", ".nbfcn", ".bin") and "error" not in resolve_triplet_paths(e.path)
            entries.append({
                "name": e.name,
                "type": "file",
                "path": rel_path,
                "size": size,
                "isImage": is_std_image or is_tile_image,
            })
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"]))
        return jsonify(entries)
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400


@bp.get("/raw")
def raw():
    name = request.args.get("name")
    rel_path = request.args.get("path")
    if not name or not rel_path:
        return jsonify({"error": "name, path는 필수입니다"}), 400

    try:
        ext = os.path.splitext(rel_path)[1].lower()
        target = resolve_in_unpack(name, rel_path)
        if not os.path.exists(target):
            return jsonify({"error": "파일을 찾을 수 없습니다"}), 404

        if ext in IMAGE_EXTS:
            return send_file(target)
        if ext in (".nbfc", ".nbfcn", ".bin"):
            resolved = resolve_triplet_paths(target)
            if "error" in resolved:
                return jsonify({"error": resolved["error"]}), 400
            with open(resolved["tilePath"], "rb") as f:
                tile_buf = f.read()
            with open(resolved["palettePath"], "rb") as f:
                pal_buf = f.read()
            if resolved["mode"] == "grid":
                n_tiles = len(nbfc_image.load_tiles(tile_buf))
                width_override = known_width_override(os.path.basename(target), n_tiles)
                if isinstance(width_override, list):
                    png = nbfc_image.decode_tile_grid_png(tile_buf, pal_buf, segments=width_override)
                else:
                    png = nbfc_image.decode_tile_grid_png(tile_buf, pal_buf, map_w=width_override or 32)
            else:
                with open(resolved["screenPath"], "rb") as f:
                    screen_buf = f.read()
                n_entries = len(nbfc_image.load_screen(screen_buf))
                width_override = known_width_override(os.path.basename(target), n_entries)
                png = nbfc_image.decode_tilemap_png(tile_buf, pal_buf, screen_buf, map_w=width_override)
            base = os.path.splitext(os.path.basename(target))[0]
            return Response(
                png,
                mimetype="image/png",
                headers={"Content-Disposition": f'inline; filename="{base}.png"'},
            )
        return jsonify({"error": f"미리보기를 지원하지 않는 형식입니다: {ext}"}), 400
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400


@bp.post("/image")
def upload_image():
    name = request.args.get("name")
    rel_path = request.args.get("path")
    if not name or not rel_path:
        return jsonify({"error": "name, path는 필수입니다"}), 400
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "image 파일이 필요합니다"}), 400

    try:
        ext = os.path.splitext(rel_path)[1].lower()
        if ext not in (".nbfc", ".nbfcn", ".bin"):
            return jsonify({"error": f"리팩을 지원하지 않는 형식입니다: {ext}"}), 400
        target = resolve_in_unpack(name, rel_path)
        if not os.path.exists(target):
            return jsonify({"error": "파일을 찾을 수 없습니다"}), 404

        resolved = resolve_triplet_paths(target)
        if "error" in resolved:
            return jsonify({"error": resolved["error"]}), 400
        if resolved["mode"] != "full":
            return jsonify({"error": "이 파일은 미리보기 전용입니다 (스크린맵 또는 전용 팔레트가 없어 재인코딩을 지원하지 않습니다)"}), 400

        with open(resolved["palettePath"], "rb") as f:
            palette_buf = f.read()
        with open(resolved["screenPath"], "rb") as f:
            screen_buf = f.read()
        orig_entry_count = len(nbfc_image.load_screen(screen_buf))

        encoded = nbfc_image.encode_tilemap_png(file.read(), palette_buf, orig_entry_count)
        with open(resolved["tilePath"], "wb") as f:
            f.write(encoded["nbfc"])
        with open(resolved["screenPath"], "wb") as f:
            f.write(encoded["nbfs"])
        return jsonify({"ok": True, "tileCount": orig_entry_count})
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400


@bp.post("/images-batch")
def upload_images_batch():
    name = request.args.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "images 파일이 필요합니다"}), 400

    root = proj.unpack_dir(name)
    if not os.path.exists(root):
        return jsonify({"error": "프로젝트를 찾을 수 없습니다"}), 404

    results = []
    for file in files:
        base = os.path.splitext(file.filename)[0]
        try:
            matches = find_images_by_basename(name, base)
            if not matches:
                results.append({"file": file.filename, "ok": False, "error": "일치하는 파일을 찾지 못했습니다"})
                continue
            if len(matches) > 1:
                results.append({
                    "file": file.filename,
                    "ok": False,
                    "error": f"여러 파일과 일치해 자동 선택할 수 없습니다: {', '.join(m['rel'] for m in matches)}",
                })
                continue
            match = matches[0]
            target = os.path.join(root, match["rel"])
            resolved = resolve_triplet_paths(target)
            if "error" in resolved:
                results.append({"file": file.filename, "ok": False, "error": resolved["error"]})
                continue

            with open(resolved["palettePath"], "rb") as f:
                palette_buf = f.read()
            with open(resolved["screenPath"], "rb") as f:
                screen_buf = f.read()
            orig_entry_count = len(nbfc_image.load_screen(screen_buf))
            encoded = nbfc_image.encode_tilemap_png(file.read(), palette_buf, orig_entry_count)
            with open(resolved["tilePath"], "wb") as f:
                f.write(encoded["nbfc"])
            with open(resolved["screenPath"], "wb") as f:
                f.write(encoded["nbfs"])
            results.append({"file": file.filename, "ok": True, "matchedPath": match["rel"], "tileCount": orig_entry_count})
        except Exception as ex:
            results.append({"file": file.filename, "ok": False, "error": str(ex)})

    return jsonify({"results": results})
