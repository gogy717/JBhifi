"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { CategorySelect } from "@/components/category-select";
import { useShop } from "@/components/shop/context";
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
    <Suspense fallback={<p className="text-sm text-neutral-500">Loading the catalogue…</p>}>
      <Catalogue />
    </Suspense>
  );
}

function Catalogue() {
  const router = useRouter();
  const params = useSearchParams();
  const { store, categories } = useShop();
  const [added, setAdded] = useState<string>();
  const filters = Object.fromEntries(FILTERS.map((name) => [name, params.get(name) ?? ""])) as Filters;
  const filtered = FILTERS.some((name) => filters[name]);

  /** Show the catalogue with these filters changed; an empty value removes a filter. */
  const show = (changes: Partial<Filters>) => {
    const next = new URLSearchParams(params.toString());
    for (const [name, value] of Object.entries(changes)) {
      if (value) next.set(name, value);
      else next.delete(name);
    }
    const query = next.toString();
    router.replace(query ? `${SHOP_PAGES.catalogue.href}?${query}` : SHOP_PAGES.catalogue.href, { scroll: false });
  };
  const clear = () => router.replace(SHOP_PAGES.catalogue.href, { scroll: false });

  // The search and price boxes apply together, on Enter or "Apply"; the two lists apply as soon as they change.
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

  return (
    <div className="space-y-5">
      <title>Shop all products · JB Hi-Fi</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> / Shop all products
      </nav>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Shop all products</h1>
          <p className="mt-1 text-sm text-neutral-600">
            Prices are the current price — the sale price while a promotion runs. Stock is for{" "}
            <b>{store?.name ?? "your store"}</b>; change it under “My store” above.
          </p>
        </div>
        {products.data && (
          <p className="text-sm text-neutral-600">
            {rows.length} {rows.length === 1 ? "product" : "products"}{filtered && " match"}
          </p>
        )}
      </div>

      <Card>
        {/* Keyed on the applied values: the page stays mounted when only the URL's query changes, so after a
            header search, "Clear filters" or back/forward the boxes are re-created showing what the URL says. */}
        <form key={JSON.stringify([filters.q, filters.min_price, filters.max_price])} onSubmit={apply}
          className="grid items-end gap-3 p-4 sm:grid-cols-2 lg:grid-cols-[2fr_repeat(4,minmax(0,1fr))_auto]">
          <Field label="Search">
            <input name="q" type="search" className={inputClass} defaultValue={filters.q}
              placeholder="Name, SKU or brand" />
          </Field>
          <Field label="Category">
            <CategorySelect categories={categories} allLabel="All categories" value={categoryId}
              onChange={(id) => show({ category: id === undefined ? "" : String(id) })} />
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
          <Field label="Price from ($)">
            <input name="min_price" type="number" min={0} step="0.01" className={inputClass}
              defaultValue={filters.min_price} placeholder="0" />
          </Field>
          <Field label="Price to ($)">
            <input name="max_price" type="number" min={0} step="0.01" className={inputClass}
              defaultValue={filters.max_price} placeholder="Any" />
          </Field>
          <Button type="submit" tone="primary">Apply</Button>
        </form>
        {(filtered || brands.error) && (
          <div className="flex flex-wrap items-center gap-3 border-t border-neutral-200 px-4 py-3">
            {filtered && <Button size="sm" onClick={clear}>Clear filters</Button>}
            {brands.error && <ErrorBox error={brands.error} />}
          </div>
        )}
      </Card>

      {added && (
        <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          Added <b>{added}</b> to your cart.{" "}
          <Link href={SHOP_PAGES.cart.href} className="font-medium underline">Go to cart →</Link>
        </p>
      )}

      {products.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={products.error} />
          <Button onClick={products.reload}>Try again</Button>
        </div>
      )}

      {!products.error && !products.data && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <div key={index} className="h-64 animate-pulse rounded-xl bg-neutral-200" />
          ))}
        </div>
      )}

      {!products.error && products.data && rows.length === 0 && (
        <Card><Empty>
          Nothing matches those filters.{" "}
          <button type="button" className="font-medium underline" onClick={clear}>Clear them</button>.
        </Empty></Card>
      )}

      {!products.error && (
        <div className={`grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4
          ${products.loading ? "opacity-60" : ""}`}>
          {rows.map((product) => (
            <ProductCard key={product.product_id} product={product} storeName={store?.name} onAdded={setAdded} />
          ))}
        </div>
      )}
    </div>
  );
}
