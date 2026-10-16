import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

// Typed from the FastAPI OpenAPI spec (npm run gen:api). Same origin: next.config.ts forwards /api/*.
export const api = createClient<paths>({ baseUrl: "" });

// Every request carries the signed-in user's Clerk session token. <ApiAuth/> (inside <ClerkProvider>)
// registers Clerk's getToken here; until then — and for guests — requests go without one.
type GetToken = (options?: { skipCache?: boolean }) => Promise<string | null>;
let getToken: GetToken = async () => null;

export function setTokenGetter(next: GetToken) {
  getToken = next;
}

const sent = new Map<string, Request>();   // a copy of each request in flight, in case it must be retried

api.use({
  async onRequest({ request, id }) {
    const token = await getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    sent.set(id, request.clone());
    return request;
  },
  async onResponse({ response, id }) {
    const copy = sent.get(id);
    sent.delete(id);
    // A token can expire between Clerk handing it out and the API checking it: retry once with a fresh one.
    if (response.status !== 401 || !copy) return response;
    const body = (await response.clone().json().catch(() => null)) as ErrorBody | null;
    if (body?.error?.code !== "invalid_token") return response;
    const token = await getToken({ skipCache: true });
    if (!token) return response;
    copy.headers.set("Authorization", `Bearer ${token}`);
    return fetch(copy);
  },
  onError({ id }) {
    sent.delete(id);
  },
});

type Schemas = components["schemas"];
export type Store = Schemas["StoreOut"];
export type Staff = Schemas["StaffOut"];
export type Category = Schemas["CategoryOut"];
export type Brand = Schemas["BrandOut"];
export type InventoryRow = Schemas["InventoryRow"];
export type Adjustment = Schemas["AdjustmentOut"];
export type AdjustmentReason = Schemas["AdjustmentCreate"]["reason"];
export type ProductSummary = Schemas["ProductSummary"];
export type ProductDetail = Schemas["ProductDetail"];
export type Spec = Schemas["Spec"];
export type Promotion = Schemas["PromotionOut"];
export type PromotionStatus = Promotion["status"];
export type Customer = Schemas["CustomerSummary"];
export type CustomerDetail = Schemas["CustomerDetail"];
export type Me = Schemas["Me"];
export type Address = Schemas["Address"];
export type AddressCreate = Schemas["AddressCreate"];
export type OrderCreate = Schemas["OrderCreate"];
export type OrderSummary = Schemas["OrderSummary"];
export type OrderDetail = Schemas["OrderDetail"];
export type OrderStatus = Schemas["StatusMove"]["from_status"];
export type StaffMove = Schemas["StatusMove"]["to_status"];

/** The 409s the application itself answers: at checkout (T1), the price changed since the review or the stock ran
 *  out; on an order's status, it moved on since the screen showed it (status_changed). Every other 409 is the
 *  database refusing the request, with the constraint's name as the code. */
export const APP_CONFLICTS: ReadonlySet<string> = new Set(["price_changed", "out_of_stock", "status_changed"]);

/** Every API error has this shape; for database rules, `code` is the constraint name (brNN_…). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
  }

  /** True when the database itself refused the request (a constraint or trigger) — not one of the
   *  application's own conflicts, so the error box doesn't call a changed price "rejected by the database". */
  get isRule(): boolean {
    return this.status === 409 && !APP_CONFLICTS.has(this.code);
  }
}

type ErrorBody = { error?: { code?: string; message?: string; detail?: unknown } };

/** Await an openapi-fetch call: return its data, or throw an ApiError. */
export async function call<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result;
  try {
    result = await request;
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the API. Is `fastapi dev app/main.py` running?");
  }
  const { data, error, response } = result;
  if (!response.ok) {
    const info = (error as ErrorBody | undefined)?.error;
    if (!info && response.status >= 500) {
      throw new ApiError(response.status, "api_unavailable",
        "The API didn't answer. Is `fastapi dev app/main.py` running, and the database up?");
    }
    throw new ApiError(response.status, info?.code ?? `http_${response.status}`,
      info?.message ?? response.statusText, info?.detail);
  }
  return data as T;
}

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, "client_error", String(error));
}
