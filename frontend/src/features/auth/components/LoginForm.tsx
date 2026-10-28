"use client";

async function redirectAfterRoleCheck(): Promise<void> {
  try {
    const response = await fetch("/api/v1/auth/landing/", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.success !== true) {
      throw new Error(
        result.message ||
        result.detail ||
        "Không thể xác định quyền tài khoản.",
      );
    }
    const destination = result.data?.redirect_to;
    const role = result.data?.role;
    if (role === "admin" && destination === "/") {
      window.location.replace("/");
      return;
    }
    if (role === "ctv" && destination === "/workspace/") {
      window.location.replace("/workspace/");
      return;
    }
    throw new Error("Quyền đăng nhập không hợp lệ.");
  } catch (error) {
    window.alert(
      error instanceof Error
        ? error.message
        : "Không thể xác định Workspace.",
    );
  }
}

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, LockKeyhole, UserRound } from "lucide-react";

import { loginAdmin } from "../api/auth-client";
import styles from "./LoginForm.module.css";

export default function LoginForm() {
  const router = useRouter();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (loading) return;

    if (!username.trim() || !password) {
      setError("Vui lòng nhập tài khoản và mật khẩu.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      await loginAdmin({
        username: username.trim(),
        password,
      });

      setPassword("");
      void redirectAfterRoleCheck();
      router.refresh();
    } catch {
      setError(
        "Đăng nhập thất bại. Kiểm tra thông tin hoặc kết nối."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.card}>
        <div className={styles.brand}>
          <div className={styles.logo}>T</div>
          <div className={styles.brandName}>
            <strong>TOOLNET</strong>
            <span>PUBLISHER</span>
          </div>
        </div>

        <div className={styles.heading}>
          <h1>Đăng nhập quản trị</h1>
          <p>Quản lý Pipeline và cộng tác viên</p>
        </div>

        <form onSubmit={handleSubmit}>
          <label htmlFor="username">Tên đăng nhập</label>
          <div className={styles.inputGroup}>
            <UserRound size={19} />
            <input
              id="username"
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              maxLength={150}
              placeholder="Nhập tên đăng nhập"
              disabled={loading}
              required
            />
          </div>

          <label htmlFor="password">Mật khẩu</label>
          <div className={styles.inputGroup}>
            <LockKeyhole size={19} />
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              placeholder="Nhập mật khẩu"
              disabled={loading}
              required
            />
            <button
              className={styles.eyeButton}
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
            >
              {showPassword ? <EyeOff size={19} /> : <Eye size={19} />}
            </button>
          </div>

          {error && (
            <div className={styles.error} role="alert">
              {error}
            </div>
          )}

          <button
            className={styles.submit}
            type="submit"
            disabled={loading}
          >
            {loading ? "Đang đăng nhập..." : "Đăng nhập"}
          </button>
        </form>

        <div className={styles.footer}>
          ToolNet Publisher · Admin Control Center
        </div>
      </section>
    </main>
  );
}
