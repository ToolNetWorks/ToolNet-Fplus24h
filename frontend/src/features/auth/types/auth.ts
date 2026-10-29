export interface AdminUser {
  id: number;
  username: string;
  role: "admin";
}

export interface CTVUser {
  id: number;
  username: string;
  role: "ctv";
}

export type AuthUser = AdminUser | CTVUser;

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface LoginResponse {
  success: boolean;
  user: AuthUser;
}

export interface CsrfResponse {
  success: boolean;
  csrfToken: string;
}
