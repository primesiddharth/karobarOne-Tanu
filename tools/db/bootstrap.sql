-- ==============================================================================
-- File: tools/db/bootstrap.sql
-- Purpose: Schema, role, and permission initialization for KarobarOne microservices
-- CAUTION: LOCAL DOCKER COMPOSE / KIND ONLY. NEVER run this script on Neon staging
-- or production! In staging/prod, provision roles and unique secure passwords
-- per service by hand in the cloud console or secrets manager (RULES §10).
-- All 8 runtime roles share dev_svc_secret and migrator roles share dev_migrator_secret
-- for local developer ergonomics only.
-- ==============================================================================

-- Revoke public schema creation
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

DO $$
DECLARE
    schemas TEXT[] := ARRAY['iam', 'tenant', 'subscription', 'approval', 'catalog', 'domain', 'customer', 'inventory'];
    s TEXT;
    migrator_role TEXT;
    svc_role TEXT;
    migrator_pass TEXT := COALESCE(current_setting('app.migrator_password', true), 'dev_migrator_secret');
    svc_pass TEXT := COALESCE(current_setting('app.svc_password', true), 'dev_svc_secret');
BEGIN
    FOREACH s IN ARRAY schemas
    LOOP
        migrator_role := s || '_migrator';
        svc_role := s || '_svc';

        -- 1. Create Runtime Service Role
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = svc_role) THEN
            EXECUTE format('CREATE ROLE %I WITH LOGIN PASSWORD %L', svc_role, svc_pass);
        END IF;

        -- 2. Create Migrator Role (DDL Owner)
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = migrator_role) THEN
            EXECUTE format('CREATE ROLE %I WITH LOGIN PASSWORD %L', migrator_role, migrator_pass);
        END IF;

        -- 3. Create Schema owned by Migrator
        EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I', s, migrator_role);

        -- 4. Grant Usage on Schema to Runtime Service Role
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', s, svc_role);

        -- 5. Set Default Privileges for Tables created by Migrator (SELECT, INSERT, UPDATE, DELETE)
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
                       migrator_role, s, svc_role);

        -- 6. Set Default Privileges for Sequences
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO %I',
                       migrator_role, s, svc_role);

        -- 7. Revoke all privileges from PUBLIC on the schema
        EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', s);

    END LOOP;
END
$$;
