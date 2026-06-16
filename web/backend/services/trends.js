"use strict";

const { DEFAULT_THRESHOLDS } = require("./indexer");

/**
 * Compute trend data points for a project.
 * @param {string} projectId
 * @param {{runs: any[]}} runsIndex
 * @returns {{
 *   project_id: string,
 *   metrics: string[],
 *   data_points: any[],
 *   thresholds: Record<string, number>
 * }}
 */
function computeTrends(projectId, runsIndex) {
  const runs = (runsIndex.runs || [])
    .filter((r) => r.project === projectId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const dataPoints = runs.map((run) => ({
    run_id: run.run_id,
    created_at: run.created_at,
    DR: run.metrics.DR ?? 0,
    CPR: run.metrics.CPR ?? 0,
    Reward: run.metrics.avg_reward ?? 0,
  }));

  return {
    project_id: projectId,
    metrics: ["DR", "CPR", "Reward"],
    data_points: dataPoints,
    thresholds: DEFAULT_THRESHOLDS,
  };
}

module.exports = { computeTrends };
