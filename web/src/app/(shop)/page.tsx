"use client";

import Link from "next/link";

import { useShop } from "@/components/shop/context";
import {
  AccountPanel, CategoryGrid, DealCard, DealOfTheWeek, Hero, SectionHeading, StartingSoon, StorePanel,
} from "@/components/shop/home-sections";
import { RecentOrders } from "@/components/shop/recent-orders";
import { RecentReturns } from "@/components/shop/recent-returns";
import { Button, ErrorBox, NoticeBanner, useNotice } from "@/components/ui";
import { api, call, type Promotion } from "@/lib/api/client";
import { useCart } from "@/lib/cart-context";
import { liveDealsByDiscount } from "@/lib/deals";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function HomePage() {
  const {
    session, customerLoading, customer, customerError, store, homeState, retailStores, setStoreId, categories,
    loadError, reload,
  } = useShop();
  const { addItem } = useCart();
  const { notice, showSuccess, clear } = useNotice();
  const storeId = store?.store_id;

  const deals = useLoad("deals:active", () =>
    call(api.GET("/api/v1/promotions", { params: { query: { status: "active" } } })));
  const upcoming = useLoad("deals:upcoming", () =>
    call(api.GET("/api/v1/promotions", { params: { query: { status: "upcoming" } } })));
  const products = useLoad("products", () => call(api.GET("/api/v1/products")));
  const stock = useLoad(`stock:${storeId}`, () =>
    storeId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/stores/{store_id}/inventory", { params: { path: { store_id: storeId } } })));
  const customerId = customer?.customer_id;
  const orders = useLoad(`home-orders:${customerId}`, () =>
    customerId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/customers/{customer_id}/orders", { params: { path: { customer_id: customerId } } })));
  // The 3 newest (the API lists them newest first). useLoad keeps the last result while the next one loads,
  // so wait for it, and keep to this customer's orders.
  const recentOrders = orders.loading
    ? undefined
    : orders.data?.filter((order) => order.customer_id === customerId).slice(0, 3);

  // Stock of each product at "my store" (R3), and each product's category (for its picture tile).
  const stockAt = stock.loading ? undefined : new Map((stock.data ?? []).map((row) => [row.product_id, row.quantity]));
  const categoryOf = new Map((products.data ?? []).map((p) => [p.product_id, p.category_id]));
  // After a failure (e.g. the API wasn't running yet), retry the shared data and this page's own loads.
  const retry = () => {
    reload();
    deals.reload();
    upcoming.reload();
    products.reload();
    stock.reload();
    orders.reload();
  };
  const liveDeals = liveDealsByDiscount(deals.data);
  const soonDeals = (upcoming.data ?? []).filter((d) => d.product_active);
  const dealOfTheWeek = liveDeals[0];
  // "Change store" offers the customer's state if it has a retail store, else the state of my store.
  const nearState = homeState && retailStores.some((s) => s.state === homeState) ? homeState : store?.state;
  const staff = session.status === "signed-in" && session.me.kind === "staff";

  const addDeal = (deal: Promotion) => {
    addItem(deal.product_id);
    showSuccess(
      <>Added <b>{deal.product_name}</b> to your cart.{" "}
        <Link href={SHOP_PAGES.cart.href} className="font-semibold underline">Go to cart →</Link></>,
    );
  };

  return (
    <div className="flex flex-col gap-14">
      <title>TechLight · Home</title>

      {loadError && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={loadError} />
          <Button onClick={retry}>Try again</Button>
        </div>
      )}

      <Hero storeName={store?.name}>
        <DealOfTheWeek deal={dealOfTheWeek} loading={deals.loading && !deals.data} categories={categories}
          categoryId={dealOfTheWeek && categoryOf.get(dealOfTheWeek.product_id)} store={store}
          quantity={dealOfTheWeek && stockAt?.get(dealOfTheWeek.product_id)} />
      </Hero>

      <section>
        <SectionHeading title="Shop by category" note="Live from the category tree (a recursive relationship)" />
        {loadError && <p className="text-[15px] text-muted">Categories couldn&apos;t be loaded — see above.</p>}
        <CategoryGrid categories={categories} />
      </section>

      <section id="deals" className="scroll-mt-6">
        <SectionHeading title="Current deals" live
          note={store ? <>Live now, with stock at {store.name}</> : "Live now: promotions running today"}
          action={<Link href={SHOP_PAGES.catalogue.href}
            className="text-[15px] font-bold text-brand-strong hover:underline">Shop all products →</Link>} />
        <NoticeBanner notice={notice} onClose={clear} />
        {deals.error && (
          <div className="flex flex-wrap items-center gap-3">
            <ErrorBox error={deals.error} />
            {!loadError && <Button onClick={retry}>Try again</Button>  /* else the banner above already offers it */}
          </div>
        )}
        {!deals.error && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(232px,1fr))] gap-4">
            {deals.loading && !deals.data
              ? Array.from({ length: 4 }, (_, i) => (
                <div key={i} aria-hidden="true" className="h-[420px] animate-pulse rounded-card bg-sand" />
              ))
              : liveDeals.map((deal) => (
                <DealCard key={deal.promotion_id} deal={deal} categoryId={categoryOf.get(deal.product_id)}
                  categories={categories} store={store} quantity={stockAt?.get(deal.product_id)} onAdd={addDeal} />
              ))}
            {!deals.loading && liveDeals.length === 0 && <p className="text-[15px] text-muted">No deals right now.</p>}
          </div>
        )}
        <StartingSoon deals={soonDeals} />
      </section>

      <section className="flex flex-wrap gap-4">
        <StorePanel store={store} nearState={nearState}
          nearby={retailStores.filter((s) => !nearState || s.state === nearState)} onChoose={setStoreId} />
        <AccountPanel session={session} customer={customer} error={customerError}
          loading={session.status === "loading" || (session.status === "signed-in" && !staff && customerLoading)} />
      </section>

      {/* A customer's own orders and returns; a guest gets "Make it yours" above instead. */}
      {customer && (
        <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <RecentOrders checking={customerLoading} signedIn staff={false} orders={recentOrders} error={orders.error} />
          <RecentReturns />
        </section>
      )}
    </div>
  );
}
