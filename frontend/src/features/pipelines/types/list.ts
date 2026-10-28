import type { PipelineStatus } from "./pipeline";

export type PipelineStatusFilter =
  | PipelineStatus
  | "all";

export interface PipelineListItem {
  id: string;
  name: string;
  status: PipelineStatus;
  created_at: string;
  ctv: {
    id: number;
    username: string;
    email: string;
    is_active: boolean;
  };
}

export interface PipelinePagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface PipelineListResponse {
  success: boolean;
  data: PipelineListItem[];
  pagination: PipelinePagination;
  message?: string;
}

export interface PipelineListParams {
  page: number;
  pageSize: number;
  search: string;
  status: PipelineStatusFilter;
}
