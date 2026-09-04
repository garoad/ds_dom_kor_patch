"""
Workspace project-state helper (new for this tool, not a port of any
analysis/*.py script). Each project lives under webtool/workspace/<name>/
and owns:
  unpack/                 - NitroPacker unpack output, never mutated after
  translations/           - per-category split CSVs, the translation "save file"
  build/                  - reinsert output (full copy of unpack/ with only
                             translated .mes files overwritten)
  output/                 - packed .nds output
  project-state.json      - { romPath, projectName, createdAt, extractedAt }

Python port of webtool/server/lib/project.js - see that file's history for
the original design notes.
"""
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(HERE, "..", "workspace"))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
NITROPACKER_BIN = (
    os.path.join(REPO_ROOT, "NitroPacker.exe")
    if os.path.exists(os.path.join(REPO_ROOT, "NitroPacker.exe"))
    else os.path.join(REPO_ROOT, "NitroPacker")
)

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def assert_valid_name(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError(f"invalid project name: {name!r} (use letters/digits/_/- only)")


def project_dir(name):
    assert_valid_name(name)
    return os.path.join(WORKSPACE_ROOT, name)


def unpack_dir(name):
    return os.path.join(project_dir(name), "unpack")


def script_dir(name):
    return os.path.join(unpack_dir(name), "data", "Script")


def csv_dir(name):
    # Translation CSVs are NOT a per-project copy - they live in the repo
    # root's translations/, the same directory analysis/mes_translate_*.py's
    # CLI oracle reads/writes. A prior design kept a second copy under
    # workspace/<name>/translations/ manually synced to root, and that
    # "두 벌 관리" split was a repeated source of silent data-loss bugs (see
    # ANALYSIS_NOTES.md's many "두 트리 diff" entries). name is validated but
    # otherwise unused here.
    assert_valid_name(name)
    return os.path.join(REPO_ROOT, "translations")


def original_rom_path(name):
    return os.path.join(project_dir(name), "original.nds")


def build_dir(name):
    return os.path.join(project_dir(name), "build")


def build_script_dir(name):
    return os.path.join(build_dir(name), "data", "Script")


def output_dir(name):
    return os.path.join(project_dir(name), "output")


def state_path(name):
    return os.path.join(project_dir(name), "project-state.json")


def read_state(name):
    p = state_path(name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_state(name, patch):
    os.makedirs(project_dir(name), exist_ok=True)
    prev = read_state(name) or {}
    next_state = {**prev, **patch, "projectName": name}
    with open(state_path(name), "w", encoding="utf-8") as f:
        json.dump(next_state, f, indent=2, ensure_ascii=False)
    return next_state


def find_project_json(dir_path):
    """Find the NitroPacker project JSON file inside a project's unpack/build dir."""
    if not os.path.exists(dir_path):
        return None
    for f in os.listdir(dir_path):
        if f.lower().endswith(".json"):
            return os.path.join(dir_path, f)
    return None


def run_nitro_packer(args):
    """Run the compiled NitroPacker CLI binary with the given argv."""
    proc = subprocess.run(
        [NITROPACKER_BIN, *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"NitroPacker {' '.join(args)} failed: "
            f"exit {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        )
    return {"stdout": proc.stdout, "stderr": proc.stderr}
