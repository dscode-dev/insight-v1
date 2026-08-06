import { createHash } from 'node:crypto';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { Logger } from '@nestjs/common';
import { Pool } from 'pg';

const logger = new Logger('migrator');

/**
 * Applies `migrations/*.sql` in filename order, once each.
 *
 * Same shape as Atlas's `scripts/migrate.py`, deliberately: this stack
 * already has one migration convention and a second one with different
 * semantics is how a database ends up in a state nobody can reason
 * about.
 *
 * Each file runs inside a transaction, so a failure half-way leaves
 * nothing applied and nothing recorded — the alternative is a schema
 * that is neither the old one nor the new one.
 */
export async function runMigrations(
  pool: Pool,
  directory: string,
): Promise<string[]> {
  await pool.query(`
    CREATE SCHEMA IF NOT EXISTS control_plane;
    CREATE TABLE IF NOT EXISTS control_plane.schema_migrations (
      filename    TEXT PRIMARY KEY,
      checksum    TEXT NOT NULL,
      applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
  `);

  const files = readdirSync(directory)
    .filter((name) => name.endsWith('.sql'))
    .sort();

  const applied = new Map<string, string>(
    (
      await pool.query<{ filename: string; checksum: string }>(
        'SELECT filename, checksum FROM control_plane.schema_migrations',
      )
    ).rows.map((row) => [row.filename, row.checksum]),
  );

  const ran: string[] = [];
  for (const filename of files) {
    const sql = readFileSync(join(directory, filename), 'utf8');
    const checksum = createHash('sha256').update(sql).digest('hex');
    const previous = applied.get(filename);

    if (previous !== undefined) {
      if (previous !== checksum) {
        // An edited migration means the database and the file disagree
        // about what was applied. Re-running it is not safe and
        // ignoring it hides a real divergence, so refuse.
        throw new Error(
          `migration ${filename} changed after it was applied — ` +
            'add a new migration instead of editing an applied one',
        );
      }
      logger.log(`skip  ${filename}`);
      continue;
    }

    logger.log(`apply ${filename}`);
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(sql);
      await client.query(
        'INSERT INTO control_plane.schema_migrations (filename, checksum) VALUES ($1, $2)',
        [filename, checksum],
      );
      await client.query('COMMIT');
      ran.push(filename);
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined);
      throw new Error(
        `migration ${filename} failed: ${
          error instanceof Error ? error.message : 'unknown error'
        }`,
      );
    } finally {
      client.release();
    }
  }
  return ran;
}
