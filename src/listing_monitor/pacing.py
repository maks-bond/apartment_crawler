import json
import random
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


class CollectionPaused(RuntimeError):
    pass


class RequestPolicy:
    def __init__(self, data_dir, config):
        self.path = data_dir/'craigslist-cooldown.json'
        fallback = config.get('request_delay_seconds', 8)
        self.minimum = config.get('request_delay_min_seconds',fallback)
        self.maximum = config.get('request_delay_max_seconds',self.minimum)
        if not 0 <= self.minimum <= self.maximum:
            raise ValueError('Invalid request delay bounds')
        self.cooldown_hours = config.get('block_cooldown_hours',48)
        self.requested = False

    def paused_until(self):
        if not self.path.exists():
            return None
        state = json.loads(self.path.read_text())
        if datetime.fromisoformat(state['until']) > datetime.now(timezone.utc):
            return state['until']
        self.path.unlink()
        return None

    def before_request(self):
        until = self.paused_until()
        if until:
            raise CollectionPaused(f'Craigslist collection paused until {until}')
        if self.requested:
            time.sleep(random.uniform(self.minimum,self.maximum))
        self.requested = True

    def pause(self, reason, retry_after=None):
        now = datetime.now(timezone.utc)
        until = now+timedelta(hours=self.cooldown_hours)
        if retry_after:
            try:
                retry_time = now+timedelta(seconds=int(retry_after))
            except ValueError:
                try:
                    retry_time = parsedate_to_datetime(retry_after)
                    if retry_time.tzinfo is None:
                        retry_time = retry_time.replace(tzinfo=timezone.utc)
                except (TypeError,ValueError):
                    retry_time = now
            until = max(until,retry_time)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps({'until':until.isoformat(),'reason':reason,'recorded_at':now.isoformat()})+'\n')
        temp.replace(self.path)
