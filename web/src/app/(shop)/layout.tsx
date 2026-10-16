import type { ReactNode } from "react";

import { ShopProvider } from "@/components/shop/context";
import { ShopFooter } from "@/components/shop/footer";
import { ShopHeader } from "@/components/shop/header";
import { CartProvider } from "@/lib/cart-context";

// Every storefront page: the header, the page on the warm canvas (1280px wide, 24px gutters), the footer.
export default function ShopLayout({ children }: { children: ReactNode }) {
  return (
    <ShopProvider>
      <CartProvider>
        <div className="flex min-h-screen flex-col bg-canvas">
          <ShopHeader />
          <main className="mx-auto w-full max-w-[1280px] flex-1 px-6 pb-[72px] pt-8">{children}</main>
          <ShopFooter />
        </div>
      </CartProvider>
    </ShopProvider>
  );
}
