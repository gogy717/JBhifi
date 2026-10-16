import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StaffProvider } from "@/components/admin/staff-gate";
import type { Me } from "@/lib/api/client";

import SupportPage from "./page";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
  call: <T,>(request: Promise<T>) => request,
}));

const nora: Me = { kind: "staff", id: 40, display_name: "Nora Fitzgerald", store_id: null, store_name: null,
  staff_type: "support", runs_store: false };

api.GET.mockImplementation(async (path: string) => {
  switch (path) {
    case "/api/v1/customers":
      return [{ customer_id: 1, full_name: "Alice Morgan", email: "alice.morgan@example.com" }];
    case "/api/v1/customers/{customer_id}":
      return { customer_id: 1, full_name: "Alice Morgan", email: "alice.morgan@example.com", phone: null,
        created_at: "2025-09-11T00:00:00Z", addresses: [] };
    case "/api/v1/customers/{customer_id}/orders":
      return [{ order_id: 1500, status: "paid", fulfilment_method: "click_collect", fulfilling_store_name: "Sydney CBD",
        placed_at: "2026-10-15T00:00:00Z", total: "1199.00" }];
    default:
      return [];
  }
});

describe("the support page", () => {
  it("the_chosen_customer_is_marked_current_and_their_orders_are_named", async () => {
    render(<StaffProvider me={nora}><SupportPage /></StaffProvider>);
    fireEvent.change(screen.getByRole("textbox", { name: "Find a customer" }), { target: { value: "alice" } });
    fireEvent.click(await screen.findByRole("button", { name: /Alice Morgan/ }));
    expect(screen.getByRole("button", { name: /Alice Morgan/ })).toHaveAttribute("aria-current", "true");
    expect(await screen.findByRole("link", { name: "Order #1500" })).toHaveAttribute("href", "/orders/1500");
  });
});
