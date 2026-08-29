# Kubernetes deployment (Helm)

This is the operations runbook. For the local development stack see the repository `README.md`.

## The environment

| Thing | Value |
|---|---|
| Cluster | DOKS `k8s-1-33-1-do-3-sfo2-1755028278626` (sfo2), context `do-sfo2-k8s-1-33-1-do-3-sfo2-1755028278626` |
| Namespace | `z-aziza` |
| Release | `aziza` |
| Ingress | `ingress-nginx`, class `nginx`, LoadBalancer `134.209.140.10` |
| Host | `aziza.danielchaddy.com` — deliberately NOT under the client's zone, which would name this service beside its siblings and publish that to Certificate Transparency |
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

**2 · The DNS record.** `aziza.danielchaddy.com` as an `A` record to `134.209.140.10`, the
ingress-nginx LoadBalancer. That zone is hosted at GoDaddy rather than in this DigitalOcean
account, so the record is created there and `doctl` cannot see it. cert-manager's HTTP-01 challenge
cannot complete before it resolves, so the certificate stays `False` and the host serves the
default backend's certificate.

Issuance publishes the hostname to public Certificate Transparency logs permanently. That is how
CT works and cannot be opted out of, which is why the name lives outside the client's zone.

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
     -d url=https://aziza.danielchaddy.com/webhook -d secret_token=<TELEGRAM_WEBHOOK_SECRET>
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

**It loads the salon's real catalog and its real people.** `scripts/seed_catalog.py` applies
`db/schema.sql`, then `aziza_adk/catalog_data.py` — the salon's own services and products at the
salon's own prices — and then `aziza_adk/staff_data.py`. There is no schema-only path.

**The invented specialists are NOT seeded here.** They live behind `--with-demo-specialists`,
which this Job does not pass, so a real database carries only people who exist.

**Removing someone from the dataset revokes them.** The seed stands down every specialist whose
ref it no longer holds, because a Telegram id the database keeps active is a credential — see
`queries.stand_down_absent`. Deactivated rather than deleted: her sales are the salon's record.

**Removing a row from the catalog retires it**, for the same reason and by the same rule. The
seed deactivates every product and service whose ref `catalog_data.py` no longer holds — see
`queries.retire_absent` — so a de-duplication that edits the dataset reaches the database instead
of leaving the dropped row sellable and still listed in the prompt.

`summary.sendMode` is `live`: the seed registers real people with real Telegram ids, so a
specialist who billed that day receives her end-of-day message. An owner who does no salon work
is owed none.

## Rebuilding after a schema change

`db/schema.sql` only creates what is absent, so a changed column never reaches a built database.
The rebuild is: check nothing real is there, drop, then upgrade with `dbBuild.enabled=true`.

```bash
# 1. REFUSE if anything real exists. sales is money billed and specialist_ledger is what a
#    specialist owes; neither can be reconstructed, and both are empty only until somebody works.
# 2. drop every table in `aziza` — `aziza_sessions` is ADK's and is left alone.
# 3. helm upgrade --set dbBuild.enabled=true
kubectl -n z-aziza delete pod aziza-0        # <- REQUIRED. Why, below.
```

**That last step is not tidying, and leaving it out strands the service.** The old image cannot
read the new schema, so its `/healthz` starts failing the moment the tables are dropped — and a
single-replica StatefulSet under `OrderedReady` **will not roll an update while its pod is
unready**. The unreadiness blocks the very update that would fix it, `helm upgrade` sits until it
times out, and the release records as failed while the old pod serves errors. Deleting the pod is
what breaks the deadlock; the StatefulSet recreates it at the new image immediately.

The StatefulSet is still right — `replicas: 1` is the at-most-one-process guarantee a Deployment
cannot give (see `templates/statefulset.yaml`). This is the cost of it, and it is only paid on a
schema change that the running image cannot read.

**Expect a gap.** Between the drop and the new pod passing readiness the service answers errors,
and Telegram deliveries in that window are lost rather than queued. Do it when nobody is working.

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
