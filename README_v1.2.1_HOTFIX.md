# PUMA Platform v1.2.1 — Deep Scan Exact Hotfix

Hotfix for the completed-job export failure:

- adds `Match статус` and `Match причина` to competitor-offer CSV schema;
- adds a defensive schema-union guard so future Deep Scan audit fields cannot crash CSV export after analysis;
- preserves v1.2 Deep Scan / Exact Product logic unchanged.

Made by Пума (Чернявський А.)
