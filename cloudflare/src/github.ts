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

// --- adding the workflow file for the customer --------------------------------

/** The workflow file we open a PR to add when a repository doesn't have one yet. */
const WORKFLOW_TEMPLATE = `# ParaCheck — parallelism and gas analysis for Solidity.
#
# The analysis runs here, on your own runner, so ParaCheck never receives a copy
# of your source. It authenticates to the ParaCheck API with a GitHub OIDC
# token, which GitHub mints for this run and signs — there is no secret to
# create, store or rotate.

name: ParaCheck

on:
  pull_request:
    paths:
      - "**.sol"
      - "foundry.toml"
      - "hardhat.config.*"
  # Lets the Scan now button in the ParaCheck dashboard start a run.
  workflow_dispatch: {}

# Least privilege: read the code, write the check, prove who we are.
# \`id-token\` is what makes the secretless authentication work.
permissions:
  contents: read
  checks: write
  id-token: write

concurrency:
  # A newer push supersedes a scan nobody is waiting on any more.
  group: paracheck-\${{ github.ref }}
  cancel-in-progress: true

jobs:
  analyze:
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - uses: actions/checkout@v4

      - name: Analyze with ParaCheck
        uses: kodykebab/venus/.github/actions/paracheck@main
        with:
          target: "."
          chain: monad
          # Set to \`high\` to fail the check — and block the merge — when a
          # high-severity finding appears. Empty means report only.
          fail-on: ""
`;

const WORKFLOW_PATH = ".github/workflows/paracheck.yml";
const BRANCH_NAME = "paracheck/add-workflow";

function utf8ToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/**
 * Opens a pull request that adds the ParaCheck workflow file.
 *
 * Deliberately a pull request, not a direct commit to the default branch: the
 * customer reviews and merges it themselves, which is both the safer thing to
 * do with write access to someone else's repository and the standard pattern
 * (Dependabot and Renovate both onboard this way). Nothing runs until they
 * merge it - opening the PR does not by itself grant scanning.
 *
 * Requires the App to hold Contents:write and Pull requests:write. Without
 * them this fails cleanly and the caller falls back to the manual-copy
 * instructions.
 */
export async function proposeWorkflowFile(
  env: Env,
  installationId: number,
  repository: string,
): Promise<{ ok: boolean; reason: string; prUrl?: string }> {
  let token: InstallationToken;
  try {
    token = await installationToken(env, installationId);
  } catch {
    return { ok: false, reason: "Could not authenticate with GitHub for this installation." };
  }
  const auth = headers(token.token);

  const repoResponse = await fetch(`${API}/repos/${repository}`, { headers: auth });
  if (!repoResponse.ok) {
    return { ok: false, reason: "ParaCheck cannot read that repository any more." };
  }
  const repoInfo = (await repoResponse.json()) as { default_branch: string; permissions?: Record<string, boolean> };
  const base = repoInfo.default_branch;

  // An existing open PR from a previous attempt is reused rather than
  // recreated, so clicking the button twice doesn't open two PRs.
  const existingPr = await findOpenPr(repository, auth, base);
  if (existingPr) return { ok: true, reason: "", prUrl: existingPr };

  const baseRefResponse = await fetch(`${API}/repos/${repository}/git/ref/heads/${base}`, {
    headers: auth,
  });
  if (!baseRefResponse.ok) {
    return { ok: false, reason: "Could not read the default branch." };
  }
  const baseSha = ((await baseRefResponse.json()) as { object: { sha: string } }).object.sha;

  const branchResponse = await fetch(`${API}/repos/${repository}/git/refs`, {
    method: "POST",
    headers: auth,
    body: JSON.stringify({ ref: `refs/heads/${BRANCH_NAME}`, sha: baseSha }),
  });
  if (!branchResponse.ok && branchResponse.status !== 422) {
    // 422 means the ref already exists - from a previous attempt whose PR was
    // since closed. Anything else is a real failure.
    if (branchResponse.status === 403 || branchResponse.status === 404) {
      return {
        ok: false,
        reason:
          "ParaCheck doesn't have permission to write to this repository yet. " +
          "Creating a branch needs the GitHub App's Contents write permission - grant it, " +
          "approve the update on the installation, then try again, or add the workflow file yourself.",
      };
    }
    return { ok: false, reason: `Could not create a branch (${branchResponse.status}).` };
  }

  const fileResponse = await fetch(`${API}/repos/${repository}/contents/${WORKFLOW_PATH}`, {
    method: "PUT",
    headers: auth,
    body: JSON.stringify({
      message: "Add ParaCheck workflow",
      content: utf8ToBase64(WORKFLOW_TEMPLATE),
      branch: BRANCH_NAME,
    }),
  });
  if (!fileResponse.ok) {
    // The file already exists on this branch from an earlier partial attempt,
    // or on the target branch itself - either way there's nothing more to add.
    if (fileResponse.status !== 422) {
      const detail = await fileResponse.text().catch(() => "");
      console.log(`proposeWorkflowFile: contents PUT -> ${fileResponse.status} ${detail.slice(0, 300)}`);
      // Committing under .github/workflows/ needs the App's dedicated Workflows
      // permission - Contents:write alone is refused with a 403. This is the
      // one that trips people up: the branch is created (that only needs
      // Contents) and then the workflow file itself is rejected.
      const hint =
        fileResponse.status === 403
          ? " Adding a file under .github/workflows/ needs the GitHub App's Workflows permission" +
            " (write), which is separate from Contents. Grant it, approve the update on the" +
            " installation, then try again."
          : "";
      return { ok: false, reason: `Could not add the workflow file (${fileResponse.status}).${hint}` };
    }
  }

  console.log(`proposeWorkflowFile: branch=${branchResponse.status} file=${fileResponse.status} base=${base}`);

  const prResponse = await fetch(`${API}/repos/${repository}/pulls`, {
    method: "POST",
    headers: auth,
    body: JSON.stringify({
      title: "Add ParaCheck",
      head: BRANCH_NAME,
      base,
      body:
        "Adds `.github/workflows/paracheck.yml`.\n\n" +
        "Nothing runs on your repository until this is merged - review it first. " +
        "Once merged, ParaCheck scans pull requests that touch `.sol` files, and the " +
        "**Scan now** button on the dashboard starts working for this repository.\n\n" +
        "The workflow runs on your own GitHub Actions runner. ParaCheck never receives " +
        "a copy of your source.",
    }),
  });
  if (!prResponse.ok) {
    // Surface GitHub's own message: 403 means Pull requests write is not
    // effective; 422 usually means the branch has no commit the base lacks.
    const detail = await prResponse.text().catch(() => "");
    console.log(`proposeWorkflowFile: pulls POST -> ${prResponse.status} ${detail.slice(0, 300)}`);
    const again = await findOpenPr(repository, auth, base);
    if (again) return { ok: true, reason: "", prUrl: again };
    const hint =
      prResponse.status === 403
        ? " The App has no Pull requests write access on this installation yet - approve the permission update, then try again."
        : prResponse.status === 422
          ? " GitHub reports nothing to open a PR from - the workflow file may already be on the default branch."
          : "";
    return { ok: false, reason: `Could not open the pull request (${prResponse.status}).${hint}` };
  }
  const pr = (await prResponse.json()) as { html_url: string };
  return { ok: true, reason: "", prUrl: pr.html_url };
}

async function findOpenPr(
  repository: string,
  auth: Record<string, string>,
  base: string,
): Promise<string | null> {
  const response = await fetch(
    `${API}/repos/${repository}/pulls?state=open&head=${repository.split("/")[0]}:${BRANCH_NAME}&base=${base}`,
    { headers: auth },
  );
  if (!response.ok) return null;
  const pulls = (await response.json()) as Array<{ html_url: string }>;
  return pulls[0]?.html_url ?? null;
}
