"use strict";

const fs = require("fs");
const path = require("path");
const yaml = require("js-yaml");

/**
 * Resolve workspace directory from env or default.
 * @returns {string}
 */
function resolveWorkspaceDir() {
  return path.resolve(process.env.WORKSPACE_DIR || "./workspace");
}

/**
 * Resolve assets directory (project configs live in assets/projects).
 * Defaults to workspace/../assets.
 * @returns {string}
 */
function resolveAssetsDir() {
  return path.resolve(
    process.env.ASSETS_DIR || path.join(resolveWorkspaceDir(), "..", "assets")
  );
}

/**
 * Read JSON file safely, returning defaultValue if missing or invalid.
 * @param {string} filePath
 * @param {any} defaultValue
 * @returns {any}
 */
function safeReadJson(filePath, defaultValue = null) {
  if (!fs.existsSync(filePath)) {
    return defaultValue;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch (err) {
    console.warn(`Failed to read JSON ${filePath}: ${err.message}`);
    return defaultValue;
  }
}

/**
 * Read YAML file safely, returning defaultValue if missing or invalid.
 * @param {string} filePath
 * @param {any} defaultValue
 * @returns {any}
 */
function safeReadYaml(filePath, defaultValue = null) {
  if (!fs.existsSync(filePath)) {
    return defaultValue;
  }
  try {
    return yaml.load(fs.readFileSync(filePath, "utf-8"));
  } catch (err) {
    console.warn(`Failed to read YAML ${filePath}: ${err.message}`);
    return defaultValue;
  }
}

/**
 * List subdirectories of a directory.
 * @param {string} dir
 * @returns {string[]}
 */
function listDirectories(dir) {
  if (!fs.existsSync(dir)) {
    return [];
  }
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort();
}

/**
 * List files in a directory.
 * @param {string} dir
 * @returns {string[]}
 */
function listFiles(dir) {
  if (!fs.existsSync(dir)) {
    return [];
  }
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isFile())
    .map((d) => d.name)
    .sort();
}

/**
 * Validate that a path stays within a base directory (prevent directory traversal).
 * @param {string} baseDir
 * @param {string} targetPath
 * @returns {string | null} resolved path or null if invalid
 */
function safeResolve(baseDir, targetPath) {
  const resolvedBase = path.resolve(baseDir);
  const resolvedTarget = path.resolve(resolvedBase, targetPath);
  if (!resolvedTarget.startsWith(resolvedBase + path.sep) && resolvedTarget !== resolvedBase) {
    return null;
  }
  return resolvedTarget;
}

module.exports = {
  resolveWorkspaceDir,
  resolveAssetsDir,
  safeReadJson,
  safeReadYaml,
  listDirectories,
  listFiles,
  safeResolve,
};
