import { createClerkClient, verifyToken } from "@clerk/backend";

import * as db from "./db";
import type { Env } from "./env";

/**
 * Who is making this request.
 *
 * Clerk is the account identity: it decides which account a request belongs to
 * and therefore what it may be billed for. GitHub remains the authority on
 * which repositories may be read - the two are not interchangeable, and the
 * dangerous mistake would be letting a Clerk session imply repository access.
 * Every route that touches a repository checks ownership in D1 as well.
 */

export interface Session {
  accountId: string;
  email: string | null;
  kind: "user" | "org";
}

/**
 * Verifies the `Authorization: Bearer <clerk token>` header.
 *
 * Returns null rather than throwing: an expired session is an ordinary 401,
 * not an error worth a stack trace.
 */
export async function sessionFrom(request: Request, env: Env): Promise<Session | null> {
  const header = request.headers.get("authorization") ?? "";
  if (!header.startsWith("Bearer ")) return null;

  try {
    const claims = await verifyToken(header.slice("Bearer ".length), {
      secretKey: env.CLERK_SECRET_KEY,
      // Only set when the deployment pins them; an empty string would be
      // checked literally and reject every otherwise-valid token.
      ...(env.CLERK_ISSUER ? { issuer: env.CLERK_ISSUER } : {}),
      ...(env.CLERK_AUDIENCE ? { audience: env.CLERK_AUDIENCE } : {}),
    });

    // An active organisation means the org is the customer, so the bill and the
    // quota belong to it rather than to whoever happens to be signed in.
    const orgId = (claims as { org_id?: string }).org_id;
    const accountId = orgId ?? claims.sub;
    if (!accountId) return null;

    return {
      accountId,
      email: (claims as { email?: string }).email ?? null,
      kind: orgId ? "org" : "user",
    };
  } catch {
    return null;
  }
}

/** Ensures the account row exists, so later writes have something to update. */
export async function requireAccount(request: Request, env: Env): Promise<Session | null> {
  const session = await sessionFrom(request, env);
  if (!session) return null;
  await db.upsertAccount(env.DB, session.accountId, session.kind, session.email);
  return session;
}

/**
 * The installation, but only if this account owns it.
 *
 * Installation ids are small sequential integers, so without this check any
 * signed-in user could read - and spend quota on - somebody else's
 * repositories by guessing.
 */
export async function ownedInstallation(
  env: Env,
  session: Session,
  installationId: number,
): Promise<db.Installation | null> {
  const installation = await db.getInstallation(env.DB, installationId);
  if (!installation || !installation.active) return null;
  if (installation.account_id !== session.accountId) return null;
  return installation;
}

/** Looks up an email for an account, used to prefill Stripe Checkout. */
export async function emailFor(env: Env, session: Session): Promise<string | null> {
  if (session.email) return session.email;
  try {
    const clerk = createClerkClient({ secretKey: env.CLERK_SECRET_KEY });
    if (session.kind === "user") {
      const user = await clerk.users.getUser(session.accountId);
      return user.primaryEmailAddress?.emailAddress ?? null;
    }
  } catch {
    // Not worth failing a checkout over: Stripe will collect one.
  }
  return null;
}
