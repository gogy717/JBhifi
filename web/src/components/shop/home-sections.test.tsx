import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Category, CustomerDetail, Promotion, Store } from "@/lib/api/client";

import { AccountPanel, CategoryGrid, DealCard, DealOfTheWeek, StorePanel } from "./home-sections";

vi.mock("@clerk/nextjs", () => ({
  SignInButton: ({ children }: { children: ReactNode }) => children,
  SignUpButton: ({ children }: { children: ReactNode }) => children,
}));

const categories: Category[] = [
  { category_id: 4, name: "Audio", parent_id: null, parent_name: null },
  { category_id: 5, name: "Gaming", parent_id: null, parent_name: null },
  { category_id: 13, name: "Headphones", parent_id: 4, parent_name: "Audio" },
  { category_id: 14, name: "Speakers", parent_id: 4, parent_name: "Audio" },
];
const store = (store_id: number, name: string, state = "NSW"): Store => ({
  store_id, name, state, store_type: "retail", suburb: name, manager_id: 1, manager_name: "Olivia Nguyen",
});
const sydney = store(1, "Sydney CBD");
const headphones: Promotion = {
  promotion_id: 3, product_id: 7, sku: "SONY-WH1000XM5", brand: "Sony",
  product_name: "WH-1000XM5 Noise Cancelling Headphones (Black)", base_price: "549.95", sale_price: "399.00",
  product_active: true, starts_at: "2026-10-01T00:00:00+11:00", ends_at: "2026-11-15T00:00:00+11:00",
  status: "active",
};

describe("the deal of the week", () => {
  it("is_a_real_promotion_with_its_prices_and_the_stock_at_my_store", () => {
    render(<DealOfTheWeek deal={headphones} categoryId={13} categories={categories} store={sydney} quantity={13} />);
    const card = screen.getByRole("link", { name: /WH-1000XM5/ });
    expect(card).toHaveAttribute("href", "/products/7");
    expect(card).toHaveTextContent("Sony · Deal of the week");
    expect(card).toHaveTextContent("$399.00");
    expect(card).toHaveTextContent("$549.95");
    expect(card).toHaveTextContent("27% off");
    expect(card).toHaveTextContent("13 in stock at Sydney CBD");
  });

  it("with_no_live_deal_says_so_and_offers_the_catalogue", () => {
    render(<DealOfTheWeek deal={undefined} categories={categories} store={sydney} />);
    expect(screen.getByText("No deals running right now.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Shop all products" })).toHaveAttribute("href", "/products");
  });
});

describe("shop by category", () => {
  it("has_a_card_per_top_level_category_with_its_icon_and_subcategories", () => {
    render(<CategoryGrid categories={categories} />);
    const audio = screen.getByRole("link", { name: /Audio/ });
    expect(audio).toHaveAttribute("href", "/products?category=4");
    expect(audio).toHaveTextContent("Headphones · Speakers");
    expect(audio.querySelector("[data-icon]")).toHaveAttribute("data-icon", "Audio");
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });
});

describe("a deal card", () => {
  it("shows_the_end_date_the_saving_and_adds_to_the_cart", () => {
    const onAdd = vi.fn();
    render(<DealCard deal={headphones} categoryId={13} categories={categories} store={sydney} quantity={2}
      onAdd={onAdd} />);
    // Day and month only: the pill sits beside the discount on a narrow tile.
    expect(screen.getByText("Ends 14 Nov")).toBeInTheDocument();
    expect(screen.getByText("Save $150.95")).toBeInTheDocument();
    expect(screen.getByText("Only 2 left at Sydney CBD")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    expect(onAdd).toHaveBeenCalledWith(headphones);
  });
});

describe("the store panel", () => {
  it("names_my_store_and_changing_it_offers_the_other_stores_nearby", () => {
    const onChoose = vi.fn();
    const bondi = store(2, "Bondi Junction");
    render(<StorePanel store={sydney} nearby={[sydney, bondi]} nearState="NSW" onChoose={onChoose} />);
    expect(screen.getByText("Sydney CBD")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Change store" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "Stores in NSW" });
    expect(within(list).queryByText("Sydney CBD")).toBeNull();
    fireEvent.click(within(list).getByRole("button", { name: /Bondi Junction/ }));
    expect(onChoose).toHaveBeenCalledWith(2);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});

describe("the account panel", () => {
  it("asks_a_guest_to_make_it_theirs", () => {
    render(<AccountPanel session={{ status: "guest" }} loading={false} />);
    expect(screen.getByText("Make it yours")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
  });

  it("greets_a_customer_by_first_name_with_their_delivery_address", () => {
    const alice: CustomerDetail = {
      customer_id: 1, full_name: "Alice Morgan", email: "alice@example.com", phone: null,
      created_at: "2026-01-01T00:00:00Z",
      addresses: [
        { address_no: 1, line1: "1 Old St", suburb: "Newtown", state: "NSW", postcode: "2042", is_active: false },
        { address_no: 2, line1: "20 George St", suburb: "Sydney", state: "NSW", postcode: "2000", is_active: true },
      ],
    };
    render(<AccountPanel session={{ status: "signed-in", me: { kind: "customer", id: 1, display_name: "Alice Morgan",
      runs_store: false } }} customer={alice} loading={false} />);
    expect(screen.getByText("Hi, Alice")).toBeInTheDocument();
    expect(screen.getByText(/Delivering to 20 George St, Sydney NSW 2000/)).toBeInTheDocument();
  });

  it("tells_staff_the_storefront_shows_what_a_guest_sees", () => {
    render(<AccountPanel session={{ status: "signed-in", me: { kind: "staff", id: 14, display_name: "Aiden Chen",
      store_id: 1, staff_type: "store", runs_store: false } }} loading={false} />);
    expect(screen.getByText(/what a guest sees/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the store admin" })).toHaveAttribute("href", "/admin");
  });
});
