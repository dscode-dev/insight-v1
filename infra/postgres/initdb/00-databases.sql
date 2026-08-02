-- SanninJiraiya Postgres bootstrap (ML-C Step 0).
-- Runs once on first init (empty data dir). Creates the per-service databases
-- and enables pgcrypto for password hashing in the super-admin seed.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Per-service logical databases (Console, Gateway, Social, future cloud svcs).
SELECT 'CREATE DATABASE gateway'  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gateway')\gexec
SELECT 'CREATE DATABASE social'   WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'social')\gexec
SELECT 'CREATE DATABASE console'  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'console')\gexec
