import type { Metadata } from "next";
import CTVWorkspace from "@/features/ctv/components/CTVWorkspace";
export const metadata: Metadata = {
  title: "CTV Workspace | ToolNet Fplus24h",
  robots: {
    index: false,
    follow: false,
  },
};
export default function WorkspacePage() {
  return <CTVWorkspace />;
}
