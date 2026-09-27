"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { StoreLine } from "@/components/shop/product-card";
import { useShop } from "@/components/shop/context";
import { Badge, Button, Card, Empty, ErrorBox, inputClass, selectClass, StockBadge } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { useCart } from "@/lib/cart-context";
import { money, percentOff } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function ProductPage() {
  const params = useParams<{ id: string }>();
  const productId = Number(params.id);
  const valid = Number.isInteger(productId) && productId > 0;
  const { store, setStoreId } = useShop();
  const { addItem } = useCart();
  const [quantity, setQuantity] = useState("1");
  const [added, setAdded] = useState(false);

  const product = useLoad(`product:${params.id}`, () =>
    valid
      ? call(api.GET("/api/v1/products/{product_id}", { params: { path: { product_id: productId } } }))
      : Promise.reject(new Error("not a product id")));

  if (!valid) {
    return (
      <Card><Empty>
        That is not a product id. <Link href="/products" className="underline">Back to the shop</Link>.
      </Empty></Card>
    );
  }

  const detail = product.data;
  const units = Math.max(1, Math.trunc(Number(quantity) || 1));
  // My store first: it is the one the stock line quotes, then the rest in store order.
  const stock = [...(detail?.stock ?? [])].sort((a, b) =>
    (b.store_id === store?.store_id ? 1 : 0) - (a.store_id === store?.store_id ? 1 : 0));
  const mine = stock.find((row) => row.store_id === store?.store_id);

  return (
    <div className="space-y-5">
      <title>{detail ? `${detail.name} · JB Hi-Fi` : "Product · JB Hi-Fi"}</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> /{" "}
        <Link href="/products" className="hover:underline">Shop all products</Link> / {detail?.name ?? "…"}
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
                  This product has been retired, so it cannot be bought. Its record is kept because past
                  orders point at it.
                </p>
              )}

              <div className="mt-5 flex flex-wrap items-end gap-3">
                <label className="block w-28">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">Quantity</span>
                  <input className={inputClass} type="number" min={1} step={1} value={quantity}
                    onChange={(event) => setQuantity(event.target.value)} aria-label="Quantity" />
                </label>
                <Button tone="primary" disabled={!detail.is_active}
                  onClick={() => { addItem(detail.product_id, units); setAdded(true); }}>
                  Add to cart
                </Button>
                <Link href="/cart"
                  className="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100">
                  Go to cart
                </Link>
              </div>
              {added && (
                <p role="status" className="mt-3 text-sm text-emerald-800">
                  Added {units} to your cart. Stock is only guaranteed once checkout has committed.
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
            {store?.store_type === "retail" && (
              <div className="border-t border-neutral-200 px-4 py-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">
                    Collect from / check stock at
                  </span>
                  <select className={selectClass} value={store?.store_id ?? ""}
                    onChange={(event) => setStoreId(Number(event.target.value))} aria-label="Choose a store">
                    {stock.filter((row) => row.store_type === "retail").map((row) => (
                      <option key={row.store_id} value={row.store_id}>{row.store_name}</option>
                    ))}
                  </select>
                </label>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
