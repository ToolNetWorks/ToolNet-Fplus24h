import OverviewCards from "@/features/dashboard/components/OverviewCards";
import { getOverview } from "@/features/dashboard/api/get-overview";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const overview = await getOverview();

  return (
    <div className="space-y-7">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">
          Dashboard
        </h1>

        <p className="mt-2 text-sm text-slate-500">
          Tổng quan hệ thống CTV và cộng tác viên.
        </p>
      </header>

      {overview ? (
        <OverviewCards overview={overview} />
      ) : (
        <div
          role="alert"
          className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800"
        >
          Không tải được dữ liệu Dashboard.
          Vui lòng kiểm tra kết nối Django API.
        </div>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="font-semibold text-slate-900">
          Quản lý CTV
        </h2>

        <p className="mt-2 text-sm text-slate-500">
          Danh sách CTV và chức năng tạo Pipeline
          sẽ được triển khai ở bước tiếp theo.
        </p>
      </section>
    </div>
  );
}
