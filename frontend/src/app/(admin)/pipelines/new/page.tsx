import type { Metadata } from "next";

import CreatePipelineForm from "@/features/pipelines/components/CreatePipelineForm";

export const metadata: Metadata = {
  title: "Quản lý Pipeline | ToolNet Fplus24h",
  robots: {
    index: false,
    follow: false,
  },
};

export default function PipelinesPage() {
  return (
    <div className="space-y-7">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">
          Quản lý Pipeline
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          Tạo Pipeline và tài khoản cộng tác viên mới.
        </p>
      </header>

      <CreatePipelineForm />
    </div>
  );
}
