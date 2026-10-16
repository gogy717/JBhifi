"use client";

import Link from "next/link";

import { ProductImage } from "@/components/product-image";
import { useShop } from "@/components/shop/context";
import { Badge, Button, Dot, LOW_STOCK } from "@/components/ui";
import type { ProductSummary } from "@/lib/api/client";
import { useCart } from "@/lib/cart-context";
import { saving } from "@/lib/deals";
import { money, percentOff } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";

/** One catalogue result: the current price, whether it is on sale, and the stock at "My store". */
export function ProductCard({ product, storeName, onAdded }: {
  product: ProductSummary;
  storeName?: string;
  onAdded?: (name: string) => void;
}) {
  const { addItem } = useCart();
  const { categories } = useShop();
  const href = `${SHOP_PAGES.catalogue.href}/${product.product_id}`;

  return (
    <article className="flex flex-col gap-3.5 rounded-card border border-line bg-white p-3.5">
      <ProductImage categoryId={product.category_id} categories={categories} brand={product.brand}>
        {product.on_sale && (
          <span className="absolute left-2.5 top-2.5"><Badge tone="sale">
            <span className="uppercase">{percentOff(product.base_price, product.current_price)}</span>
          </Badge></span>
        )}
        {!product.is_active && <span className="absolute right-2.5 top-2.5"><Badge>retired</Badge></span>}
      </ProductImage>
      <div className="flex flex-1 flex-col gap-1 px-1">
        <span className="text-xs font-bold uppercase tracking-[0.08em] text-muted">{product.brand}</span>
        <Link href={href} className="line-clamp-2 text-base font-semibold leading-snug hover:text-brand-strong">
          {product.name}
        </Link>
      </div>
      <div className="flex flex-col gap-1.5 px-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-display text-2xl font-extrabold tracking-[-0.02em]">{money(product.current_price)}</span>
          {product.on_sale && (
            <s className="text-sm text-muted"><span className="sr-only">was </span>{money(product.base_price)}</s>
          )}
        </div>
        {product.on_sale && (
          <span className="text-sm font-bold text-brand-strong">
            Save {money(saving({ base_price: product.base_price, sale_price: product.current_price }))}
          </span>
        )}
        <StoreLine quantity={product.store_quantity} storeName={storeName} className="" />
      </div>
      <div className="flex gap-2">
        {/* Stock at My store is information, not a limit: a delivery can ship from another store, and
            checkout takes the stock in the database. Only a retired product can't be bought (BR07). */}
        <Button tone="primary" className="flex-1" disabled={!product.is_active}
          onClick={() => {
            addItem(product.product_id);
            onAdded?.(product.name);
          }}>
          Add to cart
        </Button>
        <Link href={href}
          className="inline-flex h-11 items-center rounded-full border border-line px-4 text-[15px] font-semibold
            text-ink hover:bg-sand">
          Details
        </Link>
      </div>
    </article>
  );
}

/** Stock at one store, in words: plenty (green dot), LOW_STOCK or fewer (amber), none (grey dot, "Out of stock" in
 *  bold). Unknown (no store chosen yet) is not the same as none. */
export function StoreLine({ quantity, storeName, className = "mt-2" }: {
  quantity?: number | null;
  storeName?: string;
  className?: string;
}) {
  if (quantity === undefined || quantity === null || !storeName) {
    return <div className={`text-[13px] text-faint ${className}`}>Choose a store to see its stock</div>;
  }
  const [dot, text, words] = quantity === 0 ? ["bg-muted", "font-semibold text-ink", `Out of stock at ${storeName}`]
    : quantity <= LOW_STOCK ? ["bg-warn", "font-semibold text-warn-ink", `Only ${quantity} left at ${storeName}`]
    : ["bg-ok", "text-muted", `${quantity} in stock at ${storeName}`];
  return (
    <div className={`flex items-center gap-1.5 text-[13px] ${className}`}>
      <Dot className={dot} /> <span className={text}>{words}</span>
    </div>
  );
}
