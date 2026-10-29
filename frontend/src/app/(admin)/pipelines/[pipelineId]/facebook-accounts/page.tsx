import type { Metadata } from "next";
import FacebookAccountsPanel from "@/features/facebook-accounts/components/FacebookAccountsPanel";
export const metadata: Metadata = {
  title: "Facebook Accounts | ToolNet Fplus24h",
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
export default async function FacebookAccountsPage({
  params,
}: Props) {
  const { pipelineId } = await params;
  return (
    <FacebookAccountsPanel
      pipelineId={pipelineId}
    />
  );
}
