import type { Metadata } from "next";
import AlbumLibrary from "@/features/albums/components/AlbumLibrary";
export const metadata: Metadata = {
  title: "Album Library | ToolNet Publisher",
  robots: {
    index: false,
    follow: false,
  },
};
export default async function PipelineAlbumsPage({
  params,
}: {
  params: Promise<{ pipelineId: string }>;
}) {
  const { pipelineId } = await params;
  return (
    <div className="mx-auto max-w-6xl">
      <AlbumLibrary pipelineId={pipelineId} />
    </div>
  );
}
