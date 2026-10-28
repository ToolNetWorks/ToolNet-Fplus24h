"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, LoaderCircle } from "lucide-react";
import CTVShell from "./CTVShell";
interface WorkspaceData {
  pipeline: {
    id: string;
    name: string;
    status: string;
  };
  ctv: {
    id: number;
    username: string;
    email: string;
  };
  stats: {
    facebook_accounts: number;
    connected_accounts: number;
  };
}
interface ApiResponse<T> {
  success?: boolean;
  message?: string;
  detail?: string;
  data?: T;
}
async function getJSON<T>(
  url: string,
  signal: AbortSignal,
): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  const result: ApiResponse<T> =
    await response.json().catch(() => ({}));
  if (!response.ok || result.success !== true || !result.data) {
    throw new Error(
      result.message ||
      result.detail ||
      `Không thể tải dữ liệu (HTTP ${response.status}).`,
    );
  }
  return result.data;
}
export default function CTVWorkspace() {
  const [workspace, setWorkspace] =
    useState<WorkspaceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const landing = await getJSON<{
          role: string;
          redirect_to: string;
          pipeline_id: string | null;
        }>(
          "/api/v1/auth/landing/",
          controller.signal,
        );
        if (controller.signal.aborted) return;
        if (landing.role === "admin") {
          window.location.replace("/");
          return;
        }
        if (landing.role !== "ctv" || !landing.pipeline_id) {
          throw new Error("Tài khoản không có quyền CTV.");
        }
        const data = await getJSON<WorkspaceData>(
          "/api/v1/ctv/workspace/",
          controller.signal,
        );
        if (controller.signal.aborted) return;
        if (data.pipeline.id !== landing.pipeline_id) {
          throw new Error(
            "Thông tin Pipeline không khớp.",
          );
        }
        setWorkspace(data);
      } catch (cause) {
        if (controller.signal.aborted) return;
        setError(
          cause instanceof Error
            ? cause.message
            : "Không thể tải Workspace.",
        );
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }
    void load();
    return () => controller.abort();
  }, []);
  if (loading) {
    return (
      <div
        role="status"
        className="flex min-h-screen items-center justify-center gap-3 text-sm text-slate-500"
      >
        <LoaderCircle
          size={20}
          className="animate-spin"
        />
        Đang kiểm tra Workspace...
      </div>
    );
  }
  if (error || !workspace) {
    return (
      <main className="mx-auto max-w-md px-4 py-16">
        <div className="rounded-xl border border-red-200 bg-white p-6">
          <AlertCircle
            size={25}
            className="text-red-600"
          />
          <h1 className="mt-4 text-xl font-semibold">
            Không thể truy cập Workspace
          </h1>
          <p className="mt-3 text-sm text-slate-600">
            {error || "Không có dữ liệu Workspace."}
          </p>
          <Link
            href="/login/"
            className="mt-5 inline-block rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white"
          >
            Đến trang đăng nhập
          </Link>
        </div>
      </main>
    );
  }
  return <CTVShell workspace={workspace} />;
}
