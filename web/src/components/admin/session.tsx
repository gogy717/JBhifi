"use client";

import { createContext, type ReactNode, useContext } from "react";

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
  /** The staff directory or the session failed to load. */
  error?: ApiError;
  reload: () => void;
};

const AdminSessionContext = createContext<AdminSessionValue | null>(null);

export function useAdminSession(): AdminSessionValue {
  const value = useContext(AdminSessionContext);
  if (!value) throw new Error("useAdminSession() must be used inside <AdminSessionProvider>");
  return value;
}

export function AdminSessionProvider({ children }: { children: ReactNode }) {
  const [chosenStaffId, setStaffId] = useStoredId("jb.admin.staffId");
  const staff = useLoad("admin-staff", () => call(api.GET("/api/v1/staff")));
  const session = useLoad(`admin-session:${chosenStaffId ?? "guest"}`,
    () => ensureSession("staff", chosenStaffId));

  const signedIn = session.data?.kind === "staff";
  const value: AdminSessionValue = {
    staff: staff.data ?? [],
    staffLoading: staff.loading,
    chosenStaffId,
    setStaffId,
    session: signedIn ? session.data ?? undefined : undefined,
    signedIn,
    error: staff.error ?? session.error,
    reload: () => {
      staff.reload();
      session.reload();
    },
  };
  return <AdminSessionContext value={value}>{children}</AdminSessionContext>;
}
