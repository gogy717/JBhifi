import Link from "next/link";
import type { ReactNode } from "react";

import { LogoMark, Wordmark } from "@/components/brand";

/** Clerk's sign-in and sign-up boxes in the storefront's look. Clerk computes its shades from these colours, so
 *  they are the theme tokens' values (app/globals.css), not CSS variables. The shapes are style objects, not
 *  classes: Clerk's own styles are outside Tailwind's layers, so they would win over a utility class. */
export const clerkAppearance = {
  variables: {
    colorPrimary: "#1A1A1A",            // ink: the primary button
    colorForeground: "#1A1A1A",
    colorMutedForeground: "#5C5650",    // muted
    colorRing: "#E64626",               // brand: the focus ring
    fontFamily: "inherit",
  },
  elements: {
    cardBox: { borderRadius: "20px", border: "1px solid #ECE6E0", boxShadow: "none" },
    formButtonPrimary: { height: "44px", borderRadius: "9999px", fontSize: "15px", fontWeight: 700 },
    formFieldInput: { height: "44px", borderRadius: "9999px", paddingInline: "16px", fontSize: "15px" },
    socialButtonsBlockButton: { height: "44px", borderRadius: "9999px" },
    footerActionLink: { color: "#C8381A", fontWeight: 700 },
  },
};

/** The sign-in and sign-up pages: the brand panel beside Clerk's box on a wide screen, the box alone on a phone. */
export function AuthFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-[1280px] flex-col gap-8 px-4 py-8 sm:px-6 lg:py-12">
      <Link href="/" className="flex items-center gap-2.5 self-start text-ink" aria-label="TechLight home">
        <LogoMark className="h-10 w-10" />
        <Wordmark className="text-[26px]" />
      </Link>
      <div className="grid flex-1 grid-cols-1 items-center gap-10 lg:grid-cols-[minmax(0,1fr)_auto]">
        <section className="hidden flex-col gap-6 self-stretch rounded-hero bg-brand p-12 text-white lg:flex lg:justify-center">
          <span className="self-start rounded-full bg-ink px-3.5 py-2 text-[13px] font-bold tracking-[0.06em] uppercase">
            Your TechLight account
          </span>
          {/* An h2: Clerk's box carries the page's h1. White on brand is 4.0:1, under 4.5:1, so all text here is
              large text: at least 24px, or bold and at least 18.66px (the list is 19px bold). */}
          <h2 className="font-display text-[52px] leading-[1.02] font-extrabold tracking-[-0.035em]">{title}</h2>
          <ul className="max-w-md space-y-3 text-[19px] leading-snug font-bold">
            <li>Follow your orders, from paid to ready to collect.</li>
            <li>Click &amp; Collect from any TechLight store.</li>
            <li>Return items within 30 days, at the price you paid.</li>
          </ul>
        </section>
        <div className="flex justify-center">{children}</div>
      </div>
      <p className="text-[13px] text-muted">TechLight is a fictional store — a COMP9120 prototype. Payments are simulated.</p>
    </main>
  );
}
