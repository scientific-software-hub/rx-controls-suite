# TINE test device server
#
# The TINE jar is NOT on Maven Central and must be supplied at build time.
# Place tine.jar (and optionally tine-server.jar if split) in this directory
# before building, or pass TINE_JAR_URL as a build argument to download it.
#
# Build:
#   # Option A — local jar (recommended)
#   cp /path/to/tine.jar .
#   docker build -t rxtine-testserver .
#
#   # Option B — download from a known URL
#   docker build --build-arg TINE_JAR_URL=http://your-mirror/tine.jar \
#                -t rxtine-testserver .
#
# Run (standalone, no docker-compose):
#   docker run --rm -p 7000:7000 rxtine-testserver

FROM eclipse-temurin:11-jdk-alpine AS builder

WORKDIR /build

# ── obtain the TINE jar ───────────────────────────────────────────────────────
ARG TINE_JAR_URL=""
COPY tine*.jar* ./
RUN if [ -n "$TINE_JAR_URL" ] && [ ! -f tine.jar ]; then \
        wget -O tine.jar "$TINE_JAR_URL"; \
    fi && \
    ls -lh tine*.jar

# ── compile the test server ───────────────────────────────────────────────────
COPY TestDeviceServer.java .
RUN javac -cp tine.jar TestDeviceServer.java

# ─────────────────────────────────────────────────────────────────────────────
FROM eclipse-temurin:11-jre-alpine

WORKDIR /app

# Runtime artifacts
COPY --from=builder /build/tine.jar          ./
COPY --from=builder /build/TestDeviceServer*.class ./

# TINE config (mounted as /tine-config at runtime for easy override)
COPY fecid.csv           /tine-config/
COPY exports.csv         /tine-config/
COPY RXTEST-devices.csv  /tine-config/
COPY tine.properties     /tine-config/

# TINE server TCP port
EXPOSE 7000

ENV JAVA_OPTS="-Dtine.home=/tine-config"

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -cp tine.jar:. TestDeviceServer ${N_DEVICES:-1}"]
