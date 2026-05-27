{{/*
Common labels
*/}}
{{- define "carapace.labels" -}}
app.kubernetes.io/name: carapace
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
Server image with tag defaulting to appVersion
*/}}
{{- define "carapace.serverImage" -}}
{{ .Values.image.registry }}/{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Frontend image with tag defaulting to appVersion
*/}}
{{- define "carapace.frontendImage" -}}
{{ .Values.frontend.image.registry }}/{{ .Values.frontend.image.repository }}:{{ .Values.frontend.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Sandbox image with tag defaulting to appVersion
*/}}
{{- define "carapace.sandboxImage" -}}
{{ .Values.sandbox.image.registry }}/{{ .Values.sandbox.image.repository }}:{{ .Values.sandbox.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Sandbox owner name. Nil means use the release default, empty string means Deployment fallback.
*/}}
{{- define "carapace.sandboxesName" -}}
{{- if eq .Values.sandbox.sandboxesName nil -}}
{{ printf "%s-sandboxes" .Release.Name }}
{{- else -}}
{{ .Values.sandbox.sandboxesName }}
{{- end -}}
{{- end }}

{{/*
Bitwarden CLI image with tag defaulting to appVersion
*/}}
{{- define "carapace.bitwardenImage" -}}
{{ .Values.bitwarden.image.registry }}/{{ .Values.bitwarden.image.repository }}:{{ .Values.bitwarden.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Bitwarden nginx proxy image
*/}}
{{- define "carapace.bitwardenNginxImage" -}}
{{ .Values.bitwarden.nginx.image.registry }}/{{ .Values.bitwarden.nginx.image.repository }}:{{ .Values.bitwarden.nginx.image.tag }}
{{- end }}

{{/*
Standalone Bitwarden resource name for one instance.
*/}}
{{- define "carapace.bitwardenStandaloneName" -}}
{{- $root := .root -}}
{{- $instance := .instance -}}
{{- if $instance.fullnameOverride -}}
{{ $instance.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else -}}
{{ printf "%s-bitwarden-%s" $root.Release.Name $instance.name | trunc 63 | trimSuffix "-" }}
{{- end -}}
{{- end }}
