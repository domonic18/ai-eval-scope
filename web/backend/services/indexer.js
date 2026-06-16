"use strict";

const fs = require("fs");
const path = require("path");
const {
  resolveWorkspaceDir,
  resolveAssetsDir,
  safeReadJson,
  safeReadYaml,
  listDirectories,
} = require("./workspace-reader");

const DEFAULT_THRESHOLDS = {
  DR: 0.95,
  CPR: 0.9,
  Reward: 0.7,
};

/**
 * Atomic write: write to temp file then rename.
 * @param {string} targetPath
 * @param {string} content
 */
function atomicWrite(targetPath, content) {
  const dir = path.dirname(targetPath);
  fs.mkdirSync(dir, { recursive: true });
  const tmpPath = `${targetPath}.tmp`;
  fs.writeFileSync(tmpPath, content, "utf-8");
  fs.renameSync(tmpPath, targetPath);
}

/**
 * Build runs_index.json by scanning workspace/runs.
 * @param {string} workspaceDir
 * @returns {{runs: any[]}}
 */
function buildRunsIndex(workspaceDir) {
  const runsDir = path.join(workspaceDir, "runs");
  const runs = [];

  if (fs.existsSync(runsDir)) {
    const runIds = listDirectories(runsDir).sort().reverse();
    for (const runId of runIds) {
      const runDir = path.join(runsDir, runId);
      const summaryPath = path.join(runDir, "reports", "summary.json");
      const manifestPath = path.join(runDir, "run_manifest.json");

      const summary = safeReadJson(summaryPath);
      if (!summary) continue;

      const manifest = safeReadJson(manifestPath, {});
      const entry = {
        run_id: summary.run_id || runId,
        mode: manifest.mode || "unknown",
        total_samples: summary.total_samples || 0,
        metrics: summary.metrics || {},
        failure_breakdown: summary.failure_breakdown || {},
        created_at: manifest.created_at || "",
        project: manifest.project || null,
      };
      runs.push(entry);
    }
  }

  return { runs };
}

/**
 * Load project configs from assets/projects/*.yaml.
 * @param {string} assetsDir
 * @returns {{projects: any[]}}
 */
function loadProjects(assetsDir) {
  const projectsDir = path.join(assetsDir, "projects");
  const projects = [];

  if (fs.existsSync(projectsDir)) {
    const files = fs
      .readdirSync(projectsDir)
      .filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"))
      .sort();
    for (const file of files) {
      const filePath = path.join(projectsDir, file);
      const raw = safeReadYaml(filePath, {});
      const data = raw.project || raw;
      const projectId = data.id || path.basename(file, path.extname(file));
      projects.push({
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
  }

  return { projects };
}

/**
 * Cross-reference projects with runs to compute run_count and latest_run_id.
 * @param {{projects: any[]}} projectsIndex
 * @param {{runs: any[]}} runsIndex
 */
function crossReferenceProjects(projectsIndex, runsIndex) {
  const projMap = new Map(projectsIndex.projects.map((p) => [p.id, p]));
  for (const run of runsIndex.runs) {
    const projectId = run.project;
    if (projectId && projMap.has(projectId)) {
      const proj = projMap.get(projectId);
      proj.run_count += 1;
      if (!proj.latest_run_id) {
        proj.latest_run_id = run.run_id;
      }
    }
  }
}

/**
 * Rebuild workspace index files.
 * @param {string} [workspaceDir]
 * @param {string} [assetsDir]
 * @returns {{run_count: number, project_count: number}}
 */
function rebuild(workspaceDir, assetsDir) {
  const ws = workspaceDir || resolveWorkspaceDir();
  const assets = assetsDir || resolveAssetsDir();
  const indexDir = path.join(ws, "index");

  const runsIndex = buildRunsIndex(ws);
  const projectsIndex = loadProjects(assets);
  crossReferenceProjects(projectsIndex, runsIndex);

  atomicWrite(
    path.join(indexDir, "runs_index.json"),
    JSON.stringify(runsIndex, null, 2)
  );
  atomicWrite(
    path.join(indexDir, "projects.json"),
    JSON.stringify(projectsIndex, null, 2)
  );

  return {
    run_count: runsIndex.runs.length,
    project_count: projectsIndex.projects.length,
  };
}

module.exports = {
  rebuild,
  buildRunsIndex,
  loadProjects,
  crossReferenceProjects,
  DEFAULT_THRESHOLDS,
};
