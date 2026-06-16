"use strict";

const express = require("express");
const path = require("path");
const fs = require("fs");
const {
  resolveWorkspaceDir,
  safeReadJson,
  listDirectories,
  listFiles,
  safeResolve,
} = require("../services/workspace-reader");

const router = express.Router();

function getWorkspaceDir() {
  return resolveWorkspaceDir();
}

/**
 * GET /api/runs/:id
 */
router.get("/:id", (req, res) => {
  const runId = req.params.id;
  const workspaceDir = getWorkspaceDir();
  const runDir = safeResolve(path.join(workspaceDir, "runs"), runId);
  if (!runDir) {
    return res.status(400).json({ error: "Invalid run id", id: runId });
  }
  const summaryPath = path.join(runDir, "reports", "summary.json");
  const summary = safeReadJson(summaryPath);
  if (!summary) {
    return res.status(404).json({ error: "Run summary not found", id: runId });
  }
  res.json(summary);
});

/**
 * GET /api/runs/:id/tasks
 */
router.get("/:id/tasks", (req, res) => {
  const runId = req.params.id;
  const workspaceDir = getWorkspaceDir();
  const runDir = safeResolve(path.join(workspaceDir, "runs"), runId);
  if (!runDir) {
    return res.status(400).json({ error: "Invalid run id", id: runId });
  }
  const resultsDir = path.join(runDir, "results");
  const tasks = listDirectories(resultsDir);
  res.json({ tasks });
});

/**
 * GET /api/runs/:id/tasks/:task_id
 */
router.get("/:id/tasks/:task_id", (req, res) => {
  const runId = req.params.id;
  const taskId = req.params.task_id;
  const workspaceDir = getWorkspaceDir();

  const runDir = safeResolve(path.join(workspaceDir, "runs"), runId);
  if (!runDir) {
    return res.status(400).json({ error: "Invalid run id", id: runId });
  }
  const resultDir = safeResolve(path.join(runDir, "results"), taskId);
  if (!resultDir) {
    return res.status(400).json({ error: "Invalid task id", task_id: taskId });
  }

  const ruleResults = safeReadJson(path.join(resultDir, "rule_results.json"), []);
  const scores = safeReadJson(path.join(resultDir, "scores.json"), {});
  const report = safeReadJson(path.join(resultDir, "report.json"), {});
  const evidenceFiles = listFiles(path.join(resultDir, "evidence"));

  res.json({
    run_id: runId,
    task_id: taskId,
    rule_results: ruleResults,
    scores,
    report,
    evidence_files: evidenceFiles,
  });
});

/**
 * GET /api/runs/:id/tasks/:task_id/evidence/:file
 */
router.get("/:id/tasks/:task_id/evidence/:file", (req, res) => {
  const runId = req.params.id;
  const taskId = req.params.task_id;
  const fileName = path.basename(req.params.file);
  const workspaceDir = getWorkspaceDir();

  const runDir = safeResolve(path.join(workspaceDir, "runs"), runId);
  if (!runDir) {
    return res.status(400).json({ error: "Invalid run id", id: runId });
  }
  const resultDir = safeResolve(path.join(runDir, "results"), taskId);
  if (!resultDir) {
    return res.status(400).json({ error: "Invalid task id", task_id: taskId });
  }
  const evidenceDir = path.join(resultDir, "evidence");
  const filePath = safeResolve(evidenceDir, fileName);
  if (!filePath || !fs.existsSync(filePath)) {
    return res.status(404).json({ error: "Evidence file not found", file: fileName });
  }
  res.sendFile(filePath);
});

/**
 * GET /api/runs/:id/tasks/:task_id/manifest
 */
router.get("/:id/tasks/:task_id/manifest", (req, res) => {
  const runId = req.params.id;
  const taskId = req.params.task_id;
  const workspaceDir = getWorkspaceDir();

  const runDir = safeResolve(path.join(workspaceDir, "runs"), runId);
  if (!runDir) {
    return res.status(400).json({ error: "Invalid run id", id: runId });
  }
  const packageDir = safeResolve(path.join(runDir, "packages"), taskId);
  if (!packageDir) {
    return res.status(400).json({ error: "Invalid task id", task_id: taskId });
  }
  const manifestPath = path.join(packageDir, "output", "_manifest.json");
  const manifest = safeReadJson(manifestPath);
  // 非目录模式打包时 manifest 不存在，返回空对象避免前端 404
  res.json(manifest || {});
});

module.exports = router;
