#!/bin/bash
# Runs on EC2 after each deploy. .env (secrets) and venv stay on the server and are never overwritten.
set -e
cd /home/ec2-user/Ops-Analyst-Agent
[ -d venv ] || python3.11 -m venv venv
venv/bin/pip install -q -r requirements.txt
mkdir -p logs
# daily run at 05:00 UTC (08:00 Turkey); replace any old line so deploys never duplicate it
JOB="0 5 * * * cd $PWD && venv/bin/python pipeline.py >> logs/pipeline.log 2>&1"
(crontab -l 2>/dev/null | grep -v 'pipeline.py'; echo "$JOB") | crontab -
echo "deployed $(git rev-parse --short HEAD 2>/dev/null || date)" >> logs/deploys.log
