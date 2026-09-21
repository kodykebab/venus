import { Analyzer, ContainerProxy } from "./analyzer";
import { emailFor, ownedInstallation, requireAccount, type Session } from "./auth";
import { decrypt, encrypt, keyHint } from "./crypto";
import * as db from "./db";
import type { Env, ScanJob } from "./env";
import * as github from "./github";
import { decide, PLANS, PURCHASABLE, scansPerWeek } from "./plans";
import * as stripe from "./stripe";

export { Analyzer, ContainerProxy };

/**
 * The ParaCheck control plane.
 *
 * It owns identity, billing, quota and state. It never compiles anything:
 * repository analysis runs in the Analyzer container, which is the only part
 * of the system that sees customer source.
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

  /**
   * The queue consumer: one scan per invocation.
   *
   * This is where a job becomes a running container. It mints the installation
   * token here rather than carrying one in the message, so a retry an hour
   * later still works and no credential sits at rest in a queue.
   */
  async queue(batch: MessageBatch<ScanJob>, env: Env): Promise<void> {
    for (const message of batch.messages) {
      const job = message.body;
      try {
        await runScan(env, job);
        message.ack();
      } catch (error) {
        console.error(`paracheck: scan ${job.scanId} failed`, error);
        const attempt = message.attempts ?? 1;
        if (attempt >= 3) {
          // Out of retries: record why, so the dashboard shows a failed scan
          // rather than one stuck on "queued" forever.
          await db.completeScan(env.DB, job.scanId, "failed", {
            message: error instanceof Error ? error.message : "Analysis failed.",
          });
          message.ack();
        } else {
          message.retry({ delaySeconds: 30 * attempt });
        }
      }
    }
  },
} satisfies ExportedHandler<Env, ScanJob>;

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

  // --- install redirect ---------------------------------------------------
  if (path === "/api/install") return startInstall(url, request, env);
  if (path === "/api/install/callback") return finishInstall(url, env);

  // --- everything below needs a signed-in account -------------------------
  const session = await requireAccount(request, env);
  if (!session) return json({ error: "sign in to continue" }, 401);

  if (path === "/api/me") return me(env, session);
  if (path === "/api/scans" && request.method === "POST") return startScan(request, env, session);
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
    queue: Boolean(env.SCANS),
    analyzer: Boolean(env.ANALYZER),
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
    plans: PURCHASABLE.map((key) => PLANS[key]),
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
      plan: account?.plan ?? "unpaid",
      anthropicKeyHint: account?.anthropic_key_hint ?? null,
      hasStripeCustomer: Boolean(account?.stripe_customer_id),
    },
    quota,
    plan: PLANS[account?.plan ?? "unpaid"] ?? null,
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
  await env.SCANS.send({
    scanId,
    accountId: session.accountId,
    installationId,
    repository,
    pullRequest: null,
    headSha: null,
    trigger: "manual",
  });

  return json({ scanId, state: "queued" }, 202);
}

/**
 * Runs one scan: mint a token, hand the job to the container, record what came
 * back. The container posts the Check Run itself, because it is the only thing
 * that has the findings.
 */
async function runScan(env: Env, job: ScanJob): Promise<void> {
  await db.completeScan(env.DB, job.scanId, "running");

  const account = await db.getAccount(env.DB, job.accountId);
  const token = await github.installationToken(env, job.installationId);

  // BYOK: decrypted here and passed to the container for this job only. Absent
  // is a normal state - findings are deterministic either way.
  const anthropicKey = env.ENCRYPTION_KEY
    ? await decrypt(env.ENCRYPTION_KEY, account?.anthropic_key ?? null)
    : null;

  const container = env.ANALYZER.getByName(`scan-${job.scanId}`);
  const response = await container.fetch(
    new Request("https://analyzer.internal/scan", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        scanId: job.scanId,
        repository: job.repository,
        pullRequest: job.pullRequest,
        headSha: job.headSha,
        githubToken: token.token,
        anthropicKey,
      }),
    }),
  );

  if (!response.ok) {
    throw new Error(`analyzer returned ${response.status}`);
  }

  const result = (await response.json()) as {
    state: string;
    findings?: number;
    verdict?: string | null;
    message?: string;
  };
  await db.completeScan(env.DB, job.scanId, result.state, {
    findings: result.findings ?? 0,
    verdict: result.verdict ?? null,
    message: result.message ?? "",
  });
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

  const scanId = crypto.randomUUID();
  await db.createScan(env.DB, {
    id: scanId,
    account_id: installation.account_id,
    installation_id: installationId,
    repository,
    pull_request: pullRequest,
    head_sha: headSha,
    trigger: "pull_request",
    state: "queued",
  });
  await env.SCANS.send({
    scanId,
    accountId: installation.account_id,
    installationId,
    repository,
    pullRequest,
    headSha,
    trigger: "pull_request",
  });
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
    return json({ error: "choose the Hobby or Pro plan" }, 400);
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
