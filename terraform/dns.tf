# pleasant-rides.afeld.me, pointed at the Fly app, whose certificate for it is from `fly certs add`. Authenticates with CLOUDFLARE_API_TOKEN (see the README).

data "cloudflare_zone" "afeld_me" {
  filter = {
    name = "afeld.me"
  }
}

resource "cloudflare_dns_record" "app" {
  zone_id = data.cloudflare_zone.afeld_me.zone_id
  name    = "pleasant-rides.afeld.me"
  type    = "CNAME"
  # a CNAME rather than Fly's IPs, so it follows them if they change
  content = "pleasant-rides.fly.dev"
  # automatic
  ttl = 1
  # DNS only, so that Fly can issue and serve the certificate itself
  proxied = false
}
