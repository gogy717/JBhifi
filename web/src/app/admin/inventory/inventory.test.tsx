/**
 * The stock screen under a store switch (T05). The reviewer's question is "can a response that belongs to
 * store A change what store B shows?", so the API client is replaced by promises this test resolves by
 * hand and the race itself is real.
 */
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const harness = vi.hoisted(() => ({
  /** Every call the page made, so a test can assert what it asked for. */
  calls: [] as { method: string; path: string; params?: Record<string, unknown> }[],
  handle: undefined as undefined | ((method: string, path: string, init?: Record<string, unknown>) => unknown),
}));

vi.mock("@/lib/api/client", () => {
  class ApiError extends Error {
    constructor(readonly status: number, readonly code: string, message: string) {
      super(message);
    }
    get isRule() {
      return this.status === 409;
    }
  }
  const request = (method: string) => (path: string, init?: Record<string, unknown>) => {
    harness.calls.push({ method, path, params: init?.params as Record<string, unknown> | undefined });
    return harness.handle?.(method, path, init);
  };
  return {
    ApiError,
    toApiError: (error: unknown) => (error instanceof ApiError ? error : new ApiError(0, "client_error", String(error))),
    /** The real client resolves to the response body; the mock handlers return the same shape. */
    call: (request_: Promise<{ data?: unknown }>) => request_.then((response) => response.data),
    api: { GET: request("GET"), POST: request("POST"), DELETE: request("DELETE") },
  };
});

vi.mock("@/components/admin/session", () => ({
  useAdminSession: () => ({
    staff: [],
    staffLoading: false,
    chosenStaffId: 14,
    setStaffId: () => {},
    session: {
      kind: "staff", id: 14, display_name: "Aiden Chen", store_id: 1,
      store_name: "Sydney CBD", staff_type: "store", runs_store: false,
    },
    signedIn: true,
    error: undefined,
    reload: () => {},
  }),
}));

import InventoryPage from "./page";

/** A promise this test resolves by hand, so a response can arrive after the store has changed. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type Row = {
  product_id: number; sku: string; name: string; brand: string; category: string;
  current_price: string; on_sale: boolean; is_active: boolean; quantity: number;
};

const row = (product_id: number, name: string, quantity: number): Row => ({
  product_id, sku: `TEST-${product_id}`, name, brand: "Sony", category: "Headphones",
  current_price: "199.00", on_sale: false, is_active: true, quantity,
});

const STORES = [
  { store_id: 1, name: "Sydney CBD", store_type: "retail", suburb: "Sydney", state: "NSW", manager_id: 14, manager_name: "Aiden Chen" },
  { store_id: 2, name: "Bondi Junction", store_type: "retail", suburb: "Bondi", state: "NSW", manager_id: 16, manager_name: "Isla Nguyen" },
];

/** The page's shape of a request: { params: { path: {...}, query: {...} } }. */
type Params = { path?: Record<string, number>; query?: Record<string, unknown> };
const storeOf = (init?: Record<string, unknown>) => (init?.params as Params | undefined)?.path?.store_id;

beforeEach(() => {
  harness.calls.length = 0;
  harness.handle = undefined;
});

function serveInventory(rows: Record<number, Promise<Row[]>>) {
  harness.handle = (method, path, init) => {
    if (path === "/api/v1/stores") return Promise.resolve({ data: STORES });
    if (path === "/api/v1/categories") return Promise.resolve({ data: [] });
    if (path === "/api/v1/stores/{store_id}/adjustments") return Promise.resolve({ data: [] });
    if (path === "/api/v1/stores/{store_id}/inventory") {
      const storeId = storeOf(init) as number;
      return rows[storeId].then((data) => ({ data }));
    }
    throw new Error(`${method} ${path} is not expected in this test`);
  };
}

describe("the store admin's stock screen", () => {
  it("cannot let a late answer for store A change what store B shows", async () => {
    const user = userEvent.setup();
    const storeOne = deferred<Row[]>();
    const storeTwo = deferred<Row[]>();
    const adjustment = deferred<Record<string, unknown>>();
    serveInventory({ 1: storeOne.promise, 2: storeTwo.promise });
    harness.handle = ((inner) => (method: string, path: string, init?: Record<string, unknown>) => {
      if (method === "POST") return adjustment.promise.then((data) => ({ data }));
      return inner(method, path, init);
    })(harness.handle!);

    render(<InventoryPage />);
    await act(async () => storeOne.resolve([row(1, "A item", 5)]));
    expect(screen.getByText("A item")).toBeInTheDocument();

    // Start an adjustment at store 1 and leave its response in flight.
    await user.click(screen.getByRole("button", { name: "Add one A item" }));

    // Move to store 2 before store 1 answers.
    await user.selectOptions(screen.getByLabelText("Store"), "2");
    expect(screen.queryByRole("button", { name: "Add one A item" })).not.toBeInTheDocument();

    await act(async () => storeTwo.resolve([row(2, "B item", 7)]));
    const bobRow = screen.getByText("B item").closest("tr")!;
    expect(within(bobRow).getByText("7")).toBeInTheDocument();

    // Store 1's adjustment result arrives now. It must not touch store 2's rows or history.
    await act(async () => {
      adjustment.resolve({
        adjustment_id: 99, store_id: 1, product_id: 1, sku: "TEST-1", product_name: "A item",
        staff_id: 14, staff_name: "Aiden Chen", delta: 1, reason: "stocktake", note: null,
        quantity_after: 6, adjusted_at: new Date().toISOString(),
      });
    });
    // The adjustment at store 1 did happen (the success notice says so), but store 2's table is untouched.
    const table = within(screen.getByRole("table"));
    expect(table.queryByText("A item")).not.toBeInTheDocument();
    expect(within(table.getByText("B item").closest("tr")!).getByText("7")).toBeInTheDocument();
    expect(screen.getByText("No adjustments at this store yet. Try the ± buttons.")).toBeInTheDocument();
  });

  it("asks the server for the filtered rows again after an adjustment while the filter is on", async () => {
    const user = userEvent.setup();
    const rows = deferred<Row[]>();
    const shown = deferred<Row[]>();
    serveInventory({ 1: rows.promise, 2: Promise.resolve([]) });
    const base = harness.handle!;
    harness.handle = (method, path, init) => {
      if (method === "POST") {
        return Promise.resolve({
          data: {
            adjustment_id: 1, store_id: 1, product_id: 1, sku: "TEST-1", product_name: "A item",
            staff_id: 14, staff_name: "Aiden Chen", delta: 1, reason: "stocktake", note: null,
            quantity_after: 9, adjusted_at: new Date().toISOString(),
          },
        });
      }
      if (path === "/api/v1/stores/{store_id}/inventory"
        && (init?.params as Params | undefined)?.query?.low_stock_only === true) {
        return shown.promise.then((data) => ({ data }));
      }
      return base(method, path, init);
    };

    render(<InventoryPage />);
    await act(async () => rows.resolve([row(1, "A item", 2)]));
    await user.click(screen.getByLabelText("Low stock only"));
    await act(async () => shown.resolve([row(1, "A item", 2)]));

    await user.click(screen.getByRole("button", { name: "Add one A item" }));

    // Two filtered reads: the one the checkbox caused, and the refresh the adjustment caused. A local
    // edit could not know whether "9 on hand" still belongs in a "≤ 3" list.
    const filtered = harness.calls.filter((c) => c.method === "GET"
      && c.path === "/api/v1/stores/{store_id}/inventory"
      && (c.params as Params | undefined)?.query?.low_stock_only === true);
    expect(filtered).toHaveLength(2);
  });
});
