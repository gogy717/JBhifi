"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useShop } from "@/components/shop/context";
import {
  Callout, Crumbs, DetailRow, Eyebrow, pillLink, Price, SectionTitle, Skeleton,
} from "@/components/shop/page-parts";
import { StoreLine } from "@/components/shop/product-card";
import { Badge, Button, Card, Empty, ErrorBox, inputClass, StockBadge } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { fromCents, MAX_QUANTITY, toCents } from "@/lib/cart";
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
        <Link href={SHOP_PAGES.catalogue.href} className="font-bold text-brand-strong underline">Back to the shop</Link>.
      </Empty></Card>
    );
  }

  const units = Math.min(Math.max(Math.trunc(Number(quantity)) || 1, 1), MAX_QUANTITY);
  // My store first (it is the one the stock line quotes), then the rest in store order.
  const stock = [...(detail?.stock ?? [])].sort((a, b) =>
    Number(b.store_id === store?.store_id) - Number(a.store_id === store?.store_id));
  const mine = stock.find((row) => row.store_id === store?.store_id);

  return (
    <div className="space-y-8">
      <title>{`${detail?.name ?? "Product"} · TechLight`}</title>
      <Crumbs trail={[["Home", "/"], ["Shop all products", SHOP_PAGES.catalogue.href], [detail?.name ?? "…"]]} />

      {product.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={product.error} />
          <Button onClick={product.reload}>Try again</Button>
        </div>
      )}
      {!product.error && !detail && <Skeleton className="h-[420px]" />}

      {detail && (
        <>
          <section className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-10">
            {/* The product image block. The database has no product photos: the tile shows the brand. */}
            <div className="relative flex min-h-[280px] flex-col items-center justify-center gap-3 rounded-panel bg-sand
              p-8 sm:min-h-[420px]">
              {detail.on_sale && (
                <span className="absolute top-5 left-5 rounded-full bg-brand-strong px-3.5 py-1.5 text-[15px] font-extrabold
                  text-white uppercase">
                  {percentOff(detail.base_price, detail.current_price)}
                </span>
              )}
              <span className="font-display text-[28px] font-bold tracking-[-0.02em] text-muted">{detail.brand}</span>
              <span className="text-[13px] font-semibold tracking-[0.08em] text-faint uppercase">{detail.category}</span>
            </div>

            <div className="flex flex-col gap-5">
              <div className="space-y-2">
                <Eyebrow>{detail.brand} · {detail.category}</Eyebrow>
                <h1 className="font-display text-[28px] leading-[1.15] font-bold tracking-[-0.025em] sm:text-[34px]">
                  {detail.name}
                </h1>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[13px] text-muted">{detail.sku}</span>
                  {!detail.is_active && <Badge>retired</Badge>}
                </div>
              </div>

              <div className="space-y-1">
                <Price size="xl" value={detail.current_price} was={detail.on_sale ? detail.base_price : undefined} />
                {detail.on_sale && (
                  <p className="text-[15px] font-bold text-brand-strong">
                    Save {money(fromCents(toCents(detail.base_price) - toCents(detail.current_price)))}
                  </p>
                )}
              </div>

              {mine && <StoreLine quantity={mine.quantity} storeName={store?.name} />}

              {!detail.is_active && (
                <Callout tone="warn">
                  This product has been retired, so it can&apos;t be bought (BR07). Its record is kept because past
                  orders point to it.
                </Callout>
              )}

              <div className="flex flex-wrap items-end gap-3 rounded-card border border-line bg-white p-4">
                <label className="block w-24">
                  <span className="mb-1.5 block text-[12px] font-bold tracking-[0.08em] text-muted uppercase">Quantity</span>
                  <input className={inputClass} type="number" min={1} max={MAX_QUANTITY} step={1} value={quantity}
                    onChange={(event) => setQuantity(event.target.value)} />
                </label>
                {/* Enabled even when My store has none: a delivery can ship from another store. */}
                <Button tone="primary" className="min-w-40 flex-1" disabled={!detail.is_active}
                  onClick={() => {
                    addItem(detail.product_id, units);
                    setAdded(units);
                  }}>
                  Add to cart
                </Button>
                <Link href={SHOP_PAGES.cart.href} className={pillLink("outline")}>Go to cart</Link>
              </div>
              {added !== undefined && (
                <Callout tone="ok" role="status">
                  Added {added} to your cart. Stock is only taken when checkout commits.
                </Callout>
              )}
            </div>
          </section>

          <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-10">
            <section>
              <SectionTitle>Specifications</SectionTitle>
              <Card>
                {detail.specs.length === 0
                  ? <Empty>No specifications recorded for this product.</Empty>
                  : (
                    <dl className="divide-y divide-line">
                      {detail.specs.map((spec) => (
                        <DetailRow key={spec.spec_name} label={spec.spec_name}>{spec.spec_value}</DetailRow>
                      ))}
                    </dl>
                  )}
              </Card>
            </section>

            <section>
              <SectionTitle aside={<span className="text-[13px] text-muted">R3</span>}>Where it is in stock</SectionTitle>
              <Card>
                <ul className="divide-y divide-line">
                  {stock.map((row) => {
                    const isMine = row.store_id === store?.store_id;
                    return (
                      <li key={row.store_id}
                        className={`flex items-center justify-between gap-3 px-5 py-3 ${isMine ? "bg-brand-soft" : ""}`}>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2 font-semibold">
                            {row.store_name}
                            {row.store_type === "warehouse" && <Badge tone="blue">warehouse</Badge>}
                            {isMine && <Badge tone="sale">your store</Badge>}
                          </div>
                          <div className="text-[13px] text-muted">{row.state}</div>
                        </div>
                        <StockBadge quantity={row.quantity} />
                      </li>
                    );
                  })}
                </ul>
                <p className="border-t border-line px-5 py-3 text-[13px] text-muted">
                  To collect from another store, change “My store” at the top of the page.
                </p>
              </Card>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
