# The key the Google provider uses (GOOGLE_MAPS_API_KEY), created in the console when the Maps Platform was set up
resource "google_apikeys_key" "maps" {
  name         = "d40be9a6-77b1-4806-92ba-40bc668836fe"
  display_name = "Maps Platform API Key"

  restrictions {
    api_targets {
      service = "routes.googleapis.com"
    }
  }

  # the deployed app and .env depend on it, and a replacement would have a new value
  lifecycle {
    prevent_destroy = true
  }
}
