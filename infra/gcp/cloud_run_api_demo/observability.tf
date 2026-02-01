# Observability as code
#
# Creates:
# - Monitoring dashboard for Cloud Run
# - Alerts: 5xx spikes + p95 latency regression

locals {
  cloudrun_base_filter = join(" ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.label.\"service_name\"=\"${var.service_name}\"",
  ])
}

resource "google_monitoring_dashboard" "cloudrun" {
  count   = var.enable_observability ? 1 : 0
  project = var.project_id

  dashboard_json = jsonencode({
    displayName = "EventPulse — ${var.service_name} (${var.env})"
    gridLayout = {
      columns = 2
      widgets = [
        {
          title = "Request count (per 60s)"
          xyChart = {
            dataSets = [
              {
                plotType = "LINE"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = join(" ", [
                      local.cloudrun_base_filter,
                      "metric.type=\"run.googleapis.com/request_count\"",
                    ])
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_DELTA"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = []
                    }
                  }
                }
              }
            ]
            yAxis = { label = "req/min", scale = "LINEAR" }
          }
        },
        {
          title = "5xx responses (per 60s)"
          xyChart = {
            dataSets = [
              {
                plotType = "LINE"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = join(" ", [
                      local.cloudrun_base_filter,
                      "metric.type=\"run.googleapis.com/request_count\"",
                      "metric.label.\"response_code_class\"=\"5xx\"",
                    ])
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_DELTA"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = []
                    }
                  }
                }
              }
            ]
            yAxis = { label = "errors/min", scale = "LINEAR" }
          }
        },
        {
          title = "Latency p95 (ms)"
          xyChart = {
            dataSets = [
              {
                plotType = "LINE"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = join(" ", [
                      local.cloudrun_base_filter,
                      "metric.type=\"run.googleapis.com/request_latencies\"",
                    ])
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_PERCENTILE_95"
                      crossSeriesReducer = "REDUCE_MEAN"
                      groupByFields      = []
                    }
                  }
                }
              }
            ]
            yAxis = { label = "ms", scale = "LINEAR" }
          }
        },
        {
          title = "Recent errors"
          logsPanel = {
            filter = "resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${var.service_name}\" severity>=ERROR"
            resourceNames = ["projects/${var.project_id}"]
          }
        },
      ]
    }
  })
}

resource "google_monitoring_alert_policy" "cloudrun_5xx" {
  count        = var.enable_observability ? 1 : 0
  project      = var.project_id
  display_name = "EventPulse — ${var.service_name} — 5xx > 0"
  combiner     = "OR"

  conditions {
    display_name = "Any 5xx responses"

    condition_threshold {
      filter          = join(" ", [local.cloudrun_base_filter, "metric.type=\"run.googleapis.com/request_count\"", "metric.label.\"response_code_class\"=\"5xx\""])
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0

      aggregations {
        alignment_period    = "60s"
        per_series_aligner  = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = []
      }
    }
  }

  notification_channels = var.notification_channels
  user_labels = {
    app = "eventpulse"
    env = var.env
  }
}

resource "google_monitoring_alert_policy" "cloudrun_latency" {
  count        = var.enable_observability ? 1 : 0
  project      = var.project_id
  display_name = "EventPulse — ${var.service_name} — p95 latency > 1000ms"
  combiner     = "OR"

  conditions {
    display_name = "p95 latency > 1000ms"

    condition_threshold {
      filter          = join(" ", [local.cloudrun_base_filter, "metric.type=\"run.googleapis.com/request_latencies\""])
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 1000

      aggregations {
        alignment_period    = "60s"
        per_series_aligner  = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MEAN"
        group_by_fields      = []
      }
    }
  }

  notification_channels = var.notification_channels
  user_labels = {
    app = "eventpulse"
    env = var.env
  }
}
