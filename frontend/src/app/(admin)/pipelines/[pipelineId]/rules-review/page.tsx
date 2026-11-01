import Link from "next/link";
import RulesReviewPanel from "@/features/ctv/components/RulesReviewPanel";

export const metadata = { title: "Xác nhận quy tắc Facebook", robots: { index: false } };

export default async function Page({ params }: { params: Promise<{ pipelineId: string }> }) {
  const { pipelineId } = await params;
  return <main className="space-y-4 p-4"><Link href="/pipelines/" className="text-blue-700">← Danh sách Pipeline</Link>
    <h1 className="text-xl font-bold">Xác nhận quy tắc Facebook</h1><RulesReviewPanel pipelineId={pipelineId} /></main>;
}
