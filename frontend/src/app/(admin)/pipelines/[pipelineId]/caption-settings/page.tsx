import AdminCaptionSettings from '@/features/pipelines/components/AdminCaptionSettings';

export const metadata = { title: 'Khóa trang đích | ToolNet Fplus24h', robots: { index: false } };

export default async function Page({ params }: { params: Promise<{ pipelineId: string }> }) {
  const { pipelineId } = await params;
  return <AdminCaptionSettings pipelineId={pipelineId} />;
}
