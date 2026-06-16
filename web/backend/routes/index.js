"use strict";

const express = require("express");
const { rebuild } = require("../services/indexer");

const router = express.Router();

/**
 * POST /api/index/rebuild
 */
router.post("/rebuild", (req, res) => {
  try {
    const stats = rebuild();
    res.json({
      status: "ok",
      run_count: stats.run_count,
      project_count: stats.project_count,
    });
  } catch (err) {
    res.status(500).json({ error: err.message || "Index rebuild failed" });
  }
});

module.exports = router;
