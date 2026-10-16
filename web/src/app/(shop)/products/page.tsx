"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, type ReactNode, Suspense, useState } from "react";

import { useShop } from "@/components/shop/context";
import { Callout, Crumbs, focusRing, PageIntro, Skeleton } from "@/components/shop/page-parts";
import { ProductCard } from "@/components/shop/product-card";
import { Button, Card, Empty, ErrorBox, Field, inputClass, selectClass } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

// The filters live in the URL, so the header's search box (?q=), the home page's category links (?category=),
// back/forward and a shared link all show the same results.
const FILTERS = ["q", "category", "brand", "min_price", "max_price"] as const;
type Filters = Record<(typeof FILTERS)[number], string>;

export default function CataloguePage() {
  // useSearchParams needs a Suspense boundary, or `next build` can't prerender the page.
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading the catalogue…</p>}>
      <Catalogue />
    </Suspense>
  );
}

function Catalogue() {
  const router = useRouter();
  const params = useSearchParams();
  const { store, categories } = useShop();
  const [added, setAdded] = useState<string>();
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filters = Object.fromEntries(FILTERS.map((name) => [name, params.get(name) ?? ""])) as Filters;
  const filtered = FILTERS.some((name) => filters[name]);

  /** The catalogue's address with these filters changed; an empty value removes a filter. */
  const hrefWith = (changes: Partial<Filters>) => {
    const next = new URLSearchParams(params.toString());
    for (const [name, value] of Object.entries(changes)) {
      if (value) next.set(name, value);
      else next.delete(name);
    }
    const query = next.toString();
    return query ? `${SHOP_PAGES.catalogue.href}?${query}` : SHOP_PAGES.catalogue.href;
  };
  /** Show the catalogue with these filters changed. */
  const show = (changes: Partial<Filters>) => router.replace(hrefWith(changes), { scroll: false });
  const clear = () => router.replace(SHOP_PAGES.catalogue.href, { scroll: false });

  // The search and price boxes apply together, on Enter or "Apply"; the brand list applies as soon as it changes,
  // and the category pills are links.
  const apply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    show({ q: text("q"), min_price: text("min_price"), max_price: text("max_price") });
  };

  const brands = useLoad("brands", () => call(api.GET("/api/v1/brands")));
  const categoryId = filters.category ? Number(filters.category) : undefined;
  const storeId = store?.store_id;
  // Prices go as typed: the API answers 422 for a malformed one, and 422 invalid_price_range for min above max.
  const products = useLoad(JSON.stringify(["products", filters, storeId]), () =>
    call(api.GET("/api/v1/products", {
      params: {
        query: {
          q: filters.q || undefined,
          category_id: categoryId,
          brand_id: filters.brand ? Number(filters.brand) : undefined,
          min_price: filters.min_price || undefined,
          max_price: filters.max_price || undefined,
          store_id: storeId,
        },
      },
    })));
  const rows = products.data ?? [];

  // The chosen category, its top-level parent, and the parent's subcategories for the second row of pills.
  const chosen = categories.find((c) => c.category_id === categoryId);
  const parent = chosen?.parent_id ? categories.find((c) => c.category_id === chosen.parent_id) : chosen;
  const topLevel = categories.filter((c) => c.parent_id === null);
  const subcategories = parent ? categories.filter((c) => c.parent_id === parent.category_id) : [];
  const brandName = (brands.data ?? []).find((b) => String(b.brand_id) === filters.brand)?.name;

  // The filters in force, each with a way to drop it.
  const chips: [string, Partial<Filters>][] = [
    ...(filters.q ? [[`“${filters.q}”`, { q: "" }] as [string, Partial<Filters>]] : []),
    ...(chosen ? [[chosen.name, { category: "" }] as [string, Partial<Filters>]] : []),
    ...(filters.brand ? [[brandName ?? `Brand ${filters.brand}`, { brand: "" }] as [string, Partial<Filters>]] : []),
    ...(filters.min_price || filters.max_price
      ? [[priceRange(filters.min_price, filters.max_price), { min_price: "", max_price: "" }] as [string, Partial<Filters>]]
      : []),
  ];

  return (
    <div className="space-y-8">
      <title>{`${chosen?.name ?? "Shop all products"} · TechLight`}</title>
      <div className="space-y-4">
        <Crumbs trail={chosen
          ? [["Home", "/"], ["Shop all products", SHOP_PAGES.catalogue.href], [chosen.name]]
          : [["Home", "/"], ["Shop all products"]]} />
        <PageIntro title={chosen?.name ?? "Shop all products"}>
          Prices are the current price — the sale price while a promotion runs. Stock is for{" "}
          <b className="text-ink">{store?.name ?? "your store"}</b>; change it under “My store” above.
        </PageIntro>
      </div>

      <nav aria-label="Filter by category" className="space-y-3">
        <PillRow>
          <CategoryPill href={hrefWith({ category: "" })} current={!chosen}>All products</CategoryPill>
          {topLevel.map((c) => (
            <CategoryPill key={c.category_id} href={hrefWith({ category: String(c.category_id) })}
              current={c.category_id === categoryId} within={c.category_id === parent?.category_id}>
              {c.name}
            </CategoryPill>
          ))}
        </PillRow>
        {parent && subcategories.length > 0 && (
          <PillRow>
            <CategoryPill small href={hrefWith({ category: String(parent.category_id) })}
              current={parent.category_id === categoryId}>
              All {parent.name}
            </CategoryPill>
            {subcategories.map((c) => (
              <CategoryPill small key={c.category_id} href={hrefWith({ category: String(c.category_id) })}
                current={c.category_id === categoryId}>
                {c.name}
              </CategoryPill>
            ))}
          </PillRow>
        )}
      </nav>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start">
          <Button className="w-full lg:hidden" aria-expanded={filtersOpen} aria-controls="catalogue-filters"
            onClick={() => setFiltersOpen(!filtersOpen)}>
            {filtersOpen ? "Hide filters" : "Search and filters"}
          </Button>
          <div id="catalogue-filters" className={`${filtersOpen ? "block" : "hidden"} lg:block`}>
            <Card>
              {/* Keyed on the applied values: the page stays mounted when only the URL's query changes, so after a
                  header search, "Clear filters" or back/forward the boxes are re-created showing what the URL says. */}
              <form key={JSON.stringify([filters.q, filters.min_price, filters.max_price])} onSubmit={apply}
                className="space-y-4 p-5">
                <h2 className="font-display text-[18px] font-bold tracking-[-0.01em]">Filters</h2>
                <Field label="Search">
                  <input name="q" type="search" className={inputClass} defaultValue={filters.q}
                    placeholder="Name, SKU or brand" />
                </Field>
                <Field label="Brand">
                  <select className={selectClass} value={filters.brand}
                    onChange={(event) => show({ brand: event.target.value })}>
                    <option value="">All brands</option>
                    {(brands.data ?? []).map((brand) => (
                      <option key={brand.brand_id} value={brand.brand_id}>{brand.name}</option>
                    ))}
                  </select>
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="From ($)">
                    <input name="min_price" type="number" min={0} step="0.01" className={inputClass}
                      defaultValue={filters.min_price} placeholder="0" />
                  </Field>
                  <Field label="To ($)">
                    <input name="max_price" type="number" min={0} step="0.01" className={inputClass}
                      defaultValue={filters.max_price} placeholder="Any" />
                  </Field>
                </div>
                <Button type="submit" tone="primary" className="w-full">Apply</Button>
                {filtered && <Button className="w-full" onClick={clear}>Clear filters</Button>}
                {brands.error && <ErrorBox error={brands.error} />}
              </form>
            </Card>
          </div>
        </aside>

        <section aria-label="Products" className="min-w-0 space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            {products.data && (
              <p className="mr-2 text-[15px] font-bold" aria-live="polite">
                {rows.length} {rows.length === 1 ? "product" : "products"}{filtered && " match"}
              </p>
            )}
            {chips.map(([label, changes]) => (
              <button key={label} type="button" onClick={() => show(changes)}
                className={`inline-flex h-8 items-center gap-1.5 rounded-full bg-sand pr-2.5 pl-3.5 text-[13px] font-semibold
                  hover:bg-line ${focusRing}`}>
                {label} <span aria-hidden="true" className="text-muted">×</span>
                <span className="sr-only">(remove this filter)</span>
              </button>
            ))}
          </div>

          {added && (
            <Callout tone="ok" role="status">
              Added <b>{added}</b> to your cart.{" "}
              <Link href={SHOP_PAGES.cart.href} className="font-bold text-brand-strong underline-offset-2 hover:underline">
                Go to cart →
              </Link>
            </Callout>
          )}

          {products.error && (
            <div className="flex flex-wrap items-center gap-3">
              <ErrorBox error={products.error} />
              <Button onClick={products.reload}>Try again</Button>
            </div>
          )}

          {!products.error && !products.data && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
              {Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-96" />)}
            </div>
          )}

          {!products.error && products.data && rows.length === 0 && (
            <Card><Empty>
              Nothing matches those filters.{" "}
              <button type="button" className="font-bold text-brand-strong underline" onClick={clear}>Clear them</button>.
            </Empty></Card>
          )}

          {!products.error && rows.length > 0 && (
            <div className={`grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4
              ${products.loading ? "opacity-60" : ""}`}>
              {rows.map((product) => (
                <ProductCard key={product.product_id} product={product} storeName={store?.name} onAdded={setAdded} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function priceRange(min: string, max: string): string {
  if (min && max) return `$${min} – $${max}`;
  return min ? `From $${min}` : `Up to $${max}`;
}

/** A row of pills that scrolls sideways on a narrow screen instead of wrapping into a wall. */
function PillRow({ children }: { children: ReactNode }) {
  return <ul className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 sm:flex-wrap sm:overflow-visible">{children}</ul>;
}

/** One category as a pill: ink when it is the one shown, outlined when the chosen subcategory is inside it. */
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
          ${small ? "h-8 px-3.5 text-[13px]" : "h-10 px-4.5 text-[15px]"}`}>
        {children}
      </Link>
    </li>
  );
}

