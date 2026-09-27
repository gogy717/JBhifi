import { ApiError } from "./api/client";

/**
 * The demo session. The API issues a signed, HTTP-only cookie; the browser only says *who to sign in as*.
 * Nothing here is an authorisation decision — every one of those is made by the API from the cookie.
 *
 * These calls use plain `fetch` rather than the generated client: the session endpoints are tiny, and
 * keeping them out of the generated types means the sign-in code cannot be broken by an API change.
 */

export type SessionKind = "customer" | "staff";

export type Session = {
  kind: SessionKind;
  id: number;
  display_name: string;
  store_id: number | null;
  store_name: string | null;
  staff_type: string | null;
  runs_store: boolean;
};

const SESSION_URL = "/api/v1/session";

async function request(init?: RequestInit): Promise<Session | null> {
  let response: Response;
  try {
    response = await fetch(SESSION_URL, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the API. Is `fastapi dev app/main.py` running?");
  }
  if (response.status === 204) return null;
  const body = await response.json().catch(() => undefined);
  if (!response.ok) {
    const info = (body as { error?: { code?: string; message?: string } } | undefined)?.error;
    throw new ApiError(response.status, info?.code ?? `http_${response.status}`,
      info?.message ?? response.statusText);
  }
  return (body as Session | null) ?? null;
}

/** The identity the API currently sees, or null for a guest. */
export function getSession(): Promise<Session | null> {
  return request();
}

/** Become this customer or staff member (demo sign-in; the server decides whether that is allowed). */
export function signIn(kind: SessionKind, id: number): Promise<Session | null> {
  return request({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, id }),
  });
}

export function signOut(): Promise<Session | null> {
  return request({ method: "DELETE" });
}

/**
 * Make the session match the surface's chosen identity, touching nothing when it already does.
 *
 * The storefront and the admin share one cookie, so each surface declares who *it* acts as when it
 * loads: the storefront is always the chosen customer, the admin always the chosen staff member.
 * `undefined` means guest, which signs the session out.
 */
export async function ensureSession(kind: SessionKind, id: number | undefined): Promise<Session | null> {
  const current = await getSession();
  if (id === undefined) {
    if (current !== null) await signOut();
    return null;
  }
  if (current !== null && current.kind === kind && current.id === id) return current;
  return signIn(kind, id);
}
