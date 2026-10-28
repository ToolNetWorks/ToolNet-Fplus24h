"use client";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FileJson,
  LoaderCircle,
  RefreshCw,
  Search,
  Upload,
} from "lucide-react";
import {
  getFacebookAccounts,
  uploadFacebookCookie,
  type AccountListResponse,
  type ConnectionStatus,
} from "../api/facebook-accounts";
const statusLabels: Record<ConnectionStatus, string> = {
  not_connected: "Chưa kết nối",
  connected: "Đã kết nối",
  expired: "Hết phiên",
  disabled: "Vô hiệu hóa",
};
const inputClass =
  "w-full rounded-lg border border-slate-200 bg-white " +
  "px-3 py-3 text-sm text-slate-900 outline-none " +
  "focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
export default function FacebookAccountsPanel({
  pipelineId,
  backHref = "/pipelines/",
}: {
  pipelineId: string;
  backHref?: string | null;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [label, setLabel] = useState("");
  const [profileUrl, setProfileUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [success, setSuccess] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [result, setResult] =
    useState<AccountListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const refresh = useCallback(() => {
    setReload((value) => value + 1);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setListError("");
    getFacebookAccounts(
      pipelineId,
      page,
      search,
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setResult(null);
        setListError(
          cause instanceof Error
            ? cause.message
            : "Không thể tải danh sách.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [pipelineId, page, search, reload]);
  async function handleUpload(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    if (uploading || !file) return;
    setUploading(true);
    setUploadError("");
    setSuccess("");
    try {
      await uploadFacebookCookie(pipelineId, {
        label,
        profileUrl,
        file,
      });
      setSuccess(
        "Đã lưu cookie mã hóa. Phiên Facebook chưa được xác minh.",
      );
      setLabel("");
      setProfileUrl("");
      setFile(null);
      if (fileRef.current) {
        fileRef.current.value = "";
      }
      setPage(1);
      setSearch("");
      setSearchInput("");
      refresh();
    } catch (cause) {
      setUploadError(
        cause instanceof Error
          ? cause.message
          : "Upload thất bại.",
      );
    } finally {
      setUploading(false);
    }
  }
  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="space-y-3">
        {backHref && (
          <Link
            href={backHref}
            className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-blue-600"
          >
            <ArrowLeft size={17} />
            Quay lại danh sách Pipeline
          </Link>
        )}
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            Facebook Accounts
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Quản lý tài khoản Facebook thuộc Pipeline.
          </p>
        </div>
      </header>
      <form
        onSubmit={handleUpload}
        className="space-y-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            Thêm tài khoản Facebook
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Upload file cookie JSON để lưu trữ mã hóa.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <label
              htmlFor="fb-label"
              className="text-sm font-medium text-slate-700"
            >
              Tên hiển thị
            </label>
            <input
              id="fb-label"
              className={inputClass}
              value={label}
              maxLength={150}
              required
              disabled={uploading}
              placeholder="Ví dụ: Facebook A"
              onChange={(event) =>
                setLabel(event.target.value)
              }
            />
          </div>
          <div className="space-y-2">
            <label
              htmlFor="fb-url"
              className="text-sm font-medium text-slate-700"
            >
              Link Facebook (tùy chọn)
            </label>
            <input
              id="fb-url"
              type="url"
              className={inputClass}
              value={profileUrl}
              maxLength={500}
              disabled={uploading}
              placeholder="https://www.facebook.com/..."
              onChange={(event) =>
                setProfileUrl(event.target.value)
              }
            />
          </div>
        </div>
        <div className="space-y-2">
          <label
            htmlFor="fb-cookie-file"
            className="text-sm font-medium text-slate-700"
          >
            File Cookie JSON
          </label>
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5">
            <div className="mb-3 flex items-center gap-3">
              <FileJson size={27} className="text-blue-600" />
              <div>
                <p className="text-sm font-medium text-slate-700">
                  {file ? file.name : "Chọn file cookie"}
                </p>
                <p className="text-xs text-slate-500">
                  JSON, tối đa 64 KB
                </p>
              </div>
            </div>
            <input
              ref={fileRef}
              id="fb-cookie-file"
              type="file"
              accept=".json,application/json"
              required
              disabled={uploading}
              onChange={(event) =>
                setFile(event.target.files?.[0] ?? null)
              }
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:font-medium file:text-blue-700"
            />
          </div>
        </div>
        {uploadError && (
          <p
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
          >
            {uploadError}
          </p>
        )}
        {success && (
          <p
            role="status"
            className="rounded-lg bg-green-50 p-3 text-sm text-green-700"
          >
            {success}
          </p>
        )}
        <button
          type="submit"
          disabled={uploading || !file || !label.trim()}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 sm:w-auto"
        >
          {uploading ? (
            <LoaderCircle
              size={18}
              className="animate-spin"
            />
          ) : (
            <Upload size={18} />
          )}
          {uploading ? "Đang lưu..." : "Thêm tài khoản"}
        </button>
      </form>
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-slate-900">
            Danh sách tài khoản
          </h2>
          <span className="text-sm text-slate-500">
            {result?.pagination.total ?? 0} tài khoản
          </span>
        </div>
        <form
          onSubmit={handleSearch}
          className="flex flex-wrap gap-2"
        >
          <div className="relative min-w-0 flex-1">
            <Search
              size={18}
              className="absolute left-3 top-3 text-slate-400"
            />
            <input
              value={searchInput}
              onChange={(event) =>
                setSearchInput(event.target.value)
              }
              placeholder="Tìm tài khoản..."
              className={`${inputClass} pl-10`}
            />
          </div>
          <button
            type="submit"
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium"
          >
            Tìm
          </button>
          <button
            type="button"
            onClick={refresh}
            aria-label="Làm mới danh sách"
            className="rounded-lg border border-slate-200 bg-white p-3"
          >
            <RefreshCw size={18} />
          </button>
        </form>
        {listError && (
          <p
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
          >
            {listError}
          </p>
        )}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          {loading ? (
            <p role="status" className="p-8 text-center text-sm text-slate-500">
              Đang tải tài khoản...
            </p>
          ) : result?.data.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-500">
              Chưa có tài khoản Facebook phù hợp.
            </p>
          ) : (
            <div className="divide-y divide-slate-100">
              {result?.data.map((account) => (
                <div
                  key={account.id}
                  className="flex flex-wrap items-center justify-between gap-3 p-4 sm:p-5"
                >
                  <div className="min-w-0 space-y-1">
                    <p className="font-semibold text-slate-900">
                      {account.label}
                    </p>
                    {account.profile_url && (
                      <p className="break-all text-xs text-slate-500">
                        {account.profile_url}
                      </p>
                    )}
                  </div>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                    {statusLabels[account.connection_status] ??
                      account.connection_status}
                  </span>
                </div>
              ))}
            </div>
          )}
          {result && result.pagination.total_pages > 1 && (
            <div className="flex items-center justify-between border-t border-slate-100 p-4">
              <button
                type="button"
                disabled={!result.pagination.has_previous}
                onClick={() =>
                  setPage((current) => Math.max(1, current - 1))
                }
                className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-sm text-slate-500">
                Trang {result.pagination.page} /
                {" "}{result.pagination.total_pages}
              </span>
              <button
                type="button"
                disabled={!result.pagination.has_next}
                onClick={() =>
                  setPage((current) => current + 1)
                }
                className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
