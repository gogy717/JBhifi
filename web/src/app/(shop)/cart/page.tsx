"use client";

import Link from "next/link";

import { ProductImage } from "@/components/product-image";
import { useShop } from "@/components/shop/context";
import {
  Callout, Crumbs, Eyebrow, PageIntro, pillLink, Price, QuantityStepper, Skeleton,
} from "@/components/shop/page-parts";
import { Button, Card, Dot, Empty, ErrorBox } from "@/components/ui";
import { api, call, type ProductSummary } from "@/lib/api/client";
import { fromCents, lineTotalCents, MAX_QUANTITY } from "@/lib/cart";
import { useCart } from "@/lib/cart-context";
import { money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function CartPage() {
  const { store, categories } = useShop();
  const { items, ready, count, setQuantity, removeItem } = useCart();
  const storeId = store?.store_id;

  // One request for the whole catalogue — retired products too, so they can be flagged — with My store's stock.
  const products = useLoad(`cart-products:${storeId}`, () =>
    call(api.GET("/api/v1/products", { params: { query: { include_inactive: true, store_id: storeId } } })));

  const byId = new Map<number, ProductSummary>((products.data ?? []).map((row) => [row.product_id, row]));
  const lines = items.map((item) => ({ ...item, product: byId.get(item.product_id) }));
  const unknown = products.data ? lines.filter((line) => !line.product) : [];
  const retired = lines.filter((line) => line.product && !line.product.is_active);
  // Integer cents, so the subtotal is exact (lib/cart.ts).
  const subtotal = lines.reduce((total, line) =>
    total + (line.product ? lineTotalCents(line.product.current_price, line.quantity) : 0), 0);
  // Stock is only known once My store is (store_quantity is null without a store_id).
  const short = lines.filter((line) =>
    typeof line.product?.store_quantity === "number" && line.product.store_quantity < line.quantity);
  const blocked = !ready || items.length === 0 || !products.data || unknown.length > 0 || retired.length > 0;

  return (
    <div className="space-y-8">
      <title>Cart · TechLight</title>
      <div className="space-y-4">
        <Crumbs trail={[["Home", "/"], ["Shop all products", SHOP_PAGES.catalogue.href], ["Cart"]]} />
        <PageIntro title="Your cart">
          {items.length > 0 && <>Current prices; stock at <b className="text-ink">{store?.name ?? "your store"}</b>.</>}
        </PageIntro>
      </div>

      {products.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={products.error} />
          <Button onClick={products.reload}>Try again</Button>
        </div>
      )}

      {!ready && <Skeleton className="h-48" />}

      {ready && items.length === 0 && (
        <Card><Empty>
          Your cart is empty.{" "}
          <Link href={SHOP_PAGES.catalogue.href} className="font-bold text-brand-strong underline">Find something to buy →</Link>
        </Empty></Card>
      )}

      {items.length > 0 && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-8">
          <Card>
            <h2 className="sr-only">{count} {count === 1 ? "item" : "items"}</h2>
            <ul className="divide-y divide-line">
              {lines.map((line) => {
                const price = line.product?.current_price;
                const stock = line.product?.store_quantity;
                const name = line.product?.name ?? `Product #${line.product_id}`;
                return (
                  <li key={line.product_id} className="flex flex-wrap items-center gap-4 p-4 sm:flex-nowrap sm:p-5">
                    <ProductImage categoryId={line.product?.category_id} categories={categories}
                      className="h-20 w-20 shrink-0 rounded-tile" iconClassName="h-9 w-9" />

                    <div className="min-w-0 flex-1 basis-48">
                      {line.product ? (
                        <>
                          <Eyebrow>{line.product.brand}</Eyebrow>
                          <Link href={`${SHOP_PAGES.catalogue.href}/${line.product_id}`}
                            className="font-semibold leading-snug hover:text-brand-strong">
                            {line.product.name}
                          </Link>
                          <div className="font-mono text-[12px] text-muted">{line.product.sku}</div>
                          {!line.product.is_active && (
                            <p className="mt-1 text-[13px] font-semibold text-warn-ink">
                              Retired, so it can&apos;t be bought — remove it to continue.
                            </p>
                          )}
                          {line.product.is_active && typeof stock === "number" && stock < line.quantity && (
                            <p className="mt-1 flex items-center gap-1.5 text-[13px] font-semibold text-warn-ink">
                              <Dot className="bg-warn" />
                              Only {stock} at {store?.name ?? "your store"} right now. Checkout will tell you for
                              certain.
                            </p>
                          )}
                        </>
                      ) : (
                        <>
                          <div className="font-semibold">{name}</div>
                          <p className="mt-1 text-[13px] text-red-700">
                            {products.data ? "No longer in the catalogue — remove it to continue." : "Loading…"}
                          </p>
                        </>
                      )}
                    </div>

                    <div className="flex w-full items-center justify-between gap-4 sm:w-auto sm:justify-end">
                      {/* Steps of one, never below 1: only "Remove" takes a line out (an emptied number box would
                          have read as 0 and removed it). */}
                      <QuantityStepper value={line.quantity} max={MAX_QUANTITY} label={`Quantity of ${name}`}
                        onChange={(quantity) => setQuantity(line.product_id, quantity)} />

                      <div className="w-28 text-right">
                        {price && (
                          <>
                            <Price size="md" value={fromCents(lineTotalCents(price, line.quantity))} />
                            <div className="text-[13px] text-muted">{money(price)} each</div>
                          </>
                        )}
                      </div>
                    </div>

                    <button type="button" onClick={() => removeItem(line.product_id)}
                      className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-brand-strong
                        sm:ml-1">
                      Remove<span className="sr-only"> {name}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Card>

          <aside className="lg:sticky lg:top-6 lg:self-start">
            <Card>
              <div className="space-y-4 p-5">
                <h2 className="font-display text-[20px] font-bold tracking-[-0.01em]">Summary</h2>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[15px] text-muted">Subtotal ({count} {count === 1 ? "item" : "items"})</span>
                  <Price size="lg" value={fromCents(subtotal)} />
                </div>
                <p className="text-[13px] leading-relaxed text-muted">
                  Prices include any running promotion. Nothing is reserved until checkout commits, and the amount
                  charged is worked out by the database, not this page.
                </p>
                {short.length > 0 && (
                  <Callout tone="warn">
                    {short.length === 1 ? "One item is" : `${short.length} items are`} short at{" "}
                    {store?.name ?? "your store"}. You can still try: checkout re-checks the stock at the store that
                    fulfils the order, in the same transaction.
                  </Callout>
                )}
                <Link href={SHOP_PAGES.checkout.href} aria-disabled={blocked}
                  onClick={(event) => {
                    if (blocked) event.preventDefault();
                  }}
                  className={`${pillLink(blocked ? "off" : "ink")} w-full`}>
                  Checkout
                </Link>
                <Link href={SHOP_PAGES.catalogue.href} className={`${pillLink("sand")} w-full`}>
                  Continue shopping
                </Link>
                {unknown.length + retired.length > 0 && (
                  <p className="text-[13px] text-red-700">Remove the items marked above before checking out.</p>
                )}
                {!products.data && !products.error && <p className="text-[13px] text-muted">Checking prices…</p>}
              </div>
            </Card>
          </aside>
        </div>
      )}
    </div>
  );
}
