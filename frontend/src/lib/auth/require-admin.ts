import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const DJANGO_URL =
  process.env.DJANGO_INTERNAL_URL ??
  "http://127.0.0.1:8010";

const SESSION_COOKIE_NAME =
  process.env.DJANGO_SESSION_COOKIE_NAME ??
  "sessionid";

/**
 * Server-side authorization.
 *
 * Django remains the source of truth
 * for authentication and permissions.
 */
export async function requireAdmin(): Promise<void> {
  const cookieStore = await cookies();

  const session = cookieStore.get(SESSION_COOKIE_NAME);

  if (!session?.value) {
    redirect("/login/");
  }

  let authorized = false;

  try {
    const response = await fetch(
      `${DJANGO_URL}/api/v1/auth/me/`,
      {
        method: "GET",
        headers: {
          Cookie:
            `${SESSION_COOKIE_NAME}=${session.value}`,
        },
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      }
    );

    authorized = response.status === 200;
  } catch {
    authorized = false;
  }

  if (!authorized) {
    redirect("/login/");
  }
}
