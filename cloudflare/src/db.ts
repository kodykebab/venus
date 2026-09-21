import { QUOTA_WINDOW_SECONDS, type Quota, scansPerWeek } from "./plans";

/**
 * Every D1 query lives here.
 *
 * One module so the schema has a single set of callers, and so the quota
 * question - "how many scans has this account run this week" - is answered in
 * exactly one place by exactly one query.
 */

export const now = () => Math.floor(Date.now() / 1000);

export interface Account {
  id: string;
  kind: string;
  email: string | null;
  plan: string;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  anthropic_key: string | null;
  anthropic_key_hint: string | null;
}

export interface Installation {
  id: number;
  account_id: string | null;
  account_login: string;
  account_type: string;
  active: number;
}

export interface Scan {
  id: string;
  account_id: string;
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

// --- accounts ---------------------------------------------------------------

export async function upsertAccount(
  db: D1Database,
  id: string,
  kind: string,
  email: string | null,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO accounts (id, kind, email, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         email = COALESCE(excluded.email, accounts.email),
         updated_at = excluded.updated_at`,
    )
    .bind(id, kind, email, now(), now())
    .run();
}

export async function getAccount(db: D1Database, id: string): Promise<Account | null> {
  return await db.prepare("SELECT * FROM accounts WHERE id = ?").bind(id).first<Account>();
}

export async function accountByStripeCustomer(
  db: D1Database,
  customerId: string,
): Promise<Account | null> {
  return await db
    .prepare("SELECT * FROM accounts WHERE stripe_customer_id = ?")
    .bind(customerId)
    .first<Account>();
}

export async function setPlan(
  db: D1Database,
  accountId: string,
  plan: string,
  stripe?: { customerId?: string; subscriptionId?: string },
): Promise<void> {
  // Quota is counted from scans, so changing a plan writes no balance - there
  // is nothing here that a missed webhook could leave stale.
  await db
    .prepare(
      `UPDATE accounts SET
         plan = ?,
         stripe_customer_id = COALESCE(?, stripe_customer_id),
         stripe_subscription_id = COALESCE(?, stripe_subscription_id),
         updated_at = ?
       WHERE id = ?`,
    )
    .bind(plan, stripe?.customerId ?? null, stripe?.subscriptionId ?? null, now(), accountId)
    .run();
}

export async function setAnthropicKey(
  db: D1Database,
  accountId: string,
  encrypted: string | null,
  hint: string | null,
): Promise<void> {
  await db
    .prepare("UPDATE accounts SET anthropic_key = ?, anthropic_key_hint = ?, updated_at = ? WHERE id = ?")
    .bind(encrypted, hint, now(), accountId)
    .run();
}

// --- installations ----------------------------------------------------------

export async function upsertInstallation(
  db: D1Database,
  id: number,
  login: string,
  type: string,
  accountId?: string | null,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO installations (id, account_id, account_login, account_type, active, created_at, updated_at)
       VALUES (?, ?, ?, ?, 1, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         account_id = COALESCE(excluded.account_id, installations.account_id),
         account_login = excluded.account_login,
         account_type = excluded.account_type,
         active = 1,
         updated_at = excluded.updated_at`,
    )
    .bind(id, accountId ?? null, login, type, now(), now())
    .run();
}

export async function getInstallation(db: D1Database, id: number): Promise<Installation | null> {
  return await db.prepare("SELECT * FROM installations WHERE id = ?").bind(id).first<Installation>();
}

export async function installationsForAccount(
  db: D1Database,
  accountId: string,
): Promise<Installation[]> {
  const { results } = await db
    .prepare("SELECT * FROM installations WHERE account_id = ? AND active = 1 ORDER BY account_login")
    .bind(accountId)
    .all<Installation>();
  return results ?? [];
}

export async function deactivateInstallation(db: D1Database, id: number): Promise<void> {
  await db
    .prepare("UPDATE installations SET active = 0, updated_at = ? WHERE id = ?")
    .bind(now(), id)
    .run();
}

export async function claimInstallation(
  db: D1Database,
  installationId: number,
  accountId: string,
): Promise<boolean> {
  // Only claims an installation nobody owns yet. Without the `IS NULL` guard
  // this is a way to attach somebody else's repositories to your own account.
  const result = await db
    .prepare(
      "UPDATE installations SET account_id = ?, updated_at = ? WHERE id = ? AND account_id IS NULL",
    )
    .bind(accountId, now(), installationId)
    .run();
  return (result.meta?.changes ?? 0) > 0;
}

// --- repositories -----------------------------------------------------------

export async function setRepositories(
  db: D1Database,
  installationId: number,
  fullNames: string[],
): Promise<void> {
  if (!fullNames.length) return;
  const statements = fullNames.map((name) =>
    db
      .prepare(
        `INSERT INTO repositories (installation_id, full_name, active) VALUES (?, ?, 1)
         ON CONFLICT(installation_id, full_name) DO UPDATE SET active = 1`,
      )
      .bind(installationId, name),
  );
  await db.batch(statements);
}

export async function removeRepositories(
  db: D1Database,
  installationId: number,
  fullNames: string[],
): Promise<void> {
  if (!fullNames.length) return;
  await db.batch(
    fullNames.map((name) =>
      db
        .prepare("UPDATE repositories SET active = 0 WHERE installation_id = ? AND full_name = ?")
        .bind(installationId, name),
    ),
  );
}

export async function activeRepositories(
  db: D1Database,
  installationId: number,
): Promise<string[]> {
  const { results } = await db
    .prepare(
      "SELECT full_name FROM repositories WHERE installation_id = ? AND active = 1 ORDER BY full_name",
    )
    .bind(installationId)
    .all<{ full_name: string }>();
  return (results ?? []).map((row) => row.full_name);
}

export async function isRepositoryActive(
  db: D1Database,
  installationId: number,
  fullName: string,
): Promise<boolean> {
  const row = await db
    .prepare(
      "SELECT 1 AS ok FROM repositories WHERE installation_id = ? AND full_name = ? AND active = 1",
    )
    .bind(installationId, fullName)
    .first<{ ok: number }>();
  return row !== null;
}

// --- scans and quota --------------------------------------------------------

export async function createScan(
  db: D1Database,
  scan: Omit<Scan, "findings" | "verdict" | "message" | "created_at" | "completed_at">,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO scans (id, account_id, installation_id, repository, pull_request,
                          head_sha, trigger, state, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      scan.id,
      scan.account_id,
      scan.installation_id,
      scan.repository,
      scan.pull_request,
      scan.head_sha,
      scan.trigger,
      scan.state,
      now(),
    )
    .run();
}

export async function completeScan(
  db: D1Database,
  id: string,
  state: string,
  fields: { findings?: number; verdict?: string | null; message?: string | null } = {},
): Promise<void> {
  await db
    .prepare(
      `UPDATE scans SET state = ?, findings = ?, verdict = ?, message = ?, completed_at = ?
       WHERE id = ?`,
    )
    .bind(state, fields.findings ?? 0, fields.verdict ?? null, (fields.message ?? "").slice(0, 500), now(), id)
    .run();
}

/** An in-flight scan for this pull request, so a re-push supersedes rather than queues again. */
export async function openScanFor(
  db: D1Database,
  installationId: number,
  repository: string,
  pullRequest: number | null,
): Promise<Scan | null> {
  return await db
    .prepare(
      `SELECT * FROM scans
       WHERE installation_id = ? AND repository = ?
         AND (pull_request IS ? OR pull_request = ?)
         AND state IN ('queued', 'running')
       ORDER BY created_at DESC LIMIT 1`,
    )
    .bind(installationId, repository, pullRequest, pullRequest)
    .first<Scan>();
}

export async function supersedeScan(db: D1Database, id: string, headSha: string): Promise<void> {
  await db.prepare("UPDATE scans SET head_sha = ? WHERE id = ?").bind(headSha, id).run();
}

export async function recentScans(
  db: D1Database,
  accountId: string,
  limit = 25,
): Promise<Scan[]> {
  const { results } = await db
    .prepare("SELECT * FROM scans WHERE account_id = ? ORDER BY created_at DESC LIMIT ?")
    .bind(accountId, limit)
    .all<Scan>();
  return results ?? [];
}

/**
 * The quota question, asked once.
 *
 * Counts scans the account actually started inside the window. `blocked` is
 * excluded: a scan we refused cost nothing, so charging quota for it would let
 * a customer lock themselves out by clicking a disabled-looking button.
 */
export async function quotaFor(db: D1Database, account: Account | null): Promise<Quota> {
  const plan = account?.plan ?? "unpaid";
  const limit = scansPerWeek(plan);
  if (!account) {
    return { plan, limit, used: 0, remaining: limit, resetsAt: null };
  }

  const since = now() - QUOTA_WINDOW_SECONDS;
  const row = await db
    .prepare(
      `SELECT COUNT(*) AS used, MIN(created_at) AS oldest FROM scans
       WHERE account_id = ? AND created_at >= ? AND state != 'blocked'`,
    )
    .bind(account.id, since)
    .first<{ used: number; oldest: number | null }>();

  const used = row?.used ?? 0;
  return {
    plan,
    limit,
    used,
    remaining: limit === null ? null : Math.max(limit - used, 0),
    // The next unit frees up when the oldest scan in the window ages out of it.
    resetsAt: row?.oldest ? row.oldest + QUOTA_WINDOW_SECONDS : null,
  };
}

// --- webhook idempotency ----------------------------------------------------

/**
 * True the first time an event id is seen, false on every retry.
 *
 * Both Stripe and GitHub retry deliveries, and a retried
 * `checkout.session.completed` must not be able to act twice.
 */
export async function firstDelivery(
  db: D1Database,
  provider: string,
  eventId: string,
): Promise<boolean> {
  try {
    await db
      .prepare("INSERT INTO webhook_events (provider, event_id, received_at) VALUES (?, ?, ?)")
      .bind(provider, eventId, now())
      .run();
    return true;
  } catch {
    // Primary-key collision: we have processed this delivery already.
    return false;
  }
}

// --- install CSRF state -----------------------------------------------------

export async function issueInstallState(
  db: D1Database,
  accountId: string | null,
): Promise<string> {
  const state = crypto.randomUUID();
  await db
    .prepare("INSERT INTO install_states (state, account_id, created_at) VALUES (?, ?, ?)")
    .bind(state, accountId, now())
    .run();
  return state;
}

const STATE_TTL_SECONDS = 600;

/** Single-use and short-lived: returns the account that started the install. */
export async function consumeInstallState(
  db: D1Database,
  state: string,
): Promise<{ ok: boolean; accountId: string | null }> {
  if (!state) return { ok: false, accountId: null };
  const row = await db
    .prepare("SELECT account_id, created_at FROM install_states WHERE state = ?")
    .bind(state)
    .first<{ account_id: string | null; created_at: number }>();
  if (!row) return { ok: false, accountId: null };

  await db.prepare("DELETE FROM install_states WHERE state = ?").bind(state).run();
  if (now() - row.created_at > STATE_TTL_SECONDS) return { ok: false, accountId: null };
  return { ok: true, accountId: row.account_id };
}
