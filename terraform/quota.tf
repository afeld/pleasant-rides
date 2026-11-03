# Keeps the Routes API, the only paid API billed to this project, under $20 a month. The quota is the cap, since a billing budget only sends alerts.

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

# the billing account's budget is managed in Aidan's dotfiles (terraform/gcp-organization/budgets.tf), since the billing account is shared with other Projects
removed {
  from = google_billing_budget.monthly

  lifecycle {
    destroy = false
  }
}
