"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useMemo, useState } from "react";

import { useShop } from "@/components/shop/context";
import { ProductCard } from "@/components/shop/product-card";
import { Button, Card, Empty, ErrorBox, inputClass, selectClass } from "@/components/ui";
import { api, call, type Brand, type Category, type ProductSummary } from "@/lib/api/client";
import { categoryOptions } from "@/lib/categories";
import { useLoad } from "@/lib/use-load";

const TEXT_FILTERS = ["q", "category", "brand", "min_price", "max_price"] as const;
type FilterKey = (typeof TEXT_FILTERS)[number];

export default function CataloguePage() {
  // useSearchParams needs a Suspense boundary; the page itself is dynamic.
  return (
    <Suspense fallback={<p className="text-sm text-neutral-500">Loading the catalogue…</p>}>
      <Catalogue />
    </Suspense>
  );
}

function Catalogue() {
  const router = useRouter();
  const params = useSearchParams();
  const { store, categories: shopCategories } = useShop();
  const [added, setAdded] = useState<string>();

  const filters = useMemo(() => {
    const values: Record<FilterKey, string> = { q: "", category: "", brand: "", min_price: "", max_price: "" };
    for (const key of TEXT_FILTERS) values[key] = params.get(key) ?? "";
    return values;
  }, [params]);

  // The URL is the single source of truth, so back/forward and shared links restore the same view.
  const setFilter = useCallback((key: FilterKey, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(next.toString() ? `/products?${next}` : "/products", { scroll: false });
  }, [params, router]);

  const brands = useLoad("brands", () => call(api.GET("/api/v1/brands")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  const categoryId = filters.category ? Number(filters.category) : undefined;
  const brandId = filters.brand ? Number(filters.brand) : undefined;
  const storeId = store?.store_id;

  const key = ["catalogue", filters.q, categoryId, brandId, filters.min_price, filters.max_price, storeId]
    .join(":");
  const products = useLoad(key, () => call(api.GET("/api/v1/products", {
    params: {
      query: {
        q: filters.q || undefined,
        category_id: categoryId,
        brand_id: brandId,
        min_price: filters.min_price || undefined,
        max_price: filters.max_price || undefined,
        store_id: storeId,
      },
    },
  })));

  const rows = products.data ?? [];
  const anyFilter = TEXT_FILTERS.some((key) => filters[key]);

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
            {rows.length} {rows.length === 1 ? "product" : "products"}
            {anyFilter ? " match" : ""}
          </p>
        )}
      </div>

      <Card>
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">Search</span>
            <input className={inputClass} defaultValue={filters.q} placeholder="Name, SKU or brand"
              onChange={(event) => setFilter("q", event.target.value)} aria-label="Search products" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">Category</span>
            <select className={selectClass} value={filters.category} aria-label="Filter by category"
              onChange={(event) => setFilter("category", event.target.value)}>
              <option value="">All categories</option>
              {(categories.data ?? []).length > 0
                ? categoryOptions(categories.data ?? []).map((option) => (
                  <option key={option.id} value={option.id}>
                    {`${"  ".repeat(option.depth)}${option.depth > 0 ? "— " : ""}${option.label}`}
                  </option>
                ))
                : shopCategories.map((category: Category) => (
                  <option key={category.category_id} value={category.category_id}>{category.name}</option>
                ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">Brand</span>
            <select className={selectClass} value={filters.brand} aria-label="Filter by brand"
              onChange={(event) => setFilter("brand", event.target.value)}>
              <option value="">All brands</option>
              {(brands.data ?? []).map((brand: Brand) => (
                <option key={brand.brand_id} value={brand.brand_id}>{brand.name}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">Price from</span>
            <input className={inputClass} inputMode="decimal" placeholder="0.00" defaultValue={filters.min_price}
              aria-label="Lowest price" onChange={(event) => setFilter("min_price", event.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">Price to</span>
            <input className={inputClass} inputMode="decimal" placeholder="Any" defaultValue={filters.max_price}
              aria-label="Highest price" onChange={(event) => setFilter("max_price", event.target.value)} />
          </label>
        </div>
        {(anyFilter || brands.error || categories.error) && (
          <div className="flex flex-wrap items-center gap-3 border-t border-neutral-200 px-4 py-3">
            <Button size="sm" onClick={() => router.replace("/products", { scroll: false })}>Clear filters</Button>
            {(brands.error ?? categories.error) && <ErrorBox error={(brands.error ?? categories.error)!} />}
          </div>
        )}
      </Card>

      {added && (
        <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          Added <b>{added}</b> to your cart. <Link href="/cart" className="font-medium underline">Go to cart →</Link>
        </p>
      )}

      {products.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={products.error} />
          <Button onClick={products.reload}>Try again</Button>
        </div>
      )}

      {!products.error && products.loading && !products.data && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <div key={index} className="h-64 animate-pulse rounded-xl bg-neutral-200" />
          ))}
        </div>
      )}

      {!products.error && products.data && rows.length === 0 && (
        <Card><Empty>
          Nothing matches those filters. <button type="button" className="font-medium underline"
            onClick={() => router.replace("/products", { scroll: false })}>Clear them</button>.
        </Empty></Card>
      )}

      <div className={`grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4
        ${products.loading && products.data ? "opacity-60" : ""}`}>
        {rows.map((product: ProductSummary) => (
          <ProductCard key={product.product_id} product={product} storeName={store?.name}
            onAdded={setAdded} />
        ))}
      </div>
    </div>
  );
}
