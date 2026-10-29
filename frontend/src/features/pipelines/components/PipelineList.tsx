"use client";

import {
  useEffect,
  useState,
} from "react";
import Link from "next/link";
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";

import { listPipelines } from "../api/list-pipelines";
import PipelineActions from "./PipelineActions";
import type {
  PipelineListResponse,
  PipelineStatusFilter,
} from "../types/list";

const PAGE_SIZE = 10;

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleDateString("vi-VN");
}

function StatusBadge({
  status,
}: {
  status: string;
}) {
  const active = status === "active";

  return (
    <span
      className={
        "inline-flex rounded-full px-3 py-1 text-xs font-semibold " +
        (active
          ? "bg-green-50 text-green-700"
          : "bg-red-50 text-red-700")
      }
    >
      {active ? "Hoạt động" : "Tạm khóa"}
    </span>
  );
}

export default function PipelineList() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] =
    useState<PipelineStatusFilter>("all");
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [result, setResult] =
    useState<PipelineListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1);
      setSearch(searchInput.trim());
    }, 350);

    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    const controller = new AbortController();

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError("");

    listPipelines(
      {
        page,
        pageSize: PAGE_SIZE,
        search,
        status,
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
            : "Không thể kết nối API.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [page, search, status, refreshKey]);

  const items = result?.data ?? [];
  const pagination = result?.pagination;

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-900">
            Danh sách Pipeline
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Quản lý Pipeline và tài khoản CTV.
          </p>
        </div>

        <Link
          href="/pipelines/new/"
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700"
        >
          <Plus size={18} />
          Tạo Pipeline
        </Link>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search
              size={18}
              className="absolute left-3 top-3 text-slate-400"
            />
            <input
              type="search"
              value={searchInput}
              onChange={(event) =>
                setSearchInput(event.target.value)
              }
              placeholder="Tìm Pipeline, Username, Email..."
              aria-label="Tìm kiếm Pipeline"
              className="w-full rounded-lg border border-slate-200 bg-white py-3 pl-10 pr-3 text-sm text-slate-900 outline-none focus:border-blue-500"
            />
          </div>

          <select
            value={status}
            aria-label="Lọc trạng thái Pipeline"
            onChange={(event) => {
              setPage(1);
              setStatus(
                event.target.value as PipelineStatusFilter,
              );
            }}
            className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700"
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="active">Hoạt động</option>
            <option value="disabled">Tạm khóa</option>
          </select>

          <button
            type="button"
            onClick={() =>
              setRefreshKey((value) => value + 1)
            }
            aria-label="Tải lại danh sách"
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-3 text-sm text-slate-700 hover:bg-slate-50"
          >
            <RefreshCw size={17} />
            Làm mới
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          {error}
          <button
            type="button"
            onClick={() =>
              setRefreshKey((value) => value + 1)
            }
            className="ml-3 font-semibold underline"
          >
            Thử lại
          </button>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading ? (
          <div role="status" className="p-10 text-center text-sm text-slate-500">
            Đang tải danh sách Pipeline...
          </div>
        ) : !error && items.length === 0 ? (
          <div className="p-12 text-center">
            <p className="font-medium text-slate-700">
              Không tìm thấy Pipeline
            </p>
            <p className="mt-2 text-sm text-slate-400">
              Hãy thử bộ lọc khác hoặc tạo Pipeline mới.
            </p>
          </div>
        ) : !error ? (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-5 py-3.5 font-semibold">Pipeline</th>
                    <th className="px-5 py-3.5 font-semibold">CTV</th>
                    <th className="px-5 py-3.5 font-semibold">Trạng thái</th>
                    <th className="px-5 py-3.5 font-semibold">Ngày tạo</th>
                    <th className="px-5 py-3.5 text-right font-semibold">Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((item) => (
                    <tr key={item.id} className="hover:bg-slate-50/60 transition-colors">
                      <td className="px-5 py-3.5 font-semibold text-slate-800">
                        {item.name}
                      </td>
                      <td className="px-5 py-3.5">
                        <p className="font-medium text-slate-700">
                          {item.ctv.username}
                        </p>
                        <p className="text-xs text-slate-400">
                          {item.ctv.email}
                        </p>
                      </td>
                      <td className="px-5 py-3.5">
                        <StatusBadge status={item.status} />
                      </td>
                      <td className="px-5 py-3.5 text-slate-500 whitespace-nowrap">
                        {formatDate(item.created_at)}
                      </td>
                      <td className="px-5 py-3.5 text-right whitespace-nowrap">
                        <div className="flex items-center justify-end">
                          <PipelineActions
                            item={item}
                            onChanged={() =>
                              setRefreshKey((value) => value + 1)
                            }
                            onDeleted={() =>
                              setRefreshKey((value) => value + 1)
                            }
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="divide-y divide-slate-100 md:hidden">
              {items.map((item) => (
                <article key={item.id} className="p-4 sm:p-5 space-y-3 bg-white hover:bg-slate-50/40 transition">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <h3 className="font-bold text-base text-slate-900 break-words">
                        {item.name}
                      </h3>
                      <p className="mt-0.5 text-xs text-slate-400">
                        Ngày tạo: {formatDate(item.created_at)}
                      </p>
                    </div>
                    <StatusBadge status={item.status} />
                  </div>

                  <div className="rounded-lg bg-slate-50 p-2.5 text-xs text-slate-600">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-500">CTV:</span>
                      <span className="font-semibold text-slate-800">{item.ctv.username}</span>
                    </div>
                    <div className="mt-1 truncate text-slate-400">
                      {item.ctv.email}
                    </div>
                  </div>

                  <div className="pt-2 border-t border-slate-100/80">
                    <PipelineActions
                      item={item}
                      isMobile
                      onChanged={() =>
                        setRefreshKey((value) => value + 1)
                      }
                      onDeleted={() =>
                        setRefreshKey((value) => value + 1)
                      }
                    />
                  </div>
                </article>
              ))}
            </div>
          </>
        ) : null}

        {!loading && !error && pagination && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4">
            <p className="text-sm text-slate-500">
              Tổng: {pagination.total} Pipeline
            </p>

            <div className="flex items-center gap-3">
              <button
                type="button"
                aria-label="Trang trước"
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
                aria-label="Trang sau"
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
      </div>
    </section>
  );
}
