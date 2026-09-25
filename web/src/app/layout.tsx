import type { Metadata } from "next";

import "./globals.css";

// No `title` here: every page renders its own <title> (React 19), and a metadata title would come first in
// <head> and win on every page.
export const metadata: Metadata = {
  description: "COMP9120 prototype: a storefront and a store admin on the JB Hi-Fi database",
};

// The storefront (app/(shop)) and the store admin (app/admin) each bring their own layout.
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full bg-neutral-50 text-neutral-900">{children}</body>
    </html>
  );
}
