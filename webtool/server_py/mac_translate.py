"""
macOS built-in Translation framework backend (the on-device NMT engine behind
macOS/Safari's translation feature) - NOT the FoundationModels LLM.
FoundationModels was tried first but frequently just echoed/reorganized the
Japanese source instead of translating it (see analysis/ANALYSIS_NOTES.md
2026-08-10 entry). TranslationSession is a dedicated translator and reliably
translates while passing <HEX>/<이름> control tags through untouched.

Python cannot call the Swift-only Translation framework directly, so this
shells out to the same bundled Swift CLI (webtool/native/mac-translate) that
the original Node backend used, via stdin/stdout JSON - a straight port of
webtool/server/lib/macTranslate.js, no behavior changes.
"""
import json
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE_DIR = os.path.join(HERE, "..", "native", "mac-translate")
BIN_PATH = os.path.join(NATIVE_DIR, ".build", "release", "mac-translate")


def ensure_built(on_progress=None):
    if os.path.exists(BIN_PATH):
        return

    if on_progress:
        on_progress("macOS 번역 엔진을 처음 빌드하는 중입니다 (최초 1회, 수십 초 소요)...")

    proc = subprocess.run(
        ["swift", "build", "-c", "release"],
        cwd=NATIVE_DIR,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not os.path.exists(BIN_PATH):
        raise RuntimeError(f"macOS 번역 엔진 빌드 실패: {proc.stderr[-2000:]}")


def run_binary(items, on_progress=None):
    """Mirrors macTranslate.js's runBinary: stderr lines are surfaced to
    on_progress AS THEY ARRIVE (not batched after the process exits), so a
    caller streaming to SSE (routes/csv.py's /translate-stream) gets live
    progress. stdin is written from a separate thread to avoid a pipe
    deadlock (writing a large payload while stdout/stderr fill up)."""
    proc = subprocess.Popen(
        [BIN_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def write_stdin():
        try:
            proc.stdin.write(json.dumps(items))
        finally:
            proc.stdin.close()

    writer = threading.Thread(target=write_stdin)
    writer.start()

    stderr_tail = ""
    for line in proc.stderr:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        stderr_tail = line
        if on_progress:
            on_progress(line.strip())

    writer.join()
    stdout = proc.stdout.read()
    returncode = proc.wait()

    if returncode != 0:
        raise RuntimeError(f"mac-translate 종료 코드 {returncode}: {stderr_tail}")
    try:
        return json.loads(stdout)
    except ValueError as ex:
        raise RuntimeError(f"mac-translate 출력 JSON 파싱 실패: {ex}") from ex


def translate_batch(items, on_progress=None):
    if sys.platform != "darwin":
        raise RuntimeError("macOS 번역 엔진은 macOS에서만 사용할 수 있습니다.")

    ensure_built(on_progress)
    return run_binary(items, on_progress)
