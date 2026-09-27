"use client";

import Link from "next/link";

import { useShop } from "@/components/shop/context";
import { Badge, Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call, type ProductSummary } from "@/lib/api/client";
import { fromCents, lineTotalCents, MAX_QUANTITY } from "@/lib/cart";
import { useCart } from "@/lib/cart-context";
import { money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function CartPage() {
  const { store } = useShop();
  const { items, ready, setQuantity, removeItem, count } = useCart();
  const storeId = store?.store_id;

  // One request for the whole catalogue (with this store's stock), then pick the lines we hold.
  const products = useLoad(`cart-products:${storeId}`, () =>
    call(api.GET("/api/v1/products", { params: { query: { include_inactive: true, store_id: storeId } } })));

  const byId = new Map<number, ProductSummary>((products.data ?? []).map((row) => [row.product_id, row]));
  const lines: { product_id: number; quantity: number; product?: ProductSummary }[] =
    items.map((item) => ({ ...item, product: byId.get(item.product_id) }));
  const unresolved = products.data ? lines.filter((line) => !line.product) : [];
  const unavailable = lines.filter((line) => line.product && !line.product.is_active);
  const subtotal = lines.reduce((total, line) =>
    total + (line.product ? lineTotalCents(line.product.current_price, line.quantity) : 0), 0);
  const shortfall = lines.filter((line) => line.product
    && (line.product.store_quantity ?? 0) < line.quantity);
  const blocked = !ready || items.length === 0 || !products.data
    || unresolved.length > 0 || unavailable.length > 0;

  return (
    <div className="space-y-5">
      <title>Cart · JB Hi-Fi</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> /{" "}
        <Link href="/products" className="hover:underline">Shop all products</Link> / Cart
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
          Your cart is empty. <Link href="/products" className="font-medium underline">Find something to buy →</Link>
        </Empty></Card>
      )}

      {items.length > 0 && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Card title={`${count} ${count === 1 ? "item" : "items"}`}
            actions={<span className="text-xs text-neutral-500">
              Stock and prices at {store?.name ?? "your store"}, refreshed just now
            </span>}>
            <ul className="divide-y divide-neutral-100">
              {lines.map((line) => {
                const price = line.product?.current_price;
                const stock = line.product?.store_quantity ?? 0;
                return (
                  <li key={line.product_id} className="flex flex-wrap items-start gap-4 px-4 py-4">
                    <div className="min-w-[12rem] flex-1">
                      {line.product
                        ? (
                          <>
                            <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                              {line.product.brand}
                            </div>
                            <Link href={`/products/${line.product_id}`} className="font-medium hover:underline">
                              {line.product.name}
                            </Link>
                            <div className="font-mono text-xs text-neutral-500">{line.product.sku}</div>
                            {!line.product.is_active && <p className="mt-1 text-xs text-amber-700">
                              Retired — remove it to continue.
                            </p>}
                            {line.product.is_active && stock < line.quantity && (
                              <p className="mt-1 text-xs text-amber-700">
                                Only {stock} at {store?.name ?? "your store"} right now. Checkout will tell you
                                for certain.
                              </p>
                            )}
                          </>
                        )
                        : (
                          <>
                            <div className="font-medium text-neutral-900">Product #{line.product_id}</div>
                            <p className="mt-1 text-xs text-red-700">
                              {products.data ? "No longer in the catalogue — remove it to continue." : "Loading…"}
                            </p>
                          </>
                        )}
                    </div>

                    <div className="flex items-center gap-2">
                      <label className="sr-only" htmlFor={`qty-${line.product_id}`}>Quantity</label>
                      <input id={`qty-${line.product_id}`} type="number" min={1} max={MAX_QUANTITY} step={1}
                        value={line.quantity}
                        onChange={(event) => setQuantity(line.product_id, Number(event.target.value))}
                        className="h-9 w-20 rounded-md border border-neutral-300 px-2 text-sm tabular-nums" />
                    </div>

                    <div className="w-24 text-right">
                      {price && <div className="font-semibold tabular-nums">
                        {money(fromCents(lineTotalCents(price, line.quantity)))}
                      </div>}
                      {price && <div className="text-xs text-neutral-500">{money(price)} each</div>}
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
                <span className="text-sm text-neutral-600">Subtotal ({count} items)</span>
                <span className="text-xl font-bold tabular-nums">{money(fromCents(subtotal))}</span>
              </div>
              <p className="text-xs text-neutral-500">
                Prices include any running promotion. Nothing is reserved until checkout commits, and the
                final amount is worked out by the database, not this page.
              </p>
              {shortfall.length > 0 && (
                <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  {shortfall.length === 1 ? "One item is" : `${shortfall.length} items are`} short at{" "}
                  {store?.name ?? "your store"}. You can still try — checkout checks all stores’ stock in one
                  transaction.
                </p>
              )}
              <Link href="/checkout"
                aria-disabled={blocked}
                onClick={(event) => blocked && event.preventDefault()}
                className={`inline-flex h-9 w-full items-center justify-center rounded-md text-sm font-medium
                  ${blocked ? "cursor-not-allowed bg-neutral-400 text-white" : "bg-neutral-900 text-white hover:bg-neutral-700"}`}>
                Checkout
              </Link>
              <Link href="/products" className="block text-center text-sm font-medium text-neutral-700 hover:underline">
                Continue shopping
              </Link>
              {unresolved.length + unavailable.length > 0 && (
                <p className="text-xs text-red-700">
                  Remove the items marked above before checking out.
                </p>
              )}
              {products.loading && !products.data && <Badge>Checking prices…</Badge>}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
