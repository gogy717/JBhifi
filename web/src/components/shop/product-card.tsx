"use client";

import Link from "next/link";

import { Badge, Button, LOW_STOCK } from "@/components/ui";
import type { ProductSummary } from "@/lib/api/client";
import { money, percentOff } from "@/lib/format";
import { useCart } from "@/lib/cart-context";

/** One catalogue result: the current price, whether it is on sale, and stock at the chosen store. */
export function ProductCard({ product, storeName, onAdded }: {
  product: ProductSummary;
  storeName?: string;
  onAdded?: (name: string) => void;
}) {
  const { addItem } = useCart();
  const stock = product.store_quantity;
  const soldOut = stock !== undefined && stock !== null && stock <= 0;

  return (
    <article className="flex flex-col rounded-xl bg-white p-4 shadow-sm ring-1 ring-neutral-200">
      <div className="flex items-start justify-between gap-2">
        {product.on_sale
          ? <Badge tone="sale">{percentOff(product.base_price, product.current_price)}</Badge>
          : <span />}
        {!product.is_active && <Badge>retired</Badge>}
      </div>
      <div className="mt-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {product.brand}
      </div>
      <Link href={`/products/${product.product_id}`}
        className="line-clamp-2 font-medium text-neutral-900 hover:underline">
        {product.name}
      </Link>
      <div className="mt-auto pt-3">
        <span className="text-2xl font-bold">{money(product.current_price)}</span>
        {product.on_sale && (
          <s className="ml-2 text-sm text-neutral-500">
            <span className="sr-only">was </span>{money(product.base_price)}
          </s>
        )}
      </div>
      <StoreLine quantity={stock} storeName={storeName} />
      <div className="mt-3 flex gap-2">
        <Button tone="primary" disabled={soldOut}
          onClick={() => { addItem(product.product_id, 1); onAdded?.(product.name); }}>
          {soldOut ? "Out of stock" : "Add to cart"}
        </Button>
        <Link href={`/products/${product.product_id}`}
          className="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100">
          Details
        </Link>
      </div>
    </article>
  );
}

/** Stock is only shown when a store was asked about; unknown is not the same as zero. */
export function StoreLine({ quantity, storeName }: { quantity?: number | null; storeName?: string }) {
  if (quantity === undefined || quantity === null || !storeName) {
    return <div className="mt-2 text-xs text-neutral-400">Choose a store to see its stock</div>;
  }
  const [dot, text] = quantity === 0 ? ["bg-red-500", `Out of stock at ${storeName}`]
    : quantity <= LOW_STOCK ? ["bg-amber-500", `Only ${quantity} left at ${storeName}`]
    : ["bg-emerald-500", `${quantity} in stock at ${storeName}`];
  return (
    <div className="mt-2 flex items-center gap-2 text-xs text-neutral-600">
      <span className={`h-2 w-2 rounded-full ${dot}`} /> {text}
    </div>
  );
}
