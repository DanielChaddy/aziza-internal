# Kubernetes deployment (Helm)

This is the operations runbook. For the local development stack see the repository `README.md`.

## The environment

| Thing | Value |
|---|---|
| Cluster | DOKS `k8s-1-33-1-do-3-sfo2-1755028278626` (sfo2), context `do-sfo2-k8s-1-33-1-do-3-sfo2-1755028278626` |
| Namespace | `z-aziza` |
| Release | `aziza` |
| Ingress | `ingress-nginx`, class `nginx`, LoadBalancer `134.209.140.10` |
| Host | `aziza.codeaton.com.do` |
| TLS | `cert-manager` ClusterIssuer `letsencrypt-prod` (HTTP-01) |
| Registry | `ghcr.io/danielchaddy/aziza-internal`, pull secret `ghcr` — created here, because GHCR has no registry integration on this cluster |
| Database | DO Managed Postgres `dev-db-pgsql` (sfo2, PG 18) — databases `aziza` and `aziza_sessions` |
| Telemetry | The app **pushes** OTLP to the collector in the `observability` namespace |

**One workload and one scheduled job.** `sts/aziza` runs the Telegram webhook on the image's
default `CMD`; `cronjob/aziza-summary` runs `scripts/daily_summary.py` on the same image. Nothing
else is deployed.

## Prerequisites

Five things this chart does not create, in the order they are needed. None of them are in git.

**1 · The two databases.** On `dev-db-pgsql`, `aziza` and `aziza_sessions`, and a role that owns
both. They must be separate databases: ADK creates its own tables in whatever it is pointed at, and
pointed at the business schema it collides with it.

**2 · The DNS record.** `aziza.codeaton.com.do` as an `A` record to `134.209.140.10`, the
ingress-nginx LoadBalancer. cert-manager's HTTP-01 challenge cannot complete before this resolves,
so the certificate stays `False` and the host serves the default backend's certificate.

**3 · The pull secret.** GHCR is private and DOKS injects nothing for it, unlike DOCR. A GitHub
token with `read:packages` only:

```bash
kubectl -n z-aziza create secret docker-registry ghcr \
  --docker-server=ghcr.io --docker-username=<github-user> --docker-password=<token>
```

Without it the first pull is an `ImagePullBackOff`, which `--atomic` rolls back — so the release
disappears and the reason is in the events of a pod that no longer exists.

**4 · The app Secret.** `deploy/.env.example` lists every key and where its value comes from. It is
created out of band so the chart never renders a credential and `helm template` cannot leak one:

```bash
kubectl -n z-aziza create secret generic aziza-secrets \
  --from-env-file=deploy/.env --dry-run=client -o yaml | kubectl apply -f -
```

`create | apply` replaces the data wholesale, so a key added to the live Secret by hand is deleted
on the next run — add it to `deploy/.env` instead.

**5 · The webhook registration.** Telegram must be told where to deliver, with the same secret the
Secret carries:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d url=https://aziza.codeaton.com.do/webhook -d secret_token=<TELEGRAM_WEBHOOK_SECRET>
```

## Deploy

**A merge to main deploys, once `DEPLOY_ENABLED` is set.** `.github/workflows/ci.yml` runs Quality,
Test, Image and Deploy in that order: the image job pushes a tag named after the commit, and the
deploy job writes the kubeconfig, selects the context explicitly and runs `helm upgrade --install`.
The deploy job is skipped unless the repository variable `DEPLOY_ENABLED` is `true`, which is what
keeps a half-provisioned cluster from turning every push red.

**The tag is the short commit SHA, nothing else.** It has to be derivable from a git ref by anyone
holding the repository, or `helm rollback` points at an image nobody can rebuild. No `latest` moves.

**Cluster access is a stored kubeconfig**, `KUBECONFIG_B64`. The job selects the context by name
rather than trusting the kubeconfig's `current-context`, because this account has more than one
cluster and deploying to the wrong one would succeed. The trade: a stored kubeconfig is long-lived,
and is rotated like any other secret.

By hand, which is also how a rollback is driven:

```bash
helm -n z-aziza upgrade --install aziza deploy/helm/aziza \
  --set image.tag=$(git rev-parse --short HEAD) --atomic --wait --timeout 10m

helm -n z-aziza history aziza
helm -n z-aziza rollback aziza <revision>
```

## Building the database

`dbBuild.enabled` is `false` by default, so an ordinary upgrade leaves the database alone. Turn it
on for one run to create the schema:

```bash
helm -n z-aziza upgrade --install aziza deploy/helm/aziza \
  --set image.tag=$(git rev-parse --short HEAD) --set dbBuild.enabled=true --wait
```

**It seeds the fictitious salon.** `scripts/seed_mock.py` applies `db/schema.sql` and then loads
`aziza_adk/demo_data.py`, and there is no schema-only path. So a fresh release comes up with
invented specialists holding invented Telegram ids, which is why `summary.sendMode` defaults to
`simulate`: nothing can receive a live message yet. The salon's real catalog and its specialists'
real Telegram ids are both still open.

## What is not routed

`/simulate` runs a turn as whatever sender it is given and authenticates nobody. `ingress.yaml`
is an allowlist with no catch-all, so it is unreachable from the internet — and a route added to
that list later is a decision, not an accident. Reach it with a port-forward:

```bash
kubectl -n z-aziza port-forward sts/aziza 8080:8080
curl -sX POST localhost:8080/simulate -H 'content-type: application/json' \
     -d '{"sender":"700000001","text":"Le hice manicure y pedicure a Laura"}'
```

## Why the webhook cannot be scaled

`replicas: 1` is a correctness constraint, not a capacity choice, and it is not a value.
`channel_telegram/dedupe.py` and `channel_telegram/locks.py` both keep module-level state on one
event loop, so a second replica re-runs a retried delivery — charging a ticket twice — and stops
serializing one specialist's turns. Both fail silently. `templates/statefulset.yaml` carries the
detail; `tests/test_chart.py` fails if the replica count or the workload kind changes.
