import { emailFor, ownedInstallation, requireAccount, type Session } from "./auth";
import { decrypt, encrypt, keyHint } from "./crypto";
import * as db from "./db";
import type { Env } from "./env";
import * as github from "./github";
import { decide, DEFAULT_PLAN, PLANS, PURCHASABLE } from "./plans";
import * as oidc from "./oidc";
import * as stripe from "./stripe";

/**
 * The ParaCheck control plane.
 *
 * It owns identity, billing, quota and state. It never compiles anything and
 * never sees customer source: the analysis runs as a GitHub Actions workflow on
 * the customer's own runner, which authenticates back here with a GitHub OIDC
 * token rather than a secret anyone has to configure.
 *
 * Everything here is JSON. The Next.js app on Pages is the only frontend.
 */

const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...corsHeaders(), ...headers },
  });

function corsHeaders(): Record<string, string> {
  return {
    "access-control-allow-methods": "GET,POST,DELETE,OPTIONS",
    "access-control-allow-headers": "authorization,content-type",
    "access-control-max-age": "86400",
  };
}

/** The dashboard is a different origin to the API, so CORS has to be explicit. */
function withOrigin(response: Response, env: Env, request: Request): Response {
  const origin = request.headers.get("origin");
  // Reflected only when it matches the configured frontend: a wildcard with
  // credentials would let any site call this API as a signed-in user.
  if (origin && env.PUBLIC_URL && origin === env.PUBLIC_URL) {
    response.headers.set("access-control-allow-origin", origin);
    response.headers.set("access-control-allow-credentials", "true");
    response.headers.set("vary", "Origin");
  }
  return response;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return withOrigin(new Response(null, { status: 204, headers: corsHeaders() }), env, request);
    }

    try {
      const response = await route(url, request, env, ctx);
      return withOrigin(response, env, request);
    } catch (error) {
      // Never leak an internal message to a caller; the log keeps the detail.
      console.error("paracheck: unhandled error", error);
      return withOrigin(json({ error: "internal error" }, 500), env, request);
    }
  },

} satisfies ExportedHandler<Env>;

async function route(
  url: URL,
  request: Request,
  env: Env,
  ctx: ExecutionContext,
): Promise<Response> {
  const path = url.pathname;

  // --- public -------------------------------------------------------------
  if (path === "/api/health") return health(env);
  if (path === "/api/plans") return plansResponse(env);

  // --- webhooks (verified by signature, never by session) -----------------
  if (path === "/api/webhooks/github" && request.method === "POST") {
    return githubWebhook(request, env, ctx);
  }
  if (path === "/api/webhooks/stripe" && request.method === "POST") {
    return stripeWebhook(request, env);
  }

  // --- the runner (authenticated by GitHub OIDC, not a session) -----------
  if (path === "/api/runs/claim" && request.method === "POST") return claimRun(request, env);
  if (path === "/api/runs/result" && request.method === "POST") return reportRun(request, env);

  // --- install redirect ---------------------------------------------------
  if (path === "/api/install") return startInstall(url, request, env);
  if (path === "/api/install/callback") return finishInstall(url, env);

  // --- everything below needs a signed-in account -------------------------
  const session = await requireAccount(request, env);
  if (!session) return json({ error: "sign in to continue" }, 401);

  if (path === "/api/me") return me(env, session);
  if (path === "/api/scans" && request.method === "POST") return startScan(request, env, session);
  if (path === "/api/repos/add-workflow" && request.method === "POST") {
    return addWorkflow(request, env, session);
  }
  if (path === "/api/billing/checkout" && request.method === "POST") {
    return checkout(request, env, session);
  }
  if (path === "/api/billing/portal" && request.method === "POST") return portal(env, session);
  if (path === "/api/settings/anthropic-key") {
    return anthropicKey(request, env, session);
  }

  return json({ error: "not found" }, 404);
}

// --- readiness --------------------------------------------------------------

/**
 * What this deployment can actually do.
 *
 * Reports missing configuration by name, because every one of these fails at a
 * distance otherwise: a missing webhook secret rejects every delivery with a
 * 401 visible only in GitHub's own log.
 */
function health(env: Env): Response {
  const required = {
    github_app: Boolean(env.GITHUB_APP_ID && env.GITHUB_APP_PRIVATE_KEY),
    github_webhook: Boolean(env.GITHUB_WEBHOOK_SECRET),
    github_oauth: Boolean(env.GITHUB_CLIENT_ID && env.GITHUB_CLIENT_SECRET),
    clerk: Boolean(env.CLERK_SECRET_KEY),
    stripe: stripe.configured(env),
    stripe_webhook: Boolean(env.STRIPE_WEBHOOK_SECRET),
    encryption: Boolean(env.ENCRYPTION_KEY),
    database: Boolean(env.DB),
    workflow_dispatch: Boolean(env.GITHUB_APP_ID),
  };
  const missing = Object.entries(required)
    .filter(([, ok]) => !ok)
    .map(([name]) => name);

  return json({
    ok: missing.length === 0,
    environment: env.ENVIRONMENT,
    missing,
    enterpriseContact: Boolean(env.ENTERPRISE_SALES_EMAIL),
  });
}

function plansResponse(env: Env): Response {
  return json({
    plans: [PLANS.free, ...PURCHASABLE.map((key) => PLANS[key])],
    enterprise: PLANS.enterprise,
    enterpriseEmail: env.ENTERPRISE_SALES_EMAIL || null,
    checkoutAvailable: stripe.configured(env),
  });
}

// --- install ----------------------------------------------------------------

/**
 * Sends the signed-in account to GitHub to install the App.
 *
 * The state is single-use and carries the account id, which is how the
 * installation gets attached to the right customer when GitHub redirects back.
 */
async function startInstall(url: URL, request: Request, env: Env): Promise<Response> {
  const session = await requireAccount(request, env);
  const state = await db.issueInstallState(env.DB, session?.accountId ?? null);
  const target = `https://github.com/apps/${env.GITHUB_APP_SLUG}/installations/new?state=${state}`;

  // Fetched by the dashboard rather than followed as a redirect, so the
  // frontend can send the browser itself.
  if (url.searchParams.get("format") === "json") return json({ url: target });
  return Response.redirect(target, 302);
}

async function finishInstall(url: URL, env: Env): Promise<Response> {
  const installationId = Number(url.searchParams.get("installation_id"));
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state") ?? "";

  const dashboard = `${env.PUBLIC_URL}/dashboard`;

  // Verifying state is not optional: without it, an attacker can trick someone
  // into attaching their own installation to the attacker's account.
  const { ok, accountId } = await db.consumeInstallState(env.DB, state);
  if (!ok || !installationId) {
    return Response.redirect(`${dashboard}?error=install_state`, 302);
  }

  let login = "unknown";
  let type = "User";
  if (code) {
    const user = await github.exchangeOAuthCode(env, code).catch(() => null);
    if (user) {
      login = user.login;
      type = user.type;
    }
  }

  await db.upsertInstallation(env.DB, installationId, login, type, accountId);
  if (accountId) await db.claimInstallation(env.DB, installationId, accountId);

  return Response.redirect(`${dashboard}?installed=${installationId}`, 302);
}

// --- dashboard data ---------------------------------------------------------

async function me(env: Env, session: Session): Promise<Response> {
  // A run that died without reporting would otherwise show "Scanning..."
  // forever and block later scans of the same pull request.
  await db.reapStaleScans(env.DB, session.accountId);

  const account = await db.getAccount(env.DB, session.accountId);
  const installations = await db.installationsForAccount(env.DB, session.accountId);
  const quota = await db.quotaFor(env.DB, account);

  const repositories: Record<number, string[]> = {};
  for (const installation of installations) {
    repositories[installation.id] = await db.activeRepositories(env.DB, installation.id);
  }

  return json({
    account: {
      id: session.accountId,
      kind: session.kind,
      email: account?.email ?? session.email,
      plan: account?.plan ?? DEFAULT_PLAN,
      anthropicKeyHint: account?.anthropic_key_hint ?? null,
      hasStripeCustomer: Boolean(account?.stripe_customer_id),
    },
    quota,
    plan: PLANS[account?.plan ?? DEFAULT_PLAN] ?? PLANS.free,
    installations,
    repositories,
    scans: await db.recentScans(env.DB, session.accountId, 25),
    checkoutAvailable: stripe.configured(env),
  });
}

// --- scans ------------------------------------------------------------------

/** The "Scan now" button: analyse a repository without waiting for a pull request. */
async function startScan(request: Request, env: Env, session: Session): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as {
    installationId?: number;
    repository?: string;
  };
  const installationId = Number(body.installationId);
  const repository = String(body.repository ?? "");
  if (!installationId || !repository) {
    return json({ error: "installationId and repository are required" }, 400);
  }

  const installation = await ownedInstallation(env, session, installationId);
  if (!installation) return json({ error: "unknown installation" }, 403);

  // The repository must be one GitHub actually granted. The installation token
  // can reach every repository in the installation, so this field must not be
  // able to choose one that was never connected.
  if (!(await db.isRepositoryActive(env.DB, installationId, repository))) {
    return json({ error: "ParaCheck does not have access to that repository" }, 403);
  }

  const account = await db.getAccount(env.DB, session.accountId);
  const verdict = decide(await db.quotaFor(env.DB, account));
  if (!verdict.allowed) {
    // Refused at the button rather than queued to fail minutes later.
    return json({ error: verdict.reason, quota: verdict.quota }, 402);
  }

  const existing = await db.openScanFor(env.DB, installationId, repository, null);
  if (existing) return json({ scanId: existing.id, state: existing.state, deduped: true });

  const scanId = crypto.randomUUID();
  await db.createScan(env.DB, {
    id: scanId,
    account_id: session.accountId,
    installation_id: installationId,
    repository,
    pull_request: null,
    head_sha: null,
    trigger: "manual",
    state: "queued",
  });
  const dispatched = await github.dispatchWorkflow(env, installationId, repository);
  if (!dispatched.ok) {
    // A distinct state, not just "failed" with a matching message: the
    // dashboard needs to reliably tell "no workflow file yet" apart from a
    // real failure to offer the right button, and matching on message text
    // would break the moment the wording changes.
    const state = dispatched.needsWorkflow ? "no_workflow" : "failed";
    await db.completeScan(env.DB, scanId, state, { message: dispatched.reason });
    return json({ error: dispatched.reason, needsWorkflow: dispatched.needsWorkflow }, 409);
  }

  return json({ scanId, state: "queued" }, 202);
}

/**
 * The "Add ParaCheck to this repo" button: opens a pull request that adds the
 * workflow file. This is what a repository with no workflow needs before it
 * can be scanned at all - previously that state was a dead end with a message
 * telling the customer to go do it themselves.
 */
async function addWorkflow(request: Request, env: Env, session: Session): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as {
    installationId?: number;
    repository?: string;
  };
  const installationId = Number(body.installationId);
  const repository = String(body.repository ?? "");
  if (!installationId || !repository) {
    return json({ error: "installationId and repository are required" }, 400);
  }

  const installation = await ownedInstallation(env, session, installationId);
  if (!installation) return json({ error: "unknown installation" }, 403);
  if (!(await db.isRepositoryActive(env.DB, installationId, repository))) {
    return json({ error: "ParaCheck does not have access to that repository" }, 403);
  }

  const result = await github.proposeWorkflowFile(env, installationId, repository);
  if (!result.ok) return json({ error: result.reason }, 502);
  return json({ prUrl: result.prUrl });
}

// --- GitHub webhook ---------------------------------------------------------

async function githubWebhook(
  request: Request,
  env: Env,
  ctx: ExecutionContext,
): Promise<Response> {
  const body = await request.text();
  const signature = request.headers.get("x-hub-signature-256");
  if (!(await github.verifyWebhook(env.GITHUB_WEBHOOK_SECRET, body, signature))) {
    return json({ error: "bad signature" }, 401);
  }

  const deliveryId = request.headers.get("x-github-delivery") ?? "";
  if (deliveryId && !(await db.firstDelivery(env.DB, "github", deliveryId))) {
    return json({ ok: true, duplicate: true });
  }

  const event = request.headers.get("x-github-event") ?? "";
  const payload = JSON.parse(body) as GithubPayload;

  // Acknowledge fast; GitHub times out at 10 seconds and the work is queued.
  ctx.waitUntil(handleGithubEvent(env, event, payload));
  return json({ ok: true });
}

interface GithubPayload {
  action?: string;
  installation?: { id?: number; account?: { login?: string; type?: string } };
  repositories?: Array<{ full_name: string }>;
  repositories_added?: Array<{ full_name: string }>;
  repositories_removed?: Array<{ full_name: string }>;
  repository?: { full_name?: string };
  pull_request?: { number?: number; head?: { sha?: string } };
}

async function handleGithubEvent(
  env: Env,
  event: string,
  payload: GithubPayload,
): Promise<void> {
  const installationId = payload.installation?.id;
  if (!installationId) return;

  if (event === "installation") {
    const account = payload.installation?.account ?? {};
    if (["created", "unsuspend", "new_permissions_accepted"].includes(payload.action ?? "")) {
      await db.upsertInstallation(
        env.DB,
        installationId,
        account.login ?? "unknown",
        account.type ?? "User",
      );
      await db.setRepositories(
        env.DB,
        installationId,
        (payload.repositories ?? []).map((r) => r.full_name),
      );
    } else if (["deleted", "suspend"].includes(payload.action ?? "")) {
      await db.deactivateInstallation(env.DB, installationId);
    }
    return;
  }

  if (event === "installation_repositories") {
    await db.setRepositories(
      env.DB,
      installationId,
      (payload.repositories_added ?? []).map((r) => r.full_name),
    );
    await db.removeRepositories(
      env.DB,
      installationId,
      (payload.repositories_removed ?? []).map((r) => r.full_name),
    );
    return;
  }

  if (event === "pull_request") {
    if (!["opened", "synchronize", "reopened"].includes(payload.action ?? "")) return;
    await queuePullRequestScan(env, installationId, payload);
  }
}

async function queuePullRequestScan(
  env: Env,
  installationId: number,
  payload: GithubPayload,
): Promise<void> {
  const repository = payload.repository?.full_name;
  const pullRequest = payload.pull_request?.number;
  const headSha = payload.pull_request?.head?.sha;
  if (!repository || !pullRequest || !headSha) return;

  const installation = await db.getInstallation(env.DB, installationId);
  // An installation nobody has signed in for has no account to bill, so there
  // is nothing to spend and nothing to scan.
  if (!installation?.account_id || !installation.active) return;

  const account = await db.getAccount(env.DB, installation.account_id);
  const verdict = decide(await db.quotaFor(env.DB, account));
  if (!verdict.allowed) {
    // Recorded, not silently dropped: the dashboard has to be able to say why
    // a pull request never got a check.
    await db.createScan(env.DB, {
      id: crypto.randomUUID(),
      account_id: installation.account_id,
      installation_id: installationId,
      repository,
      pull_request: pullRequest,
      head_sha: headSha,
      trigger: "pull_request",
      state: "blocked",
    });
    return;
  }

  // Three pushes in a row should scan the newest head once, not queue three
  // scans of commits nobody is waiting on any more.
  const existing = await db.openScanFor(env.DB, installationId, repository, pullRequest);
  if (existing) {
    await db.supersedeScan(env.DB, existing.id, headSha);
    return;
  }

  // Nothing is queued here. The customer's workflow fires on its own
  // `pull_request` trigger and claims a scan when it starts, which is also the
  // only way a run that we did not dispatch still gets counted.
}

// --- Stripe webhook ---------------------------------------------------------

async function stripeWebhook(request: Request, env: Env): Promise<Response> {
  const body = await request.text();
  if (!(await stripe.verifyWebhook(env, body, request.headers.get("stripe-signature")))) {
    return json({ error: "bad signature" }, 401);
  }

  const event = JSON.parse(body) as {
    id: string;
    type: string;
    data: { object: Record<string, unknown> };
  };
  // Stripe retries, and a retried checkout.session.completed must not act twice.
  if (!(await db.firstDelivery(env.DB, "stripe", event.id))) {
    return json({ ok: true, duplicate: true });
  }

  const outcome = await stripe.applyEvent(env, event as never);
  if (outcome) console.log(`paracheck: ${outcome}`);
  return json({ ok: true });
}

// --- billing ----------------------------------------------------------------

async function checkout(request: Request, env: Env, session: Session): Promise<Response> {
  if (!stripe.configured(env)) {
    return json({ error: "checkout is not configured on this deployment" }, 503);
  }
  const { plan } = (await request.json().catch(() => ({}))) as { plan?: string };
  if (!plan || !PURCHASABLE.includes(plan as never)) {
    return json({ error: "choose the Pro or Team plan" }, 400);
  }

  const url = await stripe.createCheckoutSession(env, {
    accountId: session.accountId,
    plan,
    email: await emailFor(env, session),
    successUrl: `${env.PUBLIC_URL}/dashboard?subscribed=1`,
    cancelUrl: `${env.PUBLIC_URL}/pricing`,
  });
  if (!url) return json({ error: "could not start checkout" }, 502);
  return json({ url });
}

async function portal(env: Env, session: Session): Promise<Response> {
  const account = await db.getAccount(env.DB, session.accountId);
  if (!account?.stripe_customer_id) {
    return json({ error: "no subscription to manage yet" }, 404);
  }
  const url = await stripe.createPortalSession(
    env,
    account.stripe_customer_id,
    `${env.PUBLIC_URL}/dashboard`,
  );
  if (!url) return json({ error: "could not open the billing portal" }, 502);
  return json({ url });
}

// --- bring your own Claude key ----------------------------------------------

/**
 * Store or remove an account's Anthropic key.
 *
 * The plaintext exists only for the length of this request: it is encrypted,
 * never logged, and never returned - only its last four characters are.
 */
async function anthropicKey(
  request: Request,
  env: Env,
  session: Session,
): Promise<Response> {
  if (request.method === "DELETE") {
    await db.setAnthropicKey(env.DB, session.accountId, null, null);
    return json({ ok: true, hint: null });
  }
  if (request.method !== "POST") return json({ error: "not found" }, 404);
  if (!env.ENCRYPTION_KEY) {
    return json({ error: "this deployment cannot store keys: no encryption secret" }, 503);
  }

  const { key } = (await request.json().catch(() => ({}))) as { key?: string };
  const trimmed = (key ?? "").trim();
  if (!trimmed) return json({ error: "no key was submitted" }, 400);

  // Checked against the real API before storing, so a typo is caught now rather
  // than surfacing days later as scans that quietly arrive without a summary.
  const check = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": trimmed,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: "claude-opus-5",
      max_tokens: 1,
      messages: [{ role: "user", content: "hi" }],
    }),
  });
  // 401/403 mean the key is bad. Anything else - including a rate limit - means
  // it authenticated, which is all we were checking.
  if (check.status === 401 || check.status === 403) {
    return json({ error: "That key was rejected by the Anthropic API." }, 400);
  }

  await db.setAnthropicKey(
    env.DB,
    session.accountId,
    await encrypt(env.ENCRYPTION_KEY, trimmed),
    keyHint(trimmed),
  );
  return json({ ok: true, hint: keyHint(trimmed) });
}

// --- the runner ---------------------------------------------------------------
//
// These two endpoints are the whole contract with a GitHub Actions run. Both
// authenticate with a GitHub OIDC token, so the customer configures no secret
// and we still know exactly which repository is calling.

/**
 * A run asks permission before it analyses anything.
 *
 * Checking here rather than only at dispatch is what makes the quota real: a
 * workflow also fires on the repository's own `pull_request` trigger, which we
 * never sent, so this is the only point every scan passes through.
 */
async function claimRun(request: Request, env: Env): Promise<Response> {
  const identity = await oidc.identityFrom(request);
  if (!identity) return json({ error: "invalid or missing OIDC token" }, 401);

  const owner = await oidc.accountForRepository(env, identity.repository);
  if (!owner) {
    return json(
      {
        allowed: false,
        reason:
          "This repository is not connected to a ParaCheck account. Install the app and sign in at least once.",
      },
      403,
    );
  }

  const body = (await request.json().catch(() => ({}))) as {
    pullRequest?: number | null;
    headSha?: string | null;
  };
  const pullRequest = body.pullRequest ?? null;
  const headSha = body.headSha ?? null;

  // A re-run of the same commit (GitHub's "Re-run failed jobs", or a flaky
  // network retry) must not spend quota twice for one attempt. Reusing the
  // earlier scan id also means its result lands in the same history row
  // instead of a duplicate.
  const already = await db.recentScanOf(
    env.DB, owner.installationId, identity.repository, pullRequest, headSha,
  );
  if (already) {
    const account = await db.getAccount(env.DB, owner.accountId);
    const anthropicKey = env.ENCRYPTION_KEY
      ? await decrypt(env.ENCRYPTION_KEY, account?.anthropic_key ?? null)
      : null;
    return json({
      allowed: true,
      scanId: already.id,
      quota: await db.quotaFor(env.DB, account),
      anthropicKey,
    });
  }

  const account = await db.getAccount(env.DB, owner.accountId);
  const verdict = decide(await db.quotaFor(env.DB, account));
  if (!verdict.allowed) {
    // Recorded as blocked so the dashboard can explain why a pull request has
    // no check on it, but blocked scans do not count against the window.
    await db.createScan(env.DB, {
      id: crypto.randomUUID(),
      account_id: owner.accountId,
      installation_id: owner.installationId,
      repository: identity.repository,
      pull_request: pullRequest,
      head_sha: headSha,
      trigger: "pull_request",
      state: "blocked",
    });
    return json({ allowed: false, reason: verdict.reason, quota: verdict.quota }, 402);
  }

  const scanId = crypto.randomUUID();
  await db.createScan(env.DB, {
    id: scanId,
    account_id: owner.accountId,
    installation_id: owner.installationId,
    repository: identity.repository,
    pull_request: pullRequest,
    head_sha: headSha,
    trigger: pullRequest ? "pull_request" : "manual",
    state: "running",
  });

  // The account's own Claude key, for this run only. Absent is normal: findings
  // are deterministic either way.
  const anthropicKey = env.ENCRYPTION_KEY
    ? await decrypt(env.ENCRYPTION_KEY, account?.anthropic_key ?? null)
    : null;

  return json({ allowed: true, scanId, quota: verdict.quota, anthropicKey });
}

/** A run reports what it found. */
async function reportRun(request: Request, env: Env): Promise<Response> {
  const identity = await oidc.identityFrom(request);
  if (!identity) return json({ error: "invalid or missing OIDC token" }, 401);

  const body = (await request.json().catch(() => ({}))) as {
    scanId?: string;
    state?: string;
    findings?: number;
    verdict?: string | null;
    message?: string;
  };
  if (!body.scanId) return json({ error: "scanId is required" }, 400);

  // A run may only report on a scan for its own repository. Without this, any
  // repository with the app installed could overwrite another's history.
  const scan = await env.DB.prepare("SELECT repository FROM scans WHERE id = ?")
    .bind(body.scanId)
    .first<{ repository: string }>();
  if (!scan || scan.repository !== identity.repository) {
    return json({ error: "unknown scan" }, 404);
  }

  const allowed = ["done", "failed", "empty"];
  const state = allowed.includes(body.state ?? "") ? (body.state as string) : "failed";
  await db.completeScan(env.DB, body.scanId, state, {
    findings: body.findings ?? 0,
    verdict: body.verdict ?? null,
    message: body.message ?? "",
  });
  return json({ ok: true });
}
