"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Menu, PanelLeftClose, PanelLeftOpen } from "lucide-react";

import Sidebar from "./Sidebar";
import "./admin-shell.css";

type AdminShellProps = {
  children: ReactNode;
};

const STORAGE_KEY = "toolnet-sidebar-collapsed";

export default function AdminShell({
  children,
}: AdminShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(
        localStorage.getItem(STORAGE_KEY) === "true"
      );
    } catch {
      // Trình duyệt có thể chặn localStorage.
    }
  }, []);

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? "hidden" : "";

    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  function toggleDesktop() {
    const next = !collapsed;

    setCollapsed(next);

    try {
      localStorage.setItem(STORAGE_KEY, String(next));
    } catch {
      // Giữ trạng thái trong React.
    }
  }

  return (
    <div
      className={[
        "admin-shell",
        collapsed ? "sidebar-collapsed" : "",
      ].join(" ")}
    >
      <Sidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
      />

      <div className="admin-main">
        <header className="admin-topbar">
          <button
            type="button"
            className="menu-trigger desktop-trigger"
            onClick={toggleDesktop}
            aria-label={
              collapsed ? "Mở rộng menu" : "Thu gọn menu"
            }
            aria-controls="toolnet-sidebar"
            aria-expanded={!collapsed}
          >
            {collapsed ? (
              <PanelLeftOpen size={21} />
            ) : (
              <PanelLeftClose size={21} />
            )}
          </button>

          <button
            type="button"
            className="menu-trigger mobile-trigger"
            onClick={() => setMobileOpen(true)}
            aria-label="Mở menu"
            aria-controls="toolnet-sidebar"
            aria-expanded={mobileOpen}
          >
            <Menu size={22} />
          </button>

          <div className="topbar-brand">
            ToolNet Fplus24h
          </div>

          <div className="topbar-right">
            Admin Panel
          </div>
        </header>

        <main className="admin-content">
          {children}
        </main>
      </div>
    </div>
  );
}
