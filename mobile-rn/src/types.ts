// 与后端 FastAPI 响应对齐（snake_case 字段）

export interface HealthResponse {
  status: string;
  agent_runtime?: {
    active_client?: string;
    mode?: string;
    model_name?: string;
    degraded?: boolean;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface CopilotSession {
  session_id: string;
  title?: string;
  [key: string]: unknown;
}

export interface CopilotRun {
  run_id: string;
  session_id?: string;
  [key: string]: unknown;
}
