"use strict";

const express = require("express");
const fs = require("fs");
const path = require("path");

const proj = require("../lib/project");
const pipeline = require("../lib/pipeline");
const mc = require("../lib/mesCodec");

const router = express.Router();

function groupCsvByFile(rows) {
  const byFile = new Map();
  for (const row of rows) {
    if (!byFile.has(row.file)) byFile.set(row.file, new Map());
    byFile.get(row.file).set(Number(row.block), row);
  }
  return byFile;
}

function parseBlockFromMessage(msg) {
  const m = /^block (\d+):\s*(.*)$/.exec(msg);
  if (!m) return { block: null, message: msg };
  return { block: Number(m[1]), message: m[2] };
}

router.post("/reinsert", (req, res) => {
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  const state = proj.readState(name);
  if (!state) return res.status(404).json({ error: "프로젝트를 찾을 수 없습니다" });

  const unpackDir = proj.unpackDir(name);
  if (!fs.existsSync(unpackDir)) return res.status(400).json({ error: "먼저 롬을 언팩해야 합니다" });

  try {
    const rows = pipeline.readCsv(name);
    if (!rows.length) return res.status(400).json({ error: "CSV가 비어 있습니다. 먼저 CSV를 생성하세요" });

    const buildDir = proj.buildDir(name);
    fs.rmSync(buildDir, { recursive: true, force: true });
    fs.cpSync(unpackDir, buildDir, { recursive: true });

    const byFile = groupCsvByFile(rows);
    let filesWritten = 0;
    let filesSkipped = 0;
    const problems = [];

    for (const [fname, rowsByBlock] of byFile) {
      let hasTranslation = false;
      for (const r of rowsByBlock.values()) {
        if (r.translation && r.translation.trim()) {
          hasTranslation = true;
          break;
        }
      }
      if (!hasTranslation) continue;

      const { tokens, relPath, problems: fileProblems } = pipeline.buildFileTokens(name, fname, rowsByBlock);
      if (fileProblems.length) {
        filesSkipped += 1;
        for (const msg of fileProblems) {
          problems.push({ file: fname, ...parseBlockFromMessage(msg) });
        }
        continue;
      }
      const outPath = relPath
        ? path.join(buildDir, "data", relPath)
        : path.join(proj.buildScriptDir(name), fname);
      mc.dumpValues(tokens, outPath);
      filesWritten += 1;
    }

    // Apply Korean BDF font art into build/data/Font_DOM.nbfc
    pipeline.applyFontArt(name);

    proj.writeState(name, { reinsertedAt: new Date().toISOString() });
    res.json({ filesWritten, filesSkipped, problems });
  } catch (ex) {
    res.status(500).json({ error: ex.message });
  }
});

router.post("/pack", async (req, res) => {
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  const state = proj.readState(name);
  if (!state) return res.status(404).json({ error: "프로젝트를 찾을 수 없습니다" });

  const buildDir = proj.buildDir(name);
  if (!fs.existsSync(buildDir)) return res.status(400).json({ error: "먼저 재삽입(reinsert)을 실행해야 합니다" });

  const projectJson = proj.findProjectJson(buildDir);
  if (!projectJson) return res.status(500).json({ error: `build/ 안에서 NitroPacker 프로젝트 JSON을 찾을 수 없습니다: ${buildDir}` });

  try {
    const outDir = proj.outputDir(name);
    fs.mkdirSync(outDir, { recursive: true });
    const outPath = path.join(outDir, `${name}.nds`);
    await proj.runNitroPacker(["pack", "-p", projectJson, "-r", outPath]);
    proj.writeState(name, { packedAt: new Date().toISOString() });
    res.json({ ok: true, outputPath: outPath });
  } catch (ex) {
    res.status(500).json({ error: ex.message });
  }
});

router.get("/download", (req, res) => {
  const { name } = req.query;
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  const outPath = path.join(proj.outputDir(name), `${name}.nds`);
  if (!fs.existsSync(outPath)) return res.status(404).json({ error: "빌드된 ROM이 없습니다. 먼저 빌드하세요" });
  res.download(outPath, `${name}.nds`);
});

module.exports = router;
