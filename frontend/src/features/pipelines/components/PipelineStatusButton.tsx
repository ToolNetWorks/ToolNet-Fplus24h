"use client";

import { useState } from "react";
import {
  LockKeyhole,
  LockKeyholeOpen,
  LoaderCircle,
} from "lucide-react";

import { updatePipelineStatus } from "../api/update-pipeline-status";
import type { PipelineListItem } from "../types/list";

interface Props {
  item: PipelineListItem;
  onChanged: () => void;
}

export default function PipelineStatusButton({
  item,
  onChanged,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const isActive = item.status === "active";
  const actionName = isActive ? "Khóa" : "Mở khóa";

  async function handleClick() {
    if (loading) return;

    const message = isActive
      ? `Khóa Pipeline "${item.name}" và tài khoản CTV "${item.ctv.username}"?`
      : `Mở khóa Pipeline "${item.name}" và kích hoạt lại CTV "${item.ctv.username}"?`;

    if (!window.confirm(message)) return;

    const newStatus = isActive ? "disabled" : "active";

    setLoading(true);
    setError("");

    try {
      await updatePipelineStatus(item.id, newStatus);
      onChanged();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Cập nhật trạng thái thất bại.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        aria-label={`${actionName} Pipeline ${item.name}`}
        className={
          "inline-flex min-h-10 items-center justify-center gap-2 " +
          "rounded-lg border px-4 py-2 text-sm font-semibold " +
          "transition disabled:cursor-not-allowed disabled:opacity-50 " +
          (isActive
            ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
            : "border-green-200 bg-green-50 text-green-700 hover:bg-green-100")
        }
      >
        {loading ? (
          <LoaderCircle size={16} className="animate-spin" />
        ) : isActive ? (
          <LockKeyhole size={16} />
        ) : (
          <LockKeyholeOpen size={16} />
        )}
        {loading ? "Đang xử lý..." : actionName}
      </button>

      {error && (
        <p role="alert" className="max-w-60 text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
