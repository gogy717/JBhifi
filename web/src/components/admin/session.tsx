"use client";

import { createContext, type ReactNode, useContext, useSyncExternalStore } from "react";

import { type ApiError, api, call, type Staff } from "@/lib/api/client";
import { useStoredId } from "@/lib/browser-storage";
import { ensureSession, type Session } from "@/lib/session";
import { useLoad } from "@/lib/use-load";

/**
 * The admin's demo identity. The picker's choice lives in this browser; the API trusts only the signed
 * session cookie, so the admin surface declares who *it* acts as (a staff member) whenever it loads.
 */

type AdminSessionValue = {
  staff: Staff[];
  staffLoading: boolean;
  chosenStaffId?: number;
  setStaffId: (id: number | undefined) => void;
  /** The verified session, when it is a staff member. */
  session?: Session;
  signedIn: boolean;
  /** The staff directory failed to load: the picker has nothing to offer. */
  staffError?: ApiError;
  /** The staff directory or the session failed to load. */
  error?: ApiError;
  reload: () => void;
};

const AdminSessionContext = createContext<AdminSessionValue | null>(null);

/**
 * False for the server render and the first client render, true afterwards — see `shop/context.tsx`.
 * The admin declares who *it* acts as too, so a refresh must not sign the chosen staff member out
 * before the browser has had a chance to say who that is.
 */
const neverChanges = () => () => {};

function useHydrated(): boolean {
  return useSyncExternalStore(neverChanges, () => true, () => false);
}

export function useAdminSession(): AdminSessionValue {
  const value = useContext(AdminSessionContext);
  if (!value) throw new Error("useAdminSession() must be used inside <AdminSessionProvider>");
  return value;
}

export function AdminSessionProvider({ children }: { children: ReactNode }) {
  const [chosenStaffId, setStaffId] = useStoredId("jb.admin.staffId");
  const hydrated = useHydrated();
  const staff = useLoad("admin-staff", () => call(api.GET("/api/v1/staff")));
  const session = useLoad(
    hydrated ? `admin-session:${chosenStaffId ?? "guest"}` : "admin-session:hydrating",
    () => (hydrated ? ensureSession("staff", chosenStaffId) : Promise.resolve(null)));

  const signedIn = session.data?.kind === "staff";
  const value: AdminSessionValue = {
    staff: staff.data ?? [],
    staffLoading: staff.loading,
    chosenStaffId,
    setStaffId,
    session: signedIn ? session.data ?? undefined : undefined,
    signedIn,
    staffError: staff.error,
    error: staff.error ?? session.error,
    reload: () => {
      staff.reload();
      session.reload();
    },
  };
  return <AdminSessionContext value={value}>{children}</AdminSessionContext>;
}
