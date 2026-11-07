-- Text search support for operator notes. Safe to run repeatedly.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE SCHEMA IF NOT EXISTS enrich;

-- unaccent() is only STABLE; this wrapper pins the dictionary so it can be used in an index.
CREATE OR REPLACE FUNCTION enrich.fold(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, lower(t)) $$;
