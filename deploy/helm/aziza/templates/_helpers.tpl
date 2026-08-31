{{/* Chart name, overridable by the release only through the release name. */}}
{{- define "aziza.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "aziza.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aziza.labels" -}}
app.kubernetes.io/name: {{ include "aziza.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: aziza
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Selector for the webhook workload. */}}
{{- define "aziza.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aziza.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: webhook
{{- end -}}

{{/*
Image reference. Fails the render on a tag that is empty or not a string, rather than emitting a
reference nothing can pull — an untagged image makes `helm rollback` meaningless, and a coerced one
names a tag no registry holds.
*/}}
{{- define "aziza.image" -}}
{{- if not .Values.image.tag -}}
{{- fail "image.tag is required — pass --set-string image.tag=$(git rev-parse --short HEAD). An untagged image makes helm rollback meaningless." -}}
{{- end -}}
{{- if not (kindIs "string" .Values.image.tag) -}}
{{- fail "image.tag must be a string — pass --set-string, not --set. A short SHA that is all digits is coerced to a number, and printf renders it as %!s(int64=…) instead of a tag." -}}
{{- end -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}

{{/* Cluster convention for TLS secret names: <host>-tls. */}}
{{- define "aziza.tlsSecretName" -}}
{{- printf "%s-tls" .Values.ingress.host -}}
{{- end -}}

{{/*
The env wiring for the webhook.

Order is load-bearing. `envFrom` resolves later entries over earlier ones, so the git-reviewable
ConfigMap is listed AFTER the Secret: the Secret is created with `--from-env-file=deploy/.env`,
which drags along whatever non-secret keys that file happens to carry, and the ConfigMap must win.

DATABASE_URL and ADK_SESSION_DB_URL are then set as explicit `env:` entries, which beat `envFrom`
outright. This is the fix for the most likely deploy bug: a .env written for docker-compose points
both at localhost:5434 and relies on compose to override them. `envFrom` has no such layer, so a
verbatim copy would have the pod dial localhost — /healthz 503s, readiness never passes, and the
rollout just looks hung.
*/}}
{{- define "aziza.envFrom" -}}
envFrom:
  - secretRef:
      name: {{ .Values.existingSecret }}
  - configMapRef:
      name: {{ include "aziza.fullname" . }}-env
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: {{ .Values.existingSecret }}
        key: DATABASE_URL
  - name: ADK_SESSION_DB_URL
    valueFrom:
      secretKeyRef:
        name: {{ .Values.existingSecret }}
        key: ADK_SESSION_DB_URL
{{- end -}}
