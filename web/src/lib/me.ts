import { useAuth } from "@clerk/nextjs";

import { type ApiError, api, call, type Me } from "@/lib/api/client";
import { useLoad } from "@/lib/use-load";

export type MeState =
  | { status: "loading" }
  | { status: "guest" }
  | { status: "signed-in"; me: Me }
  | { status: "error"; error: ApiError; retry: () => void };

/** Who is signed in, as the API sees them: waits for Clerk to load, then asks GET /me (which links a new
 *  sign-in to a customer or staff row the first time). */
export function useMe(): MeState {
  const { isLoaded, isSignedIn, userId } = useAuth();
  const me = useLoad(`me:${isLoaded ? (userId ?? "guest") : "loading"}`, () =>
    isLoaded && isSignedIn ? call(api.GET("/api/v1/me")) : Promise.resolve(undefined));
  if (!isLoaded || me.loading) return { status: "loading" };
  if (!isSignedIn) return { status: "guest" };
  if (me.error) return { status: "error", error: me.error, retry: me.reload };
  return me.data ? { status: "signed-in", me: me.data } : { status: "loading" };
}
