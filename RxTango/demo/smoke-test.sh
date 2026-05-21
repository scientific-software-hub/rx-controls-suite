#!/usr/bin/env bash

set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${DEMO_DIR}"

echo "== C++ Tango storage-ring smoke test =="

docker compose config >/dev/null

JBANG_DIR=/tmp/jbang jbang build scripts/StorageRingDashboard.java
JBANG_DIR=/tmp/jbang jbang build scripts/CorrelatedOrbitSnapshot.java
JBANG_DIR=/tmp/jbang jbang build scripts/SmoothedCurrentWriter.java
JBANG_DIR=/tmp/jbang jbang build scripts/BeamLossInterlocks.java
JBANG_DIR=/tmp/jbang jbang build scripts/RingBackpressure.java
JBANG_DIR=/tmp/jbang jbang build scripts/SetStorageRingScenario.java

docker compose build storage-ring-sim >/dev/null

echo "Smoke test passed"
