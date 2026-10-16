import Link from "next/link";
import type { ReactNode } from "react";

import { focusRing } from "@/components/shop/page-parts";
import type { Category } from "@/lib/api/client";
import { money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";

// The catalogue's filters live in the URL, so the header's search box (?q=), the home page's category links
// (?category=), back/forward and a shared link all show the same results. These helpers read and write them.

export const FILTERS = ["q", "category", "brand", "min_price", "max_price"] as const;
export type Filters = Record<(typeof FILTERS)[number], string>;

export function readFilters(params: URLSearchParams): Filters {
  return Object.fromEntries(FILTERS.map((name) => [name, params.get(name) ?? ""])) as Filters;
}

/** The catalogue's address with these filters changed and the rest kept; an empty value removes a filter. */
export function catalogueHref(params: URLSearchParams, changes: Partial<Filters>): string {
  const next = new URLSearchParams(params.toString());
  for (const [name, value] of Object.entries(changes)) {
    if (value) next.set(name, value);
    else next.delete(name);
  }
  const query = next.toString();
  return query ? `${SHOP_PAGES.catalogue.href}?${query}` : SHOP_PAGES.catalogue.href;
}

export type Chip = { key: string; label: string; changes: Partial<Filters> };

/** One chip per filter in force, each clearing only its own. Names come from the loaded lists; until they arrive a
 *  chip says what kind of filter it is, never the id. */
export function filterChips(filters: Filters, names: { category?: string; brand?: string }): Chip[] {
  const chips: Chip[] = [];
  if (filters.q) chips.push({ key: "q", label: `“${filters.q}”`, changes: { q: "" } });
  if (filters.category) chips.push({ key: "category", label: names.category ?? "Category", changes: { category: "" } });
  if (filters.brand) chips.push({ key: "brand", label: names.brand ?? "Brand", changes: { brand: "" } });
  if (filters.min_price || filters.max_price) {
    const [min, max] = [priceText(filters.min_price), priceText(filters.max_price)];
    const label = filters.min_price && filters.max_price ? `${min} – ${max}` : filters.min_price ? `From ${min}` : `Up to ${max}`;
    chips.push({ key: "price", label, changes: { min_price: "", max_price: "" } });
  }
  return chips;
}

/** A price from the URL as money, or as typed when it isn't a number (the API answers 422 for that). */
function priceText(value: string): string {
  return value !== "" && Number.isFinite(Number(value)) ? money(value) : value;
}

/** The category tree as two rows of pills: the top-level categories, then the chosen one's subcategories. Links,
 *  so each keeps the other filters and works with back/forward. */
export function CategoryPills({ categories, category, hrefFor }: {
  categories: Category[];
  /** The ?category= value: may name a category the tree hasn't loaded (yet). */
  category: string;
  hrefFor: (category: string) => string;
}) {
  const categoryId = category ? Number(category) : undefined;
  const chosen = categories.find((c) => c.category_id === categoryId);
  const parent = chosen?.parent_id ? categories.find((c) => c.category_id === chosen.parent_id) : chosen;
  const subcategories = parent ? categories.filter((c) => c.parent_id === parent.category_id) : [];
  return (
    <nav aria-label="Filter by category" className="space-y-2">
      <PillRow>
        <CategoryPill href={hrefFor("")} current={!category}>All products</CategoryPill>
        {categories.filter((c) => c.parent_id === null).map((c) => (
          <CategoryPill key={c.category_id} href={hrefFor(String(c.category_id))}
            current={c.category_id === categoryId} within={c.category_id === parent?.category_id}>
            {c.name}
          </CategoryPill>
        ))}
      </PillRow>
      {parent && subcategories.length > 0 && (
        <PillRow>
          <CategoryPill small href={hrefFor(String(parent.category_id))} current={parent.category_id === categoryId}>
            All {parent.name}
          </CategoryPill>
          {subcategories.map((c) => (
            <CategoryPill small key={c.category_id} href={hrefFor(String(c.category_id))}
              current={c.category_id === categoryId}>
              {c.name}
            </CategoryPill>
          ))}
        </PillRow>
      )}
    </nav>
  );
}

/** A row of pills that scrolls sideways on a phone instead of wrapping into a wall. The padding keeps the focus ring
 *  inside the scrolling box, which clips. */
function PillRow({ children }: { children: ReactNode }) {
  return <ul className="-mx-1 flex gap-2 overflow-x-auto p-1 sm:flex-wrap sm:overflow-visible">{children}</ul>;
}

/** One category: ink when it is the one shown, outlined in ink when the chosen subcategory is inside it. */
function CategoryPill({ href, current, within = false, small = false, children }: {
  href: string;
  current: boolean;
  within?: boolean;
  small?: boolean;
  children: ReactNode;
}) {
  const tone = current ? "bg-ink text-white"
    : within ? "border border-ink bg-white text-ink"
    : "border border-line bg-white text-ink hover:border-ink";
  return (
    <li className="shrink-0">
      <Link href={href} replace scroll={false} aria-current={current ? "page" : undefined}
        className={`inline-flex items-center rounded-full font-bold whitespace-nowrap transition-colors ${tone} ${focusRing}
          ${small ? "h-8 px-3.5 text-[13px]" : "h-11 px-5 text-[15px]"}`}>
        {children}
      </Link>
    </li>
  );
}
