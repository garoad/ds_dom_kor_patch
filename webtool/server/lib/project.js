"use strict";

// Workspace project-state helper (new for this tool, not a port). Each
// project lives under webtool/workspace/<name>/ and owns:
//   unpack/                 - NitroPacker unpack output, never mutated after
//   translations/           - per-category split CSVs, the translation "save file"
//   build/                  - reinsert output (full copy of unpack/ with only
//                              translated .mes files overwritten)
//   output/                 - packed .nds output
//   project-state.json      - { romPath, projectName, createdAt, extractedAt }

const fs = require("fs");
const path = require("path");
const { execFile } = require("child_process");

const WORKSPACE_ROOT = path.resolve(__dirname, "..", "..", "workspace");
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const NITROPACKER_BIN = path.join(REPO_ROOT, "NitroPacker");

const NAME_RE = /^[A-Za-z0-9_-]+$/;

function assertValidName(name) {
  if (typeof name !== "string" || !NAME_RE.test(name)) {
    throw new Error(`invalid project name: ${JSON.stringify(name)} (use letters/digits/_/- only)`);
  }
}

function projectDir(name) {
  assertValidName(name);
  return path.join(WORKSPACE_ROOT, name);
}

function unpackDir(name) {
  return path.join(projectDir(name), "unpack");
}

function scriptDir(name) {
  return path.join(unpackDir(name), "data", "Script");
}

function csvDir(name) {
  return path.join(projectDir(name), "translations");
}

function originalRomPath(name) {
  return path.join(projectDir(name), "original.nds");
}

function buildDir(name) {
  return path.join(projectDir(name), "build");
}

function buildScriptDir(name) {
  return path.join(buildDir(name), "data", "Script");
}

function outputDir(name) {
  return path.join(projectDir(name), "output");
}

function statePath(name) {
  return path.join(projectDir(name), "project-state.json");
}

function readState(name) {
  const p = statePath(name);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

function writeState(name, patch) {
  fs.mkdirSync(projectDir(name), { recursive: true });
  const prev = readState(name) || {};
  const next = { ...prev, ...patch, projectName: name };
  fs.writeFileSync(statePath(name), JSON.stringify(next, null, 2));
  return next;
}

function listProjects() {
  if (!fs.existsSync(WORKSPACE_ROOT)) return [];
  return fs
    .readdirSync(WORKSPACE_ROOT, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .filter((name) => NAME_RE.test(name))
    .map((name) => readState(name))
    .filter(Boolean);
}

/** Find the NitroPacker project JSON file inside a project's unpack/build dir. */
function findProjectJson(dir) {
  if (!fs.existsSync(dir)) return null;
  const hit = fs.readdirSync(dir).find((f) => f.toLowerCase().endsWith(".json"));
  return hit ? path.join(dir, hit) : null;
}

/** Run the compiled NitroPacker CLI binary with the given argv, Promise-wrapped. */
function runNitroPacker(args) {
  return new Promise((resolve, reject) => {
    execFile(NITROPACKER_BIN, args, { maxBuffer: 64 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) {
        reject(new Error(`NitroPacker ${args.join(" ")} failed: ${err.message}\n${stdout}\n${stderr}`));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

module.exports = {
  WORKSPACE_ROOT,
  NITROPACKER_BIN,
  runNitroPacker,
  assertValidName,
  projectDir,
  unpackDir,
  scriptDir,
  csvDir,
  originalRomPath,
  buildDir,
  buildScriptDir,
  outputDir,
  statePath,
  readState,
  writeState,
  listProjects,
  findProjectJson,
};
