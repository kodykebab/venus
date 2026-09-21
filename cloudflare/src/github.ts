import { b64decode, hmacSha256Hex, timingSafeEqual } from "./crypto";
import type { Env } from "./env";

/**
 * GitHub App authentication and the Checks API.
 *
 * Two token types, and the difference matters: the App JWT proves we are the
 * App and can do almost nothing on its own, while an installation token is
 * scoped to one installation's repositories and expires in an hour. Only the
 * second ever touches a repository, and it is minted per job rather than held.
 */

const API = "https://api.github.com";

const headers = (token: string) => ({
  authorization: `Bearer ${token}`,
  accept: "application/vnd.github+json",
  "content-type": "application/json",
  "user-agent": "paracheck",
  "x-github-api-version": "2022-11-28",
});

/** Minimal DER: wrap `content` in a tag with a correctly encoded length. */
function derTagged(tag: number, content: Uint8Array): Uint8Array {
  let length: number[];
  if (content.length < 0x80) {
    length = [content.length];
  } else {
    const bytes: number[] = [];
    for (let n = content.length; n > 0; n = Math.floor(n / 256)) bytes.unshift(n % 256);
    length = [0x80 | bytes.length, ...bytes];
  }
  return new Uint8Array([tag, ...length, ...content]);
}

/**
 * PKCS#1 -> PKCS#8.
 *
 * GitHub hands out "BEGIN RSA PRIVATE KEY", which is PKCS#1. WebCrypto only
 * imports PKCS#8, so without this every GitHub App key ever issued would be
 * rejected - and the symptom is an opaque DataError at the first token mint,
 * long after the key looked fine in the config.
 *
 * The conversion is pure structure: PKCS#8 is a SEQUENCE of a version, the
 * rsaEncryption algorithm identifier, and the original PKCS#1 DER as an OCTET
 * STRING. No key material changes.
 */
function pkcs1ToPkcs8(pkcs1: Uint8Array): Uint8Array {
  const version = [0x02, 0x01, 0x00];
  // AlgorithmIdentifier: OID 1.2.840.113549.1.1.1 (rsaEncryption), NULL params.
  const algorithm = [
    0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86,
    0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00,
  ];
  const wrapped = derTagged(0x04, pkcs1);
  const body = new Uint8Array([...version, ...algorithm, ...wrapped]);
  return derTagged(0x30, body);
}

/** A PEM in either shape -> a WebCrypto signing key. */
async function importPrivateKey(pem: string): Promise<CryptoKey> {
  const isPkcs1 = pem.includes("BEGIN RSA PRIVATE KEY");
  const body = pem
    .replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----/, "")
    .replace(/-----END [A-Z ]*PRIVATE KEY-----/, "")
    .replace(/\s+/g, "");

  const der = b64decode(body);
  return crypto.subtle.importKey(
    "pkcs8",
    isPkcs1 ? pkcs1ToPkcs8(der) : der,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

function b64url(input: string | Uint8Array): string {
  const bytes = typeof input === "string" ? new TextEncoder().encode(input) : input;
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function appJwt(env: Env): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  // Backdated a minute: GitHub rejects a token whose iat is in the future, and
  // small clock differences between us and them are normal.
  const payload = b64url(
    JSON.stringify({ iat: now - 60, exp: now + 540, iss: env.GITHUB_APP_ID }),
  );
  const key = await importPrivateKey(env.GITHUB_APP_PRIVATE_KEY);
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(`${header}.${payload}`),
  );
  return `${header}.${payload}.${b64url(new Uint8Array(signature))}`;
}

export interface InstallationToken {
  token: string;
  expiresAt: string;
}

export async function installationToken(
  env: Env,
  installationId: number,
): Promise<InstallationToken> {
  const jwt = await appJwt(env);
  const response = await fetch(`${API}/app/installations/${installationId}/access_tokens`, {
    method: "POST",
    headers: headers(jwt),
  });
  if (!response.ok) {
    throw new Error(`could not mint an installation token: ${response.status}`);
  }
  const data = (await response.json()) as { token: string; expires_at: string };
  return { token: data.token, expiresAt: data.expires_at };
}

/**
 * Verifies `X-Hub-Signature-256` over the raw body.
 *
 * Without this anyone who learns the webhook URL can invent installations and
 * pull requests, so an unsigned or mis-signed delivery is rejected outright.
 */
export async function verifyWebhook(
  secret: string,
  body: string,
  signatureHeader: string | null,
): Promise<boolean> {
  if (!secret || !signatureHeader?.startsWith("sha256=")) return false;
  const expected = await hmacSha256Hex(secret, body);
  return timingSafeEqual(signatureHeader.slice("sha256=".length), expected);
}

export async function exchangeOAuthCode(
  env: Env,
  code: string,
): Promise<{ login: string; type: string } | null> {
  const tokenResponse = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
    }),
  });
  if (!tokenResponse.ok) return null;
  const { access_token } = (await tokenResponse.json()) as { access_token?: string };
  if (!access_token) return null;

  const userResponse = await fetch(`${API}/user`, { headers: headers(access_token) });
  if (!userResponse.ok) return null;
  const user = (await userResponse.json()) as { login: string; type: string };
  // The user token is used here and deliberately not stored: the installation
  // token is what the service needs to do its job.
  return { login: user.login, type: user.type };
}

// --- Checks API -------------------------------------------------------------

export async function createCheckRun(
  repository: string,
  headSha: string,
  token: string,
): Promise<number | null> {
  const response = await fetch(`${API}/repos/${repository}/check-runs`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({
      name: "ParaCheck",
      head_sha: headSha,
      status: "in_progress",
      started_at: new Date().toISOString(),
      output: {
        title: "Analysing",
        summary: "Looking for expensive storage, execution and parallelism patterns.",
      },
    }),
  });
  if (!response.ok) {
    console.error(`paracheck: could not create a check run: ${response.status}`);
    return null;
  }
  return ((await response.json()) as { id: number }).id;
}

export async function completeCheckRun(
  repository: string,
  checkRunId: number,
  token: string,
  result: {
    conclusion: string;
    title: string;
    summary: string;
    annotations?: unknown[];
  },
): Promise<void> {
  // The Checks API takes at most 50 annotations per request. More than that in
  // one review is noise anyway, so they are capped rather than paginated.
  const annotations = (result.annotations ?? []).slice(0, 50);
  const response = await fetch(`${API}/repos/${repository}/check-runs/${checkRunId}`, {
    method: "PATCH",
    headers: headers(token),
    body: JSON.stringify({
      status: "completed",
      completed_at: new Date().toISOString(),
      conclusion: result.conclusion,
      output: { title: result.title, summary: result.summary, annotations },
    }),
  });
  if (!response.ok) {
    console.error(`paracheck: could not complete check run ${checkRunId}: ${response.status}`);
  }
}

/** A finished check that explains a failure, rather than a check that never appears. */
export async function failCheckRun(
  repository: string,
  checkRunId: number,
  token: string,
  reason: string,
): Promise<void> {
  await completeCheckRun(repository, checkRunId, token, {
    conclusion: "neutral",
    title: "Could not analyse this change",
    summary: reason,
  });
}

/**
 * Triggers the customer's ParaCheck workflow.
 *
 * This is the "Scan now" button. It needs the workflow file to exist in the
 * repository's default branch, which is why a 404 here is reported as "add the
 * workflow" rather than as a failure - that is what it almost always means.
 */
export async function dispatchWorkflow(
  env: Env,
  installationId: number,
  repository: string,
  workflow = "paracheck.yml",
): Promise<{ ok: boolean; reason: string; needsWorkflow?: boolean }> {
  let token: InstallationToken;
  try {
    token = await installationToken(env, installationId);
  } catch {
    return { ok: false, reason: "Could not authenticate with GitHub for this installation." };
  }

  const repoResponse = await fetch(`${API}/repos/${repository}`, {
    headers: headers(token.token),
  });
  if (!repoResponse.ok) {
    return { ok: false, reason: "ParaCheck cannot read that repository any more." };
  }
  const { default_branch } = (await repoResponse.json()) as { default_branch: string };

  const response = await fetch(
    `${API}/repos/${repository}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: headers(token.token),
      body: JSON.stringify({ ref: default_branch }),
    },
  );

  if (response.status === 204) return { ok: true, reason: "" };
  if (response.status === 404) {
    return {
      ok: false,
      needsWorkflow: true,
      reason:
        "This repository has no .github/workflows/paracheck.yml on its default branch yet. Add it and scans can run.",
    };
  }
  return {
    ok: false,
    reason: `GitHub refused to start the workflow (${response.status}).`,
  };
}
