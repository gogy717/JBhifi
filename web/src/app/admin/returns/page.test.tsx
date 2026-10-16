import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StaffProvider } from "@/components/admin/staff-gate";
import type { Me, ReturnSummary, Store } from "@/lib/api/client";

import ReturnsDeskPage from "./page";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
  call: <T,>(request: Promise<T>) => request,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: () => {} }) }));

const nora: Me = { kind: "staff", id: 40, display_name: "Nora Fitzgerald", store_id: null, store_name: null,
  staff_type: "support", runs_store: false };
const store = (store_id: number, name: string): Store => ({
  store_id, name, state: "NSW", store_type: "retail", suburb: name, manager_id: 1, manager_name: "Olivia Nguyen",
});
const aReturn = (return_id: number, status: string) => ({
  return_id, order_id: 3, status, reason: "Too big", requested_at: "2026-10-10T00:00:00Z", value: "189.00",
  received_store_name: null, lines: [],
}) as unknown as ReturnSummary;

beforeEach(() => {
  api.GET.mockReset();
  api.GET.mockImplementation((path: string, options?: { params: { path: { store_id: number } } }) => {
    if (path === "/api/v1/stores") return Promise.resolve([store(1, "Sydney CBD"), store(2, "Bondi Junction")]);
    if (options?.params.path.store_id === 1) return Promise.resolve([aReturn(7, "received"), aReturn(8, "received")]);
    return new Promise(() => {});   // the second store's desk is still loading
  });
});

const count = (name: RegExp) => within(screen.getByRole("group", { name: /Returns at/ }))
  .getByRole("button", { name }).querySelector(".font-display")?.textContent;

describe("the returns desk", () => {
  it("the_list_is_a_named_section", async () => {
    render(<StaffProvider me={nora}><ReturnsDeskPage /></StaffProvider>);
    expect(await screen.findByRole("link", { name: "#7" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Desk at Sydney CBD/ })).toBeInTheDocument();
  });

  it("another_store_never_shows_the_last_store_s_counts", async () => {
    render(<StaffProvider me={nora}><ReturnsDeskPage /></StaffProvider>);
    await screen.findByRole("link", { name: "#7" });
    expect(count(/Received/)).toBe("2");
    fireEvent.change(screen.getByRole("combobox", { name: "Store" }), { target: { value: "2" } });
    expect(count(/Received/)).toBe("–");
  });
});
