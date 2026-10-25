#!/bin/bash
# Daily job that cron starts at 05:00 UTC. EventBridge Scheduler starts the instance at 04:55 UTC;
# after the run the instance stops itself, so it runs about 10 minutes a day.
# A manual `python pipeline.py` never stops the instance: only this script does.
cd "$(dirname "$0")/.."
venv/bin/python pipeline.py >> logs/pipeline.log 2>&1
echo "daily run done $(date -u +%Y-%m-%dT%H:%M:%SZ), stopping in 5 min (cancel: sudo shutdown -c)" >> logs/pipeline.log
sudo shutdown -h +5
