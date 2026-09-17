# PUMA job persistence

PUMA keeps `/app/data/jobs` as the runtime working directory. On Render Free this directory is ephemeral and can disappear after a redeploy, restart, or spin-down.

Production can optionally mirror every analysis job to any S3-compatible object store. Cloudflare R2 is the intended low-cost/default provider, but Amazon S3 and compatible providers can use the same variables.

## What is persisted

For every analysis job the durable layer mirrors:

- `status.json`
- the original uploaded catalog (required for one-click rerun)
- `PUMA_doPUMAgatel_market_report.xlsx`
- `PUMA_classic_analytical_report.xlsx`

After a fresh container starts, remote job statuses are discovered automatically. Missing input/report files are restored on demand. Jobs that were `queued` or `running` during a container interruption are marked `interrupted` instead of pretending they completed.

## Environment variables

Set these only in the hosting provider's secret/environment settings. Never commit credentials to Git.

| Variable | Required | Example / purpose |
|---|---|---|
| `PUMA_S3_BUCKET` | yes | `puma-jobs` |
| `PUMA_S3_ENDPOINT` | yes | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `PUMA_S3_ACCESS_KEY_ID` | yes | R2/S3 access key |
| `PUMA_S3_SECRET_ACCESS_KEY` | yes | R2/S3 secret key |
| `PUMA_S3_REGION` | no | `auto` for R2 (default) |
| `PUMA_S3_PREFIX` | no | `jobs` (default) |
| `PUMA_S3_STATUS_SYNC_SECONDS` | no | `5` (default throttle for running progress) |

If any required S3 variable is absent, PUMA remains in `local` mode and behaves like the previous build.

## Health check

`GET /api/storage`

Local fallback:

```json
{"durable": false, "mode": "local"}
```

Configured S3/R2:

```json
{"durable": true, "mode": "s3"}
```

No secrets, bucket names, endpoints, or credentials are returned by this endpoint.

## Render persistent disk alternative

A paid Render web service can instead attach a persistent disk at `/app/data`. The existing job layout already works with that mount and does not require S3 variables. Render Free web services cannot attach persistent disks.
