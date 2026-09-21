"use client";

import { useAuth } from "@clerk/clerk-react";
import { useEffect } from "react";

import { setTokenGetter } from "@/lib/api";

/**
 * Hands Clerk's token getter to the API client.
 *
 * Clerk exposes it only through a hook, and the API client is called from
 * plain functions. Rather than thread a token through every call site, this
 * registers the getter once and clears it on unmount so a signed-out session
 * cannot leave a stale closure behind.
 */
export function ClerkTokenBridge() {
  const { getToken } = useAuth();

  useEffect(() => {
    setTokenGetter(() => getToken());
    return () => setTokenGetter(null);
  }, [getToken]);

  return null;
}
