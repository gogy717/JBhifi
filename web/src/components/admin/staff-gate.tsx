"use client";

import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { createContext, type ReactNode, useContext } from "react";

import { LogoMark, Wordmark } from "@/components/brand";
import { Button, ErrorBox } from "@/components/ui";
import type { Me } from "@/lib/api/client";
import { useMe } from "@/lib/me";

const StaffContext = createContext<Me | null>(null);

/** The signed-in staff member. Only inside <StaffGate>. */
export function useStaff(): Me {
  const me = useContext(StaffContext);
  if (!me) throw new Error("useStaff() must be used inside <StaffGate>");
  return me;
}

/** Provides the signed-in staff member to the admin's pages: StaffGate, once it knows who is signed in, and tests. */
export function StaffProvider({ me, children }: { me: Me; children: ReactNode }) {
  return <StaffContext value={me}>{children}</StaffContext>;
}

/** Store managers and support staff maintain the catalogue and promotions (spec §4.5). */
export function canEditCatalogue(me: Me): boolean {
  return me.staff_type === "support" || me.runs_store;
}

/** The admin is for staff. proxy.ts already sent signed-out visitors to sign-in; this checks who they are.
 *  It only decides what to show: the API refuses whatever a caller may not do, whatever the screen shows. */
export function StaffGate({ children }: { children: ReactNode }) {
  const session = useMe();
  if (session.status === "loading") {
    return <GatePanel><p className="text-sm text-muted">Checking who you are…</p></GatePanel>;
  }
  if (session.status === "error") {
    return (
      <GatePanel>
        <ErrorBox error={session.error} />
        <Button onClick={session.retry}>Try again</Button>
      </GatePanel>
    );
  }
  if (session.status === "guest" || session.me.kind !== "staff") {
    return (
      <GatePanel>
        <title>Staff only · TechLight Admin</title>
        <h1 className="text-2xl font-bold tracking-[-0.02em]">Staff only</h1>
        <p className="text-[15px] text-muted">
          The store admin is for staff. Sign in with a staff account, or go back to the storefront.
        </p>
        <div className="flex items-center gap-3">
          <UserButton />
          <Link href="/" className="text-[15px] font-semibold text-brand-strong hover:underline">← Storefront</Link>
        </div>
      </GatePanel>
    );
  }
  return <StaffProvider me={session.me}>{children}</StaffProvider>;
}

/** Before the admin opens: the logo and one card on the canvas. */
function GatePanel({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-start justify-center px-4 pt-[12vh]">
      <div className="w-full max-w-md space-y-4 rounded-card border border-line bg-white p-6">
        <div className="flex items-center gap-2.5">
          <LogoMark className="h-9 w-9" />
          <span>
            <Wordmark className="text-xl" />
            <span className="mt-1 block text-[11px] font-bold uppercase tracking-[0.08em] text-brand-strong">
              Store admin
            </span>
          </span>
        </div>
        {children}
      </div>
    </div>
  );
}
