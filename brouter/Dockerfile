# A BRouter server (https://github.com/abrensch/brouter) with its routing data built in, for running on Fly.io (see fly.toml here) and locally (see compose.yaml). Rebuild without the cache to get fresh data, which the public server updates weekly.

# built from a release, since the published release images (ghcr.io/abrensch/brouter) lag behind and are amd64-only
FROM gradle:jdk17-jammy AS build
ARG BROUTER_VERSION=v1.7.10
RUN git clone --depth 1 --branch $BROUTER_VERSION https://github.com/abrensch/brouter.git /brouter
WORKDIR /brouter
RUN ./gradlew :brouter-server:build -x test

# the segments (routing data) and profiles, from the public server
FROM curlimages/curl:8.10.1 AS data
# 5x5° tiles, named for their southwest corner; W75_N40 covers all of the sample trips (lon -75 to -70, lat 40 to 45). See https://brouter.de/brouter/segments4/ for others.
ARG TILES=W75_N40
USER root
RUN set -eu; \
  mkdir -p /data/segments4 /data/profiles2; \
  get() { echo "downloading $1"; curl -fsSL -o /data/$1 https://brouter.de/brouter/$1; }; \
  for tile in $TILES; do get segments4/$tile.rd5; done; \
  # all of the public server's profiles, since the server only comes with some (e.g. not quaelnix-gravel), and its lookups.dat, which goes with its segments
  get profiles2/lookups.dat; \
  for profile in $(curl -fsSL https://brouter.de/brouter/profiles2/ | grep -o '[A-Za-z0-9_.-]*\.brf' | sort -u); do get profiles2/$profile; done

FROM eclipse-temurin:17-jre
WORKDIR /brouter
COPY --from=build /brouter/brouter-server/build/libs/brouter-*-all.jar brouter.jar
COPY --from=data /data ./
# where uploaded profiles go; the server takes it as relative to profiles2
RUN mkdir profiles2/customprofiles
EXPOSE 17777
# more memory and time than the defaults, for long routes. The arguments are the segments, profiles, and uploaded profiles directories, the port, and the number of threads.
CMD ["java", "-Xmx1G", "-Xms256M", "-DmaxRunningTime=300", "-DuseRFCMimeType=false", "-cp", "brouter.jar", "btools.server.RouteServer", "segments4", "profiles2", "customprofiles", "17777", "4"]
