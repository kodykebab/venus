# Cloudflare Control Plane

This directory is the planned low-cost deployment for ParaCheck. It is not a
replacement for the analyzer runtime.

## Responsibilities

The Worker will own:

- Clerk session verification and account lookup.
- Stripe Checkout creation and webhook handling.
- GitHub webhook signature verification.
- Paid quota checks and review-run records in D1.
- Dispatching an approved review workflow to GitHub Actions.
- Enterprise contact routing and dashboard APIs.

Cloudflare Pages hosts the static demo and public UI. GitHub Actions owns the
expensive and untrusted work: repository checkout, dependency installation,
Foundry, solc, Slither, and ParaCheck.

Claude remains disabled for launch. The Worker must never require or forward an
Anthropic key unless the future BYOK feature is explicitly enabled.

## Important GitHub limitation

The current `.github/actions/analyze` is a composite action. A customer
repository still needs a workflow that invokes it. A Worker cannot run a
composite action by itself.

There are two rollout options:

1. Initial low-cost rollout: document a one-time workflow file customers add to
   their repository. The workflow runs on pull requests and uses the public
   ParaCheck action.
2. Full GitHub App rollout: the Worker receives the installation webhook, mints
   an installation token, creates or updates a ParaCheck workflow in each
   selected repository, and dispatches the review through GitHub Actions.

Do not advertise the full automatic GitHub App experience until option 2 is
implemented and tested with a private repository.

## Local setup

Install Wrangler and create the D1 database:

```bash
cd cloudflare
npm install -D wrangler typescript @cloudflare/workers-types
npx wrangler login
npx wrangler d1 create paracheck
npx wrangler d1 execute paracheck --local --file=schema.sql
```

Copy the returned database id into `wrangler.toml`. Set production secrets with
`wrangler secret put`; never put private keys, Clerk JWT keys, or Stripe secrets
in `wrangler.toml`.

## Required Worker endpoints

- `GET /healthz`
- `POST /github/webhook`
- `POST /stripe/webhook`
- `POST /checkout`
- `GET /account`
- `GET /reviews`

## Required implementation before deployment

- Verify Clerk JWTs with `jose` and enforce issuer/audience.
- Verify GitHub HMAC signatures before parsing webhook JSON.
- Verify Stripe signatures and deduplicate webhook event IDs in D1.
- Atomically decrement review quota before dispatching a workflow.
- Restore quota if dispatch fails.
- Use GitHub installation tokens only for the selected installation.
- Never log tokens, private keys, webhook payload secrets, or Anthropic keys.
- Add tests for replayed webhooks, concurrent quota claims, failed dispatches,
  and unauthorized account access.

## Deployment sequence

```bash
cd cloudflare
npx wrangler d1 execute paracheck --remote --file=schema.sql
npx wrangler secret put CLERK_JWT_KEY
npx wrangler secret put CLERK_ISSUER
npx wrangler secret put CLERK_AUDIENCE
npx wrangler secret put GITHUB_APP_ID
npx wrangler secret put GITHUB_APP_PRIVATE_KEY
npx wrangler secret put GITHUB_WEBHOOK_SECRET
npx wrangler secret put STRIPE_WEBHOOK_SECRET
npx wrangler deploy
```

Cloudflare Pages can deploy `demo-page/` separately. Do not advertise the Worker
as production-ready until its private-repository end-to-end test passes.
