"use client";

import { useAuth } from "@clerk/nextjs";
import { useLayoutEffect } from "react";

import { setTokenGetter } from "@/lib/api/client";

/** Gives the API client Clerk's getToken, so each request carries the signed-in user's session token.
 *  A layout effect runs before every component's ordinary effects, so even the first loads have it. */
export function ApiAuth() {
  const { getToken } = useAuth();
  useLayoutEffect(() => setTokenGetter(getToken), [getToken]);
  return null;
}
