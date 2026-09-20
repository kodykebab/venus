import { createRemoteJWKSet, jwtVerify } from "jose";

export interface Env {
  DB: D1Database;
  ENVIRONMENT: string;
  DEMO_ORIGIN: string;
  CLERK_JWKS_URL: string;
  CLERK_ISSUER: string;
  CLERK_AUDIENCE: string;
}

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

async function clerkUserId(request: Request, env: Env): Promise<string | null> {
  const authorization = request.headers.get("authorization") || "";
  const [scheme, token] = authorization.split(" ");
  if (scheme?.toLowerCase() !== "bearer" || !token || !env.CLERK_JWKS_URL) {
    return null;
  }

  try {
    const jwks = createRemoteJWKSet(new URL(env.CLERK_JWKS_URL));
    const { payload } = await jwtVerify(token, jwks, {
      issuer: env.CLERK_ISSUER || undefined,
      audience: env.CLERK_AUDIENCE || undefined,
    });
    return typeof payload.sub === "string" ? payload.sub : null;
  } catch {
    return null;
  }
}

export default {
  async fetch(request: Request, _env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/healthz") {
      return json({ ok: true, service: "paracheck-control-plane", ready: false });
    }

    if (request.method === "GET" && url.pathname === "/account") {
      const userId = await clerkUserId(request, _env);
      return userId ? json({ authenticated: true, userId }) : json({ error: "sign in required" }, 401);
    }

    // Keep unimplemented control-plane routes explicit. This prevents a partial
    // deployment from appearing to accept payments or GitHub webhooks.
    if (["/checkout", "/github/webhook", "/stripe/webhook"].includes(url.pathname)) {
      return json({ error: "control plane not ready for production" }, 501);
    }

    return json({ error: "not found" }, 404);
  },
};
