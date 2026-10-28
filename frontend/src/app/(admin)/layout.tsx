import type { ReactNode } from "react";

import AdminShell from "@/components/layout/AdminShell";
import { requireAdmin } from "@/lib/auth/require-admin";

export const dynamic = "force-dynamic";

interface AdminLayoutProps {
  children: ReactNode;
}

export default async function AdminLayout({
  children,
}: AdminLayoutProps) {
  await requireAdmin();

  return (
    <AdminShell>
      {children}
    </AdminShell>
  );
}
