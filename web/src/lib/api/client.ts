import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

// Typed from the FastAPI OpenAPI spec (npm run gen:api). Same origin: next.config.ts forwards /api/*.
export const api = createClient<paths>({ baseUrl: "" });

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
export type Address = Schemas["Address"];
export type OrderSummary = Schemas["OrderSummary"];
export type OrderDetail = Schemas["OrderDetail"];
export type OrderLine = Schemas["OrderLine"];
export type OrderStatus = OrderDetail["status"];
export type FulfilmentMethod = OrderDetail["fulfilment_method"];
export type Payment = Schemas["Payment"];
export type StatusHistoryEntry = Schemas["StatusHistoryEntry"];
export type ReturnEligibility = Schemas["ReturnEligibility"];
export type ReturnableLine = Schemas["ReturnableLine"];
export type ReturnSummary = Schemas["ReturnSummary"];
export type ReturnDetail = Schemas["ReturnDetail"];
export type ReturnStatus = ReturnDetail["status"];
export type ReturnStatusEntry = Schemas["ReturnStatusEntry"];

/**
 * Codes the *application* raises. The database's own refusals are the odd ones out, so `isRule` is
 * "409 and not one of these" — that keeps the rule names (`br07_...`) inspectable while a conflict such
 * as `price_changed` is not mislabelled as a database rule.
 */
const APPLICATION_CODES = new Set([
  "validation_error", "invalid_value", "not_found", "not_signed_in", "staff_only", "customer_only",
  "manager_only", "store_staff_only", "other_store", "not_your_account", "staff_cannot_read_this",
  "demo_sign_in_disabled", "price_changed", "out_of_stock", "product_unavailable", "address_inactive",
  "delivery_needs_address", "invalid_price_range", "duplicate_items", "duplicate_lines", "stale_status",
  "idempotency_conflict", "cancellation_required", "cancellation_conflict", "return_status_transition",
  "network_error", "api_unavailable", "client_error",
]);

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

  /** True when the database itself refused the request (a constraint or trigger). */
  get isRule(): boolean {
    return this.status === 409 && !APPLICATION_CODES.has(this.code) && !this.code.startsWith("http_");
  }

  /** True when the request was refused for a reason the page can explain and the user can act on. */
  get isConflict(): boolean {
    return this.status === 409 && !this.isRule;
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
