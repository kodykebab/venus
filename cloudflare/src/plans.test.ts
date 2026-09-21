import { describe, expect, it } from "vitest";

import { decrypt, encrypt, keyHint, timingSafeEqual } from "./crypto";
import { decide, PLANS, PURCHASABLE, QUOTA_WINDOW_SECONDS, scansPerWeek, type Quota } from "./plans";

const quota = (over: Partial<Quota> = {}): Quota => ({
  plan: "hobby",
  limit: 20,
  used: 0,
  remaining: 20,
  resetsAt: null,
  ...over,
});

describe("plan limits", () => {
  it("publishes the launch quotas", () => {
    expect(scansPerWeek("hobby")).toBe(20);
    expect(scansPerWeek("pro")).toBe(100);
  });

  it("gives enterprise no fixed cap", () => {
    expect(scansPerWeek("enterprise")).toBeNull();
  });

  it("fails closed on an unpaid or misspelled plan", () => {
    // The dangerous bug would be an unknown plan reading as unlimited.
    expect(scansPerWeek("unpaid")).toBe(0);
    expect(scansPerWeek("Pro")).toBe(0);
    expect(scansPerWeek("")).toBe(0);
  });

  it("only sells the plans that have a Stripe price", () => {
    for (const key of PURCHASABLE) {
      expect(PLANS[key].priceEnv).toBeDefined();
    }
    expect(PLANS.enterprise.priceEnv).toBeUndefined();
  });

  it("advertises a weekly scan count matching the enforced limit", () => {
    // The pricing page renders these strings, the gate reads scansPerWeek.
    for (const key of PURCHASABLE) {
      const plan = PLANS[key];
      expect(plan.features[0]).toBe(`${plan.scansPerWeek} scans per week`);
    }
  });
});

describe("quota decisions", () => {
  it("allows a scan with quota left", () => {
    expect(decide(quota({ used: 3, remaining: 17 })).allowed).toBe(true);
  });

  it("refuses once the window is full, and says when it frees up", () => {
    const resetsAt = Math.floor(Date.now() / 1000) + QUOTA_WINDOW_SECONDS;
    const verdict = decide(quota({ used: 20, remaining: 0, resetsAt }));
    expect(verdict.allowed).toBe(false);
    expect(verdict.reason).toContain("20/20");
    expect(verdict.reason).toContain("frees up");
  });

  it("tells an unpaid account to pick a plan instead of showing a zero quota", () => {
    const verdict = decide(quota({ plan: "unpaid", limit: 0, remaining: 0 }));
    expect(verdict.allowed).toBe(false);
    expect(verdict.reason).toContain("Choose a");
    // "0/0 scans used" reads like a bug rather than a paywall.
    expect(verdict.reason).not.toContain("0/0");
  });

  it("never blocks enterprise on a count", () => {
    const verdict = decide(quota({ plan: "enterprise", limit: null, used: 900, remaining: null }));
    expect(verdict.allowed).toBe(true);
  });
});

describe("key storage", () => {
  it("round-trips a key without storing the plaintext", async () => {
    const stored = await encrypt("secret", "sk-ant-api03-EXAMPLE1234");
    expect(stored).not.toContain("EXAMPLE");
    expect(await decrypt("secret", stored)).toBe("sk-ant-api03-EXAMPLE1234");
  });

  it("produces a different ciphertext each time", async () => {
    // A fixed IV would make identical keys identifiable in a leaked export.
    const a = await encrypt("secret", "sk-ant-same");
    const b = await encrypt("secret", "sk-ant-same");
    expect(a).not.toBe(b);
  });

  it("degrades instead of throwing when the secret has rotated", async () => {
    const stored = await encrypt("old-secret", "sk-ant-key");
    expect(await decrypt("new-secret", stored)).toBeNull();
    expect(await decrypt("secret", "not-even-ciphertext")).toBeNull();
    expect(await decrypt("secret", null)).toBeNull();
  });

  it("shows only the last four characters", () => {
    expect(keyHint("sk-ant-api03-SECRET9RQ2")).toBe("...9RQ2");
  });
});

describe("timingSafeEqual", () => {
  it("compares correctly", () => {
    expect(timingSafeEqual("abc", "abc")).toBe(true);
    expect(timingSafeEqual("abc", "abd")).toBe(false);
    expect(timingSafeEqual("abc", "abcd")).toBe(false);
    expect(timingSafeEqual("", "")).toBe(true);
  });
});
