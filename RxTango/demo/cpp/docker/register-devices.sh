#!/usr/bin/env bash

set -euo pipefail

TANGO_HOST="${TANGO_HOST:-tango-dbds:10000}"
export TANGO_HOST

echo "Waiting for Tango database at ${TANGO_HOST}"
until tango_admin --ping-database >/dev/null 2>&1; do
  sleep 1
done

tango_admin --delete-server StorageRingSim/demo >/dev/null 2>&1 || true

tango_admin --add-server StorageRingSim/demo StorageRingController sr/demo/controller
tango_admin --add-server StorageRingSim/demo StorageRingSector \
  sr/demo/sector01,sr/demo/sector02,sr/demo/sector03,sr/demo/sector04,\
sr/demo/sector05,sr/demo/sector06,sr/demo/sector07,sr/demo/sector08

for index in 1 2 3 4 5 6 7 8; do
  device_name="$(printf 'sr/demo/sector%02d' "${index}")"
  tango_admin --add-property "${device_name}" SectorIndex "${index}"
done

echo "StorageRingSim devices registered"
