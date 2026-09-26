"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { useShop } from "@/components/shop/context";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Badge, Button, ErrorBox, LOW_STOCK } from "@/components/ui";
import { api, call, type Promotion, type ReturnSummary, type Store } from "@/lib/api/client";
import { productCountsByCategory } from "@/lib/categories";
import { formatDate, formatDateTime, formatLastDay, money, percentOff } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

const discount = (p: Promotion) => 1 - Number(p.sale_price) / Number(p.base_price);

export default function HomePage() {
  const { customerLoading, customer, store, homeState, retailStores, setStoreId, categories, loadError,
    customerError, reload } = useShop();
  // The greeting area reports whichever failure the viewer can act on first.
  const greetingError = customerError ?? loadError;
  const customerId = customer?.customer_id;
  const storeId = store?.store_id;

  const deals = useLoad("deals:active", () =>
    call(api.GET("/api/v1/promotions", { params: { query: { status: "active" } } })));
  const upcoming = useLoad("deals:upcoming", () =>
    call(api.GET("/api/v1/promotions", { params: { query: { status: "upcoming" } } })));
  const products = useLoad("products", () => call(api.GET("/api/v1/products")));
  const myOrders = useLoad(`home-orders:${customerId ?? "guest"}`, () =>
    customerId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/customers/{customer_id}/orders", { params: { path: { customer_id: customerId } } })));
  const myReturns = useLoad(`home-returns:${customerId ?? "guest"}`, () =>
    customerId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/customers/{customer_id}/returns", { params: { path: { customer_id: customerId } } })));
  const stock = useLoad(`stock:${storeId}`, () =>
    storeId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/stores/{store_id}/inventory", { params: { path: { store_id: storeId } } })));

  // Stock of each product at "my store" (R3), for the deal cards.
  const stockAt = stock.loading ? undefined : new Map((stock.data ?? []).map((row) => [row.product_id, row.quantity]));
  // After a failure (e.g. the API wasn't running yet), retry the shared data and this page's own loads.
  const retry = () => {
    reload();
    deals.reload();
    upcoming.reload();
    products.reload();
    stock.reload();
    myOrders.reload();
    myReturns.reload();
  };
  // A retired product's promotion isn't advertised: it can't be bought.
  const liveDeals = (deals.data ?? []).filter((d) => d.product_active).sort((a, b) => discount(b) - discount(a));
  const soonDeals = (upcoming.data ?? []).filter((d) => d.product_active);
  const address = customer?.addresses.find((a) => a.is_active);
  // "Stores near you": the customer's state if it has a retail store, else the state of my store.
  const nearState = homeState && retailStores.some((s) => s.state === homeState) ? homeState : store?.state;
  // Counts come from the shared recursive walk, so a grandchild's products count towards its ancestors.
  const counts = productCountsByCategory(categories, (products.data ?? []).map((p) => p.category_id));
  const recentOrders = (myOrders.data ?? []).slice(0, 3);
  const activeReturns = (myReturns.data ?? []).filter((row) => row.status !== "rejected").slice(0, 3);

  return (
    <div className="space-y-10">
      <title>JB Hi-Fi · Home</title>

      {/* ---------------------------------------------------------------- greeting */}
      <section className="flex flex-wrap items-end justify-between gap-6 rounded-2xl bg-white p-6 shadow-sm
        ring-1 ring-neutral-200">
        <div>
          {customerLoading
            ? <div aria-hidden="true" className="h-9 w-48 animate-pulse rounded bg-neutral-200" />
            : (
              <h1 className="text-3xl font-bold tracking-tight">
                {customer ? `Hi, ${customer.full_name.split(" ")[0]}` : "Welcome to JB Hi-Fi"}
              </h1>
            )}
          {greetingError ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <ErrorBox error={greetingError} />
              <Button onClick={retry}>Try again</Button>
            </div>
          ) : (
            <p className="mt-2 text-neutral-600">
              {store ? <>Your store is <b>{store.name}</b> ({store.state}) — Click &amp; Collect and stock shown here.</>
                : "Loading stores…"}
            </p>
          )}
          <p className="mt-1 text-sm text-neutral-500">
            {customerLoading ? "\u00a0"
              : !customer ? "Guest: choose a customer under “Signed in as” to see a personal home page (demo sign-in)."
              : address ? <>Delivering to {address.line1}, {address.suburb} {address.state} {address.postcode}.</>
              : "No current delivery address — add one in My account."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <QuickLink href={SHOP_PAGES.catalogue.href}>Shop all products</QuickLink>
          <QuickLink href={SHOP_PAGES.orders.href}>My orders</QuickLink>
          <QuickLink href={SHOP_PAGES.stores.href}>Find a store</QuickLink>
        </div>
      </section>

      {/* ---------------------------------------------------------------- deals */}
      <section id="deals" className="scroll-mt-4">
        <SectionHeading title="Current deals" note="Live: promotions running now, with stock at your store"
          action={<Link href={SHOP_PAGES.catalogue.href} className="text-sm font-medium hover:underline">
            Shop all products →</Link>} />
        {deals.error && (
          <div className="flex flex-wrap items-center gap-3">
            <ErrorBox error={deals.error} />
            {!loadError && <Button onClick={retry}>Try again</Button>  /* else the greeting already offers it */}
          </div>
        )}
        {!deals.error && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {deals.loading && !deals.data
              ? Array.from({ length: 4 }, (_, i) => <div key={i} className="h-52 animate-pulse rounded-xl bg-neutral-200" />)
              : liveDeals.map((deal) => (
                <DealCard key={deal.promotion_id} deal={deal} store={store} quantity={stockAt?.get(deal.product_id)} />
              ))}
            {!deals.loading && liveDeals.length === 0 && <p className="text-sm text-neutral-500">No deals right now.</p>}
          </div>
        )}
        {soonDeals.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl bg-neutral-900 px-4 py-3 text-sm
            text-neutral-200">
            <span className="font-semibold text-yellow-300">Starting soon</span>
            {soonDeals.map((p) => (
              <span key={p.promotion_id}>
                {p.brand} {p.product_name} <b className="text-white">{money(p.sale_price)}</b>
                <span className="text-neutral-400"> from {formatDate(p.starts_at)}</span>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* ---------------------------------------------------------------- categories */}
      <section>
        <SectionHeading title="Shop by category" note="Live: the category tree (a recursive relationship)" />
        {loadError && <p className="text-sm text-neutral-500">Categories couldn&apos;t be loaded — see above.</p>}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {categories.filter((c) => c.parent_id === null).map((parent) => {
            const children = categories.filter((c) => c.parent_id === parent.category_id);
            const count = (id: number) => counts.get(id) ?? 0;
            const total = count(parent.category_id);
            return (
              <div key={parent.category_id} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-neutral-200">
                <Link href={`${SHOP_PAGES.catalogue.href}?category=${parent.category_id}`}
                  className="font-semibold hover:underline">{parent.name}</Link>
                <div className="mt-0.5 text-xs text-neutral-500">
                  {products.data ? `${total} products` : "…"}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {children.map((c) => (
                    <Link key={c.category_id} href={`${SHOP_PAGES.catalogue.href}?category=${c.category_id}`}
                      className="rounded-full bg-neutral-100 px-2.5 py-1 text-xs text-neutral-700 hover:bg-yellow-200">
                      {c.name}{products.data && <span className="text-neutral-500"> {count(c.category_id)}</span>}
                    </Link>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ---------------------------------------------------------------- orders and returns (reserved) */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <HomePanel title="My orders" href={SHOP_PAGES.orders.href} action="All orders →"
          empty={customer ? "No orders yet." : "Sign in (demo) to see your orders here."}>
          {recentOrders.map((order) => (
            <a key={order.order_id} href={`/orders/${order.order_id}`}
              className="flex items-center justify-between gap-3 py-2.5 hover:bg-neutral-50">
              <span>
                <span className="font-medium">Order #{order.order_id}</span>
                <span className="block text-xs text-neutral-500">{formatDateTime(order.placed_at)}</span>
              </span>
              <span className="flex items-center gap-3">
                <span className="text-sm tabular-nums">{money(order.total)}</span>
                <StatusBadge status={order.status} />
              </span>
            </a>
          ))}
        </HomePanel>
        <HomePanel title="Returns" href={SHOP_PAGES.returns.href} action="All returns →"
          empty={customer ? "No returns in progress." : "Sign in (demo) to track returns here."}>
          {activeReturns.map((row: ReturnSummary) => (
            <a key={row.return_id} href={`/orders/${row.order_id}`}
              className="flex items-center justify-between gap-3 py-2.5 hover:bg-neutral-50">
              <span>
                <span className="font-medium">Return #{row.return_id}</span>
                <span className="block text-xs text-neutral-500">order #{row.order_id} · “{row.reason}”</span>
              </span>
              <StatusBadge status={row.status} />
            </a>
          ))}
        </HomePanel>
      </section>

      {/* ---------------------------------------------------------------- stores */}
      <section>
        <SectionHeading title={nearState ? `Stores in ${nearState}` : "Stores"}
          note="Live. Click & Collect is from retail stores only — never the warehouse (BR06)"
          action={<Link href={SHOP_PAGES.stores.href} className="text-sm font-medium hover:underline">All stores →</Link>} />
        {loadError && <p className="text-sm text-neutral-500">Stores couldn&apos;t be loaded — see above.</p>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {retailStores.filter((s) => !nearState || s.state === nearState).map((s) => (
            <StoreCard key={s.store_id} store={s} mine={s.store_id === store?.store_id}
              onChoose={() => setStoreId(s.store_id)} />
          ))}
        </div>
      </section>
    </div>
  );
}

function SectionHeading({ title, note, action }: { title: string; note?: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="text-xl font-bold tracking-tight">{title}</h2>
        {note && <p className="text-xs text-neutral-500">{note}</p>}
      </div>
      {action}
    </div>
  );
}

function QuickLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="rounded-md bg-neutral-900 px-3.5 py-2 text-sm font-medium text-white hover:bg-neutral-700">
      {children}
    </Link>
  );
}

function DealCard({ deal, store, quantity }: { deal: Promotion; store?: Store; quantity?: number }) {
  return (
    <Link href={`${SHOP_PAGES.catalogue.href}/${deal.product_id}`}
      className="group flex flex-col rounded-xl bg-white p-4 shadow-sm ring-1 ring-neutral-200 transition
        hover:shadow-md hover:ring-neutral-300">
      <div className="flex items-start justify-between gap-2">
        <span className="rounded bg-yellow-300 px-2 py-0.5 text-xs font-black uppercase text-neutral-900">
          {percentOff(deal.base_price, deal.sale_price)}
        </span>
        <span className="text-xs text-neutral-500">last day {formatLastDay(deal.ends_at)}</span>
      </div>
      <div className="mt-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">{deal.brand}</div>
      <div className="line-clamp-2 font-medium text-neutral-900 group-hover:underline">{deal.product_name}</div>
      <div className="mt-auto pt-3">
        <span className="text-2xl font-bold">{money(deal.sale_price)}</span>
        <s className="ml-2 text-sm text-neutral-500"><span className="sr-only">was </span>{money(deal.base_price)}</s>
      </div>
      <StockLine quantity={quantity} store={store} />
    </Link>
  );
}

function StockLine({ quantity, store }: { quantity?: number; store?: Store }) {
  if (quantity === undefined || !store) return <div className="mt-2 h-5" />;
  const [dot, text] = quantity === 0 ? ["bg-red-500", `Out of stock at ${store.name}`]
    : quantity <= LOW_STOCK ? ["bg-amber-500", `Only ${quantity} left at ${store.name}`]
    : ["bg-emerald-500", `${quantity} in stock at ${store.name}`];
  return (
    <div className="mt-2 flex items-center gap-2 text-xs text-neutral-600">
      <span className={`h-2 w-2 rounded-full ${dot}`} /> {text}
    </div>
  );
}

function HomePanel({ title, href, action, empty, children }: {
  title: string; href: string; action: string; empty: string; children: ReactNode;
}) {
  const hasRows = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-neutral-200">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-bold">{title}</h2>
        <Link href={href} className="text-sm font-medium hover:underline">{action}</Link>
      </div>
      {hasRows
        ? <div className="mt-2 divide-y divide-neutral-100">{children}</div>
        : <p className="mt-2 text-sm text-neutral-500">{empty}</p>}
    </section>
  );
}

function StoreCard({ store, mine, onChoose }: { store: Store; mine: boolean; onChoose: () => void }) {
  return (
    <div className={`rounded-xl bg-white p-4 shadow-sm ring-1 ${mine ? "ring-2 ring-neutral-900" : "ring-neutral-200"}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{store.name}</div>
          <div className="text-xs text-neutral-500">{store.suburb} {store.state}</div>
        </div>
        {mine && <Badge tone="sale">Your store</Badge>}
      </div>
      <div className="mt-2 text-xs text-neutral-500">Manager: {store.manager_name}</div>
      {!mine && (
        <button type="button" onClick={onChoose} className="mt-3 text-sm font-medium text-neutral-800 hover:underline">
          Make this my store
        </button>
      )}
    </div>
  );
}
