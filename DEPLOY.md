# Deploying ParaCheck

```
Cloudflare Worker (static assets)   the Next.js site, Clerk sign-in
        |
        v  fetch with a Clerk token
Cloudflare Worker (control plane)   identity, billing, quota, webhooks  ->  D1
        |
        v  workflow_dispatch / the repo's own pull_request trigger
GitHub Actions (customer's runner)  git, Foundry, solc, Slither  ->  GitHub Check Run
        |
        +-- authenticates back with a GitHub OIDC token, not a secret
```

The Worker is the control plane. It never compiles anything and never receives
a copy of customer source — the analysis runs where the code already is.

**Everything here runs on free tiers.** Workers, D1 and static assets are all
within the free plan. There is no container and no queue: Cloudflare Containers
require Workers Paid, which is what moved the compute to GitHub Actions.

---

## What is live now

| Piece | URL |
| --- | --- |
| Site | https://paracheck-web.kritarthshankr.workers.dev |
| API | https://paracheck-control-plane.kritarthshankr.workers.dev |
| Health | `/api/health` → `{"ok": true, "missing": []}` |
| GitHub App | https://github.com/apps/paracheck (App ID 5015487) |

Plans, from `cloudflare/src/plans.ts`:

| Plan | Price | Scans / rolling 30 days |
| --- | --- | --- |
| Free | $0 | 10 |
| Pro | $24.99/mo | 100 |
| Team | $49.99/mo | 250 |
| Enterprise | custom | agreed in the contract |

---

## 1. Accounts you need

| Where | What |
| --- | --- |
| Cloudflare | free account; `wrangler login` needs the `containers:write` scope only if you ever go back to Containers |
| GitHub | a GitHub App (below) |
| Clerk | an application — publishable key (public) + secret key |
| Stripe | two recurring Prices, for Pro and Team |
| Anthropic | nothing. Customers bring their own key; you never pay for inference |

---

## 2. Cloudflare resources

> **Applying `schema.sql` to a database that already has tables does almost
> nothing.** Every statement is `CREATE TABLE IF NOT EXISTS`, which is exactly
> as quiet when the existing table is wrong as when it is right. This bit us
> once: the database kept an earlier scaffold's `accounts` table across several
> deploys, and the first signed-in request would have failed on a missing
> column. Always check afterwards:
>
> ```bash
> npx wrangler d1 execute paracheck --remote --command "PRAGMA table_info(accounts)"
> ```
>
> To replace a table that has diverged, rename rather than drop —
> `ALTER TABLE accounts RENAME TO accounts_old` — then re-apply the schema.

```bash
cd cloudflare
npm install                               # needs Node 22+ for wrangler 4
npx wrangler login

npx wrangler d1 create paracheck          # copy database_id into wrangler.toml
npm run db:remote                         # applies schema.sql
```

Set `database_id` and `PUBLIC_URL` in `wrangler.toml`. `PUBLIC_URL` must be the
exact origin the site is served from: CORS reflects only that value, so a stale
one means every dashboard call is blocked by the browser with nothing in the
server logs.

---

## 3. Worker secrets

```bash
cd cloudflare
for s in CLERK_SECRET_KEY GITHUB_APP_ID GITHUB_CLIENT_ID GITHUB_CLIENT_SECRET \
         GITHUB_WEBHOOK_SECRET ENCRYPTION_KEY \
         STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET \
         STRIPE_PRO_PRICE_ID STRIPE_TEAM_PRICE_ID; do
  npx wrangler secret put "$s"
done

# From the file, never pasted as one line: a PEM mangled into literal \n looks
# set and then fails at the first token mint.
npx wrangler secret put GITHUB_APP_PRIVATE_KEY < your-app.private-key.pem
```

`ENCRYPTION_KEY` is yours to generate (`openssl rand -base64 32`) and encrypts
customers' Anthropic keys at rest. **Rotating it makes every stored key
unreadable** — scans keep working, they just fall back to deterministic
findings until each customer re-enters a key.

GitHub issues **PKCS#1** private keys (`BEGIN RSA PRIVATE KEY`). The Worker
converts them; no need to run `openssl pkcs8` first.

---

## 4. Deploy

```bash
cd cloudflare && npx wrangler deploy
cd ../web && npm run build && npx wrangler deploy
curl https://<worker>/api/health
```

The site is an assets-only Worker, not a Pages project: `wrangler pages`
assumes an SSR Next.js app and tries to convert the project to OpenNext. This
export is fully static.

---

## 5. The GitHub App

Create at **github.com/settings/apps/new**.

| Field | Value |
| --- | --- |
| Homepage URL | the site URL |
| Redirect URI | `https://<worker>/api/install/callback` |
| Request user authorization (OAuth) during installation | **on** |
| Webhook URL | `https://<worker>/api/webhooks/github` |
| Webhook secret | same value as `GITHUB_WEBHOOK_SECRET` |
| Where can this be installed | **Any account** |

Repository permissions: **Contents** read & write · **Metadata** read · **Pull
requests** read & write · **Checks** read & write · **Actions** read & write.

Contents and Pull requests need **write**, not read: the "Add workflow" button
opens a pull request that adds `.github/workflows/paracheck.yml`, which means
creating a branch, committing a file and opening the PR. With read-only on
either, branch creation returns 403 and no PR is ever created. (Actions write is
what lets the Scan now button dispatch a workflow.) Changing these after the App
exists requires each installer to approve the new permissions on their
installation before a token carries them.

Subscribe to: **Pull request**. `Installation` and `Installation repositories`
are delivered to Apps automatically and are not in the subscribe list.

Put the App's slug in `wrangler.toml` as `GITHUB_APP_SLUG`.

---

## 6. Stripe

Create two recurring monthly Prices — Pro and Team — and set their `price_...`
ids. The `prod_...` id is the product, not the price; only the price id works.

The webhook endpoint can be created from the API, which also returns its
signing secret:

```bash
curl -s https://api.stripe.com/v1/webhook_endpoints -u "$STRIPE_SECRET_KEY:" \
  -d "url=https://<worker>/api/webhooks/stripe" \
  -d "enabled_events[]=checkout.session.completed" \
  -d "enabled_events[]=invoice.paid" \
  -d "enabled_events[]=invoice.payment_failed" \
  -d "enabled_events[]=customer.subscription.updated" \
  -d "enabled_events[]=customer.subscription.deleted"
```

**The amounts in Stripe are not read by the app.** Published prices live in
`cloudflare/src/plans.ts` and `web/lib/plans.ts`. Change one and you must change
all three, or the page advertises a price the card is not charged.

Going live is the same four values again from live mode, plus a second webhook
endpoint.

---

## 7. Clerk

- `CLERK_SECRET_KEY` as a Worker secret
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` as a build variable for the site

Add the site's domain to Clerk's allowed origins. If you pin `iss`/`aud`, set
`CLERK_ISSUER` / `CLERK_AUDIENCE` in `wrangler.toml`; leave them empty
otherwise — an empty string is compared literally and rejects every token.

---

## 8. The customer's side

The repository containing `.github/actions/paracheck` must be **public**, since
customer workflows check it out.

Customers add `.github/workflows/paracheck.yml` (copy from this repo). It needs
`id-token: write`, which is what lets the run prove which repository it is
without any secret to configure.

---

## 9. Verify

Build variables for the site:

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | the Worker's URL |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key |
| `NEXT_PUBLIC_SALES_EMAIL` | where Enterprise enquiries go |
| `NEXT_PUBLIC_SITE_URL` | the site URL, for metadata |

These compile into the bundle, so a change needs a rebuild, and none may be a
secret.

Then:

1. `GET /api/health` → `{"ok": true, "missing": []}`
2. Sign in; the dashboard loads on the Free plan with 10 scans
3. **Connect GitHub**, install on one repository
4. Add the workflow file, open a pull request touching a `.sol` file → a Check
   Run appears
5. **Scan now** on the dashboard → a Check Run on the default branch
6. Subscribe with test card `4242 4242 4242 4242` → plan changes
7. Exhaust the quota and confirm the refusal says when it frees up

---

## Security notes worth keeping

The analysis runs on the customer's runner, so the untrusted build executes on
GitHub's ephemeral infrastructure rather than ours, and we never hold their
source. Inside that job, `analyzer/static/sandbox.py` still applies: build tools
get an allowlisted environment rather than the job's own — which holds
`GITHUB_TOKEN` and, when supplied, an Anthropic key — and CPU, memory, file size
and process count are capped.

Runs authenticate with a **GitHub Actions OIDC token**, verified against
GitHub's public keys with the audience pinned. There is no shared secret for a
customer to store, and a token minted for another service will not verify here.

Quota is counted from the `scans` table over a rolling 30 days rather than
granted at checkout. There is no balance to replenish, so a missed Stripe event
cannot leave a paying account throttled to zero.

---

## Verified, and not

**Verified live:** the Worker and site deploy and serve; `/api/health` reports
ok; the GitHub App JWT authenticates as ParaCheck; Stripe checkout sessions
build for both plans at the advertised amounts; and the Stripe webhook path was
exercised against the deployed Worker — a signed event writes the plan to D1, a
replayed event id is ignored as a duplicate, and forged, stale and unsigned
deliveries are all rejected with 401.

**Not yet verified:** a real end-to-end scan. Nobody has installed the App on a
repository, run the workflow, or had a Check Run posted. The OIDC claim path
and the analyzer's behaviour on a real project are untested in production.

**Credentials that need rotating before launch:** the GitHub App private key,
its client secret, and the Clerk secret key all passed through a chat
transcript during setup.
