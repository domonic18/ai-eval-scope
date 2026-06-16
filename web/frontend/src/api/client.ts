import axios from "axios";
import type {
  Project,
  RunSummary,
  RunIndexEntry,
  TrendData,
  TaskDetail,
  DirectoryManifest,
} from "../types";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "",
  headers: {
    "Content-Type": "application/json",
  },
});

export const getProjects = () =>
  api.get<{ projects: Project[] }>("/api/projects").then((r) => r.data.projects);

export const getProject = (id: string) =>
  api.get<Project>(`/api/projects/${id}`).then((r) => r.data);

export const getProjectRuns = (id: string) =>
  api.get<{ runs: RunIndexEntry[] }>(`/api/projects/${id}/runs`).then((r) => r.data.runs);

export const getProjectTrends = (id: string) =>
  api.get<TrendData>(`/api/projects/${id}/trends`).then((r) => r.data);

export const getRun = (id: string) =>
  api.get<RunSummary>(`/api/runs/${id}`).then((r) => r.data);

export const getRunTasks = (id: string) =>
  api.get<{ tasks: string[] }>(`/api/runs/${id}/tasks`).then((r) => r.data.tasks);

export const getTaskDetail = (runId: string, taskId: string) =>
  api.get<TaskDetail>(`/api/runs/${runId}/tasks/${taskId}`).then((r) => r.data);

export const getTaskManifest = (runId: string, taskId: string) =>
  api
    .get<DirectoryManifest>(`/api/runs/${runId}/tasks/${taskId}/manifest`)
    .then((r) => r.data);

export const rebuildIndex = () => api.post<{ status: string; run_count: number; project_count: number }>("/api/index/rebuild");

export const getEvidenceUrl = (runId: string, taskId: string, file: string) =>
  `/api/runs/${runId}/tasks/${taskId}/evidence/${file}`;

export default api;
