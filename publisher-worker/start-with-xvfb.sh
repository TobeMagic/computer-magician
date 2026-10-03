#!/bin/bash
# Wrapper script to start Xvfb then run the publisher worker
set -e

# Start Xvfb if not already running
if [ ! -S /tmp/.X11-unix/X99 ]; then
    echo "Starting Xvfb on display :99..."
    nohup Xvfb :99 -screen 0 1280x720x24 > /dev/null 2>&1 &
    XVFB_PID=$!
    # Wait for X server to be ready
    sleep 2
    if [ ! -S /tmp/.X11-unix/X99 ]; then
        echo "ERROR: Xvfb failed to start"
        exit 1
    fi
    echo "Xvfb started with PID $XVFB_PID"
fi

export DISPLAY=:99
echo "Starting publisher worker with DISPLAY=$DISPLAY"
exec npm run start --prefix /workspace/aimagician/publisher-worker
