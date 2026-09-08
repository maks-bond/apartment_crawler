#!/bin/sh
set -u
cd /home/maksym/dev/apartment_crawler || exit 1
mkdir -p data/logs
export PYTHONPATH=src
printf '\n[%s] daily collection started\n' "$(date --iso-8601=seconds)" >> data/logs/daily.log
python3 -m apartment_monitor collect --all >> data/logs/daily.log 2>&1
collect_status=$?
python3 -m apartment_monitor report >> data/logs/daily.log 2>&1
python3 -m apartment_monitor export >> data/logs/daily.log 2>&1
printf '[%s] daily collection finished status=%s\n' "$(date --iso-8601=seconds)" "$collect_status" >> data/logs/daily.log
exit "$collect_status"
