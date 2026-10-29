import type {
  AuthUser,
  CsrfResponse,
  LoginCredentials,
  LoginResponse,
} from "../types/auth";

const API_BASE = "/api/v1/auth";

export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}

async function parseResponse<T>(
  response: Response
): Promise<T> {
  const body: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const errorBody = body as { message?: string } | null;
    throw new AuthError(
      errorBody?.message || "Yêu cầu thất bại. Vui lòng thử lại."
    );
  }

  if (!body || typeof body !== "object") {
    throw new AuthError("Phản hồi máy chủ không hợp lệ.");
  }

  return body as T;
}

export async function getCsrfToken(): Promise<string> {
  const response = await fetch(`${API_BASE}/csrf/`, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
  });

  const data = await parseResponse<CsrfResponse>(response);

  if (!data.success || !data.csrfToken) {
    throw new AuthError("Không lấy được CSRF Token.");
  }

  return data.csrfToken;
}

export async function loginUser(
  credentials: LoginCredentials
): Promise<AuthUser> {
  const csrfToken = await getCsrfToken();

  const response = await fetch(`${API_BASE}/login/`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify(credentials),
  });

  const data = await parseResponse<LoginResponse>(response);

  if (!data.success || !data.user || (data.user.role !== "admin" && data.user.role !== "ctv")) {
    throw new AuthError(data.message || "Đăng nhập không thành công.");
  }

  return data.user;
}

export const loginAdmin = loginUser;
