# PUMA Platform v1.3

PUMA — production-oriented market analysis and product-content platform.

## Current production baseline

Active market sources:

- Prom
- Epicentr
- Hotline
- WEB_SHOPS

Rozetka is frozen. Allo/Comfy are paused. Zakupka is not part of production.

The matcher is treated as stable. Any future matcher change must include a regression case and pass the full matcher gate chain before release.

## Market analysis

The production engine:

- keeps supplier SKU/article immutable;
- separates supplier SKU from public model/MPN identity;
- canonicalizes RU/UA and mixed-script identity text;
- validates brand/model/variant/category conflicts;
- excludes AMBIGUOUS and CONFLICT offers from market price statistics;
- reports min / median / average / max market prices;
- keeps marketplace URLs and identity confidence;
- supports checkpoint/resume for long-running jobs;
- uses durable S3-compatible storage for job inputs, status, checkpoints and reports.

## Production hardening

Current runtime includes:

- optional fail-closed authentication with PUMA_AUTH_TOKEN;
- Bearer auth for API clients and Basic auth for browser access;
- bounded active jobs and outstanding queue;
- start-rate limiting;
- duplicate job suppression;
- cooperative cancel with checkpoint preservation;
- Serper request/cache accounting with optional cost estimation;
- combined, web and worker execution modes;
- public /healthz endpoint.

## Config v2

config.json remains backward-compatible with legacy PriceIntel keys.

New production settings live under the production section and are loaded through puma_config.py. The production source allowlist is not derived from the old legacy marketplace list.

## Runtime

Production web entrypoint:

    durable_wsgi:app

Background worker entrypoint prepared for split deployment:

    python puma_worker.py

The live Render service currently remains in combined mode until a dedicated worker service is provisioned with the same durable-storage and provider secrets.

## Tests and gates

Key gates include:

- PUMA Production Hardening
- PUMA Gold Regression
- PUMA v1.3 Exact Five Smoke
- Recovery13
- Mixed18
- Full1000

Post-production cleanup has its own regression gate and runs the full pytest suite.

## Legacy

The historical PriceIntel CLI is retained only as a compatibility wrapper:

    python main.py <catalog>

Its implementation lives under legacy/.

Version-specific historical README files remain as migration/history material and are not the source of truth for the current production architecture.
