"""Python port of webtool/server/routes/build.js - see that file for the
original route contract this mirrors byte-for-byte (paths, JSON shapes)."""
import os
import re
import shutil
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, send_file

import mes_codec as mc
import pipeline
import project as proj

bp = Blueprint("build", __name__)

_BLOCK_MSG_RE = re.compile(r"^block (\d+):\s*(.*)$")


def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _group_csv_by_file(rows):
    by_file = {}
    for row in rows:
        by_file.setdefault(row["file"], {})[int(row["block"])] = row
    return by_file


def _parse_block_from_message(msg):
    m = _BLOCK_MSG_RE.match(msg)
    if not m:
        return {"block": None, "message": msg}
    return {"block": int(m.group(1)), "message": m.group(2)}


@bp.post("/reinsert")
def reinsert():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    state = proj.read_state(name)
    if not state:
        return jsonify({"error": "프로젝트를 찾을 수 없습니다"}), 404

    unpack_dir = proj.unpack_dir(name)
    if not os.path.exists(unpack_dir):
        return jsonify({"error": "먼저 롬을 언팩해야 합니다"}), 400

    try:
        rows = pipeline.read_csv(name)
        if not rows:
            return jsonify({"error": "CSV가 비어 있습니다. 먼저 CSV를 생성하세요"}), 400

        build_dir = proj.build_dir(name)
        shutil.rmtree(build_dir, ignore_errors=True)
        shutil.copytree(unpack_dir, build_dir)

        by_file = _group_csv_by_file(rows)
        files_written = 0
        files_skipped = 0
        problems = []

        for fname, rows_by_block in by_file.items():
            has_translation = any(
                r.get("translation") and r["translation"].strip()
                for r in rows_by_block.values()
            )
            if not has_translation:
                continue

            result = pipeline.build_file_tokens(name, fname, rows_by_block)
            if result["problems"]:
                files_skipped += 1
                for msg in result["problems"]:
                    problems.append({"file": fname, **_parse_block_from_message(msg)})
                continue

            rel_path = result["relPath"]
            out_path = (
                os.path.join(build_dir, "data", rel_path) if rel_path
                else os.path.join(proj.build_script_dir(name), fname)
            )
            mc.dump_values(result["tokens"], out_path)
            files_written += 1

        pipeline.apply_font_art(name)

        proj.write_state(name, {"reinsertedAt": _now_iso()})
        return jsonify({"filesWritten": files_written, "filesSkipped": files_skipped, "problems": problems})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@bp.post("/pack")
def pack():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    state = proj.read_state(name)
    if not state:
        return jsonify({"error": "프로젝트를 찾을 수 없습니다"}), 404

    build_dir = proj.build_dir(name)
    if not os.path.exists(build_dir):
        return jsonify({"error": "먼저 재삽입(reinsert)을 실행해야 합니다"}), 400

    project_json = proj.find_project_json(build_dir)
    if not project_json:
        return jsonify({"error": f"build/ 안에서 NitroPacker 프로젝트 JSON을 찾을 수 없습니다: {build_dir}"}), 500

    try:
        out_dir = proj.output_dir(name)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{name}.nds")
        proj.run_nitro_packer(["pack", "-p", project_json, "-r", out_path])
        proj.write_state(name, {"packedAt": _now_iso()})
        return jsonify({"ok": True, "outputPath": out_path})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@bp.get("/download")
def download():
    name = request.args.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    out_path = os.path.join(proj.output_dir(name), f"{name}.nds")
    if not os.path.exists(out_path):
        return jsonify({"error": "빌드된 ROM이 없습니다. 먼저 빌드하세요"}), 404
    return send_file(out_path, as_attachment=True, download_name=f"{name}.nds")
