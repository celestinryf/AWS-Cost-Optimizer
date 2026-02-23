import type {
  ExecuteRequest,
  ExecuteResponse,
  ExecutionAuditRecord,
  RollbackRequest,
  RollbackResponse,
  RunDetails,
  RunSummary,
  ScanRequest,
  ScanResponse,
  ScoreRequest,
  ScoreResponse,
} from "../types";

const BASE = "http://127.0.0.1:8000/api/v1";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore JSON parse errors
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // Health
  health: () => request<{ status: string }>("/health"),

  // Optimizer workflow
  scan: (req: ScanRequest) =>
    request<ScanResponse>("/optimizer/scan", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  score: (req: ScoreRequest) =>
    request<ScoreResponse>("/optimizer/score", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  execute: (req: ExecuteRequest) =>
    request<ExecuteResponse>("/optimizer/execute", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  rollback: (req: RollbackRequest) =>
    request<RollbackResponse>("/optimizer/rollback", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  // Run queries
  listRuns: () => request<RunSummary[]>("/optimizer/runs"),

  getRun: (runId: string) => request<RunDetails>(`/optimizer/runs/${runId}`),

  getAudit: (runId: string, executionId?: string) => {
    const qs = executionId ? `?execution_id=${encodeURIComponent(executionId)}` : "";
    return request<ExecutionAuditRecord[]>(`/optimizer/runs/${runId}/audit${qs}`);
  },
};

export { ApiError };
