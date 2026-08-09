import { randomBytes, scrypt, ScryptOptions, timingSafeEqual } from 'node:crypto';

/**
 * `promisify(scrypt)` resolves to the 3-argument overload, which drops
 * the options parameter — and the options are exactly what sets the
 * cost. Wrapped by hand so N/r/p/maxmem actually reach it.
 */
function scryptAsync(
  password: string,
  salt: Buffer,
  keylen: number,
  options: ScryptOptions,
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    scrypt(password, salt, keylen, options, (error, derived) => {
      if (error) reject(error);
      else resolve(derived);
    });
  });
}

/**
 * Operator password hashing for the Control Plane.
 *
 * scrypt from node:crypto rather than bcrypt/argon2: no native build in
 * the image, no extra dependency, and it is memory-hard, which is the
 * property that matters against GPU cracking.
 *
 * NOT pgcrypto's `crypt()` — the shape the Gateway used. Verifying in
 * the database means the plaintext password travels inside a SQL
 * statement, where it shows up in `pg_stat_activity` and in any
 * statement logging that is ever switched on. The Control Plane is the
 * identity authority now, so the secret should not leave it.
 *
 * Format: `scrypt$N$r$p$<salt-b64>$<hash-b64>`. Self-describing on
 * purpose — the parameters travel with the hash, so raising the cost
 * later does not invalidate existing passwords.
 */

// ~64 MB per hash at r=8, N=2^15. Chosen to stay comfortable inside the
// container's memory while making bulk offline cracking expensive.
const N = 32768;
const R = 8;
const P = 1;
const KEY_LEN = 64;
const SALT_LEN = 16;

// scrypt's memory use is roughly 128 * N * r bytes; Node refuses to run
// unless maxmem allows it, and the default (32 MB) is below what these
// parameters need.
const MAX_MEM = 192 * 1024 * 1024;

export const PASSWORD_MIN_LENGTH = 12;

export class WeakPasswordError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'WeakPasswordError';
  }
}

export function assertUsablePassword(password: string): void {
  // Length in code points, not bytes: a passphrase of accented or
  // non-Latin characters is not weaker for being fewer bytes.
  if ([...password].length < PASSWORD_MIN_LENGTH) {
    throw new WeakPasswordError(
      `password must be at least ${PASSWORD_MIN_LENGTH} characters`,
    );
  }
  // This repo's .env template ships `__required__` for unfilled secrets,
  // and it has reached a running deployment before — it became the
  // Postgres superuser name on the robozao host.
  if (password === '__required__') {
    throw new WeakPasswordError(
      'refusing the __required__ placeholder as a password',
    );
  }
}

export async function hashPassword(password: string): Promise<string> {
  assertUsablePassword(password);
  const salt = randomBytes(SALT_LEN);
  const derived = await scryptAsync(password, salt, KEY_LEN, {
    N,
    r: R,
    p: P,
    maxmem: MAX_MEM,
  });
  return [
    'scrypt',
    N,
    R,
    P,
    salt.toString('base64'),
    derived.toString('base64'),
  ].join('$');
}

/**
 * Constant-time verification. Returns false for anything malformed
 * rather than throwing: a corrupt stored hash must read as "wrong
 * password", never as a 500 that tells an attacker the account exists.
 */
export async function verifyPassword(
  password: string,
  stored: string,
): Promise<boolean> {
  const parts = stored.split('$');
  if (parts.length !== 6 || parts[0] !== 'scrypt') {
    return false;
  }
  const [, rawN, rawR, rawP, saltB64, hashB64] = parts;
  const n = Number(rawN);
  const r = Number(rawR);
  const p = Number(rawP);
  if (!Number.isInteger(n) || !Number.isInteger(r) || !Number.isInteger(p)) {
    return false;
  }

  let expected: Buffer;
  let salt: Buffer;
  try {
    expected = Buffer.from(hashB64!, 'base64');
    salt = Buffer.from(saltB64!, 'base64');
  } catch {
    return false;
  }
  if (expected.length === 0 || salt.length === 0) {
    return false;
  }

  let derived: Buffer;
  try {
    derived = await scryptAsync(password, salt, expected.length, {
      N: n,
      r,
      p,
      maxmem: MAX_MEM,
    });
  } catch {
    // Parameters outside what this Node build will run (a hash written
    // by a future, costlier configuration, say).
    return false;
  }
  // Length is compared first: timingSafeEqual throws on a mismatch.
  return (
    derived.length === expected.length && timingSafeEqual(derived, expected)
  );
}
