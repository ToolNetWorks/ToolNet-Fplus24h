"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Workflow,
  Users,
  Settings,
  X,
} from "lucide-react";

import LogoutButton from "@/features/auth/components/LogoutButton";

type SidebarProps = {
  collapsed: boolean;
  mobileOpen: boolean;
  onClose: () => void;
};

const menuItems = [
  {
    label: "Dashboard",
    href: "/",
    icon: LayoutDashboard,
    enabled: true,
  },
  {
    label: "Quản lý Pipeline",
    href: "/pipelines",
    icon: Workflow,
    enabled: true,
  },
  {
    label: "Quản lý CTV",
    href: "/ctv",
    icon: Users,
    enabled: false,
  },
  {
    label: "Cài đặt Admin",
    href: "/settings",
    icon: Settings,
    enabled: false,
  },
];

export default function Sidebar({
  collapsed,
  mobileOpen,
  onClose,
}: SidebarProps) {
  const pathname = usePathname();

  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          className="sidebar-overlay"
          aria-label="Đóng menu"
          onClick={onClose}
        />
      )}

      <aside
        id="toolnet-sidebar"
        className={[
          "toolnet-sidebar",
          collapsed ? "is-collapsed" : "",
          mobileOpen ? "mobile-open" : "",
        ].join(" ")}
      >
        <div className="sidebar-brand">
          <div className="brand-logo">T</div>

          <div className="brand-title">
            <strong>TOOLNET</strong>
            <span>PUBLISHER</span>
          </div>

          <button
            className="sidebar-close"
            onClick={onClose}
            aria-label="Đóng menu"
            type="button"
          >
            <X size={20} />
          </button>
        </div>

        <div className="sidebar-section-title">
          QUẢN TRỊ HỆ THỐNG
        </div>

        <nav className="sidebar-nav">
          {menuItems.map((item) => {
            const Icon = item.icon;

            const active =
              pathname === item.href ||
              (item.href !== "/" &&
                pathname.startsWith(`${item.href}/`));

            const content = (
              <>
                <Icon size={19} strokeWidth={1.9} />
                <span className="nav-text">
                  {item.label}
                </span>
              </>
            );

            if (!item.enabled) {
              return (
                <div
                  key={item.href}
                  className="sidebar-link is-disabled"
                  title={`${item.label} - đang phát triển`}
                  aria-disabled="true"
                >
                  {content}
                </div>
              );
            }

            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                className={[
                  "sidebar-link",
                  active ? "active" : "",
                ].join(" ")}
                title={item.label}
              >
                {content}
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="footer-account">
            <div className="account-avatar">A</div>

            <div className="account-details">
              <strong>Administrator</strong>
              <span>Admin Workspace</span>
            </div>
          </div>

          <LogoutButton />
        </div>
      </aside>
    </>
  );
}
