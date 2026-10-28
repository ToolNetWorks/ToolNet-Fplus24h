import { getCsrfToken } from "@/features/auth/api/auth-client";
interface ChangePasswordResponse {
  success?: boolean;
  message?: string;
  new_password?: string[];
  confirm_password?: string[];
  non_field_errors?: string[];
  detail?: string;
}
export async function changeCTVPassword(
  pipelineId: string,
  password: string,
  confirmPassword: string,
): Promise<void> {
  if (!pipelineId) {
    throw new Error("Pipeline không hợp lệ.");
  }
  if (!password || !confirmPassword) {
    throw new Error("Vui lòng nhập đầy đủ mật khẩu.");
  }
  if (password !== confirmPassword) {
    throw new Error("Mật khẩu xác nhận không khớp.");
  }
  const csrfToken = await getCsrfToken();
  const response = await fetch(
    `/api/v1/admin/pipelines/${encodeURIComponent(pipelineId)}/ctv/password/`,
    {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
        Accept: "application/json",
      },
      body: JSON.stringify({
        new_password: password,
        confirm_password: confirmPassword,
      }),
    },
  );
  const result: ChangePasswordResponse =
    await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    throw new Error(
      "Phiên đăng nhập không hợp lệ hoặc không đủ quyền.",
    );
  }
  if (!response.ok || result.success !== true) {
    const errors = [
      ...(result.new_password ?? []),
      ...(result.confirm_password ?? []),
      ...(result.non_field_errors ?? []),
    ];
    throw new Error(
      errors.join(" ") ||
      result.message ||
      result.detail ||
      "Không thể đổi mật khẩu CTV.",
    );
  }
}
