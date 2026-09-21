import { createRemoteJWKSet, jwtVerify } from "jose";

import * as db from "./db";
import type { Env } from "./env";

/**
 * Authenticating a GitHub Actions run, with no shared secret.
 *
 * The analysis runs on the customer's own runner, so it has to prove to us
 * which repository it is before we count a scan against an account. The
 * obvious way would be a `PARACHECK_TOKEN` repository secret, but that is a
 * long-lived credential the customer has to create, store and rotate - and one
 * that a malicious workflow in any other repo could replay if it leaked.
 *
 * GitHub Actions can instead mint a short-lived OIDC token whose claims name
 * the repository, signed by GitHub. We verify it against GitHub's public keys,
 * so the proof is cryptographic and the customer configures nothing.
 *
 * The audience is pinned: without it, a token minted for some other service
 * would verify here too.
 */

const ISSUER = "https://token.actions.githubusercontent.com";
export const AUDIENCE = "paracheck";

// Cached across requests by the runtime, so the JWKS is not refetched per scan.
let jwks: ReturnType<typeof createRemoteJWKSet> | null = null;

function keys() {
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(`${ISSUER}/.well-known/jwks`));
  }
  return jwks;
}

export interface ActionsIdentity {
  repository: string;       // "owner/repo"
  repositoryOwner: string;
  repositoryId: string;
  workflowRef: string;
  runId: string | null;
}

/**
 * Verifies `Authorization: Bearer <OIDC token>`.
 *
 * Returns null rather than throwing: a bad token is a 401, not an incident.
 */
export async function identityFrom(request: Request): Promise<ActionsIdentity | null> {
  const header = request.headers.get("authorization") ?? "";
  if (!header.startsWith("Bearer ")) return null;

  try {
    const { payload } = await jwtVerify(header.slice("Bearer ".length), keys(), {
      issuer: ISSUER,
      audience: AUDIENCE,
    });

    const repository = payload.repository as string | undefined;
    if (!repository || !repository.includes("/")) return null;

    return {
      repository,
      repositoryOwner: (payload.repository_owner as string) ?? repository.split("/")[0],
      repositoryId: String(payload.repository_id ?? ""),
      workflowRef: (payload.job_workflow_ref as string) ?? "",
      runId: (payload.run_id as string) ?? null,
    };
  } catch {
    return null;
  }
}

/**
 * The installation and account a verified run belongs to.
 *
 * A run proves which repository it is, not who pays for it. That link is ours:
 * the repository must be one an installation actually granted us, and that
 * installation must be claimed by an account. Anything else - an uninstalled
 * repo, an installation nobody signed in for - has no account to bill and is
 * refused rather than scanned for free.
 */
export async function accountForRepository(
  env: Env,
  repository: string,
): Promise<{ accountId: string; installationId: number } | null> {
  const row = await env.DB.prepare(
    `SELECT r.installation_id AS installation_id, i.account_id AS account_id
       FROM repositories r
       JOIN installations i ON i.id = r.installation_id
      WHERE r.full_name = ? AND r.active = 1 AND i.active = 1
        AND i.account_id IS NOT NULL
      LIMIT 1`,
  )
    .bind(repository)
    .first<{ installation_id: number; account_id: string }>();

  if (!row) return null;
  return { accountId: row.account_id, installationId: row.installation_id };
}

/** Re-exported so routes can record without importing db twice. */
export { db };
