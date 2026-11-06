# A GraphHopper server (https://github.com/graphhopper/graphhopper) with its routing data built in, for running on Fly.io (see fly.toml here) and locally (see compose.yaml). Rebuild without the cache to get fresh data, which Geofabrik updates daily.

# the OpenStreetMap data, from Geofabrik's extracts, merged and cut down to an area
FROM debian:trixie-slim AS osm
# Geofabrik extracts (see https://download.geofabrik.de/), merged together. The defaults cover the sample trips.
ARG REGIONS="north-america/us/new-york north-america/us/new-jersey north-america/us/connecticut"
# the part of them to keep, as west,south,east,north, to keep the import small; the default is the same area as BRouter's (see brouter/Dockerfile). Empty keeps all of it.
ARG BBOX="-75,40,-70,45"
# a .osm.pbf file to use instead of REGIONS, e.g. a small one for testing
ARG PBF_URL=""
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl osmium-tool && rm -rf /var/lib/apt/lists/*
WORKDIR /osm
RUN set -eu; \
  mkdir /download; \
  get() { echo "downloading $1"; curl -fsSL -o "/download/$(basename "$1")" "$1"; }; \
  if [ -n "$PBF_URL" ]; then \
    get "$PBF_URL"; \
  else \
    for region in $REGIONS; do get "https://download.geofabrik.de/$region-latest.osm.pbf"; done; \
  fi; \
  osmium merge --output /download/merged.osm.pbf /download/*.osm.pbf; \
  if [ -n "$BBOX" ]; then \
    osmium extract --bbox "$BBOX" --strategy smart --output map.osm.pbf /download/merged.osm.pbf; \
  else \
    mv /download/merged.osm.pbf map.osm.pbf; \
  fi; \
  rm -r /download

FROM eclipse-temurin:21-jre AS base
ARG GRAPHHOPPER_VERSION=11.0
WORKDIR /graphhopper
ADD https://github.com/graphhopper/graphhopper/releases/download/$GRAPHHOPPER_VERSION/graphhopper-web-$GRAPHHOPPER_VERSION.jar graphhopper.jar
COPY config.yml ./

# the graph, built in the image so the server starts in seconds rather than importing on every start
FROM base AS import
# the import needs more memory than serving does
ARG JAVA_OPTS="-Xmx4g"
COPY --from=osm /osm/map.osm.pbf /osm/
RUN java $JAVA_OPTS -jar graphhopper.jar import config.yml

FROM base
COPY --from=import /graphhopper/graph-cache graph-cache
EXPOSE 8989
CMD ["java", "-Xmx1g", "-jar", "graphhopper.jar", "server", "config.yml"]
