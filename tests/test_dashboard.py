import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from listing_monitor.db import connect, save
from rent_dashboard.data import Store, readonly
from rent_dashboard.server import handler


ROOT = Path(__file__).resolve().parent.parent


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'config').mkdir()
        (self.root/'config/craigslist.json').write_text(json.dumps({'regions':{'pen':'Peninsula'},'categories':{'apa':'rentals'}}))
        (self.root/'config/properties.json').write_text('[]')
        self.db = connect(self.root/'data/craigslist.sqlite3')
        self.store = Store(self.root)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def snapshot(self, day, price=2000, status='partial', category='rentals', scope='dwelling', numeric=None):
        stamp=day+'T12:00:00+00:00'
        run = self.db.execute('INSERT INTO runs(started_at,finished_at,search_key,url,status,http_status) VALUES(?,?,?,?,?,?)',
            (stamp,stamp,'pen:apa','https://sfbay.craigslist.org/search/pen/apa',status,403 if status=='failed' else 200)).lastrowid
        if status=='partial':
            row={'source_id':'abc','url':'https://www.craigslist.org/view/d/studio/abc','title':'Studio',
                 'city':'Mountain View','county':'Santa Clara','category':category,'bedrooms':0,
                 'price':price,'price_period':'month','sqft':500,'sqft_scope':scope,
                 'latitude':37.4,'longitude':-122.1,'geo_cell':'0.01:3740:-12210','short_term':False}
            save(self.db,run,row,stamp,{'canonical_post_id':numeric} if numeric else None)
        self.db.commit()

    def test_same_id_changes_missing_day_and_failed_collection(self):
        self.snapshot('2026-10-01',2000)
        self.snapshot('2026-10-02',1800)
        self.snapshot('2026-10-04',1700,status='failed')
        result=self.store.dashboard({'from':'2026-10-01','to':'2026-10-04'})
        self.assertEqual(result['snapshot_day'],'2026-10-02')
        self.assertEqual(result['stats']['inventory'],1)
        self.assertAlmostEqual(result['series'][1]['matched_change_pct'],-10)
        self.assertIsNone(result['series'][2]['inventory'])
        self.assertIsNone(result['series'][3]['inventory'])
        self.assertEqual(result['series'][0]['coverage_key'],result['series'][1]['coverage_key'])
        self.assertNotEqual(result['series'][1]['coverage_key'],result['series'][3]['coverage_key'])
        self.assertEqual(result['latest_health'][0]['http_status'],403)
        self.assertEqual(result['latest_health'][0]['last_success_day'],'2026-10-02')

    def test_location_area_and_period_filters_apply_to_entire_history(self):
        self.snapshot('2026-10-01')
        query={'from':'2026-10-01','to':'2026-10-01','city':'Mountain View','bbox':'-122.2,37.3,-122.0,37.5','sqft_min':'400','sqft_max':'600'}
        result=self.store.dashboard(query)
        self.assertEqual(result['stats']['median_psf'],4)
        self.assertEqual(result['stats']['sqft_priced'],1)
        self.assertEqual(self.store.dashboard(dict(query,bbox='-123,38,-122,39'))['stats']['inventory'],0)
        self.assertEqual(self.store.dashboard(dict(query,period='week'))['stats']['priced'],0)
        self.assertEqual(self.store.dashboard(dict(query,city='San Francisco'))['series'][0]['inventory'],0)
        with self.assertRaises(ValueError):
            self.store.dashboard(dict(query,bbox='nan,0,1,2'))
        with self.assertRaises(ValueError):
            self.store.dashboard(dict(query,sqft_min='nan'))

    def test_room_uncertain_area_and_zero_price_exclusions(self):
        self.snapshot('2026-10-01',category='rooms',scope='unknown')
        self.snapshot('2026-10-02',0,category='rooms',scope='unknown')
        result=self.store.dashboard({'from':'2026-10-01','to':'2026-10-02','category':'rooms'})
        self.assertEqual(result['stats']['inventory'],1)
        self.assertIsNone(result['stats']['median_price'])
        self.assertIsNone(result['series'][0]['median_psf'])
        self.assertEqual(result['series'][0]['sqft_priced'],0)

    def test_promoted_identity_uses_database_id_and_history_spans_days(self):
        self.snapshot('2026-10-01')
        self.snapshot('2026-10-02',numeric='123456')
        result=self.store.dashboard({'from':'2026-10-01','to':'2026-10-02'})
        self.assertEqual(result['listings'][0]['id'],'123456')
        history=self.store.history('craigslist','123456')['observations']
        self.assertEqual(len(history),2)
        self.assertEqual({r['id'] for r in history},{'123456'})

    def test_readonly_missing_database_and_empty_history_are_not_inventory_zero(self):
        db=readonly(self.root/'data/craigslist.sqlite3')
        with self.assertRaises(sqlite3.OperationalError):
            db.execute('DELETE FROM observations')
        db.close()
        absent=self.root/'data/missing.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):
            readonly(absent)
        self.assertFalse(absent.exists())
        result=self.store.dashboard({'from':'2026-10-01','to':'2026-10-02'})
        self.assertIsNone(result['stats']['inventory'])

    def test_http_routes_and_errors_never_serve_database_files(self):
        class Socket:
            def __init__(self,path,host='127.0.0.1:8765'):
                self.request=io.BytesIO(f'GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n'.encode())
                self.output=bytearray()
            def makefile(self,*args,**kwargs):return self.request
            def sendall(self,value):self.output.extend(value)
        for path,host,code in [('/api/meta','localhost:8765',200),
            ('/data/craigslist.sqlite3','localhost',404),('/api/dashboard?source=evil','localhost',400),
            ('/api/meta','untrusted.example',403),('/app.js','127.0.0.1',200)]:
            sock=Socket(path,host)
            handler(self.store)(sock,('127.0.0.1',1234),object())
            self.assertIn(f' {code} '.encode(),sock.output.split(b'\r\n')[0])

    def test_community_zero_success_is_distinct_from_failed_collection(self):
        from apartment_monitor.db import connect as community_connect, upsert_property
        (self.root/'config/properties.json').write_text(json.dumps([{'id':'test','enabled':True}]))
        db=community_connect(self.root/'data/apartment_monitor.sqlite3')
        upsert_property(db,{'id':'test','name':'Test','enabled':True,'metadata':{'city':'Mountain View'}})
        for id,day,status in [('one','2026-10-01','explicit_no_availability'),('two','2026-10-02','blocked')]:
            db.execute('INSERT INTO collection_runs(id,property_id,started_at,finished_at,status,completeness,http_status) VALUES(?,?,?,?,?,?,?)',
                       (id,'test',day+'T12:00:00Z',day+'T12:00:00Z',status,'complete' if id=='one' else 'unknown',200 if id=='one' else 403))
        db.commit();db.close()
        result=self.store.dashboard({'source':'communities','from':'2026-10-01','to':'2026-10-02'})
        self.assertEqual(result['series'][0]['inventory'],0)
        self.assertIsNone(result['series'][1]['inventory'])
        self.assertEqual(result['snapshot_day'],'2026-10-01')


class SshConfigurationTests(unittest.TestCase):
    def test_configure_script_preserves_original_is_idempotent_and_resolves_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config'
            original='Host collector\n  HostName example.org\n  User maksym\n  Port 2222\n  IdentityFile "/tmp/key file"\nHost *\n  ServerAliveInterval 5\n'
            path.write_text(original)
            args=[sys.executable,str(ROOT/'scripts/configure-dashboard-ssh.py'),'collector','--config',str(path)]
            dry=subprocess.run(args+['--dry-run'],capture_output=True,text=True,check=True)
            self.assertIn('LocalForward 127.0.0.1:8765',dry.stdout)
            self.assertEqual(path.read_text(),original)
            subprocess.run(args,capture_output=True,text=True,check=True)
            first=path.read_text()
            subprocess.run(args,capture_output=True,text=True,check=True)
            self.assertEqual(path.read_text(),first)
            self.assertTrue(first.endswith(original))
            self.assertEqual(len(list(Path(temp).glob('config.backup-*'))),2)
            config=subprocess.run(['ssh','-G','-F',str(path),'apartment-dashboard'],capture_output=True,text=True,check=True).stdout
            self.assertIn('hostname example.org',config)
            self.assertIn('port 2222',config)
            self.assertIn('requesttty force',config)
            self.assertIn('remotecommand cd /home/maksym/dev/apartment_crawler && exec sh scripts/dashboard.sh --port 8765',config)
            original_config=subprocess.run(['ssh','-G','-F',str(path),'collector'],capture_output=True,text=True,check=True).stdout
            self.assertIn('serveraliveinterval 5',original_config)
            self.assertNotIn('localforward ',original_config)


if __name__=='__main__':
    unittest.main()
