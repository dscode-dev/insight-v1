/**
 * Control Plane operational commands. Run inside the service image.
 *
 *   node dist/cli.js migrate      apply migrations/*.sql
 *   node dist/cli.js seed         create the first operator from env
 *
 * The image has no shell and no psql, so these ship as commands rather
 * than scripts. Both are idempotent and safe to re-run on every deploy.
 */
import { join } from 'node:path';

import { Logger } from '@nestjs/common';
import { Pool } from 'pg';

import { loadConfig } from './config/config';
import { runMigrations } from './db/migrator';
import { DatabaseService } from './db/database.service';
import { OperatorRepository } from './identity/operator.repository';
import { WeakPasswordError } from './identity/password';
import { isRole, Role } from './identity/rbac';

const logger = new Logger('cli');

const MIGRATIONS_DIR = join(__dirname, '..', 'migrations');

async function migrate(): Promise<void> {
  const config = loadConfig();
  const pool = new Pool({ connectionString: config.CONTROL_PLANE_DATABASE_URL });
  try {
    const applied = await runMigrations(pool, MIGRATIONS_DIR);
    logger.log(
      applied.length === 0
        ? 'control-plane migrations up to date'
        : `applied ${applied.length}: ${applied.join(', ')}`,
    );
  } finally {
    await pool.end();
  }
}

/**
 * Create the first console operator.
 *
 * A freshly migrated Control Plane has an empty `operators` table, so
 * nobody can sign in and the screens that would create an account are
 * themselves behind the login.
 *
 * Will NOT change an existing operator's password unless
 * CONSOLE_SEED_RESET_PASSWORD=true. A seed that silently rewrote the
 * admin credential on every deploy is a way to lock people out — and
 * deploys re-run far more often than anyone expects.
 */
async function seed(): Promise<void> {
  const env = process.env;
  const username = (env.CONSOLE_SEED_USERNAME ?? '').trim();
  const email = (env.CONSOLE_SEED_EMAIL ?? '').trim().toLowerCase();
  // NOT trimmed: leading/trailing spaces are legitimate password
  // characters, and stripping them would make the stored password
  // differ from the one the operator was handed.
  const password = env.CONSOLE_SEED_PASSWORD ?? '';
  const rawRole = (env.CONSOLE_SEED_ROLE ?? 'SuperAdmin').trim();
  const reset = (env.CONSOLE_SEED_RESET_PASSWORD ?? '').toLowerCase() === 'true';

  const missing = Object.entries({
    CONSOLE_SEED_USERNAME: username,
    CONSOLE_SEED_EMAIL: email,
    CONSOLE_SEED_PASSWORD: password,
  })
    .filter(([, value]) => value === '')
    .map(([name]) => name)
    .sort();
  if (missing.length > 0) {
    throw new Error(`missing required env: ${missing.join(', ')}`);
  }
  if (!email.includes('@')) {
    throw new Error('CONSOLE_SEED_EMAIL must be an email address');
  }
  if (!isRole(rawRole)) {
    throw new Error(
      `CONSOLE_SEED_ROLE ${rawRole} is not a role the console understands`,
    );
  }
  const role = rawRole as Role;

  const db = new DatabaseService();
  const operators = new OperatorRepository(db);
  try {
    const existing = await operators.findByIdentifier(username);
    if (existing !== null) {
      if (!reset) {
        logger.log(
          `operator ${existing.username} already exists (role=${existing.role}` +
            `${existing.isActive ? '' : ', INACTIVE — cannot sign in'}) — nothing to do`,
        );
        return;
      }
      await operators.setPassword(existing.id, password);
      logger.log(
        `password reset for ${existing.username}; all its sessions were revoked`,
      );
      return;
    }

    const created = await operators.createOperator({
      username,
      email,
      displayName: env.CONSOLE_SEED_DISPLAY_NAME || username,
      role,
      password,
    });
    logger.log(`created operator ${created.username} (role=${created.role})`);
  } finally {
    await db.onModuleDestroy();
  }
}

async function main(): Promise<void> {
  const command = process.argv[2];
  switch (command) {
    case 'migrate':
      await migrate();
      return;
    case 'seed':
      await seed();
      return;
    default:
      throw new Error(`unknown command ${command ?? '(none)'} — use migrate|seed`);
  }
}

main().catch((error: unknown) => {
  // Never print the whole environment or config: it carries the
  // password and the database DSN.
  const message =
    error instanceof WeakPasswordError || error instanceof Error
      ? error.message
      : 'unknown error';
  logger.error(message);
  process.exit(1);
});
