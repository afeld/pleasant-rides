# What existed in the project before Terraform managed it. These do nothing once applied, so they can be deleted after the first `terraform apply`.

import {
  to = google_apikeys_key.maps
  id = "projects/pleasant-rides/locations/global/keys/d40be9a6-77b1-4806-92ba-40bc668836fe"
}

import {
  for_each = toset(["cloudresourcemanager.googleapis.com", "apikeys.googleapis.com", "routes.googleapis.com"])
  to       = google_project_service.services[each.value]
  id       = "pleasant-rides/${each.value}"
}
