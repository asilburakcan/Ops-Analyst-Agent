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
echo "deployed $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> logs/deploys.log

# Streamlit operator view as a service, bound to localhost only (reach it with SSM port forwarding; no open port)
sudo tee /etc/systemd/system/ops-app.service >/dev/null <<UNIT
[Unit]
Description=Ops Analyst Agent Streamlit app
After=network-online.target

[Service]
User=ec2-user
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/streamlit run app.py --server.headless true --server.address 127.0.0.1 --server.port 8501
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable ops-app >/dev/null 2>&1
sudo systemctl restart ops-app
