"use strict";

const express = require("express");
const path = require("path");

const projectRoutes = require("./routes/project");
const csvRoutes = require("./routes/csv");
const buildRoutes = require("./routes/build");
const fileRoutes = require("./routes/files");

const app = express();
const PORT = process.env.PORT || 4000;

app.use(express.json({ limit: "10mb" }));

app.use("/api/project", projectRoutes);
app.use("/api/csv", csvRoutes);
app.use("/api/build", buildRoutes);
app.use("/api/files", fileRoutes);

app.use(express.static(path.join(__dirname, "..", "public")));

app.listen(PORT, () => {
  console.log(`DOM 한글패치 툴 서버 실행 중: http://localhost:${PORT}`);
});
