# Pleasant Ride Planner

Mapping apps are good at getting you from place to place, but they generally optimize for minimum travel time. For travel by bike, that isn't always desirable. This repository is exploring what it would mean to find the "most pleasant" bike route from A to B. This applies within cities/towns, and also in more rural areas.

## Working definition

A "pleasant" bike ride is:

- **Enjoyable**
  - Things to look at, such as:
    - Nature
    - Good views
  - Points of interest
- **Easy**
  - Avoids steep climbs/descents
  - Avoids taking a ton of turns
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
    - Only 1-2 lanes
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

   Valhalla and BRouter use public servers and don't need keys. The Apple Maps provider needs macOS with the Xcode command line tools (`xcode-select --install`); it compiles a small Swift program the first time it runs. Scoring also uses Valhalla's public server, plus [Overture Maps](https://overturemaps.org/) data for scenery, points of interest, and remoteness, which is downloaded from its public S3 bucket.

1. Start the app:

   ```sh
   uv run --env-file .env streamlit run app.py
   ```

   It opens at http://localhost:8501. The app reruns when you save `app.py`, its pages under `app_pages/`, or anything under `pleasant_rides/`. Routes are cached to disk (in `~/.streamlit/cache`) per provider (and its settings) and origin/destination, so they're kept across restarts. To refetch them, use "Clear cache" from the app's ⋮ menu.

## Benchmarking

The app's Benchmark page compares providers' routing parameters. It scores each variant's first route on a few sample trips. To try new parameters, add a variant to `VARIANTS` in [`pleasant_rides/benchmark.py`](pleasant_rides/benchmark.py). Results come from the providers' live servers, so they can drift; compare against the baselines (the `(current)` variants) from the same run. It also shows how long each variant's provider took to return routes; for cached routes, that's from when they were fetched.

## See also

- [Cyclemate](https://cyclemate.club/)
  - [Methodology](https://cyclemate.club/supersafe)
