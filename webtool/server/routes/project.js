"use strict";

const express = require("express");
const multer = require("multer");
const fs = require("fs");
const path = require("path");

const proj = require("../lib/project");
const pipeline = require("../lib/pipeline");

const router = express.Router();

// 브라우저는 로컬 파일의 절대경로를 노출하지 않으므로(드래그앤드롭도 동일), 경로 입력 대신
// 파일 자체를 업로드받아 서버 워크스페이스에 저장한 뒤 그 경로로 NitroPacker를 실행한다.
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 512 * 1024 * 1024 },
});

// POST /api/project/unpack  multipart/form-data: romFile, projectName
router.post("/unpack", upload.single("romFile"), async (req, res) => {
  const projectName = req.body && req.body.projectName;
  const file = req.file;
  if (!file || !projectName) {
    return res.status(400).json({ error: "romFile, projectName은 필수입니다" });
  }
  try {
    proj.assertValidName(projectName);
  } catch (ex) {
    return res.status(400).json({ error: ex.message });
  }
  if (!file.originalname.toLowerCase().endsWith(".nds")) {
    return res.status(400).json({ error: `.nds 롬 파일이 아닙니다: ${file.originalname}` });
  }

  try {
    const romPath = proj.originalRomPath(projectName);
    fs.mkdirSync(proj.projectDir(projectName), { recursive: true });
    fs.writeFileSync(romPath, file.buffer);

    const unpackDir = proj.unpackDir(projectName);
    fs.mkdirSync(unpackDir, { recursive: true });
    await proj.runNitroPacker(["unpack", "-r", romPath, "-o", unpackDir, "-n", projectName]);

    const scriptDir = proj.scriptDir(projectName);
    const mesCount = fs.existsSync(scriptDir)
      ? fs.readdirSync(scriptDir).filter((f) => f.toLowerCase().endsWith(".mes")).length
      : 0;

    const state = proj.writeState(projectName, {
      romFileName: file.originalname,
      romPath,
      createdAt: new Date().toISOString(),
    });

    res.json({ ok: true, state, mesCount });
  } catch (ex) {
    res.status(500).json({ error: ex.message });
  }
});

router.get("/list", (req, res) => {
  res.json(proj.listProjects());
});

router.get("/status", (req, res) => {
  const { name } = req.query;
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  const state = proj.readState(name);
  if (!state) return res.status(404).json({ error: "프로젝트를 찾을 수 없습니다" });

  const summaries = pipeline.fileSummaries(name);
  res.json({
    state,
    csvExists: fs.existsSync(proj.csvDir(name)),
    totalBlocks: summaries.reduce((a, s) => a + s.blockCount, 0),
    translatedBlocks: summaries.reduce((a, s) => a + s.translatedCount, 0),
    buildExists: fs.existsSync(proj.buildDir(name)),
    outputExists: fs.existsSync(proj.outputDir(name)) && fs.readdirSync(proj.outputDir(name)).some((f) => f.endsWith(".nds")),
  });
});

module.exports = router;
