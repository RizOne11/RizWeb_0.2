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
- uses durable S3-compatible storage for job inputs, status, checkpoints and reports when all PUMA_S3_* settings are configured; otherwise storage is local and does not survive an ephemeral-container replacement;
- refuses to publish queued/running/done transitions if required file uploads fail, and surfaces durable write failures as job errors.

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

For a Render web service running a worker with an HTTP health endpoint:

    python puma_worker_service.py

This wrapper stays idle without storage settings (HTTP 200, ready=false).
Once configured, readiness requires a recent successful storage synchronization;
storage synchronization failures return HTTP 503. This verifies list/read access,
not write permissions; actual uploads are checked when job transitions occur.

The checked-in render.yaml provisions only the combined web service. Split deployment
requires a separately provisioned worker with the same durable-storage and provider
secrets, PUMA_EXECUTION_MODE=worker on the worker and PUMA_EXECUTION_MODE=web on
the web tier. The worker supports one active instance; multi-worker claiming is
not implemented. Live Render settings must be verified independently.

## Tests and gates

Key gates include:

- PUMA Production Hardening
- PUMA Gold Regression
- PUMA v1.3 Exact Five Smoke
- Recovery13
- Mixed18
- Full1000

Post-production cleanup has its own regression gate and runs the full pytest suite.
Production Hardening and Post Production Cleanup also run on pull requests to main.
Recovery13, Mixed18 and Full1000 are explicit live checks (workflow_dispatch or
their dedicated branch/path triggers), not automatic gates on every main push.
Recovery13 rejects the locked false positives and refresh source loss; Full1000
rejects refresh product/source loss. Mixed18 gates SKU query isolation and
canonicalization; its market coverage is reported without a minimum threshold.

## Legacy

The historical PriceIntel CLI is retained only as a compatibility wrapper:

    python main.py <catalog>

Its implementation lives under legacy/.

Version-specific historical README files remain as migration/history material and are not the source of truth for the current production architecture.
