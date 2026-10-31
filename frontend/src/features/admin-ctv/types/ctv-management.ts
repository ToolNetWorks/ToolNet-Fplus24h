import type { PipelineStatus } from "@/features/pipelines/types/pipeline";

export type CTVStatusFilter = PipelineStatus | "all";

export interface CTVListItem {
  id: string;
  pipeline: {
    id: string;
    name: string;
    status: PipelineStatus;
    created_at: string;
  } | null;
  ctv: {
    id: number;
    username: string;
    email: string;
    is_active: boolean;
    last_login: string | null;
  };
}

export interface CTVPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface CTVListResponse {
  success: boolean;
  data: CTVListItem[];
  pagination: CTVPagination;
  message?: string;
}

export interface CTVListParams {
  page: number;
  pageSize: number;
  search: string;
  status: CTVStatusFilter;
}

export interface CreateCTVInput {
  name: string;
  status: PipelineStatus;
  ctv_username: string;
  ctv_email: string;
  ctv_password: string;
  ctv_password_confirm: string;
}

export interface CTVAuditLogItem {
  id: number;
  created_at: string;
  admin: {
    id: number;
    username: string;
  };
  action:
    | "create_ctv"
    | "lock_ctv"
    | "unlock_ctv"
    | "reset_password";
  action_label: string;
  pipeline_id: string | null;
  pipeline_name: string;
  ctv_id: number | null;
  ctv_username: string;
}

export interface CTVAuditLogResponse {
  success: boolean;
  data: CTVAuditLogItem[];
  pagination: CTVPagination;
  message?: string;
}

export interface CTVAuditLogParams {
  page: number;
  pageSize: number;
}
