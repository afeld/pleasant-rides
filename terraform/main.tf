# The app's Google Cloud project (the APIs it uses, its Maps key, and its spending limits) and its DNS record. See "Deploying" in the README.

terraform {
  required_providers {
    google = {
      source = "hashicorp/google"
    }
    # for the Routes API's quota (see quota.tf), which only it can set
    google-beta = {
      source = "hashicorp/google-beta"
    }
    cloudflare = {
      source = "cloudflare/cloudflare"
    }
  }
}

provider "google" {
  project = "pleasant-rides"
  # bill API calls to this project rather than requiring application-default credentials with a quota project, so a token from `gcloud auth print-access-token` works (see the README)
  billing_project       = "pleasant-rides"
  user_project_override = true
}

provider "google-beta" {
  project               = "pleasant-rides"
  billing_project       = "pleasant-rides"
  user_project_override = true
}

locals {
  services = [
    # Terraform needs these to manage the project and its Maps key, so they're turned on with gcloud first (see the README)
    "cloudresourcemanager.googleapis.com",
    "apikeys.googleapis.com",
    # for the budget (see quota.tf)
    "billingbudgets.googleapis.com",
    # the Google provider (pleasant_rides/providers/google.py)
    "routes.googleapis.com",
    # Gemini Cloud Assist, for help managing the project in the console
    "cloudaicompanion.googleapis.com",
    "geminicloudassist.googleapis.com",
  ]
}

resource "google_project_service" "services" {
  for_each = toset(local.services)
  service  = each.value
  # leave them on if this config is ever removed, rather than breaking the app
  disable_on_destroy = false
}
