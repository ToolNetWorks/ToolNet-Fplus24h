"use client";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Users,
  UsersRound,
  Network,
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
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
import { getCsrfToken } from "@/features/auth/api/auth-client";
import CTVAccountsTable from "./CTVAccountsTable";
import CTVProxyTable from "./CTVProxyTable";
import CTVGroupsTable from "./CTVGroupsTable";
import CTVAlbumsTable from "./CTVAlbumsTable";
import CTVMediaSources from "./CTVMediaSources";
import CTVPublishingJobs from "./CTVPublishingJobs";
import CTVScheduler from "./CTVScheduler";
import CTVDashboard from "./CTVDashboard";
import "./ctv-shell.css";

type Tab = "overview" | "accounts" | "proxies" | "groups" | "albums" | "media" | "jobs" | "scheduler";

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
        label: "Quản lý Proxy",
        icon: Network,
        tab: "proxies",
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
      { label: "Cấu hình Album nguồn", icon: SlidersHorizontal, tab: "media" },
      { label: "Cấu hình lịch tự động", icon: CalendarDays, tab: "scheduler" },
      { label: "Đăng bài viết nhóm", icon: FileText },
      { label: "AI viết Caption", icon: Sparkles },
      { label: "Lịch đăng bài", icon: CalendarDays, tab: "jobs" },
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
  proxies: "Quản lý Proxy",
  groups: "Quản lý Facebook Groups",
  albums: "Thư viện Album ảnh",
  media: "Cấu hình Album nguồn",
  jobs: "Lịch đăng bài & Hàng đợi",
  scheduler: "Cấu hình lịch tự động",
};

const STORAGE_KEY = "toolnet-ctv-sidebar-collapsed";

export default function CTVShell({
  workspace,
}: {
  workspace: WorkspacePayload;
}) {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [mediaDirty, setMediaDirty] = useState(false);
  const [schedulerDirty, setSchedulerDirty] = useState(false);
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
    if (tab === activeTab) {
      setMobileOpen(false);
      return;
    }
    if (activeTab === "media" && mediaDirty &&
        !window.confirm("Cấu hình Album nguồn có thay đổi chưa lưu. Rời trang và bỏ thay đổi?")) {
      return;
    }
    if (activeTab === "scheduler" && schedulerDirty &&
        !window.confirm("Cấu hình lịch có thay đổi chưa lưu. Rời trang và bỏ thay đổi?")) {
      return;
    }
    setActiveTab(tab);
    setMediaDirty(false);
    setSchedulerDirty(false);
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
            <CTVDashboard pipelineId={workspace.pipeline.id} pipelineName={workspace.pipeline.name} onNavigate={selectTab} />
          )}
          {activeTab === "accounts" && (
            <CTVAccountsTable pipelineId={workspace.pipeline.id} />
          )}
          {activeTab === "proxies" && (
            <CTVProxyTable pipelineId={workspace.pipeline.id} />
          )}
          {activeTab === "groups" && (
            <CTVGroupsTable pipelineId={workspace.pipeline.id} />
          )}
          {activeTab === "albums" && (
            <CTVAlbumsTable pipelineId={workspace.pipeline.id} />
          )}
          {activeTab === "jobs" && (
            <CTVPublishingJobs pipelineId={workspace.pipeline.id} />
          )}
          {activeTab === "scheduler" && (
            <CTVScheduler pipelineId={workspace.pipeline.id} onDirtyChange={setSchedulerDirty} />
          )}
          {activeTab === "media" && (
            <CTVMediaSources
              pipelineId={workspace.pipeline.id}
              onDirtyChange={setMediaDirty}
            />
          )}
        </main>
      </div>
    </div>
  );
}
