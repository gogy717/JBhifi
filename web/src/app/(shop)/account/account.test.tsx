/**
 * T06: "My account" manages addresses the only way the data allows — add one, retire one (BR16).

 * The network is mocked at the API-client boundary, so the request the page really sends is what is
 * asserted and the record it shows afterwards is the one the API would have returned.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const harness = vi.hoisted(() => ({
  addresses: [] as unknown[],
  requests: [] as { method: string; path: string; init?: Record<string, unknown> }[],
}));

vi.mock("@/lib/api/client", () => {
  class ApiError extends Error {
    constructor(readonly status: number, readonly code: string, message: string,
      readonly detail?: unknown) {
      super(message);
    }
    get isRule() {
      return this.status === 409;
    }
    get isConflict() {
      return false;
    }
  }
  const request = (method: string) => (path: string, init?: Record<string, unknown>) => {
    harness.requests.push({ method, path, init });
    return Promise.resolve(method === "GET" ? { data: read(path) } : { data: undefined });
  };
  return {
    ApiError,
    toApiError: (error: unknown) =>
      (error instanceof ApiError ? error : new ApiError(0, "client_error", String(error))),
    call: (outcome: Promise<{ data?: unknown }>) => outcome.then((response) => response.data),
    api: { GET: request("GET"), POST: request("POST"), PATCH: request("PATCH") },
  };
});

vi.mock("@/lib/session", () => ({
  ensureSession: () => Promise.resolve({
    kind: "customer", id: 7, display_name: "Priya Raman", store_id: null, store_name: null,
    staff_type: null, runs_store: false,
  }),
}));

import { ShopProvider } from "@/components/shop/context";
import AccountPage from "./page";

const address = (address_no: number, line1: string, is_active = true) =>
  ({ address_no, line1, suburb: "Sydney", state: "NSW", postcode: "2000", is_active });

function read(path: string) {
  if (path === "/api/v1/customers") {
    return [{ customer_id: 7, full_name: "Priya Raman", email: "priya@example.com" }];
  }
  if (path === "/api/v1/stores" || path === "/api/v1/categories") return [];
  if (path === "/api/v1/customers/{customer_id}") {
    return {
      customer_id: 7, full_name: "Priya Raman", email: "priya@example.com", phone: null,
      created_at: new Date("2026-01-05T00:00:00Z").toISOString(), addresses: harness.addresses,
    };
  }
  throw new Error(`${path} is not expected in this test`);
}

const renderPage = () => render(<ShopProvider><AccountPage /></ShopProvider>);

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("jb.shop.customerId", "7");
  harness.requests = [];
  harness.addresses = [address(1, "1 Demo St")];
});

describe("my account", () => {
  it("shows the customer's details and their current addresses", async () => {
    renderPage();
    expect(await screen.findByText("1 Demo St")).toBeInTheDocument();
    expect(screen.getByText("priya@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retire…" })).toBeInTheDocument();
  });

  it("adds an address with the fields that were typed, then shows what the API returned", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Add address" }));

    await user.type(screen.getByLabelText("Street address"), "12/40 Collins Street");
    await user.type(screen.getByLabelText("Suburb"), "Melbourne");
    await user.selectOptions(screen.getByLabelText("State"), "VIC");
    await user.type(screen.getByLabelText("Postcode"), "3000");

    // The API numbers the address; the page must not invent one, so it re-reads the customer.
    harness.addresses = [address(1, "1 Demo St"),
      { ...address(2, "12/40 Collins Street"), suburb: "Melbourne", state: "VIC", postcode: "3000" }];
    await user.click(screen.getByRole("button", { name: "Save address" }));

    expect(harness.requests.find((entry) => entry.method === "POST")).toMatchObject({
      path: "/api/v1/customers/{customer_id}/addresses",
      init: {
        params: { path: { customer_id: 7 } },
        body: { line1: "12/40 Collins Street", suburb: "Melbourne", state: "VIC", postcode: "3000" },
      },
    });
    expect(await screen.findByText("12/40 Collins Street")).toBeInTheDocument();
  });

  it("will not save an address whose postcode is not four digits", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Add address" }));
    await user.type(screen.getByLabelText("Street address"), "9 New Street");
    await user.type(screen.getByLabelText("Suburb"), "Newtown");
    await user.type(screen.getByLabelText("Postcode"), "20");
    expect(screen.getByRole("button", { name: "Save address" })).toBeDisabled();
    expect(screen.getByText(/Four digits/)).toBeInTheDocument();
  });

  it("retires an address by deactivating it, and never edits it", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Retire…" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    harness.addresses = [address(1, "1 Demo St", false)];
    await user.click(screen.getByRole("button", { name: "Retire address" }));

    expect(harness.requests.find((entry) => entry.method === "PATCH")).toMatchObject({
      path: "/api/v1/customers/{customer_id}/addresses/{address_no}",
      init: {
        params: { path: { customer_id: 7, address_no: 1 } },
        body: { is_active: false },
      },
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText("retired")).toBeInTheDocument();
    expect(screen.getByText("kept on past orders")).toBeInTheDocument();
  });
});
