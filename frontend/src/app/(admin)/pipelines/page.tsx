import type { Metadata } from "next";

import PipelineList from "@/features/pipelines/components/PipelineList";

export const metadata: Metadata = {
  title: "Danh sách CTV | ToolNet Fplus24h",
  robots: {
    index: false,
    follow: false,
  },
};

export default function PipelinesPage() {
  return (
    <div className="space-y-6">
      <PipelineList />
    </div>
  );
}
