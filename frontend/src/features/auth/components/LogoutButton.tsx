"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";

import { getCsrfToken } from "../api/auth-client";

export default function LogoutButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleLogout() {
    if (loading) return;

    setLoading(true);
    setError("");

    try {
      const csrfToken = await getCsrfToken();

      const response = await fetch(
        "/api/v1/auth/logout/",
        {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          headers: {
            "X-CSRFToken": csrfToken,
          },
        }
      );

      if (!response.ok) {
        throw new Error("Logout failed");
      }

      router.replace("/login/");
      router.refresh();
    } catch {
      setError("Không thể đăng xuất. Vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={handleLogout}
        disabled={loading}
        className="sidebar-link w-full cursor-pointer border-0 bg-transparent text-left"
      >
        <LogOut size={19} />
        <span className="nav-text">
          {loading ? "Đang đăng xuất..." : "Đăng xuất"}
        </span>
      </button>

      {error && (
        <p role="alert" className="px-3 text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
