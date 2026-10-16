import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Category } from "@/lib/api/client";

import { catalogueHref, CategoryPills, filterChips, type Filters, readFilters } from "./catalogue-filters";

const NONE: Filters = { q: "", category: "", brand: "", min_price: "", max_price: "" };
const tree: Category[] = [
  { category_id: 4, name: "Audio", parent_id: null },
  { category_id: 5, name: "Gaming", parent_id: null },
  { category_id: 13, name: "Headphones", parent_id: 4 },
  { category_id: 14, name: "Speakers", parent_id: 4 },
] as Category[];

describe("the catalogue's address", () => {
  it("changes_one_filter_and_keeps_the_others", () => {
    const params = new URLSearchParams("q=sony&brand=15&category=4");
    expect(catalogueHref(params, { category: "13" })).toBe("/products?q=sony&brand=15&category=13");
    expect(catalogueHref(params, { brand: "" })).toBe("/products?q=sony&category=4");
    expect(catalogueHref(new URLSearchParams("category=4"), { category: "" })).toBe("/products");
  });

  it("reads_only_the_five_filters", () => {
    expect(readFilters(new URLSearchParams("q=tv&utm=x&max_price=500"))).toEqual({ ...NONE, q: "tv", max_price: "500" });
  });
});

describe("the chips for the filters in force", () => {
  it("each_chip_clears_exactly_its_own_filter", () => {
    const chips = filterChips({ q: "sony", category: "13", brand: "15", min_price: "100", max_price: "" },
      { category: "Headphones", brand: "Sony" });
    expect(chips.map((chip) => [chip.label, chip.changes])).toEqual([
      ["“sony”", { q: "" }],
      ["Headphones", { category: "" }],
      ["Sony", { brand: "" }],
      ["From $100.00", { min_price: "", max_price: "" }],
    ]);
  });

  it("never_shows_a_database_id_while_the_names_load", () => {
    const labels = filterChips({ ...NONE, category: "13", brand: "15" }, {}).map((chip) => chip.label);
    expect(labels).toEqual(["Category", "Brand"]);
  });

  it("shows_a_price_range_as_money_and_a_hand_typed_one_as_typed", () => {
    expect(filterChips({ ...NONE, min_price: "100", max_price: "499.5" }, {})[0].label).toBe("$100.00 – $499.50");
    expect(filterChips({ ...NONE, max_price: "abc" }, {})[0].label).toBe("Up to abc");
  });
});

describe("the category pills", () => {
  const hrefFor = (category: string) => catalogueHref(new URLSearchParams("q=sony"), { category });

  it("marks_all_products_only_when_no_category_is_asked_for", () => {
    const { rerender } = render(<CategoryPills categories={tree} category="" hrefFor={hrefFor} />);
    expect(screen.getByRole("link", { name: "All products" })).toHaveAttribute("aria-current", "page");
    // A category the tree doesn't have yet (still loading, or a stale link) is still a filter in force.
    rerender(<CategoryPills categories={[]} category="13" hrefFor={hrefFor} />);
    expect(screen.getByRole("link", { name: "All products" })).not.toHaveAttribute("aria-current");
  });

  it("opens_the_chosen_categorys_subcategories_and_keeps_the_search", () => {
    render(<CategoryPills categories={tree} category="13" hrefFor={hrefFor} />);
    expect(screen.getByRole("link", { name: "Headphones" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Audio" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "All Audio" })).toHaveAttribute("href", "/products?q=sony&category=4");
    const rows = screen.getAllByRole("list");
    expect(within(rows[1]).getAllByRole("link").map((link) => link.textContent))
      .toEqual(["All Audio", "Headphones", "Speakers"]);
  });
});
