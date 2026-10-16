import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import localFont from "next/font/local";

import { ApiAuth } from "@/components/api-auth";

import "./globals.css";

// The two typefaces, each one variable Latin font file under the SIL Open Font License (fonts/*-OFL.txt).
// globals.css uses Sora (600–800) for the wordmark, headings and prices through --font-sora, and Figtree
// (400–700) for everything else through --font-figtree.
const sora = localFont({ src: "./fonts/Sora-latin.woff2", weight: "600 800", variable: "--font-sora" });
const figtree = localFont({ src: "./fonts/Figtree-latin.woff2", weight: "400 700", variable: "--font-figtree" });

// No `title` here: every page renders its own <title> (React 19), and a metadata title would come first in
// <head> and win on every page.
export const metadata: Metadata = {
  description: "COMP9120 prototype: a storefront and a store admin on the TechLight database",
};

// The storefront (app/(shop)) and the store admin (app/admin) each bring their own layout. Clerk's provider
// sits inside <body> (Clerk's rule for the App Router); sign-in and sign-up have their own pages.
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`h-full antialiased ${sora.variable} ${figtree.variable}`}>
      <body className="min-h-full bg-canvas text-ink">
        <ClerkProvider signInUrl="/sign-in" signUpUrl="/sign-up"><ApiAuth />{children}</ClerkProvider>
      </body>
    </html>
  );
}
