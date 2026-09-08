import hashlib
import gzip
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from apartment_monitor.adapters import parse_avalon, parse_g5, parse_jonah, parse_martin, parse_sevens, parse_sightmap
from apartment_monitor.db import derive_events, save_observations, upsert_property


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def run_lock(path: Path):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"collection lock exists: {path}") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def fetch(url: str, *, timeout: int = 30, retries: int = 2) -> tuple[bytes, int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "ApartmentWatch/0.1 (+local personal monitor)", "Accept": "text/html, application/json", "Accept-Encoding": "identity"})
    # Some locally installed Python builds do not discover the OS CA bundle.
    ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    tls_context = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle.exists() else None)
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=tls_context) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return raw, response.status, response.headers.get_content_type()
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
    raise last


def fetch_martin(url: str) -> tuple[bytes, int, str]:
    page, status, _ = fetch(url)
    text = page.decode("utf-8", errors="replace")
    import re
    candidates = re.findall(r"var ajaxData = (\{.*?\});", text)
    ajax = next((json.loads(value) for value in candidates if "nonce_floorplans" in value), None)
    if not ajax:
        raise ValueError("Martin page is missing public inventory nonces")
    endpoint = ajax["url"]
    results = {}
    actions = (("floorplans", "get_api_floorplans", ajax["nonce_floorplans"]),
               ("units", "get_api_apartments_availability", ajax["nonce_apartments"]))
    for key, action, nonce in actions:
        body = urllib.parse.urlencode({"action": action, "nonce": nonce}).encode()
        request = urllib.request.Request(endpoint, data=body,
            headers={"User-Agent":"ApartmentWatch/0.1 (+local personal monitor)",
                     "Content-Type":"application/x-www-form-urlencoded"})
        ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
        context = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle.exists() else None)
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            results[key] = json.loads(response.read())
    return json.dumps(results, sort_keys=True).encode(), status, "application/json"


def fetch_yardi_wordpress(url: str) -> tuple[bytes, int, str]:
    """Fetch exact units exposed by the public Yardi WordPress component."""
    import re
    page, status, _ = fetch(url)
    text = page.decode("utf-8", errors="replace")
    endpoint_match = re.search(r'yrd_flrpn_ajax_data\s*=\s*(\{.*?\})', text)
    floorplans_nonce = re.search(r"data-nonce-floorplans=['\"]([^'\"]+)", text)
    apartments_nonce = re.search(r"data-nonce-apartments=['\"]([^'\"]+)", text)
    if not endpoint_match or not floorplans_nonce or not apartments_nonce:
        raise ValueError("Yardi WordPress page is missing public inventory configuration")
    endpoint = json.loads(endpoint_match.group(1))["url"]
    results = {}
    actions = (("floorplans", "yrd_flrpn_get_api_floorplans", floorplans_nonce.group(1)),
               ("units", "yrd_flrpn_get_api_apartments_availability", apartments_nonce.group(1)))
    ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    context = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle.exists() else None)
    for key, action, nonce in actions:
        body = urllib.parse.urlencode({"action": action, "nonce": nonce}).encode()
        request = urllib.request.Request(endpoint, data=body, headers={
            "User-Agent": "ApartmentWatch/0.1 (+local personal monitor)",
            "Content-Type": "application/x-www-form-urlencoded", "Accept-Encoding": "identity"})
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            results[key] = json.loads(response.read())
    return json.dumps(results, sort_keys=True).encode(), status, "application/json"


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, headers={
        "User-Agent": "ApartmentWatch/0.1 (+local personal monitor)",
        "Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity"})
    ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    context = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle.exists() else None)
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return json.loads(response.read())


def fetch_g5(config: dict) -> tuple[bytes, int, str]:
    endpoint, urn = config["availability_url"], config["metadata"]["location_urn"]
    floorplan_query = "query C($u:String!){apartmentComplex(locationUrn:$u){floorplans{id name beds baths sqft totalAvailableUnits}}}"
    response = _post_json(endpoint, {"query": floorplan_query, "variables": {"u": urn}})
    floorplans = ((response.get("data") or {}).get("apartmentComplex") or {}).get("floorplans")
    if not isinstance(floorplans, list):
        raise ValueError("G5 floorplan response is incomplete")
    unit_query = "query U($f:Int!,$u:String){units(floorplanId:$f,locationUrn:$u){id externalId name displayName sqftDisplay availabilityDate specials{id name term amount} prices{id priceType formattedPrice value leaseTermBasisMin}}}"
    units_by_floorplan = {}
    for fp in floorplans:
        if fp.get("beds") is not None and float(fp["beds"]) <= 1:
            result = _post_json(endpoint, {"query": unit_query, "variables": {"f": fp["id"], "u": urn}})
            units = (result.get("data") or {}).get("units")
            if not isinstance(units, list):
                raise ValueError(f"G5 unit response is incomplete for floorplan {fp['id']}")
            units_by_floorplan[str(fp["id"])] = units
    return json.dumps({"floorplans": floorplans, "units_by_floorplan": units_by_floorplan}, sort_keys=True).encode(), 200, "application/json"


def collect(db, property_config: dict, data_dir: Path, *, run_id: str | None = None,
            fetcher=fetch, raw_override: bytes | None = None) -> str:
    run_id = run_id or str(uuid.uuid4())
    started = utc_now()
    property_id = property_config["id"]
    upsert_property(db, property_config)
    db.execute("INSERT OR IGNORE INTO collection_runs(id,property_id,started_at,status) VALUES(?,?,?,'running')",
               (run_id, property_id, started))
    if db.execute("SELECT status FROM collection_runs WHERE id=?", (run_id,)).fetchone()[0] != "running":
        return run_id
    db.commit()
    raw = None
    http_status = None
    content_type = None
    try:
        if raw_override is None:
            if property_config.get("adapter") == "martin" and fetcher is fetch:
                raw, http_status, content_type = fetch_martin(property_config["availability_url"])
            elif property_config.get("adapter") == "yardi_wordpress" and fetcher is fetch:
                raw, http_status, content_type = fetch_yardi_wordpress(property_config["availability_url"])
            elif property_config.get("adapter") == "g5" and fetcher is fetch:
                raw, http_status, content_type = fetch_g5(property_config)
            else:
                raw, http_status, content_type = fetcher(property_config["availability_url"])
        else:
            raw, http_status, content_type = raw_override, 200, "text/html"
        digest = hashlib.sha256(raw).hexdigest()
        artifact_dir = data_dir / "raw" / started[:10]
        artifact_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".json" if content_type == "application/json" else ".html"
        artifact = artifact_dir / f"{property_id}-{run_id}{suffix}"
        artifact.write_bytes(raw)
        db.execute("INSERT OR IGNORE INTO artifacts(run_id,path,sha256,content_type,byte_count) VALUES(?,?,?,?,?)",
                   (run_id, str(artifact), digest, content_type, len(raw)))
        parser = {"sevens": parse_sevens, "jonah": parse_jonah, "avalon": parse_avalon,
                  "martin": parse_martin, "yardi_wordpress": parse_martin,
                  "sightmap": parse_sightmap, "g5": parse_g5}.get(property_config.get("adapter"))
        if parser is None:
            raise ValueError(f"unsupported adapter: {property_config.get('adapter')}")
        result = parser(raw.decode("utf-8", errors="replace"))
        finished = utc_now()
        save_observations(db, run_id, property_id, finished, result.offers)
        db.execute("""UPDATE collection_runs SET finished_at=?,status=?,completeness=?,http_status=?,
          parser_version=?,evidence=?,observed_count=? WHERE id=?""",
          (finished, result.status, result.completeness, http_status, result.parser_version,
           result.evidence, len(result.offers), run_id))
        if result.completeness == "complete":
            derive_events(db, run_id, property_id)
        db.commit()
        return run_id
    except urllib.error.HTTPError as exc:
        status = "blocked" if exc.code in (401, 403, 429) else "network_error"
        _fail(db, run_id, status, exc.code, str(exc))
        exc.close()
    except (urllib.error.URLError, TimeoutError) as exc:
        _fail(db, run_id, "network_error", http_status, str(exc))
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        _fail(db, run_id, "parse_error", http_status, str(exc))
    return run_id


def _fail(db, run_id, status, http_status, error):
    db.execute("UPDATE collection_runs SET finished_at=?,status=?,http_status=?,error=? WHERE id=?",
               (utc_now(), status, http_status, error, run_id))
    db.commit()
