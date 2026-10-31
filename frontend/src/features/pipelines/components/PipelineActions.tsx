"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import {
  ChevronDown,
  FolderCheck,
  Images,
  KeyRound,
  Sparkles,
  LockKeyhole,
  LockKeyholeOpen,
  Trash2,
  Users,
} from "lucide-react";

import PipelineEditButton from "./PipelineEditButton";
import PipelineStatusButton, {
  type PipelineStatusActionHandle,
} from "./PipelineStatusButton";
import CTVPasswordButton, {
  type CTVPasswordActionHandle,
} from "./CTVPasswordButton";
import PipelineDeleteButton, {
  type PipelineDeleteActionHandle,
} from "./PipelineDeleteButton";
import type { PipelineListItem } from "../types/list";

interface Props {
  item: PipelineListItem;
  onChanged: () => void;
  onDeleted: () => void;
  isMobile?: boolean;
}

const emptySubscribe = () => () => {};

export default function PipelineActions({
  item,
  onChanged,
  onDeleted,
  isMobile = false,
}: Props) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number }>({
    top: 0,
    left: 0,
  });

  const mounted = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );

  const statusActionRef = useRef<PipelineStatusActionHandle | null>(null);
  const passwordActionRef = useRef<CTVPasswordActionHandle | null>(null);
  const deleteActionRef = useRef<PipelineDeleteActionHandle | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    function updatePosition() {
      if (!triggerRef.current) return;
      const rect = triggerRef.current.getBoundingClientRect();
      const menuWidth = 224;
      const menuHeight = 340;
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      const showAbove = spaceBelow < menuHeight + 10 && spaceAbove > spaceBelow;

      const top = showAbove
        ? Math.max(8, rect.top - menuHeight - 6)
        : Math.min(window.innerHeight - menuHeight - 8, rect.bottom + 6);

      let left = rect.right - menuWidth;
      const maxLeft = window.innerWidth - menuWidth - 12;
      if (left > maxLeft) {
        left = maxLeft;
      }
      if (left < 12) {
        left = 12;
      }

      setPosition({ top, left });
    }

    updatePosition();

    function handleClickOutside(event: MouseEvent) {
      if (
        triggerRef.current?.contains(event.target as Node) ||
        menuRef.current?.contains(event.target as Node)
      ) {
        return;
      }
      setIsOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    function handleScroll(event: Event) {
      if (menuRef.current?.contains(event.target as Node)) return;
      setIsOpen(false);
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", updatePosition);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", updatePosition);
    };
  }, [isOpen]);

  const isActive = item.status === "active";

  const handleToggleStatus = () => {
    setIsOpen(false);
    void statusActionRef.current?.toggle();
  };

  const handleOpenPassword = () => {
    setIsOpen(false);
    passwordActionRef.current?.open();
  };

  const handleOpenDelete = () => {
    setIsOpen(false);
    deleteActionRef.current?.open();
  };

  return (
    <div className={`flex items-center gap-2 ${isMobile ? "w-full" : ""}`}>
      {/* Invisible triggers keeping dialogs mounted in DOM */}
      <PipelineStatusButton
        item={item}
        onChanged={onChanged}
        actionRef={statusActionRef}
        hideTrigger
      />
      <CTVPasswordButton
        item={item}
        actionRef={passwordActionRef}
        hideTrigger
      />
      <PipelineDeleteButton
        item={item}
        onDeleted={onDeleted}
        actionRef={deleteActionRef}
        hideTrigger
      />

      {/* 1. Nút Chỉnh sửa */}
      <PipelineEditButton
        item={item}
        onChanged={onChanged}
        triggerClassName={`inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 text-xs sm:text-sm font-semibold text-blue-700 hover:bg-blue-100 transition shadow-sm ${
          isMobile ? "flex-1" : ""
        }`}
      />

      {/* 2. Nút Thao tác ▾ */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label={`Menu thao tác CTV ${item.name}`}
        className={`inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs sm:text-sm font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition shadow-sm ${
          isMobile ? "flex-1" : ""
        } ${isOpen ? "ring-2 ring-blue-500/20 border-blue-400" : ""}`}
      >
        <span>Thao tác</span>
        <ChevronDown
          size={14}
          className={`text-slate-400 transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* Dropdown Menu portaled to document.body */}
      {mounted &&
        isOpen &&
        createPortal(
          <div
            ref={menuRef}
            style={{
              position: "fixed",
              top: `${position.top}px`,
              left: `${position.left}px`,
              zIndex: 9999,
            }}
            className="w-56 rounded-xl border border-slate-200/90 bg-white p-1.5 shadow-2xl transition animate-in fade-in zoom-in-95 duration-100"
            role="menu"
        aria-label={`Menu thao tác CTV ${item.name}`}
          >
            {/* Khóa / Mở khóa */}
            <button
              type="button"
              role="menuitem"
              onClick={handleToggleStatus}
              className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs sm:text-sm font-medium transition-colors text-left ${
                isActive
                  ? "text-amber-700 hover:bg-amber-50"
                  : "text-green-700 hover:bg-green-50"
              }`}
            >
              {isActive ? (
                <LockKeyhole
                  size={16}
                  className="text-amber-600 flex-shrink-0"
                />
              ) : (
                <LockKeyholeOpen
                  size={16}
                  className="text-green-600 flex-shrink-0"
                />
              )}
              <span>{isActive ? "Khóa CTV" : "Mở khóa CTV"}</span>
            </button>

            {/* Đổi mật khẩu */}
            <button
              type="button"
              role="menuitem"
              onClick={handleOpenPassword}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs sm:text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors text-left"
            >
              <KeyRound size={16} className="text-slate-400 flex-shrink-0" />
              <span>Đổi mật khẩu CTV</span>
            </button>

            <div className="my-1 border-t border-slate-100" />

            {/* Facebook Accounts */}
            <Link
              href={`/pipelines/${item.id}/facebook-accounts/`}
              role="menuitem"
              onClick={() => setIsOpen(false)}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs sm:text-sm font-medium text-slate-700 hover:bg-blue-50 hover:text-blue-700 transition-colors"
            >
              <Users size={16} className="text-blue-500 flex-shrink-0" />
              <span>Facebook Accounts</span>
            </Link>

            {/* Facebook Groups */}
            <Link
              href={`/pipelines/${item.id}/facebook-groups/`}
              role="menuitem"
              onClick={() => setIsOpen(false)}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs sm:text-sm font-medium text-slate-700 hover:bg-indigo-50 hover:text-indigo-700 transition-colors"
            >
              <FolderCheck size={16} className="text-indigo-500 flex-shrink-0" />
              <span>Facebook Groups</span>
            </Link>

            {/* Album Library */}
            <Link
              href={`/pipelines/${item.id}/albums/`}
              role="menuitem"
              onClick={() => setIsOpen(false)}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs sm:text-sm font-medium text-slate-700 hover:bg-violet-50 hover:text-violet-700 transition-colors"
            >
              <Images size={16} className="text-violet-500 flex-shrink-0" />
              <span>Album Library</span>
            </Link>

            <div className="my-1 border-t border-slate-100" />

            <Link
              href={`/pipelines/${item.id}/caption-settings/`}
              role="menuitem"
              onClick={() => setIsOpen(false)}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs sm:text-sm font-medium text-slate-700 hover:bg-blue-50 hover:text-blue-700"
            >
              <Sparkles size={16} className="text-blue-500 flex-shrink-0" />
              <span>AI Caption & Trang đích</span>
            </Link>
            {/* Xóa */}
            <button
              type="button"
              role="menuitem"
              onClick={handleOpenDelete}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs sm:text-sm font-medium text-red-600 hover:bg-red-50 hover:text-red-700 transition-colors text-left"
            >
              <Trash2 size={16} className="text-red-500 flex-shrink-0" />
              <span>Xóa CTV</span>
            </button>
          </div>,
          document.body,
        )}
    </div>
  );
}
