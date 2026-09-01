"""Python port of webtool/server/routes/project.js - see that file for the
original route contract this mirrors byte-for-byte (paths, JSON shapes)."""
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

import pipeline
import project as proj

bp = Blueprint("project", __name__)


def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@bp.post("/unpack")
def unpack():
    project_name = request.form.get("projectName")
    file = request.files.get("romFile")
    if not file or not project_name:
        return jsonify({"error": "romFile, projectName은 필수입니다"}), 400
    try:
        proj.assert_valid_name(project_name)
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400
    if not file.filename.lower().endswith(".nds"):
        return jsonify({"error": f".nds 롬 파일이 아닙니다: {file.filename}"}), 400

    try:
        rom_path = proj.original_rom_path(project_name)
        os.makedirs(proj.project_dir(project_name), exist_ok=True)
        file.save(rom_path)

        unpack_dir = proj.unpack_dir(project_name)
        os.makedirs(unpack_dir, exist_ok=True)
        proj.run_nitro_packer(["unpack", "-r", rom_path, "-o", unpack_dir, "-n", project_name])

        script_dir = proj.script_dir(project_name)
        mes_count = 0
        if os.path.exists(script_dir):
            mes_count = sum(1 for f in os.listdir(script_dir) if f.lower().endswith(".mes"))

        state = proj.write_state(project_name, {
            "romFileName": file.filename,
            "romPath": rom_path,
            "createdAt": _now_iso(),
        })

        return jsonify({"ok": True, "state": state, "mesCount": mes_count})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@bp.get("/status")
def status():
    name = request.args.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    state = proj.read_state(name)
    if not state:
        return jsonify({"error": "프로젝트를 찾을 수 없습니다"}), 404

    summaries = pipeline.file_summaries(name)
    output_dir = proj.output_dir(name)
    output_exists = os.path.exists(output_dir) and any(
        f.endswith(".nds") for f in os.listdir(output_dir)
    )
    return jsonify({
        "state": state,
        "csvExists": os.path.exists(proj.csv_dir(name)),
        "totalBlocks": sum(s["blockCount"] for s in summaries),
        "translatedBlocks": sum(s["translatedCount"] for s in summaries),
        "buildExists": os.path.exists(proj.build_dir(name)),
        "outputExists": output_exists,
    })
