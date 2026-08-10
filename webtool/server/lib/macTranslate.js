"use strict";

/**
 * macOS built-in Translation framework backend (the on-device NMT engine
 * behind macOS/Safari's "번역" feature) - NOT the FoundationModels LLM.
 * FoundationModels was tried first but frequently just echoed/reorganized
 * the Japanese source instead of translating it (see
 * analysis/ANALYSIS_NOTES.md 2026-08-10 entry). TranslationSession is a
 * dedicated translator and reliably translates while passing <HEX>/<이름>
 * control tags through untouched.
 *
 * Node cannot call the Swift-only Translation framework directly, so this
 * shells out to a small bundled Swift CLI (webtool/native/mac-translate)
 * via stdin/stdout JSON.
 */

const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const NATIVE_DIR = path.join(__dirname, "..", "..", "native", "mac-translate");
const BIN_PATH = path.join(NATIVE_DIR, ".build", "release", "mac-translate");

function ensureBuilt(onProgress) {
  return new Promise((resolve, reject) => {
    if (fs.existsSync(BIN_PATH)) return resolve();

    if (onProgress) onProgress("macOS 번역 엔진을 처음 빌드하는 중입니다 (최초 1회, 수십 초 소요)...");

    const child = spawn("swift", ["build", "-c", "release"], {
      cwd: NATIVE_DIR,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let errBuf = "";
    child.stderr.on("data", (d) => (errBuf += d.toString()));
    child.on("error", (err) => reject(new Error(`swift 빌드 명령을 실행할 수 없습니다: ${err.message}`)));
    child.on("close", (code) => {
      if (code !== 0 || !fs.existsSync(BIN_PATH)) {
        return reject(new Error(`macOS 번역 엔진 빌드 실패: ${errBuf.slice(-2000)}`));
      }
      resolve();
    });
  });
}

function runBinary(items, onProgress) {
  return new Promise((resolve, reject) => {
    const child = spawn(BIN_PATH, [], { stdio: ["pipe", "pipe", "pipe"] });

    let stdout = "";
    let stderrTail = "";

    child.stdout.on("data", (d) => (stdout += d));

    let stderrBuf = "";
    child.stderr.on("data", (d) => {
      stderrBuf += d.toString();
      const lines = stderrBuf.split("\n");
      stderrBuf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        stderrTail = line;
        if (onProgress) onProgress(line.trim());
      }
    });

    child.on("error", (err) => reject(new Error(`mac-translate 실행 실패: ${err.message}`)));
    child.on("close", (code) => {
      if (code !== 0) {
        return reject(new Error(`mac-translate 종료 코드 ${code}: ${stderrTail}`));
      }
      try {
        resolve(JSON.parse(stdout));
      } catch (ex) {
        reject(new Error(`mac-translate 출력 JSON 파싱 실패: ${ex.message}`));
      }
    });

    child.stdin.write(JSON.stringify(items));
    child.stdin.end();
  });
}

async function translateBatch(items, onProgress) {
  if (process.platform !== "darwin") {
    throw new Error("macOS 번역 엔진은 macOS에서만 사용할 수 있습니다.");
  }

  await ensureBuilt(onProgress);
  return runBinary(items, onProgress);
}

module.exports = { translateBatch };
