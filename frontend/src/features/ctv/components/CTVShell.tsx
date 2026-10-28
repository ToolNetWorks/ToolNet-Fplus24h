"use client";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Users,
  UsersRound,
  Images,
  CalendarDays,
  FileText,
  MessageSquare,
  Sparkles,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  X,
  LogOut,
  Layers3,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { getCsrfToken } from "@/features/auth/api/auth-client";
import CTVAccountsTable from "./CTVAccountsTable";
import FacebookGroupsPanel from "@/features/facebook-groups/components/FacebookGroupsPanel";
import AlbumLibrary from "@/features/albums/components/AlbumLibrary";
import "./ctv-shell.css";

type Tab = "overview" | "accounts" | "groups" | "albums";

interface WorkspacePayload {
  pipeline: {
    id: string;
    name: string;
    status: string;
  };
  ctv: {
    username: string;
    email: string;
  };
  stats: {
    facebook_accounts: number;
    connected_accounts: number;
  };
}

interface NavItem {
  label: string;
  icon: LucideIcon;
  tab?: Tab;
}

const navigation: {
  heading: string;
  items: NavItem[];
}[] = [
  {
    heading: "TỔNG QUAN",
    items: [
      {
        label: "Dashboard",
        icon: LayoutDashboard,
        tab: "overview",
      },
    ],
  },
  {
    heading: "QUẢN LÝ TÀI NGUYÊN",
    items: [
      {
        label: "Quản lý tài khoản",
        icon: Users,
        tab: "accounts",
      },
      {
        label: "Quản lý Groups",
        icon: UsersRound,
        tab: "groups",
      },
      {
        label: "Quản lý Album ảnh",
        icon: Images,
        tab: "albums",
      },
    ],
  },
  {
    heading: "CHỨC NĂNG ĐĂNG BÀI",
    items: [
      { label: "Đăng bài viết nhóm", icon: FileText },
      { label: "AI viết Caption", icon: Sparkles },
      { label: "Lịch đăng bài", icon: CalendarDays },
      { label: "Lịch sử đăng bài", icon: Layers3 },
    ],
  },
  {
    heading: "CHỨC NĂNG KHÁC",
    items: [
      { label: "Bình luận tự động", icon: MessageSquare },
    ],
  },
];

const titles: Record<Tab, string> = {
  overview: "Tổng quan Pipeline",
  accounts: "Danh sách tài khoản",
  groups: "Quản lý Facebook Groups",
  albums: "Thư viện Album ảnh",
};

const STORAGE_KEY = "toolnet-ctv-sidebar-collapsed";

export default function CTVShell({
  workspace,
}: {
  workspace: WorkspacePayload;
}) {
  const [activeTab, setActiveTab] = useState<Tab>("accounts");
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(STORAGE_KEY) === "true");
    } catch {
      // Private browsing may block localStorage.
    }
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileOpen(false);
    }
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("keydown", handleEscape);
    };
  }, [mobileOpen]);

  function selectTab(tab: Tab) {
    setActiveTab(tab);
    setMobileOpen(false);
  }

  function toggleSidebar() {
    setCollapsed((current) => {
      const next = !current;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // Continue with in-memory state.
      }
      return next;
    });
  }

  async function logout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setLogoutError("");
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/auth/logout/", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "X-CSRFToken": csrfToken,
        },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || data?.success !== true) {
        throw new Error("Không thể đăng xuất.");
      }
      window.location.replace("/login/");
    } catch {
      setLogoutError("Đăng xuất thất bại. Vui lòng thử lại.");
      setLoggingOut(false);
    }
  }

  const initials =
    workspace.ctv.username.slice(0, 1).toUpperCase() || "C";

  return (
    <div className={`ctv-shell ${collapsed ? "ctv-collapsed" : ""}`}>
      {mobileOpen && (
        <button
          type="button"
          className="ctv-overlay"
          onClick={() => setMobileOpen(false)}
          aria-label="Đóng menu"
        />
      )}
      <aside
        id="ctv-sidebar"
        className={`ctv-sidebar ${mobileOpen ? "ctv-open" : ""}`}
      >
        <div className="ctv-brand">
          <div className="ctv-brand-symbol">
            <Layers3 size={23} />
          </div>
          <div className="ctv-brand-wordmark">
            <strong>TOOLNET</strong>
            <span>PUBLISHER</span>
          </div>
          <button
            type="button"
            className="ctv-sidebar-close"
            onClick={() => setMobileOpen(false)}
            aria-label="Đóng sidebar"
          >
            <X size={19} />
          </button>
        </div>
        <div className="ctv-sidebar-body">
          {navigation.map((group) => (
            <section key={group.heading} className="ctv-nav-group">
              <div className="ctv-nav-heading">{group.heading}</div>
              <nav aria-label={group.heading} className="ctv-nav">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = activeTab === item.tab && !!item.tab;
                  return item.tab ? (
                    <button
                      type="button"
                      key={item.label}
                      onClick={() => selectTab(item.tab!)}
                      aria-current={active ? "page" : undefined}
                      title={item.label}
                      className={`ctv-nav-item ${active ? "ctv-active" : ""}`}
                    >
                      <Icon size={17} strokeWidth={1.8} />
                      <span className="ctv-nav-text">{item.label}</span>
                    </button>
                  ) : (
                    <div
                      key={item.label}
                      className="ctv-nav-item ctv-disabled"
                      title={`${item.label} — đang phát triển`}
                      aria-disabled="true"
                    >
                      <Icon size={17} strokeWidth={1.8} />
                      <span className="ctv-nav-text">{item.label}</span>
                    </div>
                  );
                })}
              </nav>
            </section>
          ))}
        </div>
        <div className="ctv-sidebar-footer">
          <div className="ctv-user-card">
            <div className="ctv-avatar">{initials}</div>
            <div className="ctv-user-details">
              <strong>{workspace.ctv.username}</strong>
              <span>CTV Workspace</span>
            </div>
          </div>
          <button
            type="button"
            className="ctv-logout"
            onClick={logout}
            disabled={loggingOut}
          >
            <LogOut size={17} />
            <span className="ctv-nav-text">
              {loggingOut ? "Đang đăng xuất..." : "Đăng xuất"}
            </span>
          </button>
          {logoutError && (
            <p role="alert" className="ctv-logout-error">
              {logoutError}
            </p>
          )}
        </div>
      </aside>
      <div className="ctv-main">
        <header className="ctv-topbar">
          <button
            type="button"
            className="ctv-toggle ctv-desktop-toggle"
            onClick={toggleSidebar}
            aria-label={collapsed ? "Mở rộng sidebar" : "Thu gọn sidebar"}
            aria-controls="ctv-sidebar"
          >
            {collapsed ? (
              <PanelLeftOpen size={20} />
            ) : (
              <PanelLeftClose size={20} />
            )}
          </button>
          <button
            type="button"
            className="ctv-toggle ctv-mobile-toggle"
            onClick={() => setMobileOpen(true)}
            aria-label="Mở menu"
            aria-controls="ctv-sidebar"
            aria-expanded={mobileOpen}
          >
            <Menu size={21} />
          </button>
          <div className="ctv-topbar-title">
            {titles[activeTab]}
          </div>
          <div className="ctv-topbar-right">
            <span className="ctv-pipeline-name">
              {workspace.pipeline.name}
            </span>
            <div className="ctv-topbar-avatar">{initials}</div>
          </div>
        </header>
        <main id="ctv-main-content" className="ctv-content">
          {activeTab === "overview" && (
            <div className="space-y-5">
              <div>
                <h1 className="text-xl font-bold text-slate-900">
                  Tổng quan Pipeline
                </h1>
                <p className="mt-1 text-sm text-slate-500">
                  {workspace.pipeline.name}
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 bg-white p-5">
                  <Users size={21} className="text-blue-600" />
                  <p className="mt-4 text-sm text-slate-500">
                    Tổng tài khoản Facebook
                  </p>
                  <p className="mt-2 text-3xl font-bold">
                    {workspace.stats.facebook_accounts}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-5">
                  <ShieldCheck size={21} className="text-green-600" />
                  <p className="mt-4 text-sm text-slate-500">
                    Tài khoản có trạng thái kết nối
                  </p>
                  <p className="mt-2 text-3xl font-bold">
                    {workspace.stats.connected_accounts}
                  </p>
                </div>
              </div>
            </div>
          )}
          {activeTab === "accounts" && (
            <CTVAccountsTable pipelineId={workspace.pipeline.id} />
          )}
          {activeTab === "groups" && (
            <FacebookGroupsPanel
              pipelineId={workspace.pipeline.id}
              backHref={null}
            />
          )}
          {activeTab === "albums" && (
            <AlbumLibrary
              pipelineId={workspace.pipeline.id}
              backHref={null}
            />
          )}
        </main>
      </div>
    </div>
  );
}
