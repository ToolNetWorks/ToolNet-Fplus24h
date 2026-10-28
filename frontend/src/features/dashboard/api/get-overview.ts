import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export interface DashboardOverview {
  total_pipelines: number;
  total_ctv: number;
  active_pipelines: number;
  disabled_pipelines: number;
}

interface OverviewResponse {
  success: boolean;
  data: DashboardOverview;
}

const DJANGO_URL =
  process.env.DJANGO_INTERNAL_URL ??
  "http://127.0.0.1:8010";

export async function getOverview():
  Promise<DashboardOverview | null> {

  const cookieStore = await cookies();
  const session = cookieStore.get("sessionid");

  if (!session?.value) {
    redirect("/login/");
  }

  let response: Response;

  try {
    response = await fetch(
      `${DJANGO_URL}/api/v1/admin/overview/`,
      {
        method: "GET",
        headers: {
          Cookie: `sessionid=${session.value}`,
          Accept: "application/json",
        },
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      }
    );
  } catch {
    return null;
  }

  if ([401, 403].includes(response.status)) {
    redirect("/login/");
  }

  if (!response.ok) {
    return null;
  }

  let result: OverviewResponse;

  try {
    result = await response.json();
  } catch {
    return null;
  }

  if (!result.success || !result.data) {
    return null;
  }

  const values = [
    result.data.total_pipelines,
    result.data.total_ctv,
    result.data.active_pipelines,
    result.data.disabled_pipelines,
  ];

  if (
    !values.every(
      (value) => Number.isInteger(value) && value >= 0
    )
  ) {
    return null;
  }

  return result.data;
}
