"use client";

import Link from "next/link";
import { SignedIn, SignedOut, SignInButton } from "@clerk/clerk-react";

import { Dashboard } from "@/components/Dashboard";
import { SiteHeader } from "@/components/SiteHeader";
import { EmptyState, Section } from "@/components/ui";

/**
 * Signed out this is a sign-in prompt, not a redirect: a redirect loses the
 * page someone was sent to, and a link from a teammate should still explain
 * what this is.
 */
export default function DashboardPage() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="wrap">
        <SignedOut>
          <Section eyebrow="Dashboard" first>
            <EmptyState
              heading="Sign in to see your scans"
              body="Your repositories, scan history and quota live here. Signing in also creates the account a subscription attaches to."
              action={
                <>
                  <SignInButton mode="modal">
                    <button className="btn" type="button">
                      Sign in
                    </button>
                  </SignInButton>
                  <Link className="btn secondary" href="/pricing">
                    See pricing
                  </Link>
                </>
              }
            />
          </Section>
        </SignedOut>
        <SignedIn>
          <Dashboard />
        </SignedIn>
      </main>
    </>
  );
}
