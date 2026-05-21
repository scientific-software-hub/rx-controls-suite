FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    libtango-dev \
    tango-db \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/storage-ring

COPY CMakeLists.txt /opt/storage-ring/CMakeLists.txt
COPY src /opt/storage-ring/src
COPY docker/register-devices.sh /opt/storage-ring/register-devices.sh

RUN chmod +x /opt/storage-ring/register-devices.sh \
 && cmake -S /opt/storage-ring -B /opt/storage-ring/build \
 && cmake --build /opt/storage-ring/build --parallel \
 && cp /opt/storage-ring/build/StorageRingSim /usr/local/bin/StorageRingSim

ENTRYPOINT ["/usr/local/bin/StorageRingSim"]
CMD ["demo", "-ORBendPoint", "giop:tcp:127.0.0.1:2809"]
