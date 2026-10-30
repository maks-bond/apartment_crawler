"use strict";
const $ = (id) => document.getElementById(id),
  form = $("filters");
let meta,
  data,
  page = 0,
  visible = [],
  loadingId = 0,
  viewport = null,
  fitAll = false,
  mapZoom = 0;
const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (x) =>
  x == null
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(x);
const money = (x) =>
  x == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(x);
const psf = (x) => (x == null ? "—" : "$" + x.toFixed(2));
const pct = (x) => (x == null ? "—" : (x > 0 ? "+" : "") + x.toFixed(2) + "%");
const period = () =>
  ({
    month: "/ mo",
    week: "/ wk",
    night: "/ night",
    unknown: "(period unclear)",
  })[data?.period] || "";
const rent = (x) => money(x) + (x == null ? "" : " " + period());
const dateOnly = (x) => (x ? x.slice(0, 10) : "—");
const timestamp = (x) => (x ? new Date(x).toLocaleString() : "—");
const span = (r) =>
  Math.max(
    0,
    Math.floor((new Date(r.last_seen) - new Date(r.first_seen)) / 86400000),
  );
const ratio = (r) =>
  r.price > 0 && r.sqft > 0 && r.sqft_eligible ? r.price / r.sqft : null;
const safeUrl = (x) => {
  try {
    const u = new URL(x);
    return u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
};
async function api(path) {
  const response = await fetch(path);
  const value = await response.json();
  if (!response.ok) throw Error(value.error || "Could not load data");
  return value;
}
function fill(select, entries, title) {
  select.replaceChildren(new Option(title, ""));
  for (const [value, label] of entries) select.add(new Option(label, value));
}
function configureSource(resetDates = true) {
  const source = $("source").value,
    cfg = meta.sources[source],
    community = source === "communities";
  $("city").value = "";
  $("city-options").replaceChildren(...cfg.cities.map(city => new Option(city, city)));
  fill(
    $("property"),
    cfg.properties.map((x) => [x.id, x.name]),
    "All communities",
  );
  $("property-label").hidden = !community;
  $("category-label").hidden = community;
  $("short-label").hidden = community;
  form.elements.category.value = "";
  form.elements.short_term.checked = false;
  form.elements.property.value = "";
  $("bbox").value = "";
  $("period").disabled = community;
  $("period").value = "month";
  if (resetDates) {
    const end = meta.today,
      first = cfg.first_day || end;
    let from = new Date(end + "T12:00:00Z");
    from.setUTCDate(from.getUTCDate() - 30);
    $("to").value = end;
    $("from").value = [first, from.toISOString().slice(0, 10)].sort().at(-1);
  }
}
async function load() {
  const id = ++loadingId;
  $("error").hidden = true;
  form.classList.add("busy");
  try {
    const params = new URLSearchParams(new FormData(form));
    if ($("period").disabled) params.set("period", "month");
    const result = await api("/api/dashboard?" + params);
    if (id !== loadingId) return;
    data = result;
    mapZoom = 0;
    page = 0;
    render();
  } catch (error) {
    if (id === loadingId) {
      $("error").textContent = error.message;
      $("error").hidden = false;
    }
  } finally {
    if (id === loadingId) form.classList.remove("busy");
  }
}
function render() {
  if (data.bbox) document.querySelector(".geofence-controls").open = true;
  const s = data.stats,
    healthy = data.latest_health.filter(
      (r) =>
        ["partial", "success_complete", "explicit_no_availability"].includes(
          r.status,
        ) && r.day === data.as_of,
    ).length;
  $("kpis").innerHTML = [
    [
      "Observed inventory",
      num(s.inventory),
      data.partial
        ? "Unique ad IDs in the observed sample"
        : "Units in successful daily community snapshots",
    ],
    [
      "Median asking rent",
      rent(s.median_price),
      num(s.priced) + " positive advertised prices",
    ],
    [
      "Median rent / sq ft",
      psf(s.median_psf),
      num(s.sqft_priced) + " listings with usable dwelling area",
    ],
    [
      "Collection coverage",
      healthy + " / " + data.expected_sources,
      "Sources usable on " +
        data.as_of +
        " · " +
        num(s.coordinates) +
        " map points",
    ],
  ]
    .map(
      ([title, value, note]) =>
        `<article class="kpi"><div class="eyebrow">${esc(title)}</div><div class="value">${esc(value)}</div><p class="caption">${esc(note)}</p></article>`,
    )
    .join("");
  const warnings = [];
  if (data.partial)
    warnings.push(
      "Craigslist counts are partial search samples, not total market inventory.",
    );
  else
    warnings.push(
      "Community prices are advertised base rent; fees and lease terms can differ.",
    );
  if (s.default_period_prices)
    warnings.push(
      `${num(s.default_period_prices)} prices assume a monthly period from the housing category.`,
    );
  if (data.snapshot_day !== data.as_of)
    warnings.push(
      data.snapshot_day
        ? `Latest usable snapshot is ${data.snapshot_day}; this is older than your selected date.`
        : "No usable snapshot in this date range.",
    );
  if (data.snapshot_sources < data.expected_sources)
    warnings.push(
      `Snapshot covers ${data.snapshot_sources}/${data.expected_sources} sources. Failures are excluded, not counted as empty inventory.`,
    );
  warnings.push(
    `Rent / sq ft coverage: ${num(s.sqft_priced)}/${num(s.inventory)} listings. Zero-price ads remain in inventory but not price metrics.`,
  );
  $("notice").textContent = warnings.join(" ");
  $("snapshot-label").textContent =
    "Snapshot · " + (data.snapshot_day || "no data");
  $("cities").innerHTML =
    data.cities
      .map(
        (c) =>
          `<tr><td><button class="link city-button" data-city="${esc(c.city)}">${esc(c.city)}</button></td><td>${num(c.inventory)}</td><td>${money(c.median_price)}</td><td>${psf(c.median_psf)}</td><td>${num(c.sqft_priced)}</td></tr>`,
      )
      .join("") ||
    '<tr><td colspan="5">No matching city observations.</td></tr>';
  document.querySelectorAll(".city-button").forEach(
    (button) =>
      (button.onclick = () => {
        if (button.dataset.city === "Unknown city") return;
        $("city").value = button.dataset.city;
        load();
      }),
  );
  renderMap();
  renderListings();
  renderTrends();
  renderHealth();
}
function chart(
  container,
  points,
  key,
  format,
  color = "#157c74",
  options = {},
) {
  const values = points.filter((p) => p[key] != null);
  if (!values.length) {
    container.innerHTML =
      '<div class="muted-box">No comparable observations for these filters.</div>';
    return;
  }
  const W = 650,
    H = 235,
    left = 60,
    right = 20,
    top = 20,
    bottom = 37;
  let low = Math.min(...values.map((p) => p[key])),
    high = Math.max(...values.map((p) => p[key]));
  if (options.zero) low = Math.min(0, low);
  const pad = (high - low) * 0.12 || Math.abs(high) * 0.06 || 1;
  low = options.zero && low === 0 ? 0 : low - pad;
  high += pad;
  const x = (i) =>
      left + (i / Math.max(1, points.length - 1)) * (W - left - right),
    y = (v) => top + ((high - v) / (high - low)) * (H - top - bottom);
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(options.title || key)}">`;
  for (let i = 0; i < 4; i++) {
    const v = low + ((high - low) * i) / 3,
      yy = y(v);
    svg += `<line x1="${left}" y1="${yy}" x2="${W - right}" y2="${yy}" stroke="#e5eae7"/><text x="${left - 9}" y="${yy + 4}" text-anchor="end">${esc(format(v))}</text>`;
  }
  let path = "",
    open = false,
    previousCoverage = null;
  points.forEach((p, i) => {
    if (p[key] == null) {
      open = false;
      return;
    }
    if (previousCoverage !== null && p.coverage_key !== previousCoverage)
      open = false;
    path += (open ? "L" : "M") + x(i) + "," + y(p[key]);
    previousCoverage = p.coverage_key;
    open = true;
  });
  svg += `<path d="${path}" fill="none" stroke="${color}" stroke-width="2.5"/>`;
  points.forEach((p, i) => {
    if (p[key] != null)
      svg += `<circle cx="${x(i)}" cy="${y(p[key])}" r="${points.length < 15 ? 4 : 2.5}" fill="${color}" data-point="${i}" tabindex="0"><title>${esc(p.day + " · " + format(p[key]) + " · priced n=" + p.priced + " · sq ft n=" + p.sqft_priced + " · coverage " + p.usable_sources + "/" + p.expected_sources + (key === "matched_change_pct" ? " · matched n=" + p.matched_count : ""))}</title></circle>`;
  });
  const ticks = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  for (const i of new Set(ticks)) {
    if (points[i])
      svg += `<text x="${x(i)}" y="${H - 10}" text-anchor="middle">${esc(points[i].day.slice(5))}</text>`;
  }
  svg += "</svg>";
  container.innerHTML =
    svg +
    `<p class="chart-note">${values.length === 1 ? "Baseline only — another daily observation is needed for a trend." : "Hover, tap, or focus a point for values and sample sizes. Lines break when source coverage changes."}</p>`;
  container.classList.add("interactive-chart");
  const plot = container.querySelector("svg");
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  tooltip.setAttribute("role", "status");
  tooltip.hidden = true;
  container.append(tooltip);
  const ns = "http://www.w3.org/2000/svg";
  const guide = document.createElementNS(ns, "line");
  guide.setAttribute("class", "chart-guide");
  guide.setAttribute("y1", top);
  guide.setAttribute("y2", H - bottom);
  guide.style.display = "none";
  plot.append(guide);
  function hide() {
    tooltip.hidden = true;
    guide.style.display = "none";
    plot.querySelectorAll(".active-point").forEach(p => p.classList.remove("active-point"));
  }
  function show(i) {
    const p = points[i];
    if (!p) return;
    const details = [];
    if (p.priced != null) details.push(`Priced listings: ${p.priced}`);
    if (p.sqft_priced != null) details.push(`Usable area: ${p.sqft_priced}`);
    if (p.usable_sources != null) details.push(`Sources: ${p.usable_sources}/${p.expected_sources}`);
    if (key === "matched_change_pct") details.push(`Matched listings: ${p.matched_count ?? 0}`);
    tooltip.innerHTML = `<strong>${esc(p.day)}</strong><b>${esc(options.title || key)}: ${esc(p[key] == null ? "No comparable observation" : format(p[key]))}</b>${details.map(d => `<span>${esc(d)}</span>`).join("")}`;
    tooltip.hidden = false;
    guide.style.display = "";
    guide.setAttribute("x1", x(i));
    guide.setAttribute("x2", x(i));
    plot.querySelectorAll("[data-point]").forEach(dot => dot.classList.toggle("active-point", Number(dot.dataset.point) === i));
    const rect = plot.getBoundingClientRect();
    const position = x(i) / W * rect.width;
    tooltip.style.left = `${Math.max(0, Math.min(position + 12, container.clientWidth - tooltip.offsetWidth))}px`;
    tooltip.style.top = "0px";
  }
  plot.addEventListener("pointermove", e => {
    const rect = plot.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width * W;
    show(Math.max(0, Math.min(points.length - 1, Math.round((px - left) / (W - left - right) * (points.length - 1)))));
  });
  plot.addEventListener("pointerdown", e => {
    const rect = plot.getBoundingClientRect();
    show(Math.max(0, Math.min(points.length - 1, Math.round(((e.clientX - rect.left) / rect.width * W - left) / (W - left - right) * (points.length - 1)))));
  });
  plot.addEventListener("pointerleave", hide);
  plot.addEventListener("focusin", e => {
    if (e.target.dataset.point != null) show(Number(e.target.dataset.point));
  });
  plot.addEventListener("focusout", hide);
  plot.addEventListener("keydown", e => { if (e.key === "Escape") hide(); });
}
function renderTrends() {
  chart($("chart-price"), data.series, "median_price", money, "#157c74", {
    title: "Median asking rent over time",
  });
  chart($("chart-psf"), data.series, "median_psf", psf, "#dd8058", {
    title: "Median asking rent per square foot over time",
  });
  chart($("chart-inventory"), data.series, "inventory", num, "#477ba7", {
    title: "Observed inventory over time",
    zero: true,
  });
  chart($("chart-matched"), data.series, "matched_change_pct", pct, "#157c74", {
    title: "Matched same-listing daily rent change",
  });
  $("daily").innerHTML = [...data.series]
    .reverse()
    .map(
      (p) =>
        `<tr><td>${esc(p.day)}</td><td>${p.usable_sources}/${p.expected_sources}</td><td>${num(p.inventory)}</td><td>${p.inventory == null ? "—" : num(p.priced)}</td><td>${money(p.median_price)}</td><td>${p.inventory == null ? "—" : num(p.sqft_priced)}</td><td>${psf(p.median_psf)}</td><td>${num(p.matched_count)}</td><td>${pct(p.matched_change_pct)}</td></tr>`,
    )
    .join("");
}
function renderListings() {
  const search = $("listing-search").value.trim().toLowerCase(),
    sort = $("sort").value;
  visible = data.listings.filter((r) =>
    [r.label, r.city, r.id].join(" ").toLowerCase().includes(search),
  );
  visible.sort((a, b) =>
    sort === "psf"
      ? (ratio(a) ?? Infinity) - (ratio(b) ?? Infinity)
      : sort === "span"
        ? span(b) - span(a)
        : sort === "recent"
          ? b.observed_at.localeCompare(a.observed_at)
          : (a.price > 0 ? a.price : Infinity) -
            (b.price > 0 ? b.price : Infinity),
  );
  page = Math.min(page, Math.max(0, Math.ceil(visible.length / 50) - 1));
  const rows = visible.slice(page * 50, (page + 1) * 50);
  $("listings").innerHTML =
    rows
      .map(
        (r, i) =>
          `<tr><td><button class="link listing-name" data-row="${page * 50 + i}">${esc(r.label)}</button><small>${esc(r.id)} · ${esc(r.category)}${r.short_term ? " · short-term" : ""}</small></td><td>${esc(r.city || r.location_label || "Unknown")}</td><td>${r.bedrooms === 0 ? "Studio" : num(r.bedrooms)}</td><td>${r.price > 0 ? rent(r.price) : "Unspecified"}</td><td>${num(r.sqft)}${r.sqft && !r.sqft_eligible ? "*" : ""}</td><td>${psf(ratio(r))}</td><td>${span(r)} days<small>First seen ${dateOnly(r.first_seen)}</small></td><td>${dateOnly(r.observed_at)}</td></tr>`,
      )
      .join("") ||
    '<tr><td colspan="8">No matching observations. Try widening your filters.</td></tr>';
  document
    .querySelectorAll(".listing-name")
    .forEach(
      (button) =>
        (button.onclick = () =>
          openHistory(visible[Number(button.dataset.row)])),
    );
  $("page-label").textContent = visible.length
    ? `${page * 50 + 1}–${Math.min((page + 1) * 50, visible.length)} of ${num(visible.length)} · * Area scope uncertain`
    : "No matching listings";
  $("prev").disabled = page === 0;
  $("next").disabled = (page + 1) * 50 >= visible.length;
}
function renderMap() {
  const cells = data.cells,
    metric = $("map-metric").value,
    points = data.listings.filter(
      (r) => r.latitude != null && r.longitude != null,
    );
  if (!points.length) {
    $("map").innerHTML =
      '<div class="muted-box">' +
      (data.source === "communities"
        ? "Community coordinates have not been validated. Use city and community filters."
        : "No mapped observations for these filters.") +
      "</div>";
    $("map-legend").textContent = "";
    return;
  }
  const size = meta.cell_degrees,
    longitudes = points.map((r) => r.longitude),
    latitudes = points.map((r) => r.latitude);
  const extent =
    fitAll || form.elements.city.value || form.elements.bbox.value
      ? [
          Math.min(...longitudes) - size * 2,
          Math.min(...latitudes) - size * 2,
          Math.max(...longitudes) + size * 2,
          Math.max(...latitudes) + size * 2,
        ]
      : [-122.6, 36.95, -121.4, 37.95];
  const W = 850,
    H = 480,
    pad = 40;
  const mercY = lat => (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2;
  const invY = v => Math.atan(Math.sinh(Math.PI * (1 - 2 * v))) * 180 / Math.PI;
  const cx = ((extent[0] + extent[2]) / 2 + 180) / 360;
  const cy = (mercY(extent[1]) + mercY(extent[3])) / 2;
  const scale = 2 ** mapZoom * Math.min((W - pad * 2) / ((extent[2] - extent[0]) / 360), (H - pad * 2) / (mercY(extent[1]) - mercY(extent[3])));
  const x = lon => W / 2 + ((lon + 180) / 360 - cx) * scale;
  const y = lat => H / 2 + (mercY(lat) - cy) * scale;
  viewport = { x, y, lon: px => (cx + (px - W / 2) / scale) * 360 - 180,
    lat: py => invY(cy + (py - H / 2) / scale) };
  const priced = cells.filter((c) => c[metric] != null),
    lo = Math.min(...priced.map((c) => c[metric])),
    hi = Math.max(...priced.map((c) => c[metric]));
  let svg = `<svg id="geo-svg" viewBox="0 0 ${W} ${H}" aria-label="Observed listing geographic cells. Click a cell or drag a rectangle to filter." role="img">`;
  {
    const z = Math.max(0, Math.min(16, Math.ceil(Math.log2(scale / 256))));
    const n = 2 ** z, tileSize = scale / n;
    const west = cx - W / 2 / scale, north = cy - H / 2 / scale;
    for (let tx = Math.floor(west * n); tx <= Math.floor((west + W / scale) * n); tx++) {
      for (let ty = Math.max(0, Math.floor(north * n)); ty <= Math.min(n - 1, Math.floor((north + H / scale) * n)); ty++) {
        svg += `<image class="map-tile" x="${(tx / n - west) * scale}" y="${(ty / n - north) * scale}" width="${tileSize}" height="${tileSize}" href="${esc(meta.carto_key ? `https://basemaps.cartocdn.com/rastertiles/light_all/${z}/${((tx % n) + n) % n}/${ty}.png?key=${encodeURIComponent(meta.carto_key)}` : `https://tile.openstreetmap.org/${z}/${((tx % n) + n) % n}/${ty}.png`)}"/>`;
      }
    }
  }
  let outside = 0;
  cells.forEach((c) => {
    const [step, ilat, ilon] = c.cell.split(":").map(Number),
      west = ilon * step,
      south = ilat * step;
    if (
      x(west + step) < 0 ||
      x(west) > W ||
      y(south) < 0 ||
      y(south + step) > H
    ) {
      outside += c.inventory;
      return;
    }
    const t =
      c[metric] == null
        ? null
        : hi === lo
          ? 0.65
          : (c[metric] - lo) / (hi - lo);
    const color =
      t == null
        ? "#d5dbd5"
        : metric === "inventory"
          ? `rgb(${Math.round(220 - t * 199)},${Math.round(240 - t * 116)},${Math.round(227 - t * 111)})`
          : `rgb(${Math.round(250 - t * 29)},${Math.round(230 - t * 102)},${Math.round(211 - t * 123)})`;
    svg += `<rect class="map-cell" data-cell="${esc(c.cell)}" tabindex="0" x="${x(west)}" y="${y(south + step)}" width="${x(west + step) - x(west)}" height="${y(south) - y(south + step)}" fill="${color}" fill-opacity="${Number($("map-opacity").value) / 100}"><title>${esc(c.cell + " · " + c.inventory + " observed listings · median rent " + money(c.median_price) + " · " + psf(c.median_psf) + "/sq ft · sq ft n=" + c.sqft_priced)}</title></rect>`;
  });
  svg +=
    '<text x="813" y="22" font-size="12" fill="#67767a">N ↑</text><rect id="selection" fill="#157c7420" stroke="#157c74" stroke-dasharray="5 3" hidden="hidden"/></svg>';
  $("map").innerHTML = svg;
  $("carto-credit").hidden = !meta.carto_key;
  $("tile-status").textContent = "Approximate listing locations";
  $("map").querySelectorAll("image").forEach(tile => tile.addEventListener("error", () => {
    const url = new URL(tile.getAttribute("href"));
    if (url.hostname === "basemaps.cartocdn.com") {
      const parts = url.pathname.split("/").slice(-3).join("/");
      tile.setAttribute("href", "https://tile.openstreetmap.org/" + parts);
      $("tile-status").textContent = "Using OpenStreetMap fallback; CARTO could not load.";
    } else {
      $("tile-status").textContent = "Map tiles unavailable; inventory cells remain usable.";
    }
  }));
  const formatter =
    metric === "inventory" ? num : metric === "median_psf" ? psf : money;
  $("map-legend").innerHTML = priced.length
    ? `<span>${formatter(lo)}</span><span class="legend-ramp ${metric === "inventory" ? "" : "rent"}"></span><span>${formatter(hi)}</span><span>· gray = no price data · ${cells.length} cells · ${outside} listings outside viewport</span>`
    : "No usable prices in these cells.";
  const map = $("geo-svg");
  map.dataset.scale = scale;
  $("zoom-in").disabled = mapZoom >= 4;
  $("zoom-out").disabled = mapZoom <= -2;
  let down = null;
  const at = (e) => {
    const p = map.createSVGPoint();
    p.x = e.clientX;
    p.y = e.clientY;
    return p.matrixTransform(map.getScreenCTM().inverse());
  };
  const setCell = (cell) => {
    const [step, ilat, ilon] = cell.split(":").map(Number);
    $("bbox").value = [
      ilon * step,
      ilat * step,
      (ilon + 1) * step,
      (ilat + 1) * step,
    ]
      .map((x) => x.toFixed(6))
      .join(",");
    load();
  };
  map.onpointerdown = (e) => {
    if (e.button !== 0) return;
    down = { p: at(e), cell: e.target.dataset.cell };
    map.setPointerCapture(e.pointerId);
  };
  map.onpointermove = (e) => {
    if (!down) return;
    const p = at(e),
      r = $("selection");
    r.removeAttribute("hidden");
    for (const [k, v] of Object.entries({
      x: Math.min(p.x, down.p.x),
      y: Math.min(p.y, down.p.y),
      width: Math.abs(p.x - down.p.x),
      height: Math.abs(p.y - down.p.y),
    }))
      r.setAttribute(k, v);
  };
  map.onpointerup = (e) => {
    if (!down) return;
    const p = at(e),
      old = down;
    down = null;
    $("selection").setAttribute("hidden", "hidden");
    if (Math.abs(p.x - old.p.x) < 5 || Math.abs(p.y - old.p.y) < 5) {
      if (old.cell) setCell(old.cell);
      return;
    }
    const bounds = [
      viewport.lon(Math.min(p.x, old.p.x)),
      viewport.lat(Math.max(p.y, old.p.y)),
      viewport.lon(Math.max(p.x, old.p.x)),
      viewport.lat(Math.min(p.y, old.p.y)),
    ];
    $("bbox").value = bounds.map((x) => x.toFixed(6)).join(",");
    load();
  };
  map.onpointercancel = () => {
    down = null;
    $("selection").setAttribute("hidden", "hidden");
  };
  map.querySelectorAll(".map-cell").forEach(
    (cell) =>
      (cell.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setCell(cell.dataset.cell);
        }
      }),
  );
}
function renderHealth() {
  $("health-calendar").innerHTML =
    '<div class="health-grid">' +
    data.series
      .map(
        (p) =>
          `<div class="day-tile ${p.usable_sources === p.expected_sources && p.expected_sources ? "good" : p.usable_sources ? "warn" : p.failed_attempts ? "bad" : ""}" title="${esc(p.day + " · usable " + p.usable_sources + "/" + p.expected_sources + " · non-success attempts " + p.failed_attempts)}"><strong>${p.day.slice(8)}</strong>${p.day.slice(5, 7)} · ${p.usable_sources}/${p.expected_sources}</div>`,
      )
      .join("") +
    "</div>";
  $("health").innerHTML = data.latest_health
    .map((r) => {
      const good = [
          "partial",
          "success_complete",
          "explicit_no_availability",
        ].includes(r.status),
        klass =
          good && r.day === data.as_of
            ? "good"
            : good || r.status === "skipped"
              ? "warn"
              : "bad";
      return `<tr><td>${esc(r.search_key)}</td><td><span class="status ${klass}">${esc(r.status)}</span></td><td>${esc(timestamp(r.started_at))}</td><td>${num(r.http_status)}</td><td>${esc(r.last_success_day || "—")}</td><td class="failure-text">${esc(r.error || (good ? "Usable " + (data.partial ? "partial search sample" : "complete inventory") : "No recorded attempt"))}</td></tr>`;
    })
    .join("");
  $("detail-failures").innerHTML = data.detail_failures.length
    ? '<div class="table-scroll"><table><thead><tr><th>Listing</th><th>When</th><th>HTTP</th><th>Error</th></tr></thead><tbody>' +
      data.detail_failures
        .map(
          (r) =>
            `<tr><td>${esc(r.id)}</td><td>${esc(timestamp(r.started_at))}</td><td>${num(r.http_status)}</td><td class="failure-text">${esc(r.error)}</td></tr>`,
        )
        .join("") +
      "</tbody></table></div>"
    : '<p class="caption">No detail failures recorded in this period.</p>';
}
async function openHistory(row) {
  $("history-title").textContent = row.label;
  $("history-content").textContent = "Loading history…";
  $("history-dialog").showModal();
  try {
    const params = new URLSearchParams({ source: data.source, id: row.id });
    if (row.property_id) params.set("property", row.property_id);
    const history = await api("/api/history?" + params);
    const rows = history.observations;
    const full = {
      ...row,
      last_seen: rows.at(-1)?.observed_at || row.last_seen,
    };
    const link = safeUrl(row.url);
    $("history-content").innerHTML =
      `<div class="facts"><div>First observed<br><strong>${dateOnly(row.first_seen)}</strong></div><div>Last observed<br><strong>${dateOnly(full.last_seen)}</strong></div><div>Observed span<br><strong>${span(full)} days</strong></div><div>Days seen<br><strong>${new Set(rows.map((r) => r.day)).size}</strong></div>${link ? `<div><a href="${esc(link)}" target="_blank" rel="noopener noreferrer">Open original listing ↗</a></div>` : ""}</div><p class="caption">Full stored history, independent of the dashboard date range. Observed span is elapsed time between first and last sighting, not verified continuous availability. Each lease basis or rent period remains separate. Detail fields may be cached.</p><div id="history-charts"></div><div class="table-scroll"><table><thead><tr><th>Observed (UTC)</th><th>Rent</th><th>Period</th><th>Sq ft</th><th>$/sq ft</th><th>Lease months</th><th>Available from</th></tr></thead><tbody>${[
        ...rows,
      ]
        .reverse()
        .map(
          (r) =>
            `<tr><td>${esc(r.day)}</td><td>${r.price > 0 ? money(r.price) : "Unspecified"}</td><td>${esc(r.period)}</td><td>${num(r.sqft)}</td><td>${psf(ratio(r))}</td><td>${num(r.lease_months)}</td><td>${esc(r.available_from || "—")}</td></tr>`,
        )
        .join("")}</tbody></table></div>`;
    const groups = new Map();
    for (const r of rows) {
      const key = r.period + " · " + r.basis;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(r);
    }
    for (const [basis, items] of groups) {
      const section = document.createElement("div"),
        heading = document.createElement("h3"),
        plot = document.createElement("div");
      heading.textContent = "Asking rent · " + basis;
      section.append(heading, plot);
      $("history-charts").append(section);
      const points = items.map((r) => ({
        day: r.day,
        price: r.price > 0 ? r.price : null,
        priced: 1,
        sqft_priced: ratio(r) == null ? 0 : 1,
        usable_sources: 1,
        expected_sources: 1,
      }));
      chart(plot, points, "price", money, "#157c74", {
        title: "Individual listing asking rent history",
      });
    }
  } catch (error) {
    $("history-content").textContent = error.message;
  }
}
form.onsubmit = (e) => {
  e.preventDefault();
  load();
};
$("source").onchange = () => {
  configureSource();
  load();
};
$("refresh").onclick = () => load();
$("clear-geo").onclick = () => {
  $("bbox").value = "";
  load();
};
$("city").onchange = () => {
  const cities = meta.sources[$("source").value].cities;
  const match = cities.find(city => city.toLowerCase() === $("city").value.trim().toLowerCase());
  if (match) $("city").value = match;
  $("bbox").value = "";
  fitAll = false;
  $("fit-map").textContent = "Fit all points";
  load();
};
$("zoom-in").onclick = () => { mapZoom = Math.min(4, mapZoom + 1); renderMap(); };
$("zoom-out").onclick = () => { mapZoom = Math.max(-2, mapZoom - 1); renderMap(); };
$("map-opacity").oninput = () => {
  document.querySelectorAll(".map-cell").forEach(cell => cell.setAttribute("fill-opacity", Number($("map-opacity").value) / 100));
};
$("map-metric").onchange = () => renderMap();
$("fit-map").onclick = () => {
  mapZoom = 0;
  fitAll = !fitAll;
  $("fit-map").textContent = fitAll ? "Bay Area extent" : "Fit all points";
  if (data) renderMap();
};
$("listing-search").oninput = () => {
  page = 0;
  if (data) renderListings();
};
$("sort").onchange = () => {
  page = 0;
  if (data) renderListings();
};
$("prev").onclick = () => {
  page--;
  renderListings();
};
$("next").onclick = () => {
  page++;
  renderListings();
};
$("close-dialog").onclick = () => $("history-dialog").close();
document.querySelectorAll("[data-view]").forEach(
  (button) =>
    (button.onclick = () => {
      document.querySelectorAll("[data-view]").forEach((b) => {
        b.classList.toggle("active", b === button);
        b.setAttribute("aria-selected", String(b === button));
      });
      document
        .querySelectorAll(".view")
        .forEach((v) => (v.hidden = v.id !== "view-" + button.dataset.view));
    }),
);
(async () => {
  try {
    meta = await api("/api/meta");
    for (const option of $("source").options)
      option.disabled = !meta.sources[option.value].available;
    if (
      !meta.sources.craigslist.available &&
      meta.sources.communities.available
    )
      $("source").value = "communities";
    configureSource();
    await load();
  } catch (error) {
    $("error").textContent = error.message;
    $("error").hidden = false;
    $("notice").textContent = "Could not load the local data.";
  }
})();
