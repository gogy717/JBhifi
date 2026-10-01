"use client";

import { useAuth } from "@clerk/nextjs";
import { useLayoutEffect } from "react";

import { setTokenGetter } from "@/lib/api/client";

/** Gives the API client Clerk's getToken, so each request carries the signed-in user's session token.
 *  A layout effect runs before every component's ordinary effects, so even the first loads have it.
 *
 *  Only a signed-in session has a token to send. Until Clerk has loaded — or if its script never loads
 *  (no network at the venue, a blocked domain) — and for guests, requests go without one: Clerk's own
 *  getToken would wait for Clerk to finish loading, and public pages must never wait on that. */
export function ApiAuth() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  useLayoutEffect(
    () => setTokenGetter(isLoaded && isSignedIn ? getToken : async () => null),
    [getToken, isLoaded, isSignedIn],
  );
  return null;
}
