"use client";

import { SignInButton, SignUpButton } from "@clerk/nextjs";
import Link from "next/link";
import type { ReactNode } from "react";

import { useShop } from "@/components/shop/context";
import { pillLink } from "@/components/shop/page-parts";
import { Button, Card, ErrorBox } from "@/components/ui";
import type { ApiError, CustomerDetail, Me } from "@/lib/api/client";

// Gates only decide what a page shows. The API checks every request itself (app/auth.py), whatever is on screen.

/** Anyone signed in. The page then asks the API, which decides what this person may see (an order). */
export function SignedInGate({ what, children }: { what: string; children: (me: Me) => ReactNode }) {
  const { session } = useShop();
  if (session.status === "loading") return <Checking />;
  if (session.status === "error") return <Failed error={session.error} retry={session.retry} />;
  if (session.status === "guest") return <SignInPrompt what={what} />;
  return children(session.me);
}

/** A signed-in customer, with their record (and addresses): checkout, My orders, My account. */
export function CustomerGate({ what, children }: {
  what: string;
  children: (customer: CustomerDetail) => ReactNode;
}) {
  const { session, customer, customerLoading, customerError, reloadCustomer } = useShop();
  if (session.status === "error") return <Failed error={session.error} retry={session.retry} />;
  if (session.status === "guest") return <SignInPrompt what={what} />;
  if (session.status === "signed-in" && session.me.kind === "staff") {
    return (
      <Card>
        <p className="px-5 py-10 text-center text-[15px] text-muted">
          You&apos;re signed in as staff, and this page is for customer accounts.{" "}
          <Link href="/admin" className="font-bold text-brand-strong underline">Go to the store admin →</Link>
        </p>
      </Card>
    );
  }
  if (customerError) return <Failed error={customerError} retry={reloadCustomer} />;
  if (customerLoading || !customer) return <Checking />;
  return children(customer);
}

function Checking() {
  return <p className="text-[15px] text-muted">Checking who is signed in…</p>;
}

function Failed({ error, retry }: { error: ApiError; retry: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <ErrorBox error={error} />
      <Button onClick={retry}>Try again</Button>
    </div>
  );
}

/** Clerk's sign-in opens in a modal, so the visitor stays on this page, and the cart (kept in this browser, not
 *  in the account) is still there afterwards. */
function SignInPrompt({ what }: { what: string }) {
  return (
    <section className="flex flex-col items-start gap-4 rounded-panel bg-brand-soft p-8 sm:p-10">
      <h2 className="font-display text-[24px] font-bold tracking-[-0.02em]">Sign in to {what}</h2>
      <p className="max-w-xl text-[16px] text-muted">Your cart stays as it is.</p>
      <div className="flex flex-wrap gap-2.5">
        <SignInButton mode="modal">
          <button type="button" className={pillLink("ink")}>Sign in</button>
        </SignInButton>
        <SignUpButton mode="modal">
          <button type="button" className={pillLink("outline")}>Create account</button>
        </SignUpButton>
      </div>
    </section>
  );
}
