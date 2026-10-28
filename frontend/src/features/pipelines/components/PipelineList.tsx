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
import PipelineStatusButton from "./PipelineStatusButton";
import CTVPasswordButton from "./CTVPasswordButton";
import PipelineEditButton from "./PipelineEditButton";
import PipelineDeleteButton from "./PipelineDeleteButton";
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
                    <th className="px-5 py-4">Pipeline</th>
                    <th className="px-5 py-4">CTV</th>
                    <th className="px-5 py-4">Trạng thái</th>
                    <th className="px-5 py-4">Ngày tạo</th>
                    <th className="px-5 py-4">Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td className="px-5 py-4 font-semibold text-slate-800">
                        {item.name}
                      </td>
                      <td className="px-5 py-4">
                        <p className="font-medium text-slate-700">
                          {item.ctv.username}
                        </p>
                        <p className="text-xs text-slate-400">
                          {item.ctv.email}
                        </p>
                      </td>
                      <td className="px-5 py-4">
                        <StatusBadge status={item.status} />
                      </td>
                      <td className="px-5 py-4 text-slate-500">
                        {formatDate(item.created_at)}
                      </td>
                      <td className="px-5 py-4">
                        <PipelineStatusButton
                          item={item}
                          onChanged={() =>
                            setRefreshKey((value) => value + 1)
                          }
                        />
                        <CTVPasswordButton item={item} />
                        <PipelineEditButton
                          item={item}
                          onChanged={() =>
                            setRefreshKey((value) => value + 1)
                          }
                        />
                        <PipelineDeleteButton
                          item={item}
                          onDeleted={() =>
                            setRefreshKey((value) => value + 1)
                          }
                        />
                        <Link
                          href={`/pipelines/${item.id}/facebook-accounts/`}
                          className="inline-flex min-h-10 items-center rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100"
                        >
                          Facebook Accounts
                        </Link>
                        <Link
                          href={`/pipelines/${item.id}/facebook-groups/`}
                          className="inline-flex min-h-10 items-center rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                        >
                          Facebook Groups
                        </Link>
                        <Link
                          href={`/pipelines/${item.id}/albums/`}
                          className="inline-flex min-h-10 items-center rounded-lg border border-violet-200 bg-violet-50 px-4 py-2 text-sm font-semibold text-violet-700 hover:bg-violet-100"
                        >
                          Album Library
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="divide-y divide-slate-100 md:hidden">
              {items.map((item) => (
                <article key={item.id} className="space-y-3 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-semibold text-slate-900">
                      {item.name}
                    </h3>
                    <StatusBadge status={item.status} />
                  </div>

                  <div className="text-sm text-slate-600">
                    <p>CTV: {item.ctv.username}</p>
                    <p className="break-all text-slate-400">
                      {item.ctv.email}
                    </p>
                  </div>

                  <p className="text-xs text-slate-400">
                    Ngày tạo: {formatDate(item.created_at)}
                  </p>

                  <div className="pt-1">
                    <PipelineStatusButton
                      item={item}
                      onChanged={() =>
                        setRefreshKey((value) => value + 1)
                      }
                    />
                    <CTVPasswordButton item={item} />
                    <PipelineEditButton
                      item={item}
                      onChanged={() =>
                        setRefreshKey((value) => value + 1)
                      }
                    />
                    <PipelineDeleteButton
                      item={item}
                      onDeleted={() =>
                        setRefreshKey((value) => value + 1)
                      }
                    />
                    <Link
                      href={`/pipelines/${item.id}/facebook-accounts/`}
                      className="inline-flex min-h-10 items-center rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100"
                    >
                      Facebook Accounts
                    </Link>
                    <Link
                      href={`/pipelines/${item.id}/facebook-groups/`}
                      className="inline-flex min-h-10 items-center rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      Facebook Groups
                    </Link>
                    <Link
                      href={`/pipelines/${item.id}/albums/`}
                      className="inline-flex min-h-10 items-center rounded-lg border border-violet-200 bg-violet-50 px-4 py-2 text-sm font-semibold text-violet-700 hover:bg-violet-100"
                    >
                      Album Library
                    </Link>
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
