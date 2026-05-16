---
sprint: 6.1
date: 2026-05-07
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.1 Phase 3a — TLS enforcement: terminate at LB, exempt /health, HSTS 1-year-no-preload

Three coupled decisions for HTTPS enforcement. **(1) TLS termination at the load balancer / platform**, not at uvicorn directly. App trusts `X-Forwarded-Proto` via uvicorn's `--proxy-headers --forwarded-allow-ips *` flags. Production deployment requirement: container runs on a private network, only reachable via TLS-terminating proxy (k8s ingress, AWS ALB, Render/Fly platform). Cert management is the platform's problem, not ours — production deployments use their own platform ingress and BYO-certs would create deployment friction. **(2) Custom `TLSEnforcementMiddleware` exempts `/health*` only, redirects with 308 (not 301).** Health probes pass through over plain HTTP from internal subnets — without the exemption, LBs see a redirect and silently mark the app unhealthy. 308 preserves method+body so POST stays POST after redirect (301 risks browser downgrade to GET, breaking writes). `/docs`, `/openapi.json`, `/` all redirect to HTTPS — they're public-facing and "your API docs work over plain HTTP" is the kind of small thing that makes an external reviewer wince. Custom middleware (vs Starlette's built-in `HTTPSRedirectMiddleware`) is ~15 lines and lets us inject HSTS in the same place. **(3) HSTS `max-age=31536000; includeSubDomains` (1 year, no preload).** 1 year is Chrome's preload-list minimum and the defensible floor for production; shorter signals lack of commitment, longer is overkill until preload submission. `includeSubDomains` is safe today (no subdomain story) and forecloses future-subdomain-on-HTTP footguns. **`preload` deferred** — submission hardcodes the domain into Chromium/Firefox/Safari source and removal is months-long manual; production domain is unknown so this is a near-permanent commitment to a name we don't have yet. HSTS only emitted on HTTPS responses (RFC 6797 — browsers ignore it over HTTP). Middleware order in `app/main.py`: TLS runs FIRST (registered last), then body_size, then audit — HTTP redirects don't pollute the audit queue. Gated by `ENVIRONMENT=production` strict equality (typos fail-safe to dev); `FORWARDED_ALLOW_IPS=*` default with startup warning when production+`*` (container must not be internet-reachable directly).
