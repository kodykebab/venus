"use client";

import Link from "next/link";
import { SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/clerk-react";

/**
 * The only part of the header that needs JavaScript.
 *
 * Signed out, the dominant action is connecting GitHub - that is the whole
 * product. Signed in, it is the dashboard.
 */
export function AuthNav() {
  return (
    <>
      <SignedOut>
        <SignInButton mode="modal">
          <button className="btn secondary small" type="button">
            Sign in
          </button>
        </SignInButton>
        <Link className="btn small" href="/dashboard">
          Connect GitHub
        </Link>
      </SignedOut>
      <SignedIn>
        <Link href="/dashboard">Dashboard</Link>
        <UserButton afterSignOutUrl="/" />
      </SignedIn>
    </>
  );
}
