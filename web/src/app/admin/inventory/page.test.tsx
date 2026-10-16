import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StaffProvider } from "@/components/admin/staff-gate";
import type { InventoryRow, Me } from "@/lib/api/client";

import InventoryPage from "./page";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
  call: <T,>(request: Promise<T>) => request,
}));

const aiden: Me = { kind: "staff", id: 14, display_name: "Aiden Chen", store_id: 1, store_name: "Sydney CBD",
  staff_type: "store", runs_store: false };
const nora: Me = { kind: "staff", id: 40, display_name: "Nora Fitzgerald", store_id: null, store_name: null,
  staff_type: "support", runs_store: false };
const row = { product_id: 5, sku: "APL-AP4", name: "AirPods 4", brand: "Apple", category: "Headphones",
  current_price: "189.00", on_sale: false, is_active: true, quantity: 8 } as InventoryRow;

beforeEach(() => {
  api.GET.mockReset();
  api.GET.mockImplementation(async (path: string) => {
    if (path === "/api/v1/stores") {
      return [{ store_id: 1, name: "Sydney CBD", state: "NSW", store_type: "retail", suburb: "Sydney",
        manager_id: 1, manager_name: "Olivia Nguyen" }];
    }
    if (path === "/api/v1/stores/{store_id}/inventory") return [row];
    return [];
  });
});

describe("the inventory page", () => {
  it("store_staff_get_the_adjust_column_and_its_buttons", async () => {
    render(<StaffProvider me={aiden}><InventoryPage /></StaffProvider>);
    expect(await screen.findByRole("button", { name: "Add one AirPods 4" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Adjust" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Sydney CBD/ })).toBeInTheDocument();
  });

  it("support_staff_get_no_empty_adjust_column", async () => {
    render(<StaffProvider me={nora}><InventoryPage /></StaffProvider>);
    expect(await screen.findByText("AirPods 4")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["Product", "Price", "On hand"]);
  });
});
