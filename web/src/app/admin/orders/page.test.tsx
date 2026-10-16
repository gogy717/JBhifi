import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StaffProvider } from "@/components/admin/staff-gate";
import { ApiError, type Me, type OrderSummary } from "@/lib/api/client";

import OrdersPage from "./page";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
  call: <T,>(request: Promise<T>) => request,
}));

const aiden: Me = { kind: "staff", id: 14, display_name: "Aiden Chen", store_id: 1, store_name: "Sydney CBD",
  staff_type: "store", runs_store: false };

function order(order_id: number, status: string, fulfilment_method = "click_collect"): OrderSummary {
  return {
    order_id, status, fulfilment_method, customer_id: 9, fulfilling_store_id: 1, fulfilling_store_name: "Sydney CBD",
    placed_at: "2026-10-14T00:00:00Z", last_updated_at: "2026-10-15T00:00:00Z", line_count: 1, total: "100.00",
  } as OrderSummary;
}
const waiting = [order(1, "paid"), order(2, "paid"), order(3, "picking", "delivery"), order(4, "ready")];

/** The statuses each GET of the store's orders asked for. */
const orderRequests = () => api.GET.mock.calls
  .filter(([path]) => path === "/api/v1/stores/{store_id}/orders")
  .map(([, options]) => options.params.query.status);

beforeEach(() => {
  api.GET.mockReset();
  api.GET.mockImplementation(async (path: string, options?: { params: { query: { status?: string[] } } }) => {
    if (path === "/api/v1/stores") return [];
    const statuses = options?.params.query.status;
    return statuses?.includes("cancelled") ? [order(9, "cancelled")] : waiting;
  });
});

const tile = (name: RegExp) => within(screen.getByRole("group", { name: /Orders waiting/ })).getByRole("button", { name });
/** The big figure on a tile, exactly (so 12 can't pass for 2). */
const count = (name: RegExp) => tile(name).querySelector(".font-display")?.textContent;

describe("the store's order queue", () => {
  it("counts_what_waits_at_each_step_from_the_to_do_list", async () => {
    render(<StaffProvider me={aiden}><OrdersPage /></StaffProvider>);
    expect(await screen.findByRole("link", { name: "#1" })).toBeInTheDocument();
    expect(count(/To pick/)).toBe("2");
    expect(count(/Picking/)).toBe("1");
    expect(count(/Ready to collect/)).toBe("1");
    expect(count(/Shipped/)).toBe("0");
    expect(orderRequests()).toEqual([["paid", "picking", "ready", "shipped"]]);
  });

  it("each_row_says_the_next_move", async () => {
    render(<StaffProvider me={aiden}><OrdersPage /></StaffProvider>);
    expect(await screen.findAllByRole("link", { name: /^Start picking →/ })).toHaveLength(2);
    expect(screen.getByRole("link", { name: /^Mark shipped →/ })).toHaveAttribute("href", "/admin/orders/3");
    expect(screen.getByRole("link", { name: /^Mark collected →/ })).toHaveAttribute("href", "/admin/orders/4");
  });

  it("the_list_is_a_named_section_and_each_next_link_names_its_order", async () => {
    render(<StaffProvider me={aiden}><OrdersPage /></StaffProvider>);
    await screen.findByRole("link", { name: "#1" });
    expect(screen.getByRole("heading", { name: /Sydney CBD · To do/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mark shipped →, order #3" })).toHaveAttribute("href", "/admin/orders/3");
  });

  it("an_empty_step_says_so_rather_than_that_nothing_is_waiting", async () => {
    render(<StaffProvider me={aiden}><OrdersPage /></StaffProvider>);
    await screen.findByRole("link", { name: "#1" });
    fireEvent.click(tile(/Shipped/));
    expect(screen.getByText("No orders at this step right now.")).toBeInTheDocument();
  });

  it("a_failed_to_do_load_is_shown_even_on_another_queue", async () => {
    api.GET.mockImplementation(async (path: string, options?: { params: { query: { status?: string[] } } }) => {
      if (path === "/api/v1/stores") return [];
      if (options?.params.query.status?.includes("paid")) throw new ApiError(500, "internal_error", "The API failed.");
      return [order(9, "cancelled")];
    });
    render(<StaffProvider me={aiden}><OrdersPage /></StaffProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Cancelled" }));
    expect(await screen.findByRole("link", { name: "#9" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("The API failed.");
  });

  it("a_tile_filters_the_list_it_already_has", async () => {
    render(<StaffProvider me={aiden}><OrdersPage /></StaffProvider>);
    await screen.findByRole("link", { name: "#1" });
    fireEvent.click(tile(/To pick/));
    expect(screen.getByRole("link", { name: "#2" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "#3" })).not.toBeInTheDocument();
    expect(orderRequests()).toHaveLength(1);
  });

  it("another_queue_is_one_more_request_and_the_counts_stay", async () => {
    render(<StaffProvider me={aiden}><OrdersPage /></StaffProvider>);
    await screen.findByRole("link", { name: "#1" });
    fireEvent.click(screen.getByRole("button", { name: "Cancelled" }));
    expect(await screen.findByRole("link", { name: "#9" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "#1" })).not.toBeInTheDocument();
    expect(count(/To pick/)).toBe("2");
    expect(orderRequests()).toEqual([["paid", "picking", "ready", "shipped"], ["cancelled"]]);
  });
});
