"use client";

import { useState } from "react";
import { SignedIn, SignedOut, SignInButton } from "@clerk/clerk-react";

import { api } from "@/lib/api";
import { enterpriseMailto, PLANS } from "@/lib/plans";
import { Notice, Panel } from "./ui";

/**
 * The pricing cards, and the only place a subscription starts.
 *
 * Signed out, the action is signing in - a checkout without an account has
 * nothing to attach the subscription to. Signed in, it opens Stripe.
 */
export function PlanGrid() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function subscribe(plan: string) {
    setBusy(plan);
    setError(null);
    try {
      const { url } = await api<{ url: string }>("/api/billing/checkout", {
        method: "POST",
        body: { plan },
      });
      window.location.href = url;
    } catch (cause) {
      // Stays on the page with the reason: a checkout that silently does
      // nothing is the worst possible failure on a pricing page.
      setError(cause instanceof Error ? cause.message : "Could not start checkout.");
      setBusy(null);
    }
  }

  return (
    <>
      {error ? (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <div className="grid grid-4 plans">
        {PLANS.map((plan) => (
          <Panel key={plan.key} className={plan.key === "team" ? "plan is-featured" : "plan"}>
            <div className="stat-label">{plan.label}</div>
            <div className="plan-price">
              {plan.price}
              <span className="plan-cadence">{plan.cadence}</span>
            </div>
            <p className="muted small" style={{ marginTop: 8 }}>
              {plan.blurb}
            </p>
            <ul className="plan-features">
              {plan.features.map((feature) => (
                <li key={feature}>{feature}</li>
              ))}
            </ul>

            <div className="btn-row" style={{ marginTop: "auto", paddingTop: 20 }}>
              {plan.key === "enterprise" ? (
                <a className="btn secondary" href={enterpriseMailto()}>
                  Talk to us
                </a>
              ) : plan.key === "free" ? (
                // No checkout for free: the action is simply starting.
                <>
                  <SignedOut>
                    <SignInButton mode="modal">
                      <button className="btn secondary" type="button">
                        Start free
                      </button>
                    </SignInButton>
                  </SignedOut>
                  <SignedIn>
                    <a className="btn secondary" href="/dashboard/">
                      Go to dashboard
                    </a>
                  </SignedIn>
                </>
              ) : (
                <>
                  <SignedOut>
                    <SignInButton mode="modal">
                      <button
                        className={plan.key === "team" ? "btn" : "btn secondary"}
                        type="button"
                      >
                        Choose {plan.label}
                      </button>
                    </SignInButton>
                  </SignedOut>
                  <SignedIn>
                    <button
                      className={plan.key === "team" ? "btn" : "btn secondary"}
                      type="button"
                      disabled={busy !== null}
                      onClick={() => subscribe(plan.key)}
                    >
                      {busy === plan.key ? "Opening checkout…" : `Choose ${plan.label}`}
                    </button>
                  </SignedIn>
                </>
              )}
            </div>
          </Panel>
        ))}
      </div>
    </>
  );
}
