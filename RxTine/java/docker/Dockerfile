# TINE sine-wave test device server
#
# Uses the official jsineServer.jar from the TINE distribution.
# Place jsineServer.jar and tine.jar in this directory before building.
#
# Build:
#   cp /path/to/tine.jar /path/to/jsineServer.jar .
#   docker build -t rxtine-testserver .
#
# Run (standalone):
#   docker run --rm -p 7000:7000 --hostname jsinesrv rxtine-testserver
#
# Client address (direct, no TNS):
#   /TEST/JSINESRV/SINEDEV_0@jsinesrv

FROM eclipse-temurin:11-jre-alpine

WORKDIR /app

# Runtime jars (not on Maven Central — supplied by the user)
COPY tine.jar          ./
COPY jsineServer.jar   ./

# TINE config (mounted as /tine-config; override by uncommenting volume in docker-compose.yml)
COPY fecid.csv          /tine-config/
COPY exports.csv        /tine-config/
COPY SJNEQM-devices.csv /tine-config/
COPY tine.properties    /tine-config/
# Address resolution: maps server names → FEC addresses (needed for alarm subsystem init)
COPY eqpdbase.csv       /tine-config/
COPY fecaddr.csv        /tine-config/
# Pre-populate the dynamic address cache so TINE finds addresses without ENS
RUN mkdir -p /var/tmp/tine/cache && \
    cp /tine-config/eqpdbase.csv /var/tmp/tine/cache/eqpdbase.csv && \
    cp /tine-config/fecaddr.csv  /var/tmp/tine/cache/fecaddr.csv

# TINE server TCP port
EXPOSE 7000

ENV JAVA_OPTS="-Dtine.home=/tine-config"

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -cp tine.jar:jsineServer.jar de.desy.tine.example.sine.SineDeviceServer </dev/null"]
