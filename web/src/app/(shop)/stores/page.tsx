"use client";

import Link from "next/link";
import { useState } from "react";

import { useShop } from "@/components/shop/context";
import { Badge, Button, Card, Empty, ErrorBox, inputClass, StockBadge } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { useLoad } from "@/lib/use-load";

export default function StoresPage() {
  const { store, setStoreId } = useShop();
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState<number>();
  const term = search.trim();

  // All stores, the warehouse too (the shop context keeps only the retail ones).
  const stores = useLoad("all-stores", () => call(api.GET("/api/v1/stores")));
  const matches = useLoad(`store-lookup:${term}`, () =>
    term.length < 2 ? Promise.resolve([]) : call(api.GET("/api/v1/products", { params: { query: { q: term } } })));
  const detail = useLoad(`store-lookup-product:${chosen}`, () =>
    chosen === undefined
      ? Promise.resolve(undefined)
      : call(api.GET("/api/v1/products/{product_id}", { params: { path: { product_id: chosen } } })));
  // useLoad keeps the previous product while the next loads: show only the one chosen.
  const product = detail.data?.product_id === chosen ? detail.data : undefined;

  const states = [...new Set((stores.data ?? []).map((row) => row.state))].sort();

  return (
    <div className="space-y-6">
      <title>Stores · TechLight</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> / Stores
      </nav>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Stores</h1>
        <p className="mt-1 text-sm text-neutral-600">
          Click &amp; Collect is offered by the retail stores only — never the warehouse (BR06). Your store is where
          stock is quoted and where you would pick an order up.
        </p>
      </div>

      {stores.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={stores.error} />
          <Button onClick={stores.reload}>Try again</Button>
        </div>
      )}

      <Card title="Who has it?" actions={<span className="text-xs text-neutral-500">R3</span>}>
        <div className="space-y-3 p-4">
          <label className="block max-w-md">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">
              Search the catalogue by name, brand or SKU
            </span>
            <input className={inputClass} value={search} placeholder="e.g. Sony or SONY-WH1000XM5-B"
              onChange={(event) => {
                setSearch(event.target.value);
                setChosen(undefined);
              }} />
          </label>

          {term.length >= 2 && (matches.loading && !matches.data
            ? <p className="text-sm text-neutral-500">Searching…</p>
            : (matches.data ?? []).length === 0
              ? <p className="text-sm text-neutral-500">Nothing matches “{term}”.</p>
              : (
                <div className="flex flex-wrap gap-2">
                  {(matches.data ?? []).slice(0, 8).map((match) => (
                    <Button key={match.product_id} size="sm"
                      tone={chosen === match.product_id ? "primary" : "secondary"}
                      onClick={() => setChosen(match.product_id)}>
                      {match.brand} {match.name}
                    </Button>
                  ))}
                </div>
              ))}
          {matches.error && <ErrorBox error={matches.error} />}

          {chosen !== undefined && (
            <div className="rounded-lg border border-neutral-200">
              {detail.error && <ErrorBox error={detail.error} className="m-3" />}
              {!detail.error && !product && <p className="p-4 text-sm text-neutral-500">Loading stock…</p>}
              {product && (
                <>
                  <div className="border-b border-neutral-200 px-4 py-3">
                    <div className="font-medium">{product.brand} {product.name}</div>
                    <div className="font-mono text-xs text-neutral-500">{product.sku}</div>
                  </div>
                  <ul className="divide-y divide-neutral-100">
                    {product.stock.map((row) => (
                      <li key={row.store_id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                        <span>
                          {row.store_name}
                          {row.store_type === "warehouse" && (
                            <span className="ml-2"><Badge tone="blue">warehouse</Badge></span>
                          )}
                        </span>
                        <span className="flex items-center gap-3">
                          <span className="text-xs text-neutral-500">{row.state}</span>
                          <StockBadge quantity={row.quantity} />
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>
      </Card>

      {!stores.data && !stores.error && <div className="h-40 animate-pulse rounded-xl bg-neutral-200" />}
      {stores.data?.length === 0 && <Card><Empty>No stores to show.</Empty></Card>}

      {states.map((state) => (
        <section key={state}>
          <h2 className="mb-3 text-lg font-semibold tracking-tight">{state}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(stores.data ?? []).filter((row) => row.state === state).map((row) => {
              const isMine = row.store_id === store?.store_id;
              const retail = row.store_type === "retail";
              return (
                <div key={row.store_id}
                  className={`rounded-xl bg-white p-4 shadow-sm ring-1 ${isMine ? "ring-2 ring-neutral-900" : "ring-neutral-200"}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-semibold">{row.name}</div>
                      <div className="text-xs text-neutral-500">{row.suburb} {row.state}</div>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      {isMine && <Badge tone="sale">your store</Badge>}
                      {!retail && <Badge tone="blue">warehouse</Badge>}
                    </div>
                  </div>
                  <div className="mt-2 text-xs text-neutral-500">Manager: {row.manager_name}</div>
                  {retail && !isMine && (
                    <button type="button" onClick={() => setStoreId(row.store_id)}
                      className="mt-3 text-sm font-medium text-neutral-800 hover:underline">
                      Make this my store
                    </button>
                  )}
                  {!retail && (
                    <p className="mt-3 text-xs text-neutral-500">Ships online orders; not a collection point.</p>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
