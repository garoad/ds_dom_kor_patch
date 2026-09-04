"""Flask app entrypoint - Python port of webtool/server/index.js.

Node's per-route body-size limits (express.json 10mb, multer 512MB for ROM
uploads, 16MB for image uploads) collapse here into one Flask-wide
MAX_CONTENT_LENGTH sized to the largest upload (ROM files) - Flask has no
built-in equivalent of multer's per-field limits, and a single generous cap
is harmless since this tool only ever runs against a trusted local client.
"""
import os
import sys
import io

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

LOG_PATH = os.path.abspath(os.path.join(HERE, "..", "server.log"))
ERR_PATH = os.path.abspath(os.path.join(HERE, "..", "server.err.log"))

if sys.stdout is None:
    sys.stdout = open(LOG_PATH, "a", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(ERR_PATH, "a", encoding="utf-8")

from flask import Flask, send_from_directory

from routes.project import bp as project_bp
from routes.csv import bp as csv_bp
from routes.build import bp as build_bp
from routes.files import bp as files_bp

PUBLIC_DIR = os.path.join(HERE, "..", "public")

app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
app.url_map.strict_slashes = False

app.register_blueprint(project_bp, url_prefix="/api/project")
app.register_blueprint(csv_bp, url_prefix="/api/csv")
app.register_blueprint(build_bp, url_prefix="/api/build")
app.register_blueprint(files_bp, url_prefix="/api/files")


@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def serve_public(path):
    return send_from_directory(PUBLIC_DIR, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4000))
    print(f"DOM 한글패치 툴 서버 실행 중: http://localhost:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, threaded=True)
