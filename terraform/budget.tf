# Keeps the Routes API, the only paid API billed to this project, under $20 a month. The quota is the cap, since a billing budget only sends alerts; the budget is a backstop for anything else that's billed.

locals {
  monthly_budget_usd = 20
  # the Pro rate, the higher of Compute Routes' two (https://developers.google.com/maps/billing-and-pricing/pricing), since it isn't documented whether alternative routes count as Pro. Not counting the free monthly calls, since those are per billing account.
  usd_per_route_request = 10 / 1000
  # 64, so that even a 31-day month is under budget
  route_requests_per_day = floor(local.monthly_budget_usd / local.usd_per_route_request / 31)
}

resource "google_service_usage_consumer_quota_override" "routes_per_day" {
  provider       = google-beta
  service        = "routes.googleapis.com"
  metric         = urlencode("routes.googleapis.com/compute_routes_requests")
  limit          = urlencode("/d/project")
  override_value = local.route_requests_per_day
  # needed to lower a quota by more than 10%, which this is, from unlimited
  force = true
}

data "google_project" "this" {}

resource "google_billing_budget" "monthly" {
  # `gcloud billing projects describe pleasant-rides`
  billing_account = "008587-FF94E1-5C3FFB"
  display_name    = "Pleasant Rides"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(local.monthly_budget_usd)
    }
  }

  # emails the billing account's admins as each is crossed
  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }

  # billingbudgets.googleapis.com
  depends_on = [google_project_service.services]
}
