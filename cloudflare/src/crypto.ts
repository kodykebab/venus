/**
 * Encryption for the Anthropic keys customers hand us, and the HMAC helpers
 * every signature check here shares.
 *
 * A customer's Anthropic key is a live billing credential belonging to someone
 * else. Encrypting it means a leaked D1 export - a stray backup, an over-broad
 * API token - is not immediately a leak of every customer's key. It is not
 * protection against an attacker who already has the Worker's secrets; it is
 * protection against the much more common case where data escapes and the
 * running code does not.
 */

const encoder = new TextEncoder();
const decoder = new TextDecoder();

async function aesKey(secret: string): Promise<CryptoKey> {
  // The secret is arbitrary text, so it is hashed to exactly 256 bits rather
  // than being truncated or padded into one.
  const material = await crypto.subtle.digest("SHA-256", encoder.encode(secret));
  return crypto.subtle.importKey("raw", material, { name: "AES-GCM" }, false, [
    "encrypt",
    "decrypt",
  ]);
}

/** Returns `base64(iv).base64(ciphertext)`. */
export async function encrypt(secret: string, plaintext: string): Promise<string> {
  const key = await aesKey(secret);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    encoder.encode(plaintext),
  );
  return `${b64encode(iv)}.${b64encode(new Uint8Array(ciphertext))}`;
}

/**
 * Null rather than a throw when a stored value cannot be read: rotating the
 * encryption secret should degrade scans to deterministic rendering, not make
 * every job crash.
 */
export async function decrypt(secret: string, stored: string | null): Promise<string | null> {
  if (!stored || !stored.includes(".")) return null;
  try {
    const [ivPart, cipherPart] = stored.split(".", 2);
    const key = await aesKey(secret);
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: b64decode(ivPart) },
      key,
      b64decode(cipherPart),
    );
    return decoder.decode(plaintext);
  } catch {
    return null;
  }
}

/** What the dashboard shows instead of the key: enough to recognise, not to steal. */
export function keyHint(key: string): string {
  return `...${key.slice(-4)}`;
}

export async function hmacSha256Hex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return [...new Uint8Array(signature)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Constant-time comparison.
 *
 * A webhook signature check that returns early on the first wrong byte leaks,
 * over enough attempts, which prefix was right.
 */
export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i++) {
    difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return difference === 0;
}

export function b64encode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export function b64decode(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}
