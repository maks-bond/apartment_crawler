// Optional browser QA against a running dashboard and its real local databases.
// NODE_PATH=/path/to/node_modules node tests/dashboard.browser.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require("playwright");

(async () => {
  const url = process.env.DASHBOARD_URL || "http://127.0.0.1:8765";
  const artifacts =
    process.env.DASHBOARD_ARTIFACTS || "reports/dashboard-preview";
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [],
      external = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (new URL(r.url()).origin !== new URL(url).origin && !["tile.openstreetmap.org", "basemaps.cartocdn.com"].includes(new URL(r.url()).hostname))
        external.push(r.url());
    });
    await page.route(/https:\/\/(tile.openstreetmap.org|basemaps.cartocdn.com)\//, route => route.fulfill({
      contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=", "base64")
    }));
    await page.goto(url);
    await page.waitForFunction(
      () => document.querySelectorAll("#kpis .kpi").length === 4,
    );
    assert.ok(await page.locator(".map-tile").count() > 0);
    assert.equal(await page.locator("#map-background").count(), 0);
    await page.locator(".map-settings summary").click();
    await page.locator("#map-opacity").fill("50");
    assert.equal(await page.locator(".map-cell").first().getAttribute("fill-opacity"), "0.5");
    async function update(action) {
      const response = page.waitForResponse(
        (r) => new URL(r.url()).pathname === "/api/dashboard",
      );
      await action();
      const result = await (await response).json();
      await page.waitForFunction(
        () => !document.getElementById("filters").classList.contains("busy"),
      );
      assert.equal(await page.locator("#error").isVisible(), false);
      return result;
    }
    await page.screenshot({
      path: artifacts + "/current.png",
      fullPage: false,
    });
    let baseline = await page.request.get(
      url + "/api/dashboard?source=craigslist",
    );
    assert.equal(baseline.status(), 200);
    if (await page.locator(".map-cell").count()) {
      const narrowed = await update(() =>
        page.locator(".map-cell").first().click(),
      );
      assert.ok(narrowed.bbox);
      assert.ok(narrowed.stats.inventory > 0);
      assert.equal(narrowed.cells.length, 1);
      await update(() => page.locator("#clear-geo").click());
      await page.locator("#map-metric").selectOption("median_psf");
      assert.ok(await page.locator(".map-cell").count());
    }
    const cities = await page
      .locator("#city-options option")
      .evaluateAll((options) => options.map((o) => o.value).filter(Boolean));
    if (cities.length) {
      const before = Number(await page.locator("#geo-svg").getAttribute("data-scale"));
      const selectedCity = cities.includes("Mountain View") ? "Mountain View" : cities[0];
      const city = await update(async () => { await page.locator("#city").fill(selectedCity); await page.locator("#city").press("Tab"); });
      assert.ok(city.listings.every((r) => r.city === selectedCity));
      const focused = Number(await page.locator("#geo-svg").getAttribute("data-scale"));
      assert.ok(focused > before, "Selecting a city must zoom immediately");
      await page.locator("#zoom-in").click();
      assert.equal(Number(await page.locator("#geo-svg").getAttribute("data-scale")), focused * 2);
      await page.locator("#zoom-out").click();
      assert.equal(Number(await page.locator("#geo-svg").getAttribute("data-scale")), focused);
      await update(async () => { await page.locator("#city").fill(""); await page.locator("#city").press("Tab"); });
    }
    if (await page.locator(".listing-name").count()) {
      await page.locator(".listing-name").first().click();
      await page.waitForSelector("#history-content table");
      assert.ok(await page.locator("#history-content tbody tr").count());
      await page.keyboard.press("Escape");
      assert.equal(await page.locator("#history-dialog").isVisible(), false);
    }
    await page.locator('[data-view="trends"]').click();
    const plot = page.locator("#chart-price svg");
    await plot.hover();
    await page.locator("#chart-price .chart-tooltip:not([hidden])").waitFor();
    assert.match(await page.locator("#chart-price .chart-tooltip").innerText(), /Sources:/);
    await page.locator("#chart-price [data-point]").first().focus();
    assert.match(await page.locator("#chart-price .chart-tooltip").innerText(), /20\d\d-/);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#chart-price .chart-tooltip").isVisible(), false);
    await page.screenshot({
      path: artifacts + "/craigslist-trends.png",
      fullPage: true,
    });
    const communityOption = await page
      .locator('#source option[value="communities"]')
      .isEnabled();
    if (communityOption) {
      const community = await update(() =>
        page.locator("#source").selectOption("communities"),
      );
      assert.equal(community.source, "communities");
      assert.ok(community.series.length > 1);
      await page.screenshot({
        path: artifacts + "/community-trends.png",
        fullPage: true,
      });
      await page.locator('[data-view="health"]').click();
      assert.equal(
        await page.locator("#health tr").count(),
        community.expected_sources,
      );
      await page.screenshot({
        path: artifacts + "/health.png",
        fullPage: true,
      });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('[data-view="current"]').click();
    await page.screenshot({ path: artifacts + "/mobile.png", fullPage: true });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    console.log(
      "Browser checks passed: filters, geographic cells, listing history, trends, health, mobile layout; mocked street tiles; no unexpected external requests or browser errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
