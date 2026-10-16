import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StaffProvider } from "@/components/admin/staff-gate";
import type { Me } from "@/lib/api/client";

import { Sidebar } from "./sidebar";

vi.mock("@clerk/nextjs", () => ({ UserButton: () => null }));
const segment = vi.hoisted(() => ({ current: "orders" as string | null }));
vi.mock("next/navigation", () => ({ useSelectedLayoutSegment: () => segment.current }));

const aiden: Me = { kind: "staff", id: 14, display_name: "Aiden Chen", store_id: 1, store_name: "Sydney CBD",
  staff_type: "store", runs_store: false };
const olivia: Me = { ...aiden, id: 1, display_name: "Olivia Nguyen", runs_store: true };
const nora: Me = { kind: "staff", id: 40, display_name: "Nora Fitzgerald", store_id: null, store_name: null,
  staff_type: "support", runs_store: false };

const show = (me: Me) => render(<StaffProvider me={me}><Sidebar /></StaffProvider>);

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok", db: "techlight" }))));
});

describe("the admin sidebar", () => {
  it("marks_the_section_being_shown_as_the_current_page", () => {
    segment.current = "returns";
    show(aiden);
    expect(screen.getByRole("link", { name: /Returns/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Orders/ })).not.toHaveAttribute("aria-current");
  });

  it("an_order_page_still_marks_orders", () => {
    segment.current = "orders";   // /admin/orders/42: the segment below the admin layout is still "orders"
    show(aiden);
    expect(screen.getByRole("link", { name: /Orders/ })).toHaveAttribute("aria-current", "page");
  });

  it("says_who_is_signed_in_and_for_which_store", () => {
    show(aiden);
    expect(screen.getByText("Aiden Chen")).toBeInTheDocument();
    expect(screen.getByText("Staff · Sydney CBD")).toBeInTheDocument();
  });

  it("a_manager_and_support_staff_see_their_role", () => {
    show(olivia);
    expect(screen.getByText("Manager · Sydney CBD")).toBeInTheDocument();
    show(nora);
    expect(screen.getByText("Support · all stores")).toBeInTheDocument();
  });
});
