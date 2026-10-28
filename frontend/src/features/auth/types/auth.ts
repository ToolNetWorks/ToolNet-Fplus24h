export interface AdminUser {
  id: number;
  username: string;
  role: "admin";
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface LoginResponse {
  success: boolean;
  user: AdminUser;
}

export interface CsrfResponse {
  success: boolean;
  csrfToken: string;
}
