"use client";

import { useState, type FormEvent } from "react";
import { Eye, EyeOff, LockKeyhole, UserRound } from "lucide-react";

import { loginUser, AuthError } from "../api/auth-client";
import styles from "./LoginForm.module.css";

export default function LoginForm() {
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
      const user = await loginUser({
        username: username.trim(),
        password,
      });

      setPassword("");

      // 1. Admin chuyển đến /
      if (user.role === "admin" || user.redirect_to === "/") {
        window.location.replace("/");
        return;
      }

      // 2. CTV chuyển đến /workspace/
      if (user.role === "ctv" || user.redirect_to === "/workspace/") {
        window.location.replace("/workspace/");
        return;
      }

      window.location.replace("/workspace/");
    } catch (err: unknown) {
      if (err instanceof AuthError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Đăng nhập thất bại. Kiểm tra thông tin hoặc kết nối.");
      }
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
            <span>FPLUS24H</span>
          </div>
        </div>

        <div className={styles.heading}>
          <h1>Đăng nhập hệ thống</h1>
          <p>ToolNet Fplus24h · Dành cho Quản trị viên và Cộng tác viên</p>
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
          ToolNet Fplus24h · Quản trị Pipeline & CTV Workspace
        </div>
      </section>
    </main>
  );
}
