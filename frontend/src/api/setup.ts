import { apiGet, apiPost } from "./client";

export type SetupStatus = {
  completed: boolean;
  required: boolean;
  model_connected: boolean;
  default_model: string | null;
  demo?: boolean;
};

export function fetchSetupStatus(): Promise<SetupStatus> {
  return apiGet<SetupStatus>("/api/setup");
}

export function finishSetup(): Promise<SetupStatus> {
  return apiPost<SetupStatus>("/api/setup/finish", {});
}
