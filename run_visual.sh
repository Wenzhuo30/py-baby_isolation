#!/bin/bash

set -e

WORLD_FILE=${1:-irsim_worlds/world_easy.yaml}

echo "Running visual IR-SIM simulation"
echo "World: $WORLD_FILE"
echo "Using generated/navigation_logic.py"
echo

python3 test_irsim_with_agent.py "$WORLD_FILE"