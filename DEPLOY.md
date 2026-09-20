# Deploying ParaCheck on Cloudflare

ParaCheck's launch architecture is Cloudflare plus GitHub Actions:

- Cloudflare Pages hosts the static demo in `demo-page/`.
- A Cloudflare Worker owns Clerk, Stripe, GitHub webhook, quota, and D1 control-plane work.
- GitHub Actions runs Foundry, solc, Slither, and ParaCheck against the repository.
- Claude is disabled for launch with `PARACHECK_CLAUDE_ENABLED=0`.

The Worker scaffold lives in `cloudflare/`. It currently typechecks and has a
health endpoint, but its payment/webhook routes intentionally return `501` until
the control plane is implemented.

## 1. Prerequisites

Install and authenticate the tools:

```bash
npm install
npm install -g wrangler
wrangler login
```

You also need accounts for:

- Cloudflare Pages, Workers, and D1.
- Clerk for account authentication.
- Stripe for paid plans and webhooks.
- A GitHub App for repository installation/webhooks.

Do not paste private keys, API secrets, or webhook secrets into chat or commit
them to the repository. Enter them directly when Wrangler prompts for them.

## 2. Cloudflare Pages

Deploy the static demo first:

```bash
cd demo-page
npx wrangler pages project create paracheck-demo
npx wrangler pages deploy . --project-name paracheck-demo
```

Alternatively connect the repository in the Cloudflare Pages dashboard. Use
`demo-page` as the build output directory; it is already static and needs no
build command.

## 3. Cloudflare Worker and D1

```bash
cd cloudflare
npm install
npx wrangler d1 create paracheck
```

Copy the returned database id into `cloudflare/wrangler.toml`, then initialize
local and remote schemas:

```bash
npx wrangler d1 execute paracheck --local --file=schema.sql
npx wrangler d1 execute paracheck --remote --file=schema.sql
npx wrangler dev
```

The current scaffold is not production-ready yet. `/healthz` reports
`ready: false`; `/checkout`, `/github/webhook`, and `/stripe/webhook` return
`501` until implemented.

## 4. Keys and where to get them

### Clerk

From the Clerk Dashboard:

- `CLERK_PUBLISHABLE_KEY`: public browser key, usually starts with `pk_live_`.
- `CLERK_JWT_KEY`: server-side verification key from the Clerk JWT template.
- `CLERK_ISSUER`: issuer URL from that JWT template.
- `CLERK_AUDIENCE`: the audience configured for the template.

Only the publishable key belongs in browser-facing configuration. Put the JWT
verification key in Worker secrets with `wrangler secret put`.

### Stripe

From the Stripe Dashboard:

- `STRIPE_SECRET_KEY`: server secret key.
- `STRIPE_HOBBY_PRICE_ID`: recurring Price for Hobby.
- `STRIPE_PRO_PRICE_ID`: recurring Price for Pro.
- `STRIPE_WEBHOOK_SECRET`: signing secret for the Worker webhook endpoint.

Use the agreed launch prices only after creating the corresponding recurring
Prices in Stripe:

- Hobby: `$9/month`, 20 reviews.
- Pro: `$29/month`, 100 reviews.
- Enterprise: custom, handled through the mailto form.

Configure Stripe events for:

- `checkout.session.completed`
- `invoice.paid`
- `customer.subscription.deleted`
- `invoice.payment_failed`

### GitHub App

From GitHub App settings:

- `GITHUB_APP_ID`: numeric App ID.
- `GITHUB_APP_PRIVATE_KEY`: generated PEM private key.
- `GITHUB_WEBHOOK_SECRET`: webhook signing secret.
- `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`: OAuth credentials if the setup flow uses GitHub OAuth.

The App needs least-privilege access to repository contents, pull requests, and
checks. The Worker must verify GitHub signatures before parsing webhook bodies.

### Enterprise

Set `ENTERPRISE_SALES_EMAIL` to the inbox that should receive the browser
`mailto:` Enterprise enquiry. No SMTP service is required.

### Claude

Do not configure these for launch:

```env
PARACHECK_CLAUDE_ENABLED=0
ANTHROPIC_API_KEY=
```

## 5. Set Worker secrets

From `cloudflare/`, run each command directly and enter the value at the prompt:

```bash
npx wrangler secret put CLERK_JWT_KEY
npx wrangler secret put CLERK_ISSUER
npx wrangler secret put CLERK_AUDIENCE
npx wrangler secret put GITHUB_APP_ID
npx wrangler secret put GITHUB_APP_PRIVATE_KEY
npx wrangler secret put GITHUB_WEBHOOK_SECRET
npx wrangler secret put STRIPE_SECRET_KEY
npx wrangler secret put STRIPE_HOBBY_PRICE_ID
npx wrangler secret put STRIPE_PRO_PRICE_ID
npx wrangler secret put STRIPE_WEBHOOK_SECRET
npx wrangler secret put ENTERPRISE_SALES_EMAIL
```

Never put these values in `wrangler.toml`, `schema.sql`, GitHub commits, or
client-side JavaScript.

## 6. GitHub Actions execution

The current `.github/actions/analyze` is a composite action. A customer
repository needs a workflow that invokes it. The initial rollout can provide a
copy-paste workflow file.

The full GitHub App experience still needs the Worker to:

1. Receive and verify the installation webhook.
2. Mint an installation token.
3. Create or update the ParaCheck workflow in selected repositories.
4. Dispatch or respond to pull-request workflow events.
5. Decrement quota atomically in D1 before dispatch.
6. Restore quota if dispatch fails.

Do not advertise automatic installation until this private-repository flow is
end-to-end tested.

## 7. Deploy

Only after the Worker implementation is complete and `ready` is true:

```bash
cd cloudflare
npm run typecheck
npx wrangler d1 execute paracheck --remote --file=schema.sql
npx wrangler deploy
```

Then configure:

- Clerk allowed origins and redirects for the Pages/Worker domains.
- GitHub App webhook URL: `https://YOUR_WORKER_DOMAIN/github/webhook`.
- Stripe webhook URL: `https://YOUR_WORKER_DOMAIN/stripe/webhook`.
- The Pages frontend's API origin to the Worker domain.

## Cost guardrails

- Keep Claude disabled.
- Use fixed Hobby/Pro review quotas.
- Reject reviews when quota is exhausted.
- Deduplicate Stripe and GitHub webhook event IDs in D1.
- Treat GitHub Actions minutes as a potentially variable cost and document who
  pays for private-repository Actions usage.
- Do not delete or replace the analyzer action until a private-repository test
  passes end to end.
