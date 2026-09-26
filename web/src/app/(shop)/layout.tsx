import Link from "next/link";
import type { ReactNode } from "react";

import { ShopProvider } from "@/components/shop/context";
import { ShopHeader } from "@/components/shop/header";
import { CartProvider } from "@/lib/cart-context";

export default function ShopLayout({ children }: { children: ReactNode }) {
  return (
    <ShopProvider>
      <CartProvider>
        <div className="flex min-h-screen flex-col">
          <ShopHeader />
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:py-8">{children}</main>
          <footer className="border-t border-neutral-200 bg-white">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-4 text-xs
              text-neutral-500">
              <span>COMP9120 prototype modelled on JB Hi-Fi — not the real store. Payments are simulated.</span>
              <Link href="/admin" className="font-medium text-neutral-700 hover:underline">Staff: store admin →</Link>
            </div>
          </footer>
        </div>
      </CartProvider>
    </ShopProvider>
  );
}
