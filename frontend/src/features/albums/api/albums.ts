import { getCsrfToken } from "@/features/auth/api/auth-client";
export interface Album {
  id: string;
  pipeline_id: string;
  name: string;
  description: string;
  is_enabled: boolean;
  image_count: number;
  created_at: string;
  updated_at: string;
}
export interface AlbumImage {
  id: string;
  album_id: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  width: number | null;
  height: number | null;
  position: number;
  upload_status: string;
  content_url: string | null;
  created_at?: string;
}
export interface Pagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}
export interface PageResult<T> {
  success: boolean;
  data: T[];
  pagination: Pagination;
}
export interface AlbumInput {
  name: string;
  description: string;
  is_enabled: boolean;
}
const root = (pipelineId: string) =>
  `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/albums/`;
const albumUrl = (pipelineId: string, albumId: string) =>
  `${root(pipelineId)}${encodeURIComponent(albumId)}/`;
const imagesUrl = (pipelineId: string, albumId: string) =>
  `${albumUrl(pipelineId, albumId)}images/`;
function errorMessage(data: Record<string, unknown>): string {
  if (typeof data.message === "string") {
    return data.message;
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (data.errors && typeof data.errors === "object") {
    return Object.values(data.errors)
      .flat()
      .map(String)
      .join(" ");
  }
  for (const value of Object.values(data)) {
    if (Array.isArray(value)) {
      return value.map(String).join(" ");
    }
  }
  return "Không thể xử lý yêu cầu.";
}
async function parse<T>(response: Response): Promise<T> {
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") {
    throw new Error(`Phản hồi không hợp lệ (HTTP ${response.status}).`);
  }
  const data = raw as Record<string, unknown>;
  if (!response.ok || data.success !== true) {
    throw new Error(errorMessage(data));
  }
  return raw as T;
}
export async function listAlbums(
  pipelineId: string,
  page = 1,
  signal?: AbortSignal,
): Promise<PageResult<Album>> {
  const response = await fetch(
    `${root(pipelineId)}?page=${page}&page_size=10`,
    {
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
  const result = await parse<PageResult<Album>>(response);
  if (!Array.isArray(result.data) || !result.pagination) {
    throw new Error("Danh sách Album không hợp lệ.");
  }
  return result;
}
export async function listAlbumImages(
  pipelineId: string,
  albumId: string,
  page = 1,
  signal?: AbortSignal,
): Promise<PageResult<AlbumImage>> {
  const response = await fetch(
    `${imagesUrl(pipelineId, albumId)}?page=${page}&page_size=20`,
    {
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
  const result = await parse<PageResult<AlbumImage>>(response);
  if (!Array.isArray(result.data) || !result.pagination) {
    throw new Error("Danh sách ảnh không hợp lệ.");
  }
  return result;
}
async function writeJson<T>(
  url: string,
  method: "POST" | "PATCH",
  body: object,
): Promise<T> {
  const csrfToken = await getCsrfToken();
  const response = await fetch(url, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify(body),
  });
  const result = await parse<{ data: T }>(response);
  if (!result.data) {
    throw new Error("Phản hồi thiếu dữ liệu.");
  }
  return result.data;
}
export function createAlbum(
  pipelineId: string,
  input: AlbumInput,
): Promise<Album> {
  return writeJson(root(pipelineId), "POST", input);
}
export function updateAlbum(
  pipelineId: string,
  albumId: string,
  input: Partial<AlbumInput>,
): Promise<Album> {
  return writeJson(albumUrl(pipelineId, albumId), "PATCH", input);
}
export async function uploadAlbumImages(
  pipelineId: string,
  albumId: string,
  files: File[],
  onProgress?: (progress: number, uploadId?: string) => void,
): Promise<AlbumImage[]> {
  if (files.length < 1 || files.length > 5) {
    throw new Error("Chọn từ 1 đến 5 ảnh.");
  }
  const allowed = new Set([
    "image/jpeg",
    "image/png",
    "image/webp",
  ]);
  for (const file of files) {
    if (!allowed.has(file.type)) {
      throw new Error(`${file.name}: chỉ hỗ trợ JPEG, PNG, WebP.`);
    }
    if (file.size === 0 || file.size > 10 * 1024 * 1024) {
      throw new Error(`${file.name}: dung lượng phải tối đa 10 MB.`);
    }
  }
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  const csrfToken = await getCsrfToken();

  return new Promise<AlbumImage[]>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", imagesUrl(pipelineId, albumId));
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-CSRFToken", csrfToken);

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    xhr.onreadystatechange = function () {
      if (xhr.readyState !== XMLHttpRequest.DONE) return;
      const status = xhr.status;
      if (status >= 200 && status < 300) {
        let raw: unknown;
        try {
          raw = JSON.parse(xhr.responseText);
        } catch {
          reject(new Error("Phản hồi không hợp lệ."));
          return;
        }
        const data = raw as Record<string, unknown>;
        if (data.success !== true || !Array.isArray((data as { data?: unknown }).data)) {
          reject(new Error("Kết quả upload không hợp lệ."));
          return;
        }
        if (onProgress) onProgress(100);
        resolve((data as { data: AlbumImage[] }).data);
      } else {
        let raw: unknown;
        try {
          raw = JSON.parse(xhr.responseText);
        } catch {
          raw = null;
        }
        const errMsg = raw && typeof raw === "object"
          ? errorMessage(raw as Record<string, unknown>)
          : `Yêu cầu thất bại (HTTP ${status}).`;
        reject(new Error(errMsg));
      }
    };

    xhr.onerror = () => reject(new Error("Lỗi kết nối mạng."));
    xhr.onabort = () => reject(new Error("Upload đã bị hủy."));
    xhr.send(form);
  });
}

export async function deleteAlbumImage(
  pipelineId: string,
  albumId: string,
  imageId: string,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const url =
    `${imagesUrl(pipelineId, albumId)}` +
    `${encodeURIComponent(imageId)}/`;
  const response = await fetch(url, {
    method: "DELETE",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "X-CSRFToken": csrfToken,
    },
  });
  await parse<{ success: true }>(response);
}
export type AlbumImageMove =
  | {
      image_id: string;
      direction: "up" | "down";
    }
  | {
      image_id: string;
      target_id: string;
      placement: "before" | "after";
    };
export async function moveAlbumImage(
  pipelineId: string,
  albumId: string,
  payload: AlbumImageMove,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const response = await fetch(
    `${imagesUrl(pipelineId, albumId)}reorder/`,
    {
      method: "PATCH",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify(payload),
    },
  );
  await parse<{ success: true }>(response);
}
