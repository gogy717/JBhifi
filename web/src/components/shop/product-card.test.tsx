import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProductSummary } from "@/lib/api/client";

import { ProductCard, StoreLine } from "./product-card";

const addItem = vi.fn();
vi.mock("@/lib/cart-context", () => ({ useCart: () => ({ addItem }) }));
vi.mock("@/components/shop/context", () => ({
  useShop: () => ({ categories: [{ category_id: 4, name: "Audio", parent_id: null, parent_name: null }] }),
}));

const product = (overrides: Partial<ProductSummary> = {}): ProductSummary => ({
  product_id: 7, sku: "SONY-WH1000XM5", name: "WH-1000XM5 Headphones", brand_id: 15, brand: "Sony", category_id: 4,
  category: "Audio", base_price: "549.95", current_price: "399.00", on_sale: true, is_active: true, total_stock: 40,
  store_quantity: 13, ...overrides,
});

describe("the stock line under a product", () => {
  it("plenty_is_a_count_at_the_store", () => {
    render(<StoreLine quantity={13} storeName="Sydney CBD" />);
    expect(screen.getByText("13 in stock at Sydney CBD")).toBeInTheDocument();
  });

  it("three_or_fewer_is_only_n_left", () => {
    render(<StoreLine quantity={3} storeName="Sydney CBD" />);
    expect(screen.getByText("Only 3 left at Sydney CBD")).toBeInTheDocument();
  });

  it("none_says_out_of_stock_in_words", () => {
    render(<StoreLine quantity={0} storeName="Sydney CBD" />);
    expect(screen.getByText("Out of stock at Sydney CBD")).toHaveClass("font-semibold");
  });

  it("no_store_yet_is_not_the_same_as_none", () => {
    render(<StoreLine quantity={null} storeName="Sydney CBD" />);
    expect(screen.getByText("Choose a store to see its stock")).toBeInTheDocument();
  });
});

describe("the product card", () => {
  it("shows_the_sale_and_what_it_saves_and_adds_to_the_cart", () => {
    const onAdded = vi.fn();
    render(<ProductCard product={product()} storeName="Sydney CBD" onAdded={onAdded} />);
    expect(screen.getByText("27% off")).toBeInTheDocument();
    expect(screen.getByText("Save $150.95")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    expect(addItem).toHaveBeenCalledWith(7);
    expect(onAdded).toHaveBeenCalledWith("WH-1000XM5 Headphones");
  });

  it("keeps_the_details_link_the_walkthrough_uses", () => {
    render(<ProductCard product={product()} storeName="Sydney CBD" />);
    expect(screen.getByRole("link", { name: "Details" })).toHaveAttribute("href", "/products/7");
  });

  it("a_retired_product_cant_be_added", () => {
    render(<ProductCard product={product({ is_active: false, on_sale: false })} storeName="Sydney CBD" />);
    expect(screen.getByRole("button", { name: "Add to cart" })).toBeDisabled();
    expect(screen.getByText("retired")).toBeInTheDocument();
  });
});
