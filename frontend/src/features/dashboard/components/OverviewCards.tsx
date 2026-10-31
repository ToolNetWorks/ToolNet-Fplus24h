import {
  Workflow,
  Users,
  CircleCheck,
  Lock,
} from "lucide-react";

import type {
  DashboardOverview,
} from "../api/get-overview";

interface Props {
  overview: DashboardOverview;
}

export default function OverviewCards({
  overview,
}: Props) {
  const cards = [
    {
      title: "Tổng CTV",
      value: overview.total_pipelines,
      icon: Workflow,
      color: "text-blue-600",
    },
    {
      title: "Tổng CTV",
      value: overview.total_ctv,
      icon: Users,
      color: "text-indigo-600",
    },
    {
      title: "Đang hoạt động",
      value: overview.active_pipelines,
      icon: CircleCheck,
      color: "text-green-600",
    },
    {
      title: "Đã tạm khóa",
      value: overview.disabled_pipelines,
      icon: Lock,
      color: "text-red-600",
    },
  ];

  return (
    <section className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;

        return (
          <article
            key={card.title}
            className="rounded-xl border border-slate-200 bg-white p-6"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-500">
                {card.title}
              </span>

              <Icon
                size={21}
                className={card.color}
              />
            </div>

            <div className="mt-5 text-3xl font-bold text-slate-900">
              {card.value.toLocaleString("vi-VN")}
            </div>

            <p className="mt-2 text-xs text-slate-400">
              Dữ liệu từ Neon PostgreSQL
            </p>
          </article>
        );
      })}
    </section>
  );
}
