export type UserRole = "admin" | "ctv";

export interface AuthUser {
  id: number;
  username: string;
  role: UserRole;
  redirect_to?: string;
  pipeline_id?: string | null;
}

export type AdminUser = AuthUser;

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface LoginResponse {
  success: boolean;
  message?: string;
  user?: AuthUser;
}

export interface CsrfResponse {
  success: boolean;
  csrfToken: string;
}
