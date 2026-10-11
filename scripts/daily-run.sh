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
python3 -m listing_monitor collect >> data/logs/daily.log 2>&1
listing_status=$?
python3 -m listing_monitor report >> data/logs/daily.log 2>&1
listing_report_status=$?
printf '[%s] daily collection finished communities=%s craigslist=%s craigslist_report=%s\n' "$(date --iso-8601=seconds)" "$collect_status" "$listing_status" "$listing_report_status" >> data/logs/daily.log
if [ "$collect_status" -ne 0 ] || [ "$listing_status" -ne 0 ] || [ "$listing_report_status" -ne 0 ]; then
    exit 1
fi
exit 0
