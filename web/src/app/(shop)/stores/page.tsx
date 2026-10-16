"use client";

import { useState } from "react";

import { useShop } from "@/components/shop/context";
import { Crumbs, PageIntro, SectionTitle, Skeleton } from "@/components/shop/page-parts";
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
    <div className="space-y-14">
      <title>Stores · TechLight</title>
      <div className="space-y-8">
        <div className="space-y-4">
          <Crumbs trail={[["Home", "/"], ["Stores"]]} />
          <PageIntro title="Stores">
            Click &amp; Collect is offered by the retail stores only — never the warehouse (BR06). Your store is where
            stock is quoted and where you would pick an order up.
          </PageIntro>
        </div>

        {stores.error && (
          <div className="flex flex-wrap items-center gap-3">
            <ErrorBox error={stores.error} />
            <Button onClick={stores.reload}>Try again</Button>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          {/* My store, as the homepage's dark store panel. */}
          <section aria-label="Your store" className="flex flex-col justify-between gap-6 rounded-panel bg-ink p-7 text-white
            sm:p-9">
            <div className="space-y-2">
              <span className="block text-[13px] font-bold tracking-[0.08em] text-ember uppercase">Your store</span>
              {store
                ? (
                  <p className="font-display text-[30px] leading-tight font-bold tracking-[-0.02em]">
                    {store.name} <span className="font-semibold text-on-ink-muted">{store.state}</span>
                  </p>
                )
                : <div aria-hidden="true" className="h-9 w-48 animate-pulse rounded-full bg-white/10" />}
              <p className="text-[16px] text-on-ink">
                Click &amp; Collect and stock levels on this site are shown for this store.
              </p>
            </div>
            {store && (
              <p className="text-[14px] text-on-ink-muted">
                {store.suburb} {store.state} · Manager {store.manager_name}
              </p>
            )}
          </section>

          <Card>
            <div className="space-y-4 p-5 sm:p-6">
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="font-display text-[20px] font-bold tracking-[-0.01em]">Who has it?</h2>
                <span className="text-[13px] text-muted">R3</span>
              </div>
              <label className="block">
                <span className="mb-1.5 block text-[12px] font-bold tracking-[0.08em] text-muted uppercase">
                  Search the catalogue by name, brand or SKU
                </span>
                <input className={inputClass} value={search} placeholder="e.g. Sony or SONY-WH1000XM5-B"
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setChosen(undefined);
                  }} />
              </label>

              {term.length >= 2 && (matches.loading && !matches.data
                ? <p className="text-[14px] text-muted">Searching…</p>
                : (matches.data ?? []).length === 0
                  ? <p className="text-[14px] text-muted">Nothing matches “{term}”.</p>
                  : (
                    <div className="flex flex-wrap gap-2">
                      {(matches.data ?? []).slice(0, 8).map((match) => (
                        <Button key={match.product_id} size="sm" aria-pressed={chosen === match.product_id}
                          tone={chosen === match.product_id ? "primary" : "secondary"}
                          onClick={() => setChosen(match.product_id)}>
                          {match.brand} {match.name}
                        </Button>
                      ))}
                    </div>
                  ))}
              {matches.error && <ErrorBox error={matches.error} />}

              {chosen !== undefined && (
                <div className="overflow-hidden rounded-tile border border-line">
                  {detail.error && <ErrorBox error={detail.error} className="m-3" />}
                  {!detail.error && !product && <p className="p-4 text-[14px] text-muted">Loading stock…</p>}
                  {product && (
                    <>
                      <div className="border-b border-line bg-sand px-4 py-3">
                        <div className="font-semibold">{product.brand} {product.name}</div>
                        <div className="font-mono text-[12px] text-muted">{product.sku}</div>
                      </div>
                      <ul className="max-h-80 divide-y divide-line overflow-y-auto">
                        {product.stock.map((row) => (
                          <li key={row.store_id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-[14px]">
                            <span className="flex flex-wrap items-center gap-2">
                              {row.store_name}
                              {row.store_type === "warehouse" && <Badge tone="blue">warehouse</Badge>}
                            </span>
                            <span className="flex items-center gap-3">
                              <span className="text-[13px] text-muted">{row.state}</span>
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
        </div>
      </div>

      {!stores.data && !stores.error && <Skeleton className="h-48" />}
      {stores.data?.length === 0 && <Card><Empty>No stores to show.</Empty></Card>}

      {states.map((state) => (
        <section key={state}>
          <SectionTitle>{state}</SectionTitle>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(stores.data ?? []).filter((row) => row.state === state).map((row) => {
              const isMine = row.store_id === store?.store_id;
              const retail = row.store_type === "retail";
              return (
                <article key={row.store_id}
                  className={`flex flex-col gap-4 rounded-card p-5 ${retail ? "bg-white" : "bg-sand"} ${
                    isMine ? "border-2 border-ink" : "border border-line"}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-start gap-3">
                      <span aria-hidden="true" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px]
                        bg-brand-soft">
                        <PinIcon />
                      </span>
                      <div className="min-w-0">
                        <h3 className="text-[17px] font-bold">{row.name}</h3>
                        <div className="text-[14px] text-muted">{row.suburb} {row.state}</div>
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      {isMine && <Badge tone="sale">your store</Badge>}
                      {!retail && <Badge tone="blue">warehouse</Badge>}
                    </div>
                  </div>
                  <div className="text-[13px] text-muted">Manager: {row.manager_name}</div>
                  {retail && !isMine && (
                    <div className="mt-auto">
                      <Button size="sm" onClick={() => setStoreId(row.store_id)}>Make this my store</Button>
                    </div>
                  )}
                  {retail && isMine && (
                    <p className="mt-auto text-[13px] font-semibold">Stock and Click &amp; Collect are shown for this store.</p>
                  )}
                  {!retail && (
                    <p className="mt-auto text-[13px] text-muted">Ships online orders; not a collection point.</p>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function PinIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round" className="text-brand-strong">
      <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </svg>
  );
}
