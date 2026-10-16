"use client";

import Link from "next/link";

import { useShop } from "@/components/shop/context";
import { Badge, Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call, type ProductSummary } from "@/lib/api/client";
import { fromCents, lineTotalCents, MAX_QUANTITY } from "@/lib/cart";
import { useCart } from "@/lib/cart-context";
import { money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function CartPage() {
  const { store } = useShop();
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
    <div className="space-y-5">
      <title>Cart · TechLight</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> /{" "}
        <Link href={SHOP_PAGES.catalogue.href} className="hover:underline">Shop all products</Link> / Cart
      </nav>
      <h1 className="text-2xl font-semibold tracking-tight">Your cart</h1>

      {products.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={products.error} />
          <Button onClick={products.reload}>Try again</Button>
        </div>
      )}

      {ready && items.length === 0 && (
        <Card><Empty>
          Your cart is empty.{" "}
          <Link href={SHOP_PAGES.catalogue.href} className="font-medium underline">Find something to buy →</Link>
        </Empty></Card>
      )}

      {items.length > 0 && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Card title={`${count} ${count === 1 ? "item" : "items"}`}
            actions={(
              <span className="text-xs text-neutral-500">Current prices; stock at {store?.name ?? "your store"}</span>
            )}>
            <ul className="divide-y divide-neutral-100">
              {lines.map((line) => {
                const price = line.product?.current_price;
                const stock = line.product?.store_quantity;
                return (
                  <li key={line.product_id} className="flex flex-wrap items-start gap-4 px-4 py-4">
                    <div className="min-w-[12rem] flex-1">
                      {line.product ? (
                        <>
                          <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                            {line.product.brand}
                          </div>
                          <Link href={`${SHOP_PAGES.catalogue.href}/${line.product_id}`}
                            className="font-medium hover:underline">
                            {line.product.name}
                          </Link>
                          <div className="font-mono text-xs text-neutral-500">{line.product.sku}</div>
                          {!line.product.is_active && (
                            <p className="mt-1 text-xs text-amber-700">
                              Retired, so it can&apos;t be bought — remove it to continue.
                            </p>
                          )}
                          {line.product.is_active && typeof stock === "number" && stock < line.quantity && (
                            <p className="mt-1 text-xs text-amber-700">
                              Only {stock} at {store?.name ?? "your store"} right now. Checkout will tell you for
                              certain.
                            </p>
                          )}
                        </>
                      ) : (
                        <>
                          <div className="font-medium text-neutral-900">Product #{line.product_id}</div>
                          <p className="mt-1 text-xs text-red-700">
                            {products.data ? "No longer in the catalogue — remove it to continue." : "Loading…"}
                          </p>
                        </>
                      )}
                    </div>

                    {/* Steps of one, never below 1: only "Remove" takes a line out (an emptied number box would
                        have read as 0 and removed it). */}
                    <div className="flex items-center gap-1">
                      <Button size="sm" aria-label="One fewer" disabled={line.quantity <= 1}
                        onClick={() => setQuantity(line.product_id, line.quantity - 1)}>−</Button>
                      <span className="w-8 text-center text-sm tabular-nums">{line.quantity}</span>
                      <Button size="sm" aria-label="One more" disabled={line.quantity >= MAX_QUANTITY}
                        onClick={() => setQuantity(line.product_id, line.quantity + 1)}>+</Button>
                    </div>

                    <div className="w-24 text-right">
                      {price && (
                        <>
                          <div className="font-semibold tabular-nums">
                            {money(fromCents(lineTotalCents(price, line.quantity)))}
                          </div>
                          <div className="text-xs text-neutral-500">{money(price)} each</div>
                        </>
                      )}
                    </div>

                    <button type="button" onClick={() => removeItem(line.product_id)}
                      className="text-sm text-neutral-500 underline hover:text-neutral-800">
                      Remove
                    </button>
                  </li>
                );
              })}
            </ul>
          </Card>

          <Card title="Summary">
            <div className="space-y-3 p-4">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-neutral-600">Subtotal ({count} {count === 1 ? "item" : "items"})</span>
                <span className="text-xl font-bold tabular-nums">{money(fromCents(subtotal))}</span>
              </div>
              <p className="text-xs text-neutral-500">
                Prices include any running promotion. Nothing is reserved until checkout commits, and the amount
                charged is worked out by the database, not this page.
              </p>
              {short.length > 0 && (
                <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  {short.length === 1 ? "One item is" : `${short.length} items are`} short at{" "}
                  {store?.name ?? "your store"}. You can still try: checkout re-checks the stock at the store that
                  fulfils the order, in the same transaction.
                </p>
              )}
              <Link href={SHOP_PAGES.checkout.href} aria-disabled={blocked}
                onClick={(event) => {
                  if (blocked) event.preventDefault();
                }}
                className={`inline-flex h-9 w-full items-center justify-center rounded-md text-sm font-medium text-white
                  ${blocked ? "cursor-not-allowed bg-neutral-400" : "bg-neutral-900 hover:bg-neutral-700"}`}>
                Checkout
              </Link>
              <Link href={SHOP_PAGES.catalogue.href}
                className="block text-center text-sm font-medium text-neutral-700 hover:underline">
                Continue shopping
              </Link>
              {unknown.length + retired.length > 0 && (
                <p className="text-xs text-red-700">Remove the items marked above before checking out.</p>
              )}
              {!products.data && !products.error && <Badge>Checking prices…</Badge>}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
