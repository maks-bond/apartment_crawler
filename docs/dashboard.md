# Rent Observatory: local dashboard

Updated 2026-10-11. The dashboard is an on-demand website in this repository.
It reads both SQLite databases in read-only mode. It does not collect new data,
change observations, contact listing websites, or run as a background service.
Daily crawlers continue through the existing cron regardless of dashboard use.

## What to look at

**Current view**: observed inventory, median asking rent, median rent per square
foot and source coverage; geographic cells colored by count, rent or rent per
square foot; city comparison; searchable/sortable listings with price histories.

**Trends**: daily median asking rent, daily median rent per square foot, observed
inventory, and median same-listing price change against the previous calendar
day. Sample medians reflect both price changes and changing inventory mix.
The matched chart requires the same usable source set on adjacent days, matching
listing identities, and the same rent period/category or community lease basis.
Unchanged listings are included in that median. It does not represent all homes.

**Collection health**: coverage calendar, latest attempt per source, last usable
snapshot, HTTP codes and error text, plus recent detail failures. Missing or failed
days remain blank in trend charts. Failures are never converted to zero inventory.
A complete community response with no matching units can correctly show zero.

Choose Craigslist or communities separately; their inventory and price semantics
are different. Filter by city, bedrooms, category, rent period, square-footage
range, short-term preference, community, and date range. Click a city to filter.
Click a geographic cell or drag a rectangle to apply a geofence to the current
view and every historical day. Clear it through Geofence coordinates. The default
map covers the target Bay Area; the legend counts out-of-viewport ads, and Fit all
points includes them. A street background provides context; switch it off to use the coordinate grid offline.
Community coordinates have not been validated, so those use city filters instead.

An individual history popup shows all stored history, independently of the main
chosen date range. Separate lease bases/rent periods get separate price charts.
Original listing links open only when you choose them. Advertised prices have not
been screened for scams or commercial teaser pricing.

## Start directly on the collector machine

No installation or frontend build is required. Python 3.11+ is sufficient.

```bash
cd /home/maksym/dev/apartment_crawler
./scripts/dashboard.sh
```

Open http://127.0.0.1:8765 in a browser on that machine. Keep the terminal open;
Ctrl+C stops the server. It binds only to IPv4 loopback and serves only its own
HTML/CSS/JavaScript and read-only JSON API. It does not expose raw databases,
repository files or collector controls. Application logs go to
`data/logs/dashboard.log`. The dashboard is not added to cron or systemd.

## Access from your laptop using your existing SSH connection

Run the following **on the computer with your browser**, replacing
`YOUR_EXISTING_SSH_ALIAS` with the host/alias you already use to connect to this
machine. You can also supply `maksym@your-server-hostname`.

```bash
scp YOUR_EXISTING_SSH_ALIAS:/home/maksym/dev/apartment_crawler/scripts/configure-dashboard-ssh.py /tmp/configure-dashboard-ssh.py
python3 /tmp/configure-dashboard-ssh.py YOUR_EXISTING_SSH_ALIAS
ssh apartment-dashboard
```

Then open **http://127.0.0.1:8765** in your local browser. The final command opens
an SSH tunnel and starts the remote dashboard in the foreground. Ctrl+C stops
both. Your original SSH alias continues to work normally.

The helper reads the resolved connection using `ssh -G`, copies common host,
user, port, identity and proxy settings, and adds a separate `apartment-dashboard`
entry to your local `~/.ssh/config`. It backs up existing contents with a timestamp,
uses file mode 0600, preserves existing text and makes repeated runs idempotent.
It does not copy private keys or disable host-key verification. To review first:

```bash
python3 /tmp/configure-dashboard-ssh.py YOUR_EXISTING_SSH_ALIAS --dry-run
```

The generated block includes these dashboard-specific settings:

```sshconfig
Host apartment-dashboard
    # HostName, User, Port, IdentityFile and proxy settings are resolved by the helper.
    ExitOnForwardFailure yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
    RequestTTY force
    LocalForward 127.0.0.1:8765 127.0.0.1:8765
    RemoteCommand cd /home/maksym/dev/apartment_crawler && exec sh scripts/dashboard.sh --port 8765
```

The helper is optional. For complex SSH Match rules or unusual authentication,
reuse the original SSH alias with this single command and no config changes:

```bash
ssh -tt -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:8765:127.0.0.1:8765 YOUR_EXISTING_SSH_ALIAS 'cd /home/maksym/dev/apartment_crawler && exec sh scripts/dashboard.sh'
```

Or copy `scripts/connect-dashboard.sh` to your browser computer and run
`sh connect-dashboard.sh YOUR_EXISTING_SSH_ALIAS`; it performs the same launch
using the existing SSH profile. It also accepts optional local and remote ports.
If local port 8765 is busy, configure another one:

```bash
python3 /tmp/configure-dashboard-ssh.py YOUR_EXISTING_SSH_ALIAS --local-port 8766
ssh apartment-dashboard
# Browser: http://127.0.0.1:8766
```

If the remote port is busy, add `--remote-port 8766` as well. The tunnel settings
must match the server port. A stopped server/tunnel makes the browser inaccessible;
run `ssh apartment-dashboard` again when you want to view it. Merely closing a
browser tab does not stop the foreground SSH command; use Ctrl+C in its terminal.

OpenSSH references: [LocalForward](https://man.openbsd.org/ssh_config#LocalForward),
[RemoteCommand](https://man.openbsd.org/ssh_config#RemoteCommand), and
[RequestTTY](https://man.openbsd.org/ssh_config#RequestTTY).

## Data interpretation

- Dates and daily snapshots use UTC; displayed attempt timestamps use your browser's
  timezone. The dashboard defaults to the available last 30 days.
- Current numbers come from the most recent usable calendar date in the selected
  range, without carrying older failed-source inventory into the count. Snapshot
  date and usable-source coverage are explicit. If that date predates View through,
  the page marks it as old. The health tab retains last successful source dates.
- Missing collection days create chart gaps, not connecting lines or zero inventory.
  Lines also break when the set of usable sources changes, so a coverage loss is
  not drawn as a continuous inventory/price trend.
  A filtered successful sample with no matching observations can show zero observed
  matches without implying complete market availability.
- Rent periods stay separate. Craigslist monthly prices may be inferred from the
  housing category; the page counts those assumptions. Community prices are base
  rent, not the full fee-inclusive cost. Nonpositive amounts are retained as ads but
  excluded from price metrics and price-change analysis.
- Rent per square foot requires positive rent, positive known dwelling area and
  eligible area scope. Rooms with uncertain room/dwelling area and community area
  ranges are excluded. Every chart/table includes the usable sample count.
- Craigslist coverage is partial. Count changes can reflect sampling, reposts,
  advertising or source coverage. They do not establish total city availability.
- Numeric post IDs and known opaque aliases are deduplicated per day. Separate post
  IDs can still advertise the same home. Community IDs are namespaced by property.
- Map points are approximate advertised coordinates. Boundary membership is not a
  verified address or a county-polygon result. A geographic cell can change if an
  advertiser changes the map location. City normalization has its own uncertainty.
- Observed span uses first sighting through the selected snapshot, not verified
  continuous time on market. Different community lease terms/move-in bases are not
  compared as the same quote. Multiple quotes for one unit/day are counted as one
  unit, selecting the final stored observation for the current view.
- There is currently only a first Craigslist baseline. The UI says another daily
  observation is needed for a trend. Community data already spans multiple weeks.

## Implementation and checks

`src/rent_dashboard/data.py` computes medians directly from deduplicated individual
observations, avoiding averages of bucket averages. `server.py` serves the local
JSON API and the buildless HTML/CSS/JS in `static/`. SQLite connections use `mode=ro`
and query-only transactions; the dashboard does not run migrations. Missing DBs
are shown as unavailable, not silently created. SQL filters use parameters.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
node --check src/rent_dashboard/static/app.js
sh -n scripts/dashboard.sh scripts/connect-dashboard.sh
```

Dashboard regression tests cover filtered/geofenced statistics, daily gaps,
matching IDs after promotion, comparable price changes, room/zero-price exclusions,
explicit empty community inventory versus failure, read-only DB behavior, HTTP
routing/host checks and idempotent SSH config updates preserving the original alias.

All 34 Python tests passed (26 collector tests plus 8 dashboard/SSH tests).
Chromium browser QA also passed on the real databases: filters, geographic cell
selection, dialogs, both datasets, charts, health and mobile layout, with no
JavaScript errors or external network requests. The actual laptop-to-server SSH
connection remains for you to launch using your existing host alias; no laptop
configuration was edited from this machine. The helper was verified with a
temporary SSH configuration using OpenSSH's effective-option output.

Optional real-data browser QA uses Playwright, installed separately from the app:
start the dashboard, then run `node tests/dashboard.browser.cjs` with Playwright on
Node's module path. This checks filters, map selection, dialogs, trends, health,
mobile layout and absence of unexpected external web requests (street tiles are mocked). Screenshots go under ignored
`reports/dashboard-preview/`. Browser tooling is not a dashboard runtime dependency.

The client refreshes when opened or when Refresh data is pressed; no polling or
background service is required. The server reads fresh snapshots for each API
request, so concurrent daily collection can continue independently.

## October 29: interactive plots and street context

Hover anywhere in a plot to see its nearest date and value, with sample size and
source coverage where available. Individual listing charts support the same cards.
Keyboard focus and touch are supported; Escape dismisses the card.

The inventory map now includes a muted OpenStreetMap background. Choose a city
for a closer street view, then click a cell or drag a geofence. The Street map
checkbox disables the background. Inventory rectangles still represent approximate
advertised coordinates, not verified property addresses. Tiles load directly from
`tile.openstreetmap.org` with browser caching; no keys or added runtime packages are
needed. Internet access is needed for tiles only. On failure the cells remain usable.
Attribution and [tile usage policy](https://operations.osmfoundation.org/policies/tiles/)
apply. Browser QA mocks tiles to avoid automated map downloads.

Restart the SSH dashboard session after updating, then refresh your browser. The
server now permits images from the tile host in its Content Security Policy.
