# Deploying the ParaCheck CI service

The service is one container: a FastAPI app that receives GitHub webhooks and a
worker that drains the review queue. By default they share a process, so there
is one thing to deploy.

## Checking what's missing

```bash
paracheck doctor --service          # or: docker exec <container> python service/preflight.py
```

It names every variable, what breaks without it, and which are optional. Run it
after setting secrets and before pointing GitHub at the deployment - most of
these fail late and quietly otherwise (a private key mangled by a secrets UI
looks set and fails at the first token mint, inside a background job).

## What it needs

| Secret | Where it comes from | Used for |
| --- | --- | --- |
| `GITHUB_APP_ID` | the App's settings page | minting installation tokens |
| `GITHUB_APP_PRIVATE_KEY` | "Generate a private key" on that page (PEM, newlines intact) | signing the App JWT |
| `GITHUB_WEBHOOK_SECRET` | whatever you set in the App's webhook config | verifying every delivery |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | same page | the OAuth step during install |
| `PARACHECK_PUBLIC_URL` | your deployed URL | building callback URLs |
| `ANTHROPIC_API_KEY` | console.anthropic.com | optional fallback key. Installations normally supply their own on the dashboard, billed to their own account; this covers any that haven't |
| `PARACHECK_ENCRYPTION_KEY` | generate one | encrypts the API keys installations supply. Falls back to `GITHUB_WEBHOOK_SECRET` |
| `STRIPE_SECRET_KEY` / `STRIPE_PRICE_ID` / `STRIPE_WEBHOOK_SECRET` | Stripe dashboard | paid plans (optional - without them everything runs on the free tier) |

## Fly.io

```bash
fly launch --no-deploy --copy-config       # reads fly.toml as-is
fly volumes create paracheck_data --size 10 --region iad

fly secrets set \
  GITHUB_APP_ID=... \
  GITHUB_WEBHOOK_SECRET=... \
  GITHUB_CLIENT_ID=... \
  GITHUB_CLIENT_SECRET=... \
  PARACHECK_PUBLIC_URL=https://paracheck-ci.fly.dev
fly secrets set GITHUB_APP_PRIVATE_KEY="$(cat paracheck.private-key.pem)"

fly deploy
```

Then point the GitHub App's webhook at `https://<your-app>/webhook` and its
setup URL at `https://<your-app>/setup`.

## Anywhere else that runs a container

```bash
docker build -t paracheck .
docker run -d --name paracheck \
  -p 8000:8000 \
  -v paracheck-data:/data \
  --env-file service/.env \
  --read-only --tmpfs /work:rw,exec,size=8g,mode=1777,nosuid,nodev \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --pids-limit 512 \
  --memory 4g \
  paracheck
```

Those flags are not decoration. Reviewing a pull request runs its build system,
and `forge install` and `npm install` execute arbitrary code by design, so the
container should be treated as something an attacker gets code execution in:

- `--read-only` with a `/work` tmpfs: the checkout is the only writable path,
  and it is gone when the container is. `mode=1777` matters - the container runs
  as an unprivileged user and a tmpfs mounts root-owned, so without it nothing
  can write to its own checkout. `exec` matters too: build tools legitimately run
  binaries out of `node_modules/.bin`.
- `--cap-drop ALL` and `--security-opt no-new-privileges`: nothing in a review
  needs a capability, and nothing should be able to acquire one.
- `--pids-limit` and `--memory`: a build that forks or allocates without bound
  takes itself down instead of the host.

The container-level half of that pairs with the process-level half in
`analyzer/static/sandbox.py`, which strips the service's secrets out of the
environment every build tool inherits. Neither is enough on its own.

To see why the second half is needed, a `postinstall` script in a reviewed repo
that prints every environment variable matching `KEY|SECRET|TOKEN|PASSWORD`:

```
# npm install directly
SECRET_HITS=["GPG_KEY","GITHUB_APP_PRIVATE_KEY","STRIPE_SECRET_KEY"]

# the same install, as a review runs it
SECRET_HITS=[]
```

The container alone does not stop that - the process inside it holds the keys.

## Not on Vercel

The demo page deploys to Vercel fine. This service does not: a review takes
minutes and Vercel functions cap out well below that, the queue and the review
history need a disk that survives the request, and the analyzer needs a
filesystem with git, foundry and solc on it. Any host that runs a container
with a volume works.

## Scaling the worker out

When reviews start waiting on each other, stop running the worker in the API
process and give it its own:

```
PARACHECK_INLINE_WORKER=0     # on the web process
python service/worker.py      # one or more of these
```

Claiming a job is a single atomic `UPDATE`, so workers can be added without
coordination. They do have to share the database, which is the point at which
SQLite on a volume becomes the constraint and Postgres starts being worth it.
