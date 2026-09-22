"use client";

import { ClerkProvider } from "@clerk/clerk-react";

import { ClerkTokenBridge } from "./ClerkTokenBridge";

/**
 * Clerk, client-side only.
 *
 * The plain React SDK rather than @clerk/nextjs because the site is a static
 * export: the Next.js SDK registers Server Actions, which a static export
 * cannot serve. Nothing is lost - the Worker verifies every token server-side,
 * so the browser was never the thing deciding what an account may see.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

  if (!publishableKey) {
    // A missing key would otherwise surface as a blank page with a console
    // error, which is a miserable thing to debug on a fresh deployment.
    return (
      <>
        <div className="wrap" style={{ paddingTop: 24 }}>
          <div className="notice is-error" role="status">
            Sign-in is not configured: NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is unset in this
            build. The marketing pages work; the dashboard will not.
          </div>
        </div>
        {children}
      </>
    );
  }

  // The token bridge lives here, not on the dashboard, so that every page -
  // pricing especially - can make an authenticated call. Mounted once at the
  // root it also can't fight a second copy for the getter on navigation.
  return (
    <ClerkProvider publishableKey={publishableKey}>
      <ClerkTokenBridge />
      {children}
    </ClerkProvider>
  );
}
