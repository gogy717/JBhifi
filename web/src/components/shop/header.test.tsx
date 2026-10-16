import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Category, Store } from "@/lib/api/client";

import { ShopFooter } from "./footer";
import { ShopHeader } from "./header";

// Signed out: Clerk's <Show when="signed-out"> shows its children, "signed-in" hides them.
vi.mock("@clerk/nextjs", () => ({
  Show: ({ when, children }: { when: string; children: ReactNode }) => (when === "signed-out" ? children : null),
  SignInButton: ({ children }: { children: ReactNode }) => children,
  SignUpButton: ({ children }: { children: ReactNode }) => children,
  UserButton: () => null,
}));
vi.mock("next/form", () => ({ default: (props: React.FormHTMLAttributes<HTMLFormElement>) => <form {...props} /> }));
vi.mock("@/lib/cart-context", () => ({ useCart: () => ({ count: 2 }) }));

const store = (store_id: number, name: string, state: string, store_type = "retail"): Store => ({
  store_id, name, state, store_type, suburb: name, manager_id: 1, manager_name: "Olivia Nguyen",
});
const sydney = store(1, "Sydney CBD", "NSW");
const categories: Category[] = [
  { category_id: 4, name: "Audio", parent_id: null, parent_name: null },
  { category_id: 5, name: "Gaming", parent_id: null, parent_name: null },
  { category_id: 13, name: "Headphones", parent_id: 4, parent_name: "Audio" },
];
vi.mock("@/components/shop/context", () => ({
  useShop: () => ({
    session: { status: "guest" },
    retailStores: [sydney, store(5, "Melbourne Central", "VIC")],
    store: sydney,
    setStoreId: () => {},
    categories,
  }),
}));

describe("the shop header", () => {
  it("the_utility_bar_says_which_store_click_and_collect_is_from", () => {
    render(<ShopHeader />);
    expect(screen.getByText(/Click & Collect from/)).toHaveTextContent("Click & Collect from Sydney CBD");
  });

  it("search_sends_q_to_the_catalogue", () => {
    render(<ShopHeader />);
    const box = screen.getByRole("searchbox", { name: "Search products" });
    expect(box).toHaveAttribute("name", "q");
    expect(box.closest("form")).toHaveAttribute("action", "/products");
  });

  it("my_store_is_a_labelled_choice_of_retail_stores_grouped_by_state", () => {
    render(<ShopHeader />);
    const picker = screen.getByRole("combobox", { name: "My store" });
    expect(picker).toHaveValue("1");
    expect(within(picker).getByRole("group", { name: "VIC" })).toHaveTextContent("Melbourne Central");
  });

  it("the_category_bar_has_deals_and_only_the_top_level_categories", () => {
    render(<ShopHeader />);
    const nav = screen.getByRole("navigation", { name: "Categories" });
    expect(within(nav).getByRole("link", { name: "Deals" })).toHaveAttribute("href", "/#deals");
    expect(within(nav).getByRole("link", { name: "Audio" })).toHaveAttribute("href", "/products?category=4");
    expect(within(nav).queryByRole("link", { name: "Headphones" })).toBeNull();
  });

  it("a_guest_is_offered_sign_in_and_an_account_and_the_cart_says_how_many_items", () => {
    render(<ShopHeader />);
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cart, 2 items" })).toHaveAttribute("href", "/cart");
  });
});

describe("the shop footer", () => {
  it("lists_the_top_level_categories_and_the_help_pages", () => {
    render(<ShopFooter />);
    const shop = screen.getByRole("navigation", { name: "Shop" });
    expect(within(shop).getAllByRole("link").map((a) => a.textContent)).toEqual(["Audio", "Gaming"]);
    const help = screen.getByRole("navigation", { name: "Help" });
    expect(within(help).getByRole("link", { name: "My orders" })).toHaveAttribute("href", "/orders");
  });

  it("says_the_store_is_fictional_and_keeps_the_way_into_the_store_admin", () => {
    render(<ShopFooter />);
    expect(screen.getByText(/fictional store/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /store admin/i })).toHaveAttribute("href", "/admin");
  });
});
