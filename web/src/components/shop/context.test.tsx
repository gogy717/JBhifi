/**
 * Switching the demo customer (T05, review risk 3): while the new customer's own record is still on its
 * way — or when it fails — the previous customer's details must not appear under the new name.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const harness = vi.hoisted(() => ({
  ensureSession: undefined as undefined | ((kind: string, id: number | undefined) => Promise<unknown>),
  handle: undefined as undefined | ((method: string, path: string, init?: Record<string, unknown>) => Promise<{ data?: unknown }>),
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
    return harness.handle?.(method, path, init);
  };
  return {
    ApiError,
    toApiError: (error: unknown) => (error instanceof ApiError ? error : new ApiError(0, "client_error", String(error))),
    call: (request_: Promise<{ data?: unknown }>) => request_.then((response) => response.data),
    api: { GET: request("GET"), POST: request("POST") },
  };
});

vi.mock("@/lib/session", () => ({
  ensureSession: (kind: string, id: number | undefined) => harness.ensureSession!(kind, id),
}));

import { ShopProvider, useShop } from "./context";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const detail = (customer_id: number, full_name: string) => ({
  customer_id, full_name, email: `c${customer_id}@example.com`, phone: null,
  created_at: new Date().toISOString(),
  addresses: [{ address_no: 1, line1: "1 Demo St", suburb: "Sydney", state: "NSW", postcode: "2000", is_active: true }],
});

const CUSTOMERS = [
  { customer_id: 1, full_name: "Alice Morgan", email: "alice@example.com" },
  { customer_id: 2, full_name: "Ben Okafor", email: "ben@example.com" },
];

/** The server's answer to "act as this customer": the signed session, or null for a guest. */
const session = (_kind: string, id: number | undefined) => {
  const found = CUSTOMERS.find((c) => c.customer_id === id);
  return found === undefined ? Promise.resolve(null) : Promise.resolve({
    kind: "customer", id, display_name: found.full_name,
    store_id: null, store_name: null, staff_type: null, runs_store: false,
  });
};

function Probe() {
  const { customer, customerError, setCustomerId, reload } = useShop();
  return (
    <div>
      <p data-testid="customer">{customer ? `${customer.customer_id}:${customer.full_name}` : ""}</p>
      <p data-testid="error">{customerError?.code ?? ""}</p>
      <button type="button" onClick={() => setCustomerId(2)}>switch to Ben</button>
      <button type="button" onClick={reload}>Try again</button>
    </div>
  );
}

const shown = () => screen.getByTestId("customer").textContent;
const failure = () => screen.getByTestId("error").textContent;

/** Stores and categories are not this test's subject; the customer's own record is. */
function serve(records: Record<number, Promise<unknown>>) {
  harness.handle = (method, path, init) => {
    if (path === "/api/v1/customers") return Promise.resolve({ data: CUSTOMERS });
    if (path === "/api/v1/stores" || path === "/api/v1/categories") return Promise.resolve({ data: [] });
    if (path === "/api/v1/customers/{customer_id}") {
      const id = (init?.params as { path?: { customer_id: number } } | undefined)?.path?.customer_id ?? 0;
      return records[id].then((data) => ({ data }));
    }
    throw new Error(`${method} ${path} is not expected in this test`);
  };
}

beforeEach(() => {
  window.localStorage.clear();
  harness.ensureSession = session;
});

describe("the storefront's demo customer", () => {
  it("never shows the previous customer's record under the new name", async () => {
    const user = userEvent.setup();
    const alice = deferred<unknown>();
    const ben = deferred<unknown>();
    serve({ 1: alice.promise, 2: ben.promise });
    window.localStorage.setItem("jb.shop.customerId", "1");

    render(<ShopProvider><Probe /></ShopProvider>);
    await act(async () => alice.resolve(detail(1, "Alice Morgan")));
    expect(shown()).toBe("1:Alice Morgan");

    // The shopper switches to Ben; his record has not arrived yet.
    await user.click(screen.getByRole("button", { name: "switch to Ben" }));
    await act(async () => {});
    expect(shown()).toBe("");
    expect(failure()).toBe("");

    await act(async () => ben.resolve(detail(2, "Ben Okafor")));
    expect(shown()).toBe("2:Ben Okafor");
  });

  it("surfaces a failed record and shows it after a retry", async () => {
    const user = userEvent.setup();
    const failed = deferred<unknown>();
    const retried = deferred<unknown>();
    let attempts = 0;
    serve({ 1: Promise.resolve(detail(1, "Alice Morgan")) });
    const base = harness.handle!;
    harness.handle = (method, path, init) => {
      if (path === "/api/v1/customers/{customer_id}") {
        return (attempts++ === 0 ? failed.promise : retried.promise).then((data) => ({ data }));
      }
      return base(method, path, init);
    };
    window.localStorage.setItem("jb.shop.customerId", "1");

    render(<ShopProvider><Probe /></ShopProvider>);
    await act(async () => failed.reject(new (await import("@/lib/api/client")).ApiError(500, "api_unavailable", "No API.")));
    expect(failure()).toBe("api_unavailable");
    expect(shown()).toBe("");

    await user.click(screen.getByRole("button", { name: "Try again" }));
    await act(async () => retried.resolve(detail(1, "Alice Morgan")));
    expect(failure()).toBe("");
    expect(shown()).toBe("1:Alice Morgan");
  });
});
