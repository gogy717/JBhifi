"use client";

import { useAdminSession } from "@/components/admin/session";
import { Badge, ErrorBox, selectClass } from "@/components/ui";

/**
 * The demo staff sign-in. It is deliberately labelled as a demo: the API's permissions are real, but
 * choosing an identity here is a stand-in for a login.
 */
export function StaffSessionBar() {
  const { staff, staffLoading, chosenStaffId, setStaffId, session, signedIn, error, reload } = useAdminSession();
  const groups = [...new Set(staff.map((s) => s.store_name ?? "Support (no store)"))];

  return (
    <div className="mb-5 rounded-xl border border-neutral-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <span className="text-neutral-500">Signed in as</span>
        {staffLoading
          ? <span className="text-neutral-400">Loading staff…</span>
          : (
            <select className={`${selectClass} max-w-xs`}
              value={staff.some((s) => s.staff_id === chosenStaffId) ? chosenStaffId : ""}
              onChange={(event) => setStaffId(event.target.value ? Number(event.target.value) : undefined)}
              aria-label="Demo staff sign-in">
              <option value="">Choose a staff member…</option>
              {groups.map((group) => (
                <optgroup key={group} label={group}>
                  {staff.filter((s) => (s.store_name ?? "Support (no store)") === group).map((s) => (
                    <option key={s.staff_id} value={s.staff_id}>
                      {s.full_name}{s.is_manager ? " (manager)" : ""}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          )}
        {signedIn && session && (
          <>
            <Badge tone="green">{session.display_name}</Badge>
            <span className="text-neutral-600">
              {session.store_name ?? "Support (no store)"}
            </span>
            {!session.runs_store && !session.staff_type?.includes("support") && (
              <span className="text-xs text-neutral-500">
                Store staff: stock and fulfilment for your store; the catalogue needs a manager.
              </span>
            )}
            <button type="button" onClick={reload} className="text-xs text-neutral-500 underline hover:text-neutral-800">
              refresh
            </button>
          </>
        )}
        {!signedIn && !staffLoading && (
          <span className="text-amber-700">
            Not signed in — the API will refuse every change until you pick someone.
          </span>
        )}
      </div>
      {error && <ErrorBox error={error} className="mt-3" />}
    </div>
  );
}
