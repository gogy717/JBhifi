"use client";

import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { createContext, type ReactNode, useContext } from "react";

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

/** Store managers and support staff maintain the catalogue and promotions (spec §4.5). */
export function canEditCatalogue(me: Me): boolean {
  return me.staff_type === "support" || me.runs_store;
}

/** The admin is for staff. proxy.ts already sent signed-out visitors to sign-in; this checks who they are.
 *  It only decides what to show: the API refuses whatever a caller may not do, whatever the screen shows. */
export function StaffGate({ children }: { children: ReactNode }) {
  const session = useMe();
  if (session.status === "loading") {
    return <p className="p-8 text-sm text-neutral-500">Checking who you are…</p>;
  }
  if (session.status === "error") {
    return (
      <div className="space-y-3 p-8">
        <ErrorBox error={session.error} />
        <Button onClick={session.retry}>Try again</Button>
      </div>
    );
  }
  if (session.status === "guest" || session.me.kind !== "staff") {
    return (
      <div className="mx-auto max-w-md space-y-4 p-8 text-sm">
        <title>Staff only · JB Admin</title>
        <h1 className="text-xl font-bold">Staff only</h1>
        <p className="text-neutral-600">
          The store admin is for staff. Sign in with a staff account, or go back to the storefront.
        </p>
        <div className="flex items-center gap-3">
          <UserButton />
          <Link href="/" className="font-medium hover:underline">← Storefront</Link>
        </div>
      </div>
    );
  }
  return <StaffContext value={session.me}>{children}</StaffContext>;
}
