/**
 * The product screen while the route changes underneath it (T05): a save that was started for one product
 * must never be written into the screen of another.
 */
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const harness = vi.hoisted(() => ({
  params: { id: "1" } as Record<string, string>,
  handle: undefined as undefined | ((method: string, path: string, init?: Record<string, unknown>) => unknown),
}));

vi.mock("next/navigation", () => ({ useParams: () => harness.params }));

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
    return harness.handle?.(method, path, init);
  };
  return {
    ApiError,
    toApiError: (error: unknown) => (error instanceof ApiError ? error : new ApiError(0, "client_error", String(error))),
    call: (request_: Promise<{ data?: unknown }>) => request_.then((response) => response.data),
    api: { GET: request("GET"), POST: request("POST"), PATCH: request("PATCH"), PUT: request("PUT") },
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
      store_name: "Sydney CBD", staff_type: "store", runs_store: true,
    },
    signedIn: true,
    staffError: undefined,
    error: undefined,
    reload: () => {},
  }),
}));

import ProductPage from "./page";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const product = (product_id: number, name: string) => ({
  product_id, sku: `TEST-${product_id}`, name, brand_id: 1, brand: "Sony", category_id: 1,
  category: "Headphones", base_price: "199.00", current_price: "199.00", on_sale: false,
  is_active: true, total_stock: 5, specs: [], promotions: [],
  stock: [{ store_id: 1, store_name: "Sydney CBD", store_type: "retail", state: "NSW", quantity: 5 }],
});

beforeEach(() => {
  harness.params = { id: "1" };
});

describe("the product detail screen", () => {
  it("drops a save that was started for the product the route has left", async () => {
    const user = userEvent.setup();
    const first = deferred<ReturnType<typeof product>>();
    const second = deferred<ReturnType<typeof product>>();
    const save = deferred<ReturnType<typeof product>>();

    harness.handle = (method, path) => {
      if (path === "/api/v1/brands") return Promise.resolve({ data: [{ brand_id: 1, name: "Sony" }] });
      if (path === "/api/v1/categories") return Promise.resolve({ data: [] });
      if (method === "PATCH") return save.promise.then((data) => ({ data }));
      if (path === "/api/v1/products/{product_id}") {
        return (harness.params.id === "1" ? first.promise : second.promise).then((data) => ({ data }));
      }
      throw new Error(`${method} ${path} is not expected in this test`);
    };

    const view = render(<ProductPage />);
    await act(async () => first.resolve(product(1, "One")));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sony One");

    // Edit and save product 1, leaving the request in flight.
    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "One edited");
    const details = screen.getByRole("heading", { name: "Details" }).closest("section")!;
    await user.click(within(details).getByRole("button", { name: "Save" }));

    // The route moves to product 2 before product 1's save comes back.
    harness.params = { id: "2" };
    view.rerender(<ProductPage />);
    await act(async () => second.resolve(product(2, "Two")));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sony Two");

    await act(async () => save.resolve(product(1, "One edited")));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sony Two");
  });
});
