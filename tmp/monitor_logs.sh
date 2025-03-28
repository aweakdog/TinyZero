#!/bin/bash

LOG_FILE="../logs/ContinualCountdown1.5B_SingleRun.log"

while true; do
    if [ -f "$LOG_FILE" ]; then
        clear  # Clear the screen
        echo "=== Monitoring $LOG_FILE ==="
        echo "Press Ctrl+C to exit"
        echo "=========================="
        tail -f "$LOG_FILE"
    else
        echo "Waiting for log file to be created..."
        sleep 1
    fi
done
