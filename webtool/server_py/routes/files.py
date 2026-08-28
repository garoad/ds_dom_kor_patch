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
# "<A>_p_<B>.bin"(palette) naming instead of .nbfc/.nbfp/.nbfs, but are the
# same LZ10+tile/palette/screenmap format byte-for-byte.
BIN_TILE_RE = re.compile(r"^(.+)_bg_(.+)c\.bin$", re.IGNORECASE)


def has_nbfc_siblings(dir_names, base_name, is_nn=False):
    p_ext = ".nbfpn" if is_nn else ".nbfp"
    return (base_name + p_ext) in dir_names and (base_name + ".nbfs") in dir_names


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


def has_bin_siblings(dir_names, parts):
    names = bin_sibling_names(parts)
    return names["screen"] in dir_names and names["palette"] in dir_names


def resolve_triplet_paths(target):
    """Given a tile-file path (.nbfc/.nbfcn/_bg_*c.bin), resolve its
    palette/screenmap sibling absolute paths. Returns {"error": ...} if no
    matching sibling exists or the format isn't recognized, else
    {"tilePath", "palettePath", "screenPath"}."""
    ext = os.path.splitext(target)[1].lower()
    if ext in (".nbfc", ".nbfcn"):
        is_nn = ext == ".nbfcn"
        base = target[: -len(ext)]
        palette_path = base + (".nbfpn" if is_nn else ".nbfp")
        screen_path = base + ".nbfs"
        if not os.path.exists(palette_path) or not os.path.exists(screen_path):
            return {"error": f"짝이 되는 {'.nbfpn' if is_nn else '.nbfp'}/.nbfs 파일이 없어 처리할 수 없습니다"}
        return {"tilePath": target, "palettePath": palette_path, "screenPath": screen_path}
    if ext == ".bin":
        fname = os.path.basename(target)
        parts = bin_image_parts(fname)
        if not parts:
            return {"error": "이미지로 인식되지 않는 .bin 파일입니다"}
        dir_ = os.path.dirname(target)
        names = bin_sibling_names(parts)
        screen_path = os.path.join(dir_, names["screen"])
        palette_path = os.path.join(dir_, names["palette"])
        if not os.path.exists(screen_path) or not os.path.exists(palette_path):
            return {"error": f"짝이 되는 스크린/팔레트 파일이 없어 처리할 수 없습니다 (필요: {names['screen']}, {names['palette']})"}
        return {"tilePath": target, "palettePath": palette_path, "screenPath": screen_path}
    return {"error": f"타일맵 이미지로 인식되지 않는 형식입니다: {ext}"}


def walk_image_files(dir_path, root, out):
    for entry in os.scandir(dir_path):
        if entry.is_dir():
            walk_image_files(entry.path, root, out)
            continue
        ext = os.path.splitext(entry.name)[1].lower()
        if ext not in (".nbfc", ".nbfcn", ".bin"):
            continue
        if "error" in resolve_triplet_paths(entry.path):
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
        names = {e.name for e in entries_raw}
        entries = []
        for e in entries_raw:
            rel_path = os.path.join(dir_, e.name)
            if e.is_dir():
                entries.append({"name": e.name, "type": "dir", "path": rel_path})
                continue
            ext = os.path.splitext(e.name)[1].lower()
            size = e.stat().st_size
            is_std_image = ext in IMAGE_EXTS
            is_nbfc_image = (
                (ext == ".nbfc" and has_nbfc_siblings(names, e.name[: -len(".nbfc")], False))
                or (ext == ".nbfcn" and has_nbfc_siblings(names, e.name[: -len(".nbfcn")], True))
            )
            bin_parts = bin_image_parts(e.name) if ext == ".bin" else None
            is_bin_image = bin_parts is not None and has_bin_siblings(names, bin_parts)
            entries.append({
                "name": e.name,
                "type": "file",
                "path": rel_path,
                "size": size,
                "isImage": is_std_image or is_nbfc_image or is_bin_image,
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
            with open(resolved["screenPath"], "rb") as f:
                screen_buf = f.read()
            png = nbfc_image.decode_tilemap_png(tile_buf, pal_buf, screen_buf)
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
