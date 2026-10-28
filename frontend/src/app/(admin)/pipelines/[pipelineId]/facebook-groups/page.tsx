import type { Metadata } from "next";
import FacebookGroupsPanel from "@/features/facebook-groups/components/FacebookGroupsPanel";
export const metadata: Metadata = {
  title: "Facebook Groups | ToolNet Publisher",
  robots: {
    index: false,
    follow: false,
  },
};
interface Props {
  params: Promise<{
    pipelineId: string;
  }>;
}
export default async function FacebookGroupsPage({
  params,
}: Props) {
  const { pipelineId } = await params;
  return (
    <div className="mx-auto max-w-6xl">
      <FacebookGroupsPanel pipelineId={pipelineId} />
    </div>
  );
}
