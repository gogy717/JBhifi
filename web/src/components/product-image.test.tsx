import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Category } from "@/lib/api/client";

import { ProductImage, topLevelCategory } from "./product-image";

// The seeded tree's shape: a top-level category and its subcategories (products hang on the leaves).
const categories: Category[] = [
  { category_id: 4, name: "Audio", parent_id: null, parent_name: null },
  { category_id: 5, name: "Gaming", parent_id: null, parent_name: null },
  { category_id: 13, name: "Headphones", parent_id: 4, parent_name: "Audio" },
  { category_id: 15, name: "Consoles", parent_id: 5, parent_name: "Gaming" },
];

describe("topLevelCategory", () => {
  it("a_subcategory_resolves_to_its_top_level_category", () => {
    expect(topLevelCategory(13, categories)?.name).toBe("Audio");
  });

  it("a_top_level_category_is_its_own_top", () => {
    expect(topLevelCategory(5, categories)?.name).toBe("Gaming");
  });

  it("an_unknown_category_or_a_cycle_gives_nothing_rather_than_hanging", () => {
    expect(topLevelCategory(99, categories)).toBeUndefined();
    expect(topLevelCategory(undefined, categories)).toBeUndefined();
    const loop: Category[] = [
      { category_id: 1, name: "A", parent_id: 2, parent_name: "B" },
      { category_id: 2, name: "B", parent_id: 1, parent_name: "A" },
    ];
    expect(topLevelCategory(1, loop)).toBeUndefined();
  });
});

describe("ProductImage", () => {
  it("draws_the_top_level_categorys_icon_for_a_product_on_a_leaf", () => {
    const { container } = render(<ProductImage categoryId={15} categories={categories} brand="Sony" />);
    expect(container.querySelector("[data-icon]")).toHaveAttribute("data-icon", "Gaming");
  });

  it("falls_back_to_a_generic_icon_when_the_category_is_unknown", () => {
    const { container } = render(<ProductImage categoryId={99} categories={categories} brand="Sony" />);
    expect(container.querySelector("[data-icon]")).toHaveAttribute("data-icon", "generic");
  });

  // No product photos exist: the tile is decoration (the card names the brand and product), but what is placed on
  // it — a discount, an end date — is real content.
  it("hides_the_drawing_from_screen_readers_but_not_the_badges_on_it", () => {
    render(
      <ProductImage categoryId={13} categories={categories} brand="Sony">
        <span>27% OFF</span>
      </ProductImage>,
    );
    expect(screen.getByText("Sony").closest("[aria-hidden]")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("27% OFF").closest("[aria-hidden]")).toBeNull();
  });
});
