# Deploying ParaCheck

```
Cloudflare Pages            Next.js app (marketing + dashboard), Clerk sign-in
        |
        v  fetch with a Clerk token
Cloudflare Worker           identity, billing, quota, webhooks  ->  D1 + Queues
        |
        v  queue consumer
Cloudflare Container        git clone, Foundry, solc, Slither  ->  GitHub Check Run
```

The Worker is the control plane and never compiles anything. The container is
the only part that sees customer source.

Containers and Queues both require a **paid Workers plan**.

---

## 1. Accounts and secrets you need first

| Where | What | Notes |
| --- | --- | --- |
| Cloudflare | account + paid Workers plan | Containers and Queues are not on the free plan |
| GitHub | a GitHub App | created in step 5, after you know your Worker URL |
| Clerk | an application | publishable key (public) + secret key |
| Stripe | two recurring Prices | $9/month and $29/month |
| Anthropic | nothing | customers bring their own key; you never pay for inference |

---

## 2. Cloudflare resources

```bash
cd cloudflare
npm install
npx wrangler login

# D1
npx wrangler d1 create paracheck          # copy the database_id into wrangler.toml
npm run db:remote                         # applies schema.sql

# Queues
npx wrangler queues create paracheck-scans
npx wrangler queues create paracheck-scans-dlq
```

Set `database_id` in `wrangler.toml` to the id D1 printed, and `PUBLIC_URL` to
the domain the Next.js app will be served from.

---

## 3. Worker secrets

```bash
cd cloudflare
for s in CLERK_SECRET_KEY GITHUB_APP_ID GITHUB_WEBHOOK_SECRET \
         GITHUB_CLIENT_ID GITHUB_CLIENT_SECRET \
         STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET \
         STRIPE_HOBBY_PRICE_ID STRIPE_PRO_PRICE_ID ENCRYPTION_KEY; do
  npx wrangler secret put "$s"
done

# From the file, not pasted as one line - a PEM mangled into literal \n looks
# set and then fails at the first token mint, inside a queue consumer.
npx wrangler secret put GITHUB_APP_PRIVATE_KEY < your-app.private-key.pem
```

`ENCRYPTION_KEY` is yours to generate and encrypts customers' Anthropic keys at
rest: `openssl rand -base64 32`. **Rotating it makes every stored key
unreadable** — scans keep working, they just fall back to deterministic
findings until each customer re-enters a key.

---

## 4. Deploy the Worker and container

`wrangler deploy` builds `Dockerfile.analyzer`, pushes it to Cloudflare's
registry and rolls out the Worker together:

```bash
cd cloudflare
npx wrangler deploy
curl https://<your-worker>.workers.dev/api/health
```

`/api/health` names anything still unconfigured. It should report
`{"ok": true, "missing": []}` before you point GitHub at it.

---

## 5. The GitHub App

Create it at **Settings → Developer settings → GitHub Apps → New**.

| Field | Value |
| --- | --- |
| Homepage URL | your Pages URL |
| Callback URL | `https://<worker>/api/install/callback` |
| Setup URL | `https://<worker>/api/install/callback` |
| Request user authorization (OAuth) during installation | **on** |
| Webhook URL | `https://<worker>/api/webhooks/github` |
| Webhook secret | the same value you set as `GITHUB_WEBHOOK_SECRET` |

Repository permissions: **Contents: read**, **Pull requests: read**, **Checks:
read & write**, **Metadata: read**.
Subscribe to: **Installation**, **Installation repositories**, **Pull request**.

Put the App's slug in `wrangler.toml` as `GITHUB_APP_SLUG`, then redeploy.

---

## 6. Stripe

Create one product with two recurring monthly Prices — $9 (Hobby) and $29 (Pro)
— and set their ids as `STRIPE_HOBBY_PRICE_ID` / `STRIPE_PRO_PRICE_ID`.

Add a webhook endpoint at `https://<worker>/api/webhooks/stripe` subscribed to:

```
checkout.session.completed
invoice.paid
invoice.payment_failed
customer.subscription.updated
customer.subscription.deleted
```

The signing secret is `STRIPE_WEBHOOK_SECRET`.

The **amounts in Stripe are not read by the app** — the published prices live in
`cloudflare/src/plans.ts` and `web/lib/plans.ts`. If you change one, change all
three, or the page advertises a price the card is not charged.

---

## 7. Clerk

Create an application, then set:

- `CLERK_SECRET_KEY` as a Worker secret
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` as a Pages build variable

In Clerk, add your Pages domain to the allowed origins. If you pin `iss`/`aud`,
set `CLERK_ISSUER` / `CLERK_AUDIENCE` in `wrangler.toml`; leave them empty
otherwise — an empty string would be compared literally and reject every token.

---

## 8. The Next.js app on Pages

```bash
cd web
npm install
npm run build          # static export into web/out
npx wrangler pages deploy out --project-name paracheck
```

Build-time variables:

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | your Worker's URL |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key |
| `NEXT_PUBLIC_SALES_EMAIL` | where Enterprise enquiries go |
| `NEXT_PUBLIC_SITE_URL` | the Pages URL, for metadata |

These are compiled into the bundle, so a change needs a rebuild, and none of
them may be a secret.

---

## 9. Check it end to end

1. `GET /api/health` → `{"ok": true}`.
2. Sign in on the site; the dashboard loads and shows no plan.
3. Subscribe with Stripe test card `4242 4242 4242 4242`; the plan appears.
4. **Connect GitHub**, install on one repository.
5. **Scan now** on that repository → a Check Run appears on the default branch.
6. Open a pull request touching a `.sol` file → a Check Run appears on the PR.
7. Exhaust the weekly quota and confirm the refusal says when it frees up.

---

## Security notes worth keeping

Analysing a repository means running its build system, and `forge install` and
`npm install` execute arbitrary code by design. Three layers, none sufficient
alone:

- **Egress allowlist** (`cloudflare/src/analyzer.ts`) — container internet
  access is off by default and only the hosts a Solidity toolchain needs are
  reachable. A script that steals a secret has nowhere to send it. Widening
  `allowedHosts` widens exactly this.
- **Process sandbox** (`analyzer/static/sandbox.py`) — build tools get an
  allowlisted environment rather than the process's own, `HOME` points at the
  disposable checkout, and CPU, memory, file size and process count are capped.
- **Image** (`Dockerfile.analyzer`) — unprivileged user owning none of its own
  code, read-only compiler cache owned by root.

Quota is counted from the `scans` table over a rolling seven days rather than
granted at checkout. There is no balance to replenish, so a missed recurring
Stripe event cannot leave a paying account throttled to zero.

## Known gaps

- Nothing here has run against a deployed Worker, a real Clerk session or a
  real Stripe checkout.
- The image pre-caches solc 0.8.19, 0.8.20, 0.8.24 and 0.8.28. Foundry resolves
  the newest version matching a project's pragma and downloads anything else on
  first use; that path needs verifying on real amd64 hardware.
- `service/` still contains the previous FastAPI control plane. It is no longer
  the deployment target and can be deleted once the Worker is proven.
