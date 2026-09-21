/**
 * Everything the Worker is given.
 *
 * Secrets are typed as required strings even though a misconfigured deployment
 * would leave them empty, because the readiness endpoint (`/api/health`) is
 * what reports missing configuration - not a type error at the call site.
 */
export interface Env {
  // Bindings
  DB: D1Database;

  // Vars (public)
  ENVIRONMENT: string;
  PUBLIC_URL: string;
  GITHUB_APP_SLUG: string;
  CLERK_ISSUER: string;
  CLERK_AUDIENCE: string;
  ENTERPRISE_SALES_EMAIL: string;

  // Secrets
  CLERK_SECRET_KEY: string;
  GITHUB_APP_ID: string;
  GITHUB_APP_PRIVATE_KEY: string;
  GITHUB_WEBHOOK_SECRET: string;
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
  STRIPE_SECRET_KEY: string;
  STRIPE_WEBHOOK_SECRET: string;
  STRIPE_HOBBY_PRICE_ID: string;
  STRIPE_PRO_PRICE_ID: string;
  ENCRYPTION_KEY: string;
}

