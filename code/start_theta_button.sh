#!/bin/bash

# Log file for debugging
LOGFILE="/home/flipper/mandeye_controller/code/theta_startup.log"
THETA_SCRIPT="/home/flipper/mandeye_controller/code/theta_button.py"

log() {
    echo "[$(date)] $1" >> "$LOGFILE"
}

kill_resources() {
    local resource=$1
    local description=$2
    log "Killing $description..."
    sudo kill -9 $(sudo lsof -t "$resource" 2>/dev/null) 2>/dev/null || true
    log "$description processes killed (if any)."
}

start_theta_button() {
    log "Starting theta_button.py..."
    /usr/bin/python3 "$THETA_SCRIPT" >> "$LOGFILE" 2>&1
}

# Main Execution
log "Starting theta initialization script."
kill_resources "/dev/gpiochip*" "GPIO users"
kill_resources "/dev/bus/usb/002/003" "USB users"
sleep 2
start_theta_button
