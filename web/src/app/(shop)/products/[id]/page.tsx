"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useShop } from "@/components/shop/context";
import { StoreLine } from "@/components/shop/product-card";
import { Badge, Button, Card, Empty, ErrorBox, inputClass, StockBadge } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { MAX_QUANTITY } from "@/lib/cart";
import { useCart } from "@/lib/cart-context";
import { money, percentOff } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function ProductPage() {
  const { id } = useParams<{ id: string }>();
  const productId = Number(id);
  const valid = Number.isInteger(productId) && productId > 0;
  const { store } = useShop();
  const { addItem } = useCart();
  const [quantity, setQuantity] = useState("1");
  const [added, setAdded] = useState<number>();

  const product = useLoad(`product:${id}`, () =>
    valid
      ? call(api.GET("/api/v1/products/{product_id}", { params: { path: { product_id: productId } } }))
      : Promise.resolve(undefined));
  // useLoad keeps the previous result while a new one loads: never show another product under this id.
  const detail = product.data?.product_id === productId ? product.data : undefined;

  if (!valid) {
    return (
      <Card><Empty>
        That isn&apos;t a product number.{" "}
        <Link href={SHOP_PAGES.catalogue.href} className="underline">Back to the shop</Link>.
      </Empty></Card>
    );
  }

  const units = Math.min(Math.max(Math.trunc(Number(quantity)) || 1, 1), MAX_QUANTITY);
  // My store first (it is the one the stock line quotes), then the rest in store order.
  const stock = [...(detail?.stock ?? [])].sort((a, b) =>
    Number(b.store_id === store?.store_id) - Number(a.store_id === store?.store_id));
  const mine = stock.find((row) => row.store_id === store?.store_id);

  return (
    <div className="space-y-5">
      <title>{`${detail?.name ?? "Product"} · JB Hi-Fi`}</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> /{" "}
        <Link href={SHOP_PAGES.catalogue.href} className="hover:underline">Shop all products</Link> /{" "}
        {detail?.name ?? "…"}
      </nav>

      {product.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={product.error} />
          <Button onClick={product.reload}>Try again</Button>
        </div>
      )}
      {!product.error && !detail && <div className="h-40 animate-pulse rounded-xl bg-neutral-200" />}

      {detail && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="space-y-5">
            <Card className="p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">{detail.brand}</div>
                  <h1 className="mt-1 text-2xl font-semibold tracking-tight">{detail.name}</h1>
                  <div className="mt-1 font-mono text-xs text-neutral-500">{detail.sku}</div>
                </div>
                <div className="flex gap-2">
                  {detail.on_sale && <Badge tone="sale">{percentOff(detail.base_price, detail.current_price)}</Badge>}
                  {!detail.is_active && <Badge>retired</Badge>}
                </div>
              </div>

              <div className="mt-5 flex flex-wrap items-end gap-3">
                <span className="text-3xl font-bold">{money(detail.current_price)}</span>
                {detail.on_sale && (
                  <s className="text-neutral-500"><span className="sr-only">was </span>{money(detail.base_price)}</s>
                )}
              </div>

              {!detail.is_active && (
                <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  This product has been retired, so it can&apos;t be bought (BR07). Its record is kept because past
                  orders point to it.
                </p>
              )}

              <div className="mt-5 flex flex-wrap items-end gap-3">
                <label className="block w-28">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">
                    Quantity
                  </span>
                  <input className={inputClass} type="number" min={1} max={MAX_QUANTITY} step={1} value={quantity}
                    onChange={(event) => setQuantity(event.target.value)} />
                </label>
                {/* Enabled even when My store has none: a delivery can ship from another store. */}
                <Button tone="primary" disabled={!detail.is_active}
                  onClick={() => {
                    addItem(detail.product_id, units);
                    setAdded(units);
                  }}>
                  Add to cart
                </Button>
                <Link href={SHOP_PAGES.cart.href}
                  className="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100">
                  Go to cart
                </Link>
              </div>
              {added !== undefined && (
                <p role="status" className="mt-3 text-sm text-emerald-800">
                  Added {added} to your cart. Stock is only taken when checkout commits.
                </p>
              )}
              {mine && (
                <div className="mt-4 border-t border-neutral-200 pt-3">
                  <StoreLine quantity={mine.quantity} storeName={store?.name} />
                </div>
              )}
            </Card>

            <Card title="Specifications">
              {detail.specs.length === 0
                ? <Empty>No specifications recorded for this product.</Empty>
                : (
                  <dl className="divide-y divide-neutral-100">
                    {detail.specs.map((spec) => (
                      <div key={spec.spec_name} className="flex gap-4 px-4 py-2.5 text-sm">
                        <dt className="w-40 shrink-0 text-neutral-500">{spec.spec_name}</dt>
                        <dd className="text-neutral-900">{spec.spec_value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
            </Card>
          </div>

          <Card title="Where it is in stock" actions={<span className="text-xs text-neutral-500">R3</span>}>
            <ul className="divide-y divide-neutral-100">
              {stock.map((row) => {
                const isMine = row.store_id === store?.store_id;
                return (
                  <li key={row.store_id}
                    className={`flex items-center justify-between gap-3 px-4 py-2.5 text-sm ${isMine ? "bg-yellow-50" : ""}`}>
                    <div>
                      <div className="font-medium text-neutral-900">
                        {row.store_name}
                        {row.store_type === "warehouse" && (
                          <span className="ml-2"><Badge tone="blue">warehouse</Badge></span>
                        )}
                        {isMine && <span className="ml-2"><Badge tone="sale">your store</Badge></span>}
                      </div>
                      <div className="text-xs text-neutral-500">{row.state}</div>
                    </div>
                    <StockBadge quantity={row.quantity} />
                  </li>
                );
              })}
            </ul>
            <p className="border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500">
              To collect from another store, change “My store” at the top of the page.
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
