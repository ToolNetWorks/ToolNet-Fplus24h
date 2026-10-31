import type { Metadata } from "next";

import CTVManagement from "@/features/admin-ctv/components/CTVManagement";

export const metadata: Metadata = {
  title: "Quản lý CTV | ToolNet Fplus24h",
  robots: {
    index: false,
    follow: false,
  },
};

export default function CTVManagementPage() {
  return (
    <div className="space-y-6">
      <CTVManagement />
    </div>
  );
}
