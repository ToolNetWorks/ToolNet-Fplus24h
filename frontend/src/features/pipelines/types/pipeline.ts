export type PipelineStatus = "active" | "disabled";

export interface CreatePipelineInput {
  name: string;
  status: PipelineStatus;
  ctv_username: string;
  ctv_email: string;
  ctv_password: string;
  ctv_password_confirm: string;
}

export interface PipelineResult {
  id: string;
  name: string;
  status: PipelineStatus;
  ctv: {
    id: number;
    username: string;
    email: string;
  };
}
