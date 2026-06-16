"use strict";

const express = require("express");
const path = require("path");
const {
  resolveWorkspaceDir,
  resolveAssetsDir,
  safeReadJson,
  safeReadYaml,
  safeResolve,
} = require("../services/workspace-reader");
const { computeTrends } = require("../services/trends");

const router = express.Router();

function getWorkspaceDir() {
  return resolveWorkspaceDir();
}

function getAssetsDir() {
  return resolveAssetsDir();
}

/**
 * GET /api/projects
 */
router.get("/", (req, res) => {
  const workspaceDir = getWorkspaceDir();
  const projectsPath = path.join(workspaceDir, "index", "projects.json");
  const runsPath = path.join(workspaceDir, "index", "runs_index.json");

  const projectsIndex = safeReadJson(projectsPath, { projects: [] });
  const runsIndex = safeReadJson(runsPath, { runs: [] });

  // Build latest metric lookup from runs_index
  const latestMetrics = new Map();
  for (const run of runsIndex.runs || []) {
    if (!latestMetrics.has(run.project)) {
      latestMetrics.set(run.project, run.metrics || {});
    }
  }

  const enriched = (projectsIndex.projects || []).map((proj) => {
    const metrics = latestMetrics.get(proj.id) || {};
    return {
      ...proj,
      latest_run: proj.latest_run_id
        ? {
            run_id: proj.latest_run_id,
            created_at: findRunCreatedAt(runsIndex, proj.latest_run_id),
            dr: metrics.DR ?? 0,
            cpr: metrics.CPR ?? 0,
            avg_reward: metrics.avg_reward ?? 0,
          }
        : null,
    };
  });

  res.json({ projects: enriched });
});

function findRunCreatedAt(runsIndex, runId) {
  const run = (runsIndex.runs || []).find((r) => r.run_id === runId);
  return run ? run.created_at : "";
}

/**
 * GET /api/projects/:id
 */
router.get("/:id", (req, res) => {
  const projectId = req.params.id;
  const workspaceDir = getWorkspaceDir();
  const assetsDir = getAssetsDir();

  const projectsPath = path.join(workspaceDir, "index", "projects.json");
  const projectsIndex = safeReadJson(projectsPath, { projects: [] });
  const project = (projectsIndex.projects || []).find((p) => p.id === projectId);

  if (!project) {
    // Fallback to reading assets/projects/{id}.yaml directly
    const projFile = path.join(assetsDir, "projects", `${projectId}.yaml`);
    const raw = safeReadYaml(projFile);
    if (!raw) {
      return res.status(404).json({ error: "Project not found", id: projectId });
    }
    const data = raw.project || raw;
    return res.json({
      id: projectId,
      name: data.name || projectId,
      description: data.description || "",
      default_rule_set: data.default_rule_set || "",
      default_task_set: data.default_task_set || "",
      created_at: data.created_at || "",
      latest_run_id: null,
      run_count: 0,
    });
  }

  res.json(project);
});

/**
 * GET /api/projects/:id/runs
 */
router.get("/:id/runs", (req, res) => {
  const projectId = req.params.id;
  const workspaceDir = getWorkspaceDir();
  const runsPath = path.join(workspaceDir, "index", "runs_index.json");
  const runsIndex = safeReadJson(runsPath, { runs: [] });

  const runs = (runsIndex.runs || []).filter((r) => r.project === projectId);
  res.json({ runs });
});

/**
 * GET /api/projects/:id/trends
 */
router.get("/:id/trends", (req, res) => {
  const projectId = req.params.id;
  const workspaceDir = getWorkspaceDir();
  const runsPath = path.join(workspaceDir, "index", "runs_index.json");
  const runsIndex = safeReadJson(runsPath, { runs: [] });

  const trends = computeTrends(projectId, runsIndex);
  res.json(trends);
});

module.exports = router;
