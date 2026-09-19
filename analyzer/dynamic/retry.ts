function isRateLimitError(err: unknown): boolean {
  const e = err as any;
  const code = e?.error?.code ?? e?.code;
  const message = String(e?.error?.message ?? e?.message ?? "");
  return code === -32007 || /rate limit|request limit/i.test(message);
}

/** Retries an RPC call with exponential backoff on rate-limit errors (QuickNode's
 * free/shared tiers return -32007 "N/second request limit reached"). Any other error
 * is rethrown immediately - this only exists to smooth over throughput limits, not to
 * mask real failures. */
export async function withRetry<T>(fn: () => Promise<T>, maxAttempts = 5, baseDelayMs = 800): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (!isRateLimitError(err) || attempt === maxAttempts - 1) throw err;
      const delay = baseDelayMs * 2 ** attempt;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  throw lastErr;
}
