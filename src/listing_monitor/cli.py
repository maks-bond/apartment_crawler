import argparse
import json
import logging
from pathlib import Path

from listing_monitor.collector import collect
from listing_monitor.db import connect
from listing_monitor.reporting import write_report


def main():
    parser = argparse.ArgumentParser(description='Craigslist daily housing samples and listing history')
    parser.add_argument('command',choices=['collect','report'])
    parser.add_argument('--config',type=Path,default=Path('config/craigslist.json'))
    parser.add_argument('--db',type=Path,default=Path('data/craigslist.sqlite3'))
    parser.add_argument('--data-dir',type=Path,default=Path('data'))
    parser.add_argument('--reports',type=Path,default=Path('reports'))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    logdir = args.data_dir/'logs'
    logdir.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(logdir/'craigslist.log'),logging.StreamHandler()])
    db = connect(args.db)
    try:
        if args.command == 'collect':
            result = collect(db,config,args.data_dir)
            print(json.dumps(result))
            if result['searches_failed'] or result['details_failed'] or result['searches_skipped'] or result['paused_until']:
                raise SystemExit(1)
        else:
            print(json.dumps(write_report(db,config,args.reports)))
    finally:
        db.close()
