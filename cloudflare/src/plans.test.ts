import { describe, expect, it } from "vitest";

import { decrypt, encrypt, keyHint, timingSafeEqual } from "./crypto";
import { decide, PLANS, PURCHASABLE, QUOTA_WINDOW_SECONDS, scanLimit, type Quota } from "./plans";

const quota = (over: Partial<Quota> = {}): Quota => ({
  plan: "free",
  limit: 10,
  used: 0,
  remaining: 10,
  resetsAt: null,
  ...over,
});

describe("plan limits", () => {
  it("publishes the launch quotas", () => {
    expect(scanLimit("free")).toBe(10);
    expect(scanLimit("pro")).toBe(100);
    expect(scanLimit("team")).toBe(250);
  });

  it("gets cheaper per scan as the tier goes up", () => {
    // If a bigger plan ever costs more per scan, the ladder is broken and
    // nobody has a reason to move up it.
    const perScan = (key: string) =>
      Number(PLANS[key].price.replace("$", "")) / (PLANS[key].scansPerMonth ?? 1);
    expect(perScan("team")).toBeLessThan(perScan("pro"));
  });

  it("gives enterprise no fixed cap", () => {
    expect(scanLimit("enterprise")).toBeNull();
  });

  it("falls back to the free allowance, never to unlimited", () => {
    // Two failure modes to avoid: an unknown plan reading as unlimited, and a
    // paying customer locked out by a typo. Free is the safe middle.
    expect(scanLimit("unpaid")).toBe(10);   // historical alias
    expect(scanLimit("Pro")).toBe(10);      // wrong case
    expect(scanLimit("")).toBe(10);
    expect(scanLimit("nonsense")).not.toBeNull();
  });

  it("only sells the plans that have a Stripe price", () => {
    for (const key of PURCHASABLE) {
      expect(PLANS[key].priceEnv).toBeDefined();
    }
    expect(PLANS.enterprise.priceEnv).toBeUndefined();
  });

  it("advertises a scan count matching the enforced limit", () => {
    // The pricing page renders these strings; the gate reads scanLimit.
    for (const key of ["free", ...PURCHASABLE] as string[]) {
      const plan = PLANS[key];
      expect(plan.features[0]).toBe(`${plan.scansPerMonth} scans per month`);
    }
  });

  it("sells Pro and Team - free needs no checkout, enterprise is sales-led", () => {
    expect([...PURCHASABLE]).toEqual(["pro", "team"]);
  });
});

describe("quota decisions", () => {
  it("allows a scan with quota left", () => {
    expect(decide(quota({ used: 3, remaining: 17 })).allowed).toBe(true);
  });

  it("refuses once the window is full, and says when it frees up", () => {
    const resetsAt = Math.floor(Date.now() / 1000) + QUOTA_WINDOW_SECONDS;
    const verdict = decide(quota({ used: 10, remaining: 0, resetsAt }));
    expect(verdict.allowed).toBe(false);
    expect(verdict.reason).toContain("10/10");
    expect(verdict.reason).toContain("frees up");
  });

  it("names the next tier up, not always the cheapest", () => {
    // Telling a Pro customer about Pro is noise.
    expect(decide(quota({ used: 10, remaining: 0 })).reason).toContain("Pro is $24");

    const pro = decide(quota({ plan: "pro", limit: 100, used: 100, remaining: 0 }));
    expect(pro.reason).toContain("Team is $49");
    expect(pro.reason).not.toContain("Pro is");

    const team = decide(quota({ plan: "team", limit: 250, used: 250, remaining: 0 }));
    expect(team.reason).not.toContain("is $");  // nothing left to sell them
  });

  it("lets a new free account scan straight away", () => {
    // The whole point of the free tier: install and get value with no card.
    expect(decide(quota({ used: 0, remaining: 10 })).allowed).toBe(true);
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
