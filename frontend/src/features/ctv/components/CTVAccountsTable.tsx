"use client";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ChevronLeft,
  ChevronRight,
  FileJson,
  Plus,
  RefreshCw,
  Search,
  Upload,
  X,
} from "lucide-react";
import {
  uploadFacebookCookie,
  type FacebookAccount,
  type ConnectionStatus,
} from "@/features/facebook-accounts/api/facebook-accounts";

type StatusFilter = "all" | ConnectionStatus;

type Account = FacebookAccount & {
  facebook_user_id?: string | null;
};

interface Summary {
  total: number;
  connected: number;
  not_connected: number;
  expired: number;
  disabled: number;
}

interface AccountsResponse {
  success: true;
  data: Account[];
  summary: Summary;
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
}

const labels: Record<ConnectionStatus, string> = {
  connected: "Đã kết nối",
  not_connected: "Chưa kết nối",
  expired: "Hết phiên",
  disabled: "Vô hiệu hóa",
};

const colors: Record<ConnectionStatus, string> = {
  connected: "bg-emerald-50 text-emerald-700",
  not_connected: "bg-slate-100 text-slate-600",
  expired: "bg-amber-50 text-amber-700",
  disabled: "bg-red-50 text-red-700",
};

function message(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Không thể tải dữ liệu.";
}

async function fetchAccounts(
  pipelineId: string,
  options: {
    page: number;
    pageSize: number;
    search: string;
    status: StatusFilter;
  },
  signal: AbortSignal,
): Promise<AccountsResponse> {
  const params = new URLSearchParams({
    page: String(options.page),
    page_size: String(options.pageSize),
  });
  if (options.search) {
    params.set("search", options.search);
  }
  if (options.status !== "all") {
    params.set("status", options.status);
  }
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/facebook-accounts/?${params}`,
    {
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") {
    throw new Error("Phản hồi API không hợp lệ.");
  }
  const data = raw as Partial<AccountsResponse> & {
    message?: string;
    detail?: string;
  };
  if (
    !response.ok ||
    data.success !== true ||
    !Array.isArray(data.data) ||
    !data.summary ||
    !data.pagination
  ) {
    throw new Error(
      data.message ||
      data.detail ||
      `Không thể tải tài khoản (HTTP ${response.status}).`,
    );
  }
  return data as AccountsResponse;
}

const inputClass =
  "rounded-md border border-slate-200 bg-white px-3 py-2 " +
  "text-xs text-slate-800 outline-none focus:border-blue-500";

export default function CTVAccountsTable({
  pipelineId,
}: {
  pipelineId: string;
}) {
  const [result, setResult] = useState<AccountsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [revision, setRevision] = useState(0);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [showUpload, setShowUpload] = useState(false);
  const [label, setLabel] = useState("");
  const [profileUrl, setProfileUrl] = useState("");
  const [cookieFile, setCookieFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [success, setSuccess] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetchAccounts(
      pipelineId,
      { page, pageSize, search, status },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
        setSelectedIds([]);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setResult(null);
        setSelectedIds([]);
        setError(message(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [pipelineId, page, pageSize, search, status, revision]);

  const items = result?.data ?? [];
  const summary = result?.summary;
  const pagination = result?.pagination;
  const allSelected =
    items.length > 0 &&
    items.every((item) => selectedIds.includes(item.id));

  function refresh() {
    setRevision((value) => value + 1);
  }

  function toggleOne(id: string, checked: boolean) {
    setSelectedIds((current) =>
      checked
        ? Array.from(new Set([...current, id]))
        : current.filter((item) => item !== id),
    );
  }

  function toggleAll(checked: boolean) {
    setSelectedIds(checked ? items.map((item) => item.id) : []);
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSelectedIds([]);
    setSearch(searchInput.trim());
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!cookieFile || uploading) return;
    setUploading(true);
    setUploadError("");
    setSuccess("");
    try {
      await uploadFacebookCookie(pipelineId, {
        label: label.trim(),
        profileUrl: profileUrl.trim(),
        file: cookieFile,
      });
      setSuccess(
        "Đã lưu cookie mã hóa. Trạng thái đăng nhập chưa được xác minh.",
      );
      setLabel("");
      setProfileUrl("");
      setCookieFile(null);
      setShowUpload(false);
      if (fileRef.current) {
        fileRef.current.value = "";
      }
      setPage(1);
      setSearch("");
      setSearchInput("");
      setStatus("all");
      refresh();
    } catch (cause) {
      setUploadError(message(cause));
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900">
            Danh sách tài khoản
          </h1>
          <p className="mt-1 text-xs text-slate-500">
            Tài khoản Facebook thuộc Pipeline hiện tại.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setShowUpload((value) => !value);
            setUploadError("");
          }}
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white"
        >
          {showUpload ? <X size={16} /> : <Plus size={16} />}
          {showUpload ? "Đóng" : "Thêm tài khoản"}
        </button>
      </div>

      {success && (
        <p role="status" className="rounded-md bg-green-50 p-3 text-xs text-green-700">
          {success}
        </p>
      )}

      {showUpload && (
        <form
          onSubmit={handleUpload}
          className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2"
        >
          <div className="space-y-1">
            <label htmlFor="ctv-fb-name" className="text-xs font-medium">
              Tên tài khoản
            </label>
            <input
              id="ctv-fb-name"
              value={label}
              required
              maxLength={150}
              disabled={uploading}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Facebook A"
              className={`${inputClass} w-full`}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="ctv-fb-url" className="text-xs font-medium">
              Link Facebook (không bắt buộc)
            </label>
            <input
              id="ctv-fb-url"
              type="url"
              value={profileUrl}
              maxLength={500}
              disabled={uploading}
              onChange={(event) => setProfileUrl(event.target.value)}
              className={`${inputClass} w-full`}
              placeholder="https://www.facebook.com/..."
            />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <label htmlFor="ctv-fb-cookie" className="flex items-center gap-2 text-xs font-medium">
              <FileJson size={16} />
              Cookie JSON (tối đa 64 KB)
            </label>
            <input
              ref={fileRef}
              id="ctv-fb-cookie"
              type="file"
              accept=".json,application/json"
              required
              disabled={uploading}
              onChange={(event) =>
                setCookieFile(event.target.files?.[0] ?? null)
              }
              className="block w-full rounded-md border border-dashed border-slate-200 p-3 text-xs"
            />
          </div>
          {uploadError && (
            <p role="alert" className="text-xs text-red-600 sm:col-span-2">
              {uploadError}
            </p>
          )}
          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={uploading || !cookieFile || !label.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50"
            >
              <Upload size={16} />
              {uploading ? "Đang lưu..." : "Lưu tài khoản"}
            </button>
          </div>
        </form>
      )}

      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-slate-100 p-3 text-xs">
          <span className="font-medium text-slate-700">
            Tổng: <strong>{summary?.total ?? "—"}</strong>
          </span>
          <span className="text-emerald-700">
            Đã kết nối: <strong>{summary?.connected ?? "—"}</strong>
          </span>
          <span className="text-slate-500">
            Chưa kết nối: <strong>{summary?.not_connected ?? "—"}</strong>
          </span>
          <span className="text-amber-700">
            Hết phiên: <strong>{summary?.expired ?? "—"}</strong>
          </span>
          <span className="text-red-600">
            Vô hiệu hóa: <strong>{summary?.disabled ?? "—"}</strong>
          </span>
          <span className="font-semibold text-blue-700">
            Đã chọn trên trang: {selectedIds.length}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <form
            onSubmit={handleSearch}
            className="flex min-w-[180px] flex-1 items-center gap-2"
          >
            <div className="relative min-w-0 flex-1">
              <Search
                size={15}
                className="absolute left-3 top-2.5 text-slate-400"
              />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Tìm theo tên, UID, link..."
                className={`${inputClass} w-full pl-9`}
              />
            </div>
            <button
              type="submit"
              className="rounded-md border border-slate-200 px-3 py-2 text-xs"
            >
              Tìm
            </button>
          </form>

          <select
            aria-label="Lọc trạng thái"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as StatusFilter);
              setPage(1);
              setSelectedIds([]);
            }}
            className={inputClass}
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="connected">Đã kết nối</option>
            <option value="not_connected">Chưa kết nối</option>
            <option value="expired">Hết phiên</option>
            <option value="disabled">Vô hiệu hóa</option>
          </select>

          <select
            aria-label="Số dòng mỗi trang"
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(1);
              setSelectedIds([]);
            }}
            className={inputClass}
          >
            <option value={10}>10 dòng</option>
            <option value={25}>25 dòng</option>
            <option value={50}>50 dòng</option>
          </select>

          {selectedIds.length > 0 && (
            <button
              type="button"
              onClick={() => setSelectedIds([])}
              className="rounded-md border border-slate-200 px-3 py-2 text-xs"
            >
              Bỏ chọn
            </button>
          )}

          <button
            type="button"
            onClick={refresh}
            aria-label="Làm mới danh sách tài khoản"
            className="rounded-md border border-slate-200 p-2"
          >
            <RefreshCw size={16} />
          </button>
        </div>

        {error && (
          <p role="alert" className="m-3 rounded-md bg-red-50 p-3 text-xs text-red-700">
            {error}
          </p>
        )}

        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[850px] border-collapse text-left text-xs">
            <thead className="sticky top-0 bg-slate-50 text-slate-600">
              <tr className="border-b border-slate-200">
                <th className="w-10 px-3 py-3">
                  <input
                    type="checkbox"
                    aria-label="Chọn tất cả tài khoản trên trang"
                    checked={allSelected}
                    disabled={loading || items.length === 0}
                    onChange={(event) =>
                      toggleAll(event.target.checked)
                    }
                    className="size-4 accent-blue-600"
                  />
                </th>
                <th className="w-12 px-3 py-3">STT</th>
                <th className="w-32 px-3 py-3">UID</th>
                <th className="min-w-44 px-3 py-3">Họ tên</th>
                <th className="w-36 px-3 py-3">Trạng thái</th>
                <th className="min-w-40 px-3 py-3">Kết quả</th>
                <th className="min-w-40 px-3 py-3">Hành động</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={7} className="p-10 text-center text-slate-500">
                    Đang tải danh sách tài khoản...
                  </td>
                </tr>
              ) : !error && items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-10 text-center text-slate-500">
                    Không có tài khoản phù hợp.
                  </td>
                </tr>
              ) : !error ? (
                items.map((account, index) => {
                  const selected = selectedIds.includes(account.id);
                  return (
                    <tr
                      key={account.id}
                      className={
                        selected
                          ? "bg-blue-50/70"
                          : "hover:bg-slate-50/70"
                      }
                    >
                      <td className="px-3 py-2.5">
                        <input
                          type="checkbox"
                          aria-label={`Chọn ${account.label}`}
                          checked={selected}
                          onChange={(event) =>
                            toggleOne(account.id, event.target.checked)
                          }
                          className="size-4 accent-blue-600"
                        />
                      </td>
                      <td className="px-3 py-2.5 text-slate-500">
                        {(page - 1) * pageSize + index + 1}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-slate-700">
                        {account.facebook_user_id || "—"}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="max-w-64 truncate font-medium text-slate-800">
                          {account.label}
                        </div>
                        {account.profile_url && (
                          <a
                            href={account.profile_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-1 block max-w-64 truncate text-[11px] text-blue-600 hover:underline"
                          >
                            Xem trang cá nhân
                          </a>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className={
                            `inline-flex rounded-full px-3 py-1 text-[11px] font-semibold ` +
                            colors[account.connection_status]
                          }
                        >
                          {labels[account.connection_status]}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-slate-400">
                        Chưa có tác vụ
                      </td>
                      <td className="px-3 py-2.5 text-slate-400">
                        —
                      </td>
                    </tr>
                  );
                })
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
          <span>
            {pagination
              ? `${pagination.total} tài khoản phù hợp`
              : "—"}
          </span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={!pagination?.has_previous || loading}
              onClick={() => {
                setSelectedIds([]);
                setPage((current) => Math.max(1, current - 1));
              }}
              className="rounded-md border border-slate-200 p-2 disabled:opacity-30"
              aria-label="Trang trước"
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {pagination
                ? `${pagination.page} / ${pagination.total_pages}`
                : "—"}
            </span>
            <button
              type="button"
              disabled={!pagination?.has_next || loading}
              onClick={() => {
                setSelectedIds([]);
                setPage((current) => current + 1);
              }}
              className="rounded-md border border-slate-200 p-2 disabled:opacity-30"
              aria-label="Trang tiếp"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        Trạng thái kết nối là dữ liệu lưu trong hệ thống, không phải
        xác nhận Facebook đang online tại thời điểm này. Chức năng
        thực thi đăng bài và nhật ký tác vụ sẽ được kết nối khi
        Publishing Engine hoàn thành.
      </p>
    </section>
  );
}
