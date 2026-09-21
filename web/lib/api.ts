/**
 * The client for the Worker API.
 *
 * Every call carries a Clerk session token in the Authorization header. That
 * token is the only thing the API trusts - nothing here decides what an account
 * may see, because a check made in the browser is a check an attacker skips.
 * The Worker verifies the token and re-checks ownership in D1 on every route.
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

/**
 * Set once by ClerkTokenBridge. Clerk's token getter lives in a React hook, and
 * this module is called from plain functions, so the hook hands it over here
 * rather than every caller threading it through.
 */
let getToken: (() => Promise<string | null>) | null = null;

export function setTokenGetter(getter: (() => Promise<string | null>) | null): void {
  getToken = getter;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const token = getToken ? await getToken() : null;
  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers: {
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(options.body ? { "content-type": "application/json" } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    // The API's own message, when it sent one: it knows why far better than a
    // generic "request failed" does. style.md 29 - never hide the detail from
    // a technical user.
    const message =
      (payload as { error?: string } | null)?.error ??
      `Request failed (${response.status}).`;
    throw new ApiError(message, response.status, payload);
  }
  return payload as T;
}

// --- shapes the API returns -------------------------------------------------

export interface Quota {
  plan: string;
  limit: number | null;
  used: number;
  remaining: number | null;
  resetsAt: number | null;
}

export interface Installation {
  id: number;
  account_login: string;
  account_type: string;
  active: number;
}

export interface Scan {
  id: string;
  installation_id: number;
  repository: string;
  pull_request: number | null;
  head_sha: string | null;
  trigger: string;
  state: string;
  findings: number;
  verdict: string | null;
  message: string | null;
  created_at: number;
  completed_at: number | null;
}

/** One finding, in full - matches analyzer/static/schema.py's Finding. */
export interface FindingDetail {
  source: string;
  check: string;
  severity: string;
  confidence: string;
  title: string;
  description: string;
  contract: string | null;
  file: string | null;
  lines: number[];
  suggested_fix: string | null;
  // Evidence tier: "A"/"B" proven (may block a merge), "C"/"D" leads that
  // never do. Optional because scans from before this shipped won't carry it.
  evidence?: string;
  evidence_detail?: {
    command?: string;
    vulnerable?: string;
    patched?: string;
    poc_test?: string;
  } | null;
}

export interface ScanDetail {
  scan: Scan;
  findings: FindingDetail[];
}

export interface Me {
  account: {
    id: string;
    kind: string;
    email: string | null;
    plan: string;
    anthropicKeyHint: string | null;
    hasStripeCustomer: boolean;
  };
  quota: Quota;
  installations: Installation[];
  repositories: Record<number, string[]>;
  scans: Scan[];
  checkoutAvailable: boolean;
}
