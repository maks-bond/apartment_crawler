import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from rent_dashboard.data import Store


STATIC = Path(__file__).parent/'static'


def handler(store):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host = self.headers.get('Host','').split(':')[0].lower()
            if host not in ('127.0.0.1','localhost'):
                self.respond(b'Use the loopback address for this dashboard','text/plain',403)
                return
            parsed = urlparse(self.path)
            query = {k:v[-1] for k,v in parse_qs(parsed.query).items()}
            try:
                if parsed.path=='/api/meta':
                    self.respond(json.dumps(store.meta()).encode(),'application/json')
                elif parsed.path=='/api/dashboard':
                    self.respond(json.dumps(store.dashboard(query),allow_nan=False).encode(),'application/json')
                elif parsed.path=='/api/history':
                    self.respond(json.dumps(store.history(query.get('source','craigslist'),query.get('id'),query.get('property')),
                        allow_nan=False).encode(),'application/json')
                elif parsed.path in ('/','/app.js','/style.css'):
                    name = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[parsed.path]
                    mime = {'/':'text/html','/app.js':'text/javascript','/style.css':'text/css'}[parsed.path]
                    self.respond((STATIC/name).read_bytes(),mime)
                else:
                    self.respond(b'Not found','text/plain',404)
            except (ValueError,KeyError) as exc:
                self.respond(json.dumps({'error':str(exc)}).encode(),'application/json',400)
            except Exception:
                logging.exception('Dashboard request failed: %s',parsed.path)
                self.respond(b'{"error":"Could not read the local database. See dashboard.log."}','application/json',500)

        def respond(self, body, mime, status=200):
            self.send_response(status)
            self.send_header('Content-Type',mime+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            logging.info(format,*args)
    return Handler


def main():
    parser = argparse.ArgumentParser(description='On-demand housing dashboard, listening on loopback only')
    parser.add_argument('--project-dir',type=Path,default=Path.cwd())
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    logs = args.project_dir/'data/logs'
    logs.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.FileHandler(logs/'dashboard.log'),logging.StreamHandler()])
    with ThreadingHTTPServer(('127.0.0.1',args.port),handler(Store(args.project_dir))) as server:
        print(f'Dashboard: http://127.0.0.1:{args.port} — Ctrl+C to stop',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\nDashboard stopped.',flush=True)
