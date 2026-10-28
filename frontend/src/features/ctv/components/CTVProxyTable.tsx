"use client";
import { useEffect, useState, type FormEvent } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  checkProxyHealth,
  createProxy,
  deleteProxy,
  importProxies,
  listProxies,
  searchFacebookAccounts,
  updateProxy,
  type ProxyAccount,
  type ProxyInput,
  type ProxyItem,
  type ProxyProtocol,
  type ProxyListResult,
} from "../api/proxies";

type FormMode = "create" | "edit" | "bulk" | null;

interface Draft {
  protocol: ProxyProtocol;
  host: string;
  port: string;
  account_id: string;
  username: string;
  password: string;
  is_enabled: boolean;
  notes: string;
  clear_auth: boolean;
}

const emptyDraft: Draft = {
  protocol: "http",
  host: "",
  port: "",
  account_id: "",
  username: "",
  password: "",
  is_enabled: true,
  notes: "",
  clear_auth: false,
};

const inputClass =
  "w-full rounded-md border border-slate-200 bg-white " +
  "px-3 py-2.5 text-xs text-slate-800 " +
  "outline-none focus:border-blue-500";

const statusNames = {
  healthy: "Hoạt động",
  failed: "Không kết nối",
  untested: "Chưa kiểm tra",
};

const statusColors = {
  healthy: "bg-green-50 text-green-700",
  failed: "bg-red-50 text-red-700",
  untested: "bg-slate-100 text-slate-600",
};

function errorText(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Không thể xử lý yêu cầu.";
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("vi-VN");
}

function parseBulkLines(text: string): ProxyInput[] {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 1 || lines.length > 50) {
    throw new Error("Mỗi lần nhập từ 1 đến 50 Proxy.");
  }
  return lines.map((line, index) => {
    let protocol: ProxyProtocol = "http";
    let host = "";
    let port = 0;
    let username = "";
    let password = "";
    try {
      if (line.includes("://")) {
        const url = new URL(line);
        const scheme = url.protocol.replace(":", "");
        if (
          scheme !== "http" &&
          scheme !== "https" &&
          scheme !== "socks5"
        ) {
          throw new Error();
        }
        if (
          (url.pathname && url.pathname !== "/") ||
          url.search ||
          url.hash
        ) {
          throw new Error();
        }
        protocol = scheme;
        host = url.hostname;
        port = Number(url.port);
        username = decodeURIComponent(url.username);
        password = decodeURIComponent(url.password);
      } else {
        const parts = line.split(":");
        if (parts.length !== 2 && parts.length < 4) {
          throw new Error();
        }
        host = parts[0];
        port = Number(parts[1]);
        if (parts.length >= 4) {
          username = parts[2];
          password = parts.slice(3).join(":");
        }
      }
      if (
        !host ||
        !Number.isInteger(port) ||
        port < 1 ||
        port > 65535 ||
        Boolean(username) !== Boolean(password)
      ) {
        throw new Error();
      }
      const item: ProxyInput = {
        protocol,
        host,
        port,
      };
      if (username && password) {
        item.username = username;
        item.password = password;
      }
      return item;
    } catch {
      // Never echo the input because it may contain passwords.
      throw new Error(
        `Proxy tại dòng ${index + 1} sai định dạng.`
      );
    }
  });
}

export default function CTVProxyTable({
  pipelineId,
}: {
  pipelineId: string;
}) {
  const [result, setResult] = useState<ProxyListResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [assigned, setAssigned] = useState("all");
  const [revision, setRevision] = useState(0);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [editing, setEditing] = useState<ProxyItem | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [bulkText, setBulkText] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [accounts, setAccounts] = useState<ProxyAccount[]>([]);
  const [accountSearch, setAccountSearch] = useState("");
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountError, setAccountError] = useState("");

  function refresh() {
    setRevision((value) => value + 1);
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    listProxies(
      pipelineId,
      { page, pageSize, search, status, assigned },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
        setSelectedIds([]);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(errorText(cause));
        setResult(null);
        setSelectedIds([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [pipelineId, page, pageSize, search, status, assigned, revision]);

  useEffect(() => {
    if (formMode !== "create" && formMode !== "edit") {
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setAccountLoading(true);
      setAccountError("");
      searchFacebookAccounts(
        pipelineId,
        accountSearch,
        controller.signal,
      )
        .then((items) => {
          if (!controller.signal.aborted) setAccounts(items);
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return;
          setAccounts([]);
          setAccountError(errorText(cause));
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setAccountLoading(false);
          }
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [pipelineId, formMode, accountSearch]);

  const items = result?.data ?? [];
  const pagination = result?.pagination;
  const allSelected =
    items.length > 0 &&
    items.every((item) => selectedIds.includes(item.id));

  const accountOptions = [
    ...(
      editing?.account &&
      !accounts.some((a) => a.id === editing.account?.id)
        ? [editing.account]
        : []
    ),
    ...accounts,
  ];

  function toggleAll(checked: boolean) {
    setSelectedIds(checked ? items.map((item) => item.id) : []);
  }

  function toggleOne(id: string, checked: boolean) {
    setSelectedIds((current) =>
      checked
        ? Array.from(new Set([...current, id]))
        : current.filter((value) => value !== id),
    );
  }

  function openCreate() {
    setEditing(null);
    setDraft({ ...emptyDraft });
    setBulkText("");
    setAccountSearch("");
    setFormError("");
    setFormMode("create");
  }

  function openBulk() {
    setEditing(null);
    setFormError("");
    setBulkText("");
    setFormMode("bulk");
  }

  function openEdit(item: ProxyItem) {
    setEditing(item);
    setDraft({
      protocol: item.protocol,
      host: item.host,
      port: String(item.port),
      account_id: item.account?.id ?? "",
      username: "",
      password: "",
      is_enabled: item.is_enabled,
      notes: item.notes,
      clear_auth: false,
    });
    setAccountSearch("");
    setFormError("");
    setFormMode("edit");
  }

  function closeForm() {
    if (saving) return;
    setFormMode(null);
    setEditing(null);
    setFormError("");
    setDraft({ ...emptyDraft });
    setBulkText("");
    setAccounts([]);
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !formMode) return;
    setSaving(true);
    setFormError("");
    setNotice("");
    try {
      if (formMode === "bulk") {
        const itemsToImport = parseBulkLines(bulkText);
        const response = await importProxies(
          pipelineId,
          itemsToImport,
        );
        setNotice(
          `Đã nhập ${response.data.created} Proxy thành công.`
        );
      } else {
        const port = Number(draft.port);
        if (
          !draft.host.trim() ||
          !Number.isInteger(port) ||
          port < 1 ||
          port > 65535
        ) {
          throw new Error("IP/Hostname hoặc Port không hợp lệ.");
        }
        if (
          !draft.clear_auth &&
          Boolean(draft.username) !== Boolean(draft.password)
        ) {
          throw new Error(
            "Phải nhập cả username và password Proxy."
          );
        }
        const payload: ProxyInput = {
          protocol: draft.protocol,
          host: draft.host.trim(),
          port,
          account_id: draft.account_id || null,
          is_enabled: draft.is_enabled,
          notes: draft.notes.trim(),
        };
        if (draft.clear_auth) {
          payload.username = "";
          payload.password = "";
        } else if (draft.username && draft.password) {
          payload.username = draft.username;
          payload.password = draft.password;
        }
        if (formMode === "edit") {
          if (!editing) throw new Error("Chưa chọn Proxy.");
          await updateProxy(
            pipelineId,
            editing.id,
            payload,
          );
          setNotice("Đã cập nhật Proxy.");
        } else {
          await createProxy(pipelineId, payload);
          setNotice("Đã thêm Proxy thành công.");
        }
      }
      setFormMode(null);
      setEditing(null);
      setDraft({ ...emptyDraft });
      setBulkText("");
      setAccounts([]);
      setAccountSearch("");
      setPage(1);
      refresh();
    } catch (cause) {
      setFormError(errorText(cause));
    } finally {
      setSaving(false);
    }
  }

  async function handleCheck(item: ProxyItem) {
    if (busyId || saving || !item.is_enabled) return;
    setBusyId(item.id);
    setError("");
    setNotice("");
    try {
      const response = await checkProxyHealth(
        pipelineId,
        item.id,
      );
      setNotice(
        response.data.health_status === "healthy"
          ? (
            `${item.host}:${item.port} hoạt động. ` +
            `IP: ${response.data.exit_ip ?? "—"}, ` +
            `${response.data.latency_ms ?? "—"} ms.`
          )
          : `${item.host}:${item.port}: ${response.message}`,
      );
      refresh();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggle(item: ProxyItem) {
    if (busyId || saving) return;
    setBusyId(item.id);
    setError("");
    setNotice("");
    try {
      await updateProxy(pipelineId, item.id, {
        is_enabled: !item.is_enabled,
      });
      setNotice(
        item.is_enabled ? "Đã tắt Proxy." : "Đã bật Proxy."
      );
      refresh();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(item: ProxyItem) {
    if (busyId || saving) return;
    const confirmed = window.confirm(
      `Xóa Proxy ${item.host}:${item.port}?\n` +
      "Tài khoản Facebook sẽ bị bỏ gán Proxy."
    );
    if (!confirmed) return;
    setBusyId(item.id);
    setError("");
    setNotice("");
    try {
      await deleteProxy(pipelineId, item.id);
      setNotice("Đã xóa Proxy.");
      if (items.length === 1 && page > 1) {
        setPage((current) => Math.max(1, current - 1));
      } else {
        refresh();
      }
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusyId(null);
    }
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            Quản lý Proxy
          </h1>
          <p className="mt-1 text-xs text-slate-500">
            Mỗi Facebook Account được gán tối đa một Proxy.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={openBulk}
            className="inline-flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-4 py-2.5 text-xs font-semibold text-blue-700"
          >
            <Upload size={16} />
            Nhập hàng loạt
          </button>
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white"
          >
            <Plus size={16} />
            Thêm Proxy
          </button>
        </div>
      </div>

      {notice && (
        <p role="status" className="rounded-md bg-blue-50 p-3 text-xs text-blue-800">
          {notice}
        </p>
      )}

      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">
          {error}
        </p>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-4 border-b border-slate-100 p-4 text-xs">
          <span>
            Tổng Proxy: <strong>{pagination?.total ?? "—"}</strong>
          </span>
          <span className="text-blue-700">
            Đã chọn trên trang: {selectedIds.length}
          </span>
          {selectedIds.length > 0 && (
            <button
              type="button"
              onClick={() => setSelectedIds([])}
              className="font-medium text-slate-600 underline"
            >
              Bỏ chọn
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3">
          <form
            onSubmit={handleSearch}
            className="flex min-w-[180px] flex-1 gap-2"
          >
            <div className="relative min-w-0 flex-1">
              <Search
                size={15}
                className="absolute left-3 top-3 text-slate-400"
              />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                className={`${inputClass} pl-9`}
                placeholder="Tìm IP, Host, Facebook..."
                maxLength={100}
              />
            </div>
            <button
              type="submit"
              className="rounded-md border border-slate-200 px-3 text-xs"
            >
              Tìm
            </button>
          </form>

          <select
            aria-label="Lọc trạng thái Proxy"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
            className={`${inputClass} w-auto`}
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="healthy">Hoạt động</option>
            <option value="failed">Không kết nối</option>
            <option value="untested">Chưa kiểm tra</option>
          </select>

          <select
            aria-label="Lọc tài khoản đã gán"
            value={assigned}
            onChange={(event) => {
              setAssigned(event.target.value);
              setPage(1);
            }}
            className={`${inputClass} w-auto`}
          >
            <option value="all">Tất cả tài khoản</option>
            <option value="true">Đã gán Facebook</option>
            <option value="false">Chưa gán</option>
          </select>

          <select
            aria-label="Số dòng mỗi trang"
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(1);
            }}
            className={`${inputClass} w-auto`}
          >
            <option value={10}>10 dòng</option>
            <option value={20}>20 dòng</option>
            <option value={50}>50 dòng</option>
          </select>

          <button
            type="button"
            onClick={refresh}
            aria-label="Làm mới Proxy"
            className="rounded-md border border-slate-200 p-2"
          >
            <RefreshCw size={16} />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[1050px] text-left text-xs">
            <thead className="bg-slate-50 text-slate-600">
              <tr className="border-b border-slate-200">
                <th className="w-10 px-3 py-3">
                  <input
                    type="checkbox"
                    aria-label="Chọn tất cả Proxy trên trang"
                    checked={allSelected}
                    disabled={loading || items.length === 0}
                    onChange={(event) => toggleAll(event.target.checked)}
                    className="size-4 accent-blue-600"
                  />
                </th>
                <th className="px-3 py-3">STT</th>
                <th className="px-3 py-3">Proxy</th>
                <th className="px-3 py-3">Facebook Account</th>
                <th className="px-3 py-3">Trạng thái</th>
                <th className="px-3 py-3">IP đầu ra</th>
                <th className="px-3 py-3">Độ trễ</th>
                <th className="px-3 py-3">Kiểm tra gần nhất</th>
                <th className="px-3 py-3">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={9} className="p-10 text-center text-slate-500">
                    Đang tải Proxy...
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={9} className="p-10 text-center text-slate-500">
                    Chưa có Proxy phù hợp.
                  </td>
                </tr>
              ) : (
                items.map((item, index) => (
                  <tr
                    key={item.id}
                    className={
                      selectedIds.includes(item.id)
                        ? "bg-blue-50"
                        : "hover:bg-slate-50"
                    }
                  >
                    <td className="px-3 py-3">
                      <input
                        type="checkbox"
                        aria-label={`Chọn Proxy ${item.host}`}
                        checked={selectedIds.includes(item.id)}
                        onChange={(event) =>
                          toggleOne(item.id, event.target.checked)
                        }
                        className="size-4 accent-blue-600"
                      />
                    </td>
                    <td className="px-3 py-3 text-slate-500">
                      {(page - 1) * pageSize + index + 1}
                    </td>
                    <td className="px-3 py-3">
                      <div className="font-mono font-semibold text-slate-800">
                        {item.host}:{item.port}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-500">
                        {item.protocol.toUpperCase()}
                        {item.has_auth ? " · Có xác thực" : ""}
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      {item.account?.label ?? "Chưa gán"}
                    </td>
                    <td className="px-3 py-3">
                      <span
                        className={
                          "inline-flex rounded-full px-2 py-1 text-[11px] font-medium " +
                          statusColors[item.health_status]
                        }
                      >
                        {statusNames[item.health_status]}
                      </span>
                      {!item.is_enabled && (
                        <div className="mt-1 text-[11px] text-red-600">
                          Đã tắt
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono">
                      {item.exit_ip ?? "—"}
                    </td>
                    <td className="px-3 py-3">
                      {item.latency_ms !== null
                        ? `${item.latency_ms} ms`
                        : "—"}
                    </td>
                    <td className="px-3 py-3 text-slate-500">
                      {formatDate(item.last_checked_at)}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          disabled={!!busyId || saving || !item.is_enabled}
                          onClick={() => void handleCheck(item)}
                          className="inline-flex items-center gap-1 rounded border border-blue-200 px-2 py-1.5 font-medium text-blue-700 disabled:opacity-40"
                        >
                          <ShieldCheck size={13} />
                          {busyId === item.id ? "Đang xử lý..." : "Kiểm tra"}
                        </button>
                        <button
                          type="button"
                          disabled={!!busyId || saving}
                          onClick={() => openEdit(item)}
                          className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1.5 disabled:opacity-40"
                        >
                          <Pencil size={13} />
                          Sửa
                        </button>
                        <button
                          type="button"
                          disabled={!!busyId || saving}
                          onClick={() => void handleToggle(item)}
                          className="rounded border border-slate-200 px-2 py-1.5 disabled:opacity-40"
                        >
                          {item.is_enabled ? "Tắt" : "Bật"}
                        </button>
                        <button
                          type="button"
                          disabled={!!busyId || saving}
                          onClick={() => void handleDelete(item)}
                          aria-label={`Xóa ${item.host}:${item.port}`}
                          className="rounded border border-red-200 px-2 py-1.5 text-red-600 disabled:opacity-40"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between border-t border-slate-100 p-4 text-xs text-slate-500">
          <span>{pagination?.total ?? "—"} Proxy</span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              aria-label="Trang trước"
              disabled={!pagination?.has_previous || loading}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
              className="rounded border border-slate-200 p-2 disabled:opacity-30"
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {pagination
                ? `${pagination.page}/${pagination.total_pages}`
                : "—"}
            </span>
            <button
              type="button"
              aria-label="Trang tiếp"
              disabled={!pagination?.has_next || loading}
              onClick={() => setPage((value) => value + 1)}
              className="rounded border border-slate-200 p-2 disabled:opacity-30"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>

      {formMode && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-3">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="ctv-proxy-form-title"
            className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-xl bg-white p-5 shadow-xl"
          >
            <div className="mb-5 flex items-center justify-between gap-3">
              <h2
                id="ctv-proxy-form-title"
                className="text-lg font-bold"
              >
                {formMode === "bulk"
                  ? "Nhập nhiều Proxy"
                  : formMode === "edit"
                  ? "Chỉnh sửa Proxy"
                  : "Thêm Proxy"}
              </h2>
              <button
                type="button"
                disabled={saving}
                aria-label="Đóng"
                onClick={closeForm}
                className="rounded-md border border-slate-200 p-2"
              >
                <X size={17} />
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
              {formMode === "bulk" ? (
                <>
                  <p className="text-xs text-slate-600">
                    Một Proxy mỗi dòng, tối đa 50 Proxy.
                    Hỗ trợ host:port, host:port:user:pass
                    hoặc URL có giao thức và xác thực.
                  </p>
                  <textarea
                    required
                    rows={10}
                    value={bulkText}
                    onChange={(event) =>
                      setBulkText(event.target.value)
                    }
                    className={`${inputClass} font-mono`}
                    placeholder={
                      "proxy.example.com:8000\n" +
                      "socks5://user:pass@proxy.example.org:1080"
                    }
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <p className="text-xs text-amber-700">
                    Các Proxy nhập hàng loạt chưa được gán
                    Facebook tự động. Gán từng tài khoản sau khi nhập.
                    Không chia sẻ nội dung chứa mật khẩu.
                  </p>
                </>
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <label className="space-y-1">
                      <span className="text-xs">Giao thức</span>
                      <select
                        value={draft.protocol}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            protocol: event.target.value as ProxyProtocol,
                          }))
                        }
                        className={inputClass}
                      >
                        <option value="http">HTTP</option>
                        <option value="https">HTTPS</option>
                        <option value="socks5">SOCKS5</option>
                      </select>
                    </label>
                    <label className="space-y-1 sm:col-span-2">
                      <span className="text-xs">IP / Hostname</span>
                      <input
                        required
                        maxLength={253}
                        value={draft.host}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            host: event.target.value,
                          }))
                        }
                        className={inputClass}
                        placeholder="proxy.example.com"
                      />
                    </label>
                  </div>
                  <label className="block space-y-1">
                    <span className="text-xs">Port</span>
                    <input
                      required
                      type="number"
                      min={1}
                      max={65535}
                      value={draft.port}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          port: event.target.value,
                        }))
                      }
                      className={inputClass}
                    />
                  </label>
                  <div className="space-y-2">
                    <label className="block text-xs font-medium">
                      Gán tài khoản Facebook
                    </label>
                    <input
                      value={accountSearch}
                      onChange={(event) =>
                        setAccountSearch(event.target.value)
                      }
                      placeholder="Tìm tên hoặc UID Facebook..."
                      className={inputClass}
                      maxLength={100}
                    />
                    <select
                      value={draft.account_id}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          account_id: event.target.value,
                        }))
                      }
                      className={inputClass}
                    >
                      <option value="">Chưa gán tài khoản</option>
                      {accountOptions.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.label}
                        </option>
                      ))}
                    </select>
                    {accountLoading && (
                      <p className="text-xs text-slate-500">
                        Đang tìm tài khoản...
                      </p>
                    )}
                    {accountError && (
                      <p className="text-xs text-red-600">
                        {accountError}
                      </p>
                    )}
                    <p className="text-[11px] text-slate-500">
                      Hiển thị tối đa 50 tài khoản phù hợp.
                      Nếu không thấy tài khoản cần gán, hãy tìm theo tên.
                      Một Facebook Account không thể nhận hai Proxy.
                    </p>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="space-y-1">
                      <span className="text-xs">Username Proxy</span>
                      <input
                        value={draft.username}
                        disabled={draft.clear_auth}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            username: event.target.value,
                          }))
                        }
                        className={inputClass}
                        autoComplete="off"
                        maxLength={128}
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs">Password Proxy</span>
                      <input
                        type="password"
                        value={draft.password}
                        disabled={draft.clear_auth}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            password: event.target.value,
                          }))
                        }
                        className={inputClass}
                        autoComplete="new-password"
                        maxLength={256}
                      />
                    </label>
                  </div>
                  {formMode === "edit" && (
                    <>
                      <p className="text-xs text-slate-500">
                        Để trống cả hai ô để giữ mật khẩu cũ.
                        Nhập cả hai ô để thay thế thông tin xác thực.
                      </p>
                      <label className="flex items-center gap-2 text-xs">
                        <input
                          type="checkbox"
                          checked={draft.clear_auth}
                          onChange={(event) =>
                            setDraft((current) => ({
                              ...current,
                              clear_auth: event.target.checked,
                              username: "",
                              password: "",
                            }))
                          }
                          className="size-4 accent-blue-600"
                        />
                        Xóa thông tin xác thực Proxy
                      </label>
                    </>
                  )}
                  <label className="block space-y-1">
                    <span className="text-xs">Ghi chú</span>
                    <input
                      maxLength={500}
                      value={draft.notes}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          notes: event.target.value,
                        }))
                      }
                      className={inputClass}
                    />
                  </label>
                  <label className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={draft.is_enabled}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          is_enabled: event.target.checked,
                        }))
                      }
                      className="size-4 accent-blue-600"
                    />
                    Bật Proxy
                  </label>
                </>
              )}
              {formError && (
                <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">
                  {formError}
                </p>
              )}
              <div className="flex justify-end gap-3 border-t border-slate-100 pt-4">
                <button
                  type="button"
                  onClick={closeForm}
                  disabled={saving}
                  className="rounded-md border border-slate-200 px-4 py-2.5 text-xs"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="rounded-md bg-blue-600 px-5 py-2.5 text-xs font-semibold text-white disabled:opacity-50"
                >
                  {saving ? "Đang lưu..." : "Lưu Proxy"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
