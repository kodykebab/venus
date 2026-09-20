# ParaCheck Handoff

Date: 2026-09-21

## Product Direction

ParaCheck is a developer tool for Solidity teams shipping to parallel-execution chains, especially Monad. It combines:

- Static Solidity analysis using Slither and ParaCheck's hot-slot classifier.
- Dynamic contention analysis using Foundry/anvil and trace data.
- GitHub pull-request Check Runs and annotations.
- A hosted dashboard for installations, repositories, review history, quotas, and billing.

The product should feel like a serious developer tool: sophisticated, clear, technical, and easy to use.

## Claude Decision

Claude synthesis is a future service, not part of the initial launch.

The launch path must never call Anthropic or incur Claude costs. Deterministic findings and Markdown rendering are the product for now.

This is enforced by:

```env
PARACHECK_CLAUDE_ENABLED=0
```

The flag is documented in `service/.env.example` and configured by the launch
deployment. `service/jobs.py` renders deterministic findings unless the flag is
explicitly enabled. The existing synthesis code, encrypted per-installation
Anthropic key storage, API validation, and tests remain available for a later
BYOK Claude feature.

The future BYOK model is:

- Customer supplies their own Anthropic key.
- Customer pays Anthropic directly.
- ParaCheck never pays for their Claude usage.
- Keys remain encrypted and are never passed to reviewed repository build tools.
- Model selection should initially use an allowlist rather than arbitrary model names.

The real Anthropic API call has never been executed in this environment. Mocked `messages.parse` wiring and no-key fallback are tested.

## Billing And Plans

There is no free tier. New installations start as `unpaid` with zero review entitlement. Reviews are blocked until a paid Stripe checkout completes.

Current code has these plan definitions in `service/billing.py`:

- Hobby: 50 reviews per billing period.
- Pro: 250 reviews per billing period.
- Enterprise: custom.

Current code defaults display prices to `$29/mo` for Hobby and `$99/mo` for Pro. These are not the final business decision.

The pricing discussion concluded that the initial low-friction launch prices should instead be:

- Hobby: `$9/month`, 20 reviews.
- Pro: `$29/month`, 100 reviews.
- Enterprise: custom quote and custom capped quota.

This lower pricing/quota decision has not yet been applied to the code. Change `PLANS`, display prices, dashboard copy, and docs together when applying it.

Important billing gap: checkout replenishes quota, but recurring subscription renewal handling is not complete. Add handling for `invoice.paid` or an equivalent recurring event before relying on monthly quota resets. Cancellation and payment failure currently move an installation to `unpaid`.

Never offer unlimited reviews. Review jobs can compile arbitrary repositories and consume significant CPU, memory, and GitHub Actions minutes.

## Authentication And Access

There are two separate identity boundaries:

1. GitHub App OAuth/install flow proves which GitHub installation and repositories the browser may manage.
2. Clerk proves the account identity for paid checkout.

GitHub remains the repository authorization source. Clerk does not replace GitHub installation permissions.

Implemented Clerk pieces:

- `service/clerk_auth.py` verifies Clerk JWT bearer tokens using `CLERK_JWT_KEY`.
- `CLERK_PUBLISHABLE_KEY`, `CLERK_JWT_KEY`, optional issuer, and audience are documented.
- `/account?installation_id=N` renders the Clerk sign-in shell.
- `/billing/checkout` requires both a valid Clerk token and the existing GitHub installation cookie.
- Configured Clerk deployments route the upgrade button through `/account`.

## Enterprise

Enterprise is sales-led. `/enterprise` renders a form that opens the visitor's mail client with a prefilled `mailto:` message.

The recipient is configured with:

```env
ENTERPRISE_SALES_EMAIL=you@example.com
```

There is no SMTP backend. Do not reintroduce SMTP unless explicitly desired.

## Deployment Architecture

### Current deployment direction

Fly.io has been removed from the deployment path. The `Dockerfile` remains as a
local/containerized analyzer artifact, but `fly.toml` and Fly deployment steps
are gone. The only hosted deployment target is Cloudflare Pages + Workers + D1
with GitHub Actions for analysis.

### Planned lower-cost architecture

The preferred cost-saving direction is:

```text
Cloudflare Pages
  -> static demo and public frontend

Cloudflare Worker
  -> Clerk auth
  -> Stripe Checkout/webhooks
  -> GitHub webhook verification
  -> D1 state and quotas
  -> dispatch GitHub Actions

GitHub Actions
  -> checkout repository
  -> run Foundry, solc, Slither, and ParaCheck
  -> post the GitHub Check Run
```

Cloudflare Workers cannot directly run Foundry, solc, Slither, npm installs, or arbitrary repository builds. GitHub Actions must perform the analysis. The Cloudflare Worker + D1 + GitHub Actions architecture is discussed but not implemented yet.

The existing `.github/actions/analyze/action.yml` is the starting point for the GitHub Actions execution path. The Worker still needs to dispatch workflows, enforce paid quotas, verify GitHub webhooks, and receive/report completion.

Cloudflare scaffolding now exists under `cloudflare/`:

- `cloudflare/wrangler.toml` - Worker and D1 binding configuration.
- `cloudflare/schema.sql` - accounts, webhook idempotency, and review-run tables.
- `cloudflare/src/index.ts` - explicit health endpoint and `501` placeholders for
  unimplemented production control-plane routes.
- `cloudflare/package.json`, `package-lock.json`, `tsconfig.json` - Worker tooling.
- `cloudflare/README.md` - rollout options, security requirements, and deploy steps.

The scaffold typechecks with `cd cloudflare && npm run typecheck`. It deliberately
returns `501` for payment and webhook routes so a partial deployment cannot appear
to accept production traffic.

Do not claim the Worker architecture is deployed until those pieces exist.

## UI/UX Work

Public demo surfaces were redesigned with a sophisticated Swiss-inspired developer-tool direction:

- `demo-page/index.html`: product-led hero, obvious Analyze a contract CTA, live proof panel, technical trust metadata, restrained grid texture, focus states, responsive layout.
- `demo-page/app.html`: matching technical dashboard styling and mobile single-column fix.
- `demo-page/upload.html`: matching analyzer styling, stronger input/result framing, focus states, reduced-motion handling.

The first visual attempt was too editorial/poster-like. It was revised toward a practical developer tool with a clear first action and live proof beside the product explanation.

## Files Added Or Changed

Major current changes include:

- `service/clerk_auth.py` - Clerk JWT verification.
- `service/app.py` - Clerk checkout, Stripe plan selection, Enterprise route, Claude feature gating.
- `service/billing.py` - Hobby/Pro plan IDs, quotas, Stripe metadata, unpaid state transitions.
- `service/store.py` - zero entitlement for new installs and paid quota enforcement.
- `service/dashboard.py` - account page, plan selector, Enterprise mailto form, paid/unpaid status, UI copy.
- `service/jobs.py` - deterministic rendering unless Claude is explicitly enabled.
- `service/preflight.py` - Stripe/Clerk readiness diagnostics.
- `service/.env.example` - Clerk, Stripe, Claude flag, Enterprise recipient settings.
- `service/test_service.py` - Clerk, paid quota, checkout, and security coverage.
- `demo-page/index.html`, `demo-page/app.html`, `demo-page/upload.html` - UI redesign.
- `DEPLOY.md`, `service/README.md`, `TESTING.md` - deployment/testing documentation.
- `cloudflare/` - Worker, D1 schema, Wrangler config, and deployment guide.

There is also an untracked `.claude/skills/claude/SKILL.md`. It is a repository-specific workflow note for future Claude synthesis work.

## Validation

Latest service validation:

```text
46 service tests passed
Python compilation passed
 git diff --check passed
```

Previously verified before the billing/UI changes:

- Analyzer Python tests: 47 passed.
- Analyzer Claude/review test module: 16 passed.
- TypeScript tests: 4 passed.
- TypeScript build passed.
- Foundry contract tests: 18 passed.

Known warning: one existing Starlette/httpx deprecation warning appears in the service suite.

## Immediate Next Steps

1. Implement the Worker/D1/GitHub Actions control plane before advertising zero hosting cost.
3. Apply final launch prices: Hobby `$9` / 20 reviews, Pro `$29` / 100 reviews, Enterprise custom.
4. Add recurring Stripe renewal handling to replenish monthly quotas.
5. Configure and test Stripe webhook events: `checkout.session.completed`, `invoice.paid`, `customer.subscription.deleted`, and `invoice.payment_failed`.
6. Keep Claude disabled and unset `ANTHROPIC_API_KEY` for launch.
7. Configure Clerk, Stripe Price IDs, GitHub App credentials, `PARACHECK_PUBLIC_URL`, encryption secret, and `ENTERPRISE_SALES_EMAIL` only in deployment secrets.
8. Run `paracheck doctor --service` before accepting production traffic.
