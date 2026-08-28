"""Python port of webtool/server/routes/csv.js - see that file for the
original route contract this mirrors byte-for-byte (paths, JSON shapes,
SSE event format)."""
import json
import os
import queue
import threading
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request, send_file

import mac_translate
import pipeline
import project as proj

bp = Blueprint("csv", __name__)


def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@bp.post("/extract")
def extract():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    if not proj.read_state(name):
        return jsonify({"error": "프로젝트를 찾을 수 없습니다"}), 404

    try:
        summary = pipeline.extract_project(name)
        proj.write_state(name, {"extractedAt": _now_iso()})
        return jsonify(summary)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@bp.get("/files")
def files():
    name = request.args.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    try:
        return jsonify(pipeline.file_summaries(name))
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@bp.get("/search")
def search():
    name = request.args.get("name")
    q = request.args.get("q")
    target = request.args.get("target")
    limit = request.args.get("limit")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    if not q or not q.strip():
        return jsonify({"total": 0, "results": []})

    try:
        results = pipeline.search_csv(
            name, q.strip(), target=target or "all",
            limit=int(limit) if limit else 200,
        )
        return jsonify(results)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@bp.get("/file/<fname>")
def get_file(fname):
    name = request.args.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    try:
        return jsonify(pipeline.rows_for_file(name, fname))
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@bp.post("/file/<fname>")
def save_file(fname):
    name = request.args.get("name")
    edits = request.get_json(silent=True)
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400
    if not isinstance(edits, list):
        return jsonify({"error": "body는 [{block, translation}] 배열이어야 합니다"}), 400

    try:
        report = pipeline.save_file(name, fname, edits)
        return jsonify({"ok": True, "report": report})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@bp.get("/translate-stream")
def translate_stream():
    name = request.args.get("name")
    fname = request.args.get("fname")
    if not name or not fname:
        return "name, fname은 필수입니다.", 400

    def generate():
        def send_event(data):
            return f"data: {json.dumps(data)}\n\n"

        try:
            file_rows = pipeline.rows_for_file(name, fname)
            if not file_rows:
                yield send_event({"type": "error", "message": "번역할 대사 행이 없습니다."})
                return

            sources = [r["source"] for r in file_rows]
            yield send_event({"type": "start", "total": len(sources)})

            # translate_batch() runs the Swift CLI subprocess and can take a
            # while; run it on a worker thread and relay its on_progress
            # callbacks through a queue so this generator can yield each one
            # to the client as it happens (real-time SSE), matching the
            # Node version's event-driven stderr streaming.
            q = queue.Queue()
            result = {}

            def worker():
                try:
                    result["translated"] = mac_translate.translate_batch(
                        sources, lambda msg: q.put(("progress", msg))
                    )
                except Exception as ex:
                    result["error"] = str(ex)
                finally:
                    q.put(("done", None))

            threading.Thread(target=worker, daemon=True).start()

            while True:
                kind, msg = q.get()
                if kind == "progress":
                    yield send_event({"type": "progress", "message": msg})
                else:
                    break

            if "error" in result:
                yield send_event({"type": "error", "message": result["error"]})
                return

            translated_list = result["translated"]
            edits = [
                {"block": int(r["block"]), "ai_draft": translated_list[idx], "translation": translated_list[idx]}
                for idx, r in enumerate(file_rows)
            ]

            report = pipeline.save_file(name, fname, edits)
            yield send_event({"type": "done", "translatedCount": len(edits), "report": report})
        except Exception as ex:
            yield send_event({"type": "error", "message": str(ex)})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@bp.get("/download")
def download():
    name = request.args.get("name")
    if not name:
        return jsonify({"error": "name은 필수입니다"}), 400

    trans_dir = proj.csv_dir(name)
    if not os.path.exists(trans_dir):
        return jsonify({"error": "CSV 파일이 없습니다. 먼저 생성/갱신하세요"}), 404

    zip_path = os.path.join(proj.project_dir(name), f"{name}_translations.zip")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, filenames in os.walk(trans_dir):
                for fn in filenames:
                    full = os.path.join(root, fn)
                    arcname = os.path.join("translations", os.path.relpath(full, trans_dir))
                    zf.write(full, arcname)
    except Exception as ex:
        return jsonify({"error": f"ZIP 압축 실패: {ex}"}), 500

    return send_file(zip_path, as_attachment=True, download_name=f"{name}_translations.zip")
