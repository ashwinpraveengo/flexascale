{{- define "flexascale.labels" -}}
app.kubernetes.io/name: flexascale
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "flexascale.validate" -}}
{{- if not (has .Values.policy.mode (list "observe" "live")) -}}
{{- fail (printf "policy.mode must be 'observe' or 'live', got '%s'" .Values.policy.mode) -}}
{{- end -}}
{{- if not .Values.policy.namespace -}}
{{- fail "policy.namespace (the target application namespace) is required" -}}
{{- end -}}
{{- if lt (int .Values.policy.max_replicas) (int .Values.policy.min_replicas) -}}
{{- fail "policy.max_replicas must be >= policy.min_replicas" -}}
{{- end -}}
{{- end -}}
