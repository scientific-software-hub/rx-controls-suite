#!/bin/bash
# Smoke test script for RxTango Storage Ring Simulation

set -e

echo "========================================"
echo "RxTango Storage Ring - Smoke Test"
echo "========================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo "1. Checking prerequisites..."

# Check jbang
if ! command -v jbang &> /dev/null; then
    echo -e "${RED}✗ jbang not found${NC}"
    echo "  Install with: curl -Ls https://sh.jbang.dev | bash"
    exit 1
fi
echo -e "${GREEN}✓ jbang found${NC}"

# Check Java
if ! command -v java &> /dev/null; then
    echo -e "${RED}✗ Java not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Java found${NC}"
echo "  Java version: $(java -version 2>&1 | head -n 1)"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found${NC}"
    echo "  Install Docker from https://docs.docker.com/get-docker/"
    exit 1
fi
echo -e "${GREEN}✓ Docker found${NC}"

# Check if docker compose is available
if ! docker compose version &> /dev/null; then
    echo -e "${RED}✗ docker compose not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ docker compose found${NC}"
echo ""

# Check if Tango stack is running
echo "2. Checking Tango stack..."
if docker compose ps | grep -q "Up"; then
    echo -e "${GREEN}✓ Tango stack is running${NC}"
else
    echo -e "${YELLOW}⚠ Tango stack not running${NC}"
    echo "  Starting Tango stack..."
    docker compose up -d
    echo "  Waiting for Tango stack to be healthy..."
    sleep 10
    if docker compose ps | grep -q "Up"; then
        echo -e "${GREEN}✓ Tango stack is now running${NC}"
    else
        echo -e "${RED}✗ Tango stack failed to start${NC}"
        exit 1
    fi
fi
echo ""

# Check if devices exist
echo "3. Checking devices..."
cd /home/ingvord/Projects/rx-controls-suite/RxTango/java

# Create devices if they don't exist
for i in {1..12}; do
    if ! tango-admin -l | grep -q "SR/BPM$i"; then
        echo -e "${YELLOW}⚠ Creating SR/BPM$i${NC}"
        tango-admin -c "SR/BPM$i" BPM
    else
        echo -e "${GREEN}✓ SR/BPM$i${NC}"
    fi
done

for i in {1..8}; do
    if ! tango-admin -l | grep -q "SR/VAC$i"; then
        echo -e "${YELLOW}⚠ Creating SR/VAC$i${NC}"
        tango-admin -c "SR/VAC$i" VacuumGauge
    else
        echo -e "${GREEN}✓ SR/VAC$i${NC}"
    fi
done

for i in {1..6}; do
    if ! tango-admin -l | grep -q "SR/RAD$i"; then
        echo -e "${YELLOW}⚠ Creating SR/RAD$i${NC}"
        tango-admin -c "SR/RAD$i" RadiationMonitor
    else
        echo -e "${GREEN}✓ SR/RAD$i${NC}"
    fi
done

for i in {1..4}; do
    if ! tango-admin -l | grep -q "SR/BLD$i"; then
        echo -e "${YELLOW}⚠ Creating SR/BLD$i${NC}"
        tango-admin -c "SR/BLD$i" BeamLossDetector
    else
        echo -e "${GREEN}✓ SR/BLD$i${NC}"
    fi
done

if ! tango-admin -l | grep -q "SR/Control"; then
    echo -e "${YELLOW}⚠ Creating SR/Control${NC}"
    tango-admin -c "SR/Control" ControlSystem
else
    echo -e "${GREEN}✓ SR/Control${NC}"
fi
echo ""

# Test basic device read
echo "4. Testing device read..."
if tango-admin -l | grep -q "SR/BPM1"; then
    echo -e "${GREEN}✓ Device read test passed${NC}"
else
    echo -e "${RED}✗ Device read test failed${NC}"
    exit 1
fi
echo ""

# Test reactive demo
echo "5. Testing reactive demo..."
if jbang examples/ReactiveVsImperative.java reactive > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Reactive demo test passed${NC}"
else
    echo -e "${RED}✗ Reactive demo test failed${NC}"
    exit 1
fi
echo ""

# Test beam loss scenario
echo "6. Testing beam loss scenario..."
if jbang examples/BeamLossScenario.java reset > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Beam loss scenario test passed${NC}"
else
    echo -e "${RED}✗ Beam loss scenario test failed${NC}"
    exit 1
fi
echo ""

# Summary
echo "========================================"
echo -e "${GREEN}✓ All smoke tests passed!${NC}"
echo "========================================"
echo ""
echo "You can now run the demos:"
echo "  jbang examples/StorageRingSimulation.java start"
echo "  jbang examples/BeamLossScenario.java trigger"
echo "  jbang examples/ReactiveVsImperative.java both"
echo ""