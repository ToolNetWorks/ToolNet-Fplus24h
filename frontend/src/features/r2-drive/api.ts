export type DriveEntry = {
  kind: 'pipeline' | 'album' | 'image' | 'prefix' | 'object';
  id: string;
  name: string;
  pipeline_id?: string;
  pipeline_name?: string;
  ctv_name?: string;
  album_id?: string;
  album_name?: string;
  image_count?: number;
  album_count?: number;
  file_size?: number;
  width?: number | null;
  height?: number | null;
  mime_type?: string;
  status?: string;
  created_at?: string;
  thumbnail_url?: string | null;
  preview_url?: string | null;
  download_url?: string | null;
  metadata_url?: string;
};
export type DriveLocation = {
  pipeline?: { id: string; name: string; pipelineName: string };
  album?: { id: string; name: string };
  raw?: boolean;
  prefixRef?: string;
};
export type PrefixCrumb = { name: string; ref: string };
export type DrivePage = {
  items: DriveEntry[];
  breadcrumbs?: PrefixCrumb[];
  next_cursor?: string | null;
  context?: { pipeline_id?: string; pipeline_name?: string; ctv_name?: string; album_id?: string; album_name?: string };
  pagination: { page?: number; total?: number; total_pages?: number; has_next: boolean; has_previous?: boolean; page_size: number };
};
export const DRIVE_BASE = '/api/v1/admin/config/r2-drive';

export async function readDrive<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal });
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(response.status === 403 ? 'Chỉ Super Admin được truy cập R2 Drive.' : result?.detail || result?.error || `Không đọc được dữ liệu (HTTP ${response.status}).`);
  }
  if (!result) throw new Error('Phản hồi máy chủ không hợp lệ.');
  return result as T;
}

export function driveUrl(location: DriveLocation, search: string, page: number, cursor: string): string {
  const params = new URLSearchParams({ page_size: '24' });
  if (location.raw) {
    if (location.prefixRef) params.set('ref', location.prefixRef);
    if (cursor) params.set('cursor', cursor);
    return `${DRIVE_BASE}/prefixes/?${params}`;
  }
  params.set('page', String(page));
  if (search.trim()) params.set('q', search.trim());
  let path = DRIVE_BASE;
  if (location.pipeline) path += `/pipelines/${encodeURIComponent(location.pipeline.id)}`;
  if (location.album) path += `/albums/${encodeURIComponent(location.album.id)}`;
  return `${path}/?${params}`;
}

export function formatBytes(value?: number) {
  if (value === undefined) return '—';
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}

export function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString('vi-VN') : '—';
}

export function statusLabel(status?: string) {
  return ({ ready: 'Sẵn sàng', pending: 'Chờ upload', failed: 'Upload thất bại', deleting: 'Đang xóa', enabled: 'Đang bật', disabled: 'Tạm khóa', active: 'Hoạt động', stored: 'Đã lưu trên R2' } as Record<string, string>)[status ?? ''] ?? status ?? '—';
}
