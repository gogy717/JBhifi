import { useAuth, useClerk } from "@clerk/nextjs";

import { ApiError, api, call, type Me } from "@/lib/api/client";
import { useLoad } from "@/lib/use-load";

export type MeState =
  | { status: "loading" }
  | { status: "guest" }
  | { status: "signed-in"; me: Me }
  | { status: "error"; error: ApiError; retry: () => void };

const SIGN_IN_UNAVAILABLE = new ApiError(0, "sign_in_unavailable",
  "Sign-in couldn't load (no connection to Clerk?). You can still browse as a guest.");

/** Who is signed in, as the API sees them: waits for Clerk to load, then asks GET /me (which links a new
 *  sign-in to a customer or staff row the first time). If Clerk's script fails to load, that is an error
 *  to show — not a page that says "loading" forever. */
export function useMe(): MeState {
  const { status: clerkStatus } = useClerk();
  const { isLoaded, isSignedIn, userId } = useAuth();
  const me = useLoad(`me:${isLoaded ? (userId ?? "guest") : "loading"}`, () =>
    isLoaded && isSignedIn ? call(api.GET("/api/v1/me")) : Promise.resolve(undefined));
  if (clerkStatus === "error") return { status: "error", error: SIGN_IN_UNAVAILABLE, retry: () => window.location.reload() };
  if (!isLoaded || me.loading) return { status: "loading" };
  if (!isSignedIn) return { status: "guest" };
  if (me.error) return { status: "error", error: me.error, retry: me.reload };
  return me.data ? { status: "signed-in", me: me.data } : { status: "loading" };
}
