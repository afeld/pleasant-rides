# Pleasant Ride Planner

Mapping apps are good at getting you from place to place, but they generally optimize for minimum travel time. For travel by bike, that isn't always desirable. This repository is exploring what it would mean to find the "most pleasant" bike route from A to B. This applies within cities/towns, and also in more rural areas.

![screenshot of analysis page](analysis.png)

There isn't a public instance of the app/analysis at this point - see [Running](#running) to get it working on your computer.

## Working definition

A "pleasant" bike ride is:

- **Enjoyable**
  - Things to look at, such as:
    - Nature
    - Good views
  - Points of interest
  - Quiet
- **Easy**
  - Avoids steep climbs/descents
  - Simple navigation
    - Not many turns
  - Smooth-ish surface, such as:
    - Pavement
    - Boardwalks (where cycling is permitted)
    - Crushed gravel
  - Minimal walking required, such as:
    - One-ways
    - Stairs
- **Safe**
  - Minimal:
    - Vehicular traffic
    - Intersections
  - If there _are_ motor vehicles:
    - A low speed limit
    - The fewer lanes, the better
  - Not _too_ remote
    - Theoretically walkable to somewhere you can get help if you need.

A pleasant ride is _not necessarily_ the most direct, but it shouldn't add a ton of time over the most direct route, either. Similarly, a pleasant route isn't necessarily the most popular one.

## Running

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
1. Install dependencies:

   ```sh
   uv sync
   ```

1. Create a `.env` file with API keys for the providers that need them. Any provider without a key is skipped (with a warning in the app).

   ```sh
   GOOGLE_MAPS_API_KEY=...
   GRAPHHOPPER_API_KEY=...
   CYCLEMATE_API_KEY=...
   ```

   Instead of (or as well as) Cyclemate's API key, people can sign in with Cyclemate, so its routes are requested as them, against their own rate limit. That needs an [OAuth client](https://docs.cyclemate.club/api-reference/oauth), which you get by emailing support@cyclemate.club with the app's name, its redirect URI (`http://localhost:8501/` locally), and whether it's confidential (with a secret) or public. Cyclemate asks for one client per environment. Then add it to `.env`:

   ```sh
   CYCLEMATE_CLIENT_ID=...
   # only for a confidential client
   CYCLEMATE_CLIENT_SECRET=...
   ```

   Valhalla and BRouter use public servers and don't need keys (or run BRouter yourself; see [Local BRouter](#local-brouter)). The Apple Maps provider needs macOS with the Xcode command line tools (`xcode-select --install`); it compiles a small Swift program the first time it runs. Scoring also uses Valhalla's public server, plus [Overture Maps](https://overturemaps.org/) data for scenery, points of interest, and remoteness, which is downloaded from its public S3 bucket.

1. Start the app:

   ```sh
   uv run --env-file .env streamlit run app.py
   ```

   It opens at http://localhost:8501. The app reruns when you save `app.py`, its pages under `app_pages/`, or anything under `pleasant_rides/`. Routes are cached to disk (in `~/.streamlit/cache`) per provider (and its settings) and origin/destination, so they're kept across restarts. To refetch them, use "Clear cache" from the app's ⋮ menu.

## Local BRouter

BRouter's public server is free but busy: long routes sometimes get killed, and the app waits between requests to be polite. To run your own in [Docker](https://docs.docker.com/get-started/get-docker/):

1. Start it:

   ```sh
   docker compose up
   ```

   The first time, this builds BRouter from source and downloads its routing data for the area around New York City (~120 MB), which takes a minute or two. After that it starts in a few seconds. For other areas, set `BROUTER_TILES` to [tiles](https://brouter.de/brouter/segments4/) separated by spaces, e.g. `BROUTER_TILES="W75_N40 W80_N40"`.

1. Add this to your `.env`:

   ```sh
   BROUTER_URL=http://localhost:17777/brouter
   ```

   Routes from it are cached separately from the public server's.

To stop it, run `docker compose down`. To wipe it, including the downloaded data (e.g. to get fresh data, which the public server updates weekly), run `docker compose down -v --rmi all`.

## Deploying

The app runs on [Fly.io](https://fly.io/), which stops it when nobody's connected and starts it on the next request. A volume keeps Streamlit's disk cache across restarts. Deployed copies require signing in with Google, and only the sign-in client's test users get in (see [`pleasant_rides/login.py`](pleasant_rides/login.py)), since they spend the API keys and the public servers' capacity. The Google Cloud project (`pleasant-rides`) and the `pleasant-rides.afeld.me` DNS record (in Cloudflare) are managed with [Terraform](https://developer.hashicorp.com/terraform), except for the sign-in client, which Terraform can't create.

1. Apply the Terraform config, signed in to gcloud as an owner of the project (`--no-activate` leaves your other gcloud configurations alone):

   ```sh
   gcloud auth login --no-activate <your Google account>
   ```

   ```sh
   export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token <your Google account>)
   ```

   For the DNS record, [create a Cloudflare API token](https://dash.cloudflare.com/profile/api-tokens) with the "Edit zone DNS" template, limited to the `afeld.me` zone:

   ```sh
   export CLOUDFLARE_API_TOKEN=<token>
   ```

   Terraform needs two APIs turned on before it can manage the rest, so turn those on with gcloud:

   ```sh
   gcloud services enable cloudresourcemanager.googleapis.com apikeys.googleapis.com --project pleasant-rides --account <your Google account>
   ```

   ```sh
   terraform -chdir=terraform init && terraform -chdir=terraform apply
   ```

   The state is kept locally (and ignored by Git), since it includes the Maps key itself.

1. In the [Google Auth Platform](https://console.cloud.google.com/auth/overview?project=pleasant-rides):
   1. Under Audience, choose External, leave it in Testing, and add the people who should have access as test users. Testing mode only lets test users sign in, so it's the allowlist: don't publish the app, or any Google account could get in.
   1. Under Clients, create a Web application client with the authorized redirect URI `https://pleasant-rides.afeld.me/oauth2callback`.
1. Create `.streamlit/secrets.toml` (ignored by Git) with the client's ID and secret:

   ```toml
   [auth]
   redirect_uri = "https://pleasant-rides.afeld.me/oauth2callback"
   cookie_secret = "<a long random string, e.g. from `openssl rand -hex 32`>"
   client_id = "<client ID>"
   client_secret = "<client secret>"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```

1. Install [flyctl](https://fly.io/docs/flyctl/install/), sign in (`fly auth login`), and create the app. Everything else about it is in [`fly.toml`](fly.toml).

   ```sh
   fly apps create pleasant-rides
   ```

   ```sh
   fly certs add pleasant-rides.afeld.me
   ```

1. Set the secrets: the API keys from `.env` (only the `*_KEY` variables, since e.g. `BROUTER_URL` points at your local BRouter), and `secrets.toml`, which Fly needs base64-encoded:

   ```sh
   grep '_KEY=' .env | fly secrets import --stage
   ```

   ```sh
   fly secrets set STREAMLIT_SECRETS="$(base64 < .streamlit/secrets.toml)"
   ```

   To let people sign in with Cyclemate, set the production client's ID (and secret, if it has one), which Cyclemate issues separately from your local one, for the redirect URI `https://pleasant-rides.afeld.me/` (set as `CYCLEMATE_REDIRECT_URI` in `fly.toml`):

   ```sh
   fly secrets set --stage CYCLEMATE_CLIENT_ID=... CYCLEMATE_CLIENT_SECRET=...
   ```

1. Deploy the first time, which also creates the cache volume. `--ha=false` keeps it to one machine, since the cache volume can only be attached to one, and one is plenty:

   ```sh
   fly deploy --ha=false
   ```

After that, pushes to `main` deploy automatically, through Fly's GitHub integration (set up in the [app's dashboard](https://fly.io/apps/pleasant-rides)). Later deploys update the existing machine, so they don't need `--ha=false`.

To change who has access, edit the [test users](https://console.cloud.google.com/auth/audience?project=pleasant-rides). It takes effect on their next sign-in, without a deploy.

## Benchmarking

The app's Benchmark page compares providers' routing parameters. It scores each variant's first route on a few sample trips. To try new parameters, add a variant to `VARIANTS` in [`pleasant_rides/benchmark/variants.py`](pleasant_rides/benchmark/variants.py). Results come from the providers' live servers, so they can drift; compare against the baselines (the `(current)` variants) from the same run. It also shows how long each variant's provider took to return routes; for cached routes, that's from when they were fetched.

## Bike lanes

The app's Bike lanes page compares New York City's bike lanes in [OpenStreetMap](https://www.openstreetmap.org/) (from the [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)), [Overture Maps](https://overturemaps.org/), and NYC DOT's [bike routes](https://data.cityofnewyork.us/d/mzxg-pwib) on NYC Open Data: how many kilometers of each type of lane each has, how much of each source's lanes the others have too, and a map of them. Each source is fetched once for the whole city and cached to disk; the first load can take a minute or two, since the public Overpass servers are often busy.

## Testing

```sh
uv run pytest
uv run pyright
```

The tests don't make network requests. GitHub Actions runs both on pushes to `main` and on pull requests.

## See also

- [Cyclemate](https://cyclemate.club/)
  - [Methodology](https://cyclemate.club/supersafe)
