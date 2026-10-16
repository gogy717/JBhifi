"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { catalogueHref, CategoryPills, filterChips, type Filters, readFilters } from "@/components/shop/catalogue-filters";
import { useShop } from "@/components/shop/context";
import { Callout, Crumbs, focusRing, PageIntro, Skeleton } from "@/components/shop/page-parts";
import { ProductCard } from "@/components/shop/product-card";
import { Button, Card, Empty, ErrorBox, Field, inputClass, selectClass } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

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
  // The filters live in the URL (components/shop/catalogue-filters.tsx).
  const filters = readFilters(params);
  const filtered = Object.values(filters).some(Boolean);
  const hrefWith = (changes: Partial<Filters>) => catalogueHref(params, changes);
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

  const chosen = categories.find((c) => c.category_id === categoryId);
  const brandName = (brands.data ?? []).find((b) => String(b.brand_id) === filters.brand)?.name;
  const chips = filterChips(filters, { category: chosen?.name, brand: brandName });

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

      <CategoryPills categories={categories} category={filters.category}
        hrefFor={(category) => hrefWith({ category })} />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start">
          <Button className="w-full lg:hidden" aria-expanded={filtersOpen} aria-controls="catalogue-filters"
            onClick={() => setFiltersOpen(!filtersOpen)}>
            Search and filters
          </Button>
          {/* Outside the panel, which is folded away on a phone: a failed brand list shouldn't go unnoticed. */}
          {brands.error && <ErrorBox error={brands.error} />}
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
                <fieldset>
                  <legend className="mb-1.5 text-xs font-bold tracking-[0.08em] text-muted uppercase">Price ($)</legend>
                  <div className="grid grid-cols-2 gap-3">
                    <label>
                      <span className="mb-1 block text-[13px] text-muted"><span className="sr-only">Price </span>From</span>
                      <input name="min_price" type="number" min={0} step="0.01" className={inputClass}
                        defaultValue={filters.min_price} placeholder="0" />
                    </label>
                    <label>
                      <span className="mb-1 block text-[13px] text-muted"><span className="sr-only">Price </span>To</span>
                      <input name="max_price" type="number" min={0} step="0.01" className={inputClass}
                        defaultValue={filters.max_price} placeholder="Any" />
                    </label>
                  </div>
                </fieldset>
                <Button type="submit" tone="primary" className="w-full">Apply</Button>
                {filtered && <Button className="w-full" onClick={clear}>Clear filters</Button>}
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
            {chips.map((chip) => (
              <button key={chip.key} type="button" onClick={() => show(chip.changes)}
                className={`inline-flex h-8 max-w-full items-center gap-1.5 rounded-full bg-sand pr-2.5 pl-3.5 text-[13px]
                  font-semibold hover:bg-line ${focusRing}`}>
                <span className="truncate">{chip.label}</span>
                <span aria-hidden="true" className="text-muted">×</span>
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
            <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4">
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
            <div className={`grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4
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
