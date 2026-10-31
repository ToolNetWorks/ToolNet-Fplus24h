"use client";

import { useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  History,
  RefreshCw,
} from "lucide-react";

import { listCTVAuditLog } from "../api/ctv-management";
import type {
  CTVAuditLogItem,
  CTVAuditLogResponse,
} from "../types/ctv-management";

const PAGE_SIZE = 10;

function formatDateTime(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleString("vi-VN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ActionBadge({ item }: { item: CTVAuditLogItem }) {
  const colors: Record<CTVAuditLogItem["action"], string> = {
    create_ctv: "bg-blue-50 text-blue-700",
    lock_ctv: "bg-red-50 text-red-700",
    unlock_ctv: "bg-green-50 text-green-700",
    reset_password: "bg-amber-50 text-amber-700",
  };

  return (
    <span
      className={
        "inline-flex rounded-full px-3 py-1 text-xs font-semibold " +
        colors[item.action]
      }
    >
      {item.action_label}
    </span>
  );
}

export default function CTVAuditLog({
  refreshToken,
}: {
  refreshToken: number;
}) {
  const [page, setPage] = useState(1);
  const [result, setResult] =
    useState<CTVAuditLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError("");

    listCTVAuditLog(
      {
        page,
        pageSize: PAGE_SIZE,
      },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setResult(null);
        setError(
          cause instanceof Error
            ? cause.message
            : "Không thể tải audit log.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [page, refreshToken, retryKey]);

  const items = result?.data ?? [];
  const pagination = result?.pagination;

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <History size={19} className="text-slate-500" />
          <div>
            <h2 className="text-base font-bold text-slate-900">
              Audit log quản lý CTV
            </h2>
            <p className="text-xs text-slate-500">
              Thời gian, Admin thực hiện và hành động.
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => setRetryKey((value) => value + 1)}
          aria-label="Tải lại audit log"
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw size={15} />
          Làm mới
        </button>
      </div>

      {loading ? (
        <div
          role="status"
          className="p-8 text-center text-sm text-slate-500"
        >
          Đang tải audit log...
        </div>
      ) : error ? (
        <div
          role="alert"
          className="m-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      ) : items.length === 0 ? (
        <div className="p-8 text-center text-sm text-slate-500">
          Chưa có hành động quản lý CTV nào.
        </div>
      ) : (
        <>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-5 py-3 font-semibold">
                    Thời gian
                  </th>
                  <th className="px-5 py-3 font-semibold">Admin</th>
                  <th className="px-5 py-3 font-semibold">
                    Hành động
                  </th>
                  <th className="px-5 py-3 font-semibold">CTV</th>
                  <th className="px-5 py-3 font-semibold">
                    Pipeline
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((item) => (
                  <tr key={item.id} className="hover:bg-slate-50/60">
                    <td className="whitespace-nowrap px-5 py-3 text-slate-500">
                      {formatDateTime(item.created_at)}
                    </td>
                    <td className="px-5 py-3 font-medium text-slate-700">
                      {item.admin.username}
                    </td>
                    <td className="px-5 py-3">
                      <ActionBadge item={item} />
                    </td>
                    <td className="px-5 py-3 text-slate-700">
                      {item.ctv_username || "-"}
                    </td>
                    <td className="px-5 py-3 text-slate-700">
                      {item.pipeline_name || "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="divide-y divide-slate-100 md:hidden">
            {items.map((item) => (
              <article
                key={item.id}
                className="space-y-2 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="text-xs text-slate-400">
                    {formatDateTime(item.created_at)}
                  </span>
                  <ActionBadge item={item} />
                </div>

                <div className="text-sm text-slate-700">
                  <p>
                    <span className="text-slate-500">Admin: </span>
                    <span className="font-medium">
                      {item.admin.username}
                    </span>
                  </p>
                  <p className="mt-1">
                    <span className="text-slate-500">CTV: </span>
                    {item.ctv_username || "-"}
                  </p>
                  <p className="mt-1">
                    <span className="text-slate-500">
                      Pipeline:{" "}
                    </span>
                    {item.pipeline_name || "-"}
                  </p>
                </div>
              </article>
            ))}
          </div>
        </>
      )}

      {!loading && !error && pagination && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4">
          <p className="text-sm text-slate-500">
            Tổng: {pagination.total} bản ghi
          </p>

          <div className="flex items-center gap-3">
            <button
              type="button"
              aria-label="Trang audit trước"
              disabled={!pagination.has_previous}
              onClick={() =>
                setPage((value) => Math.max(1, value - 1))
              }
              className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
            >
              <ChevronLeft size={18} />
            </button>

            <span className="text-sm text-slate-600">
              {pagination.page} / {pagination.total_pages}
            </span>

            <button
              type="button"
              aria-label="Trang audit sau"
              disabled={!pagination.has_next}
              onClick={() =>
                setPage((value) => value + 1)
              }
              className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
            >
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
