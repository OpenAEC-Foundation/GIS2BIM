#!/usr/bin/env python3
"""Validate the web service entries in GIS2BIM_Data.json.

For every entry in GIS2BIMserversRequests.webserverRequests this script
  * requests the GetCapabilities URL and checks that a real capabilities
    document (or OGC API / ArcGIS REST JSON) comes back,
  * checks that the layer / feature type used in serverrequestprefix exists,
  * collects the advertised coordinate reference systems,
  * performs a sample request (serverrequestprefix + testbbox) when the
    entry has a "testbbox", the same way GIS2BIM builds its requests,
  * checks whether the server sends CORS headers.

Only the Python standard library is required (Pillow is used, when
installed, to detect empty sample images).

Usage:
    python3 supportfiles/check_servers.py                       # whole list
    python3 supportfiles/check_servers.py --country DE --country AT
    python3 supportfiles/check_servers.py --title BE_GRB_Kaart_31370
    python3 supportfiles/check_servers.py --file my_entries.json --report report.json

The exit code is 1 when at least one entry failed.
"""

import argparse
import concurrent.futures
import io
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "GIS2BIM_Data.json")
USER_AGENT = "GIS2BIM-server-check/1.0 (+https://github.com/DutchSailor/GIS2BIM)"
CORS_ORIGIN = "https://example.org"
PREFERRED_CRS = ["EPSG:4326", "CRS:84", "EPSG:3857", "EPSG:4258", "EPSG:3035"]
MAX_CRS = 15
SKIPPED_SERVICES = {"", "POST", "GET", "xPath", "HTML", "Javascript"}

try:
    from PIL import Image
except ImportError:  # Pillow is optional
    Image = None


def local(tag):
    return tag.rsplit("}", 1)[-1]


def normalise_crs(value):
    value = value.strip()
    m = re.search(r"EPSG(?::[\d.]*)?:+(\d+)$", value, re.I) or re.search(r"/EPSG/[^/]+/(\d+)$", value, re.I)
    if m:
        return "EPSG:" + m.group(1)
    if re.search(r"CRS:?84$", value, re.I) or value.endswith("/OGC/1.3/CRS84"):
        return "CRS:84"
    return value


def query_params(url):
    query = urllib.parse.urlsplit(url).query
    return {k.lower(): v for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True)}


def request_crs(entry):
    p = query_params(entry.get("serverrequestprefix", ""))
    for key in ("crs", "srs", "srsname", "bbox-crs", "bboxsr", "insr"):
        if p.get(key):
            v = p[key]
            return "EPSG:" + v if v.isdigit() else normalise_crs(v)
    if entry.get("service") == "WMTS_TMS":
        return "EPSG:3857"
    return None


def order_crs(codes, first):
    seen, result = set(), []
    for c in ([first] if first else []) + [c for c in PREFERRED_CRS if c in codes] + list(codes):
        if c and c not in seen and (c.startswith("EPSG:") or c == "CRS:84"):
            seen.add(c)
            result.append(c)
    return result[:MAX_CRS]


class Fetcher:
    def __init__(self, timeout, insecure):
        self.timeout = timeout
        self.context = ssl.create_default_context()
        if insecure:
            self.context.check_hostname = False
            self.context.verify_mode = ssl.CERT_NONE

    def get(self, url, origin=False, limit=30_000_000):
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if origin:
            headers["Origin"] = CORS_ORIGIN
        last_error = None
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout, context=self.context) as resp:
                    body = resp.read(limit)
                    return resp.status, resp.headers, body
            except urllib.error.HTTPError as e:
                return e.code, e.headers, e.read(200_000) if e.fp else b""
            except Exception as e:  # network errors, timeouts, TLS problems
                last_error = e
                time.sleep(1 + attempt)
        raise last_error


def parse_xml(body):
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        # Some servers send a BOM or leading whitespace
        return ET.fromstring(body.lstrip(b"\xef\xbb\xbf \r\n\t"))


def check_capabilities(entry, fetcher, result):
    service = entry["service"]
    url = entry["getCapabilities"]
    status, headers, body = fetcher.get(url, origin=True)
    result["cors"] = bool(headers and headers.get("Access-Control-Allow-Origin") in ("*", CORS_ORIGIN))
    if status != 200:
        raise ValueError("GetCapabilities HTTP %s" % status)
    text_start = body.lstrip()[:1]
    names, crs = set(), []
    if text_start in (b"{", b"["):
        data = json.loads(body)
        if isinstance(data, dict) and "error" in data:
            raise ValueError("JSON error: %s" % str(data["error"])[:120])
        if service.startswith("ArcGIS"):
            sr = data.get("spatialReference") or data.get("extent", {}).get("spatialReference") or {}
            wkid = sr.get("latestWkid") or sr.get("wkid")
            if wkid:
                crs.append("EPSG:%s" % (3857 if wkid == 102100 else wkid))
            for lyr in data.get("layers", []):
                names.add(str(lyr.get("id")))
                names.add(lyr.get("name", ""))
        else:
            for c in data.get("crs", []) if isinstance(data, dict) else []:
                crs.append(normalise_crs(c))
            for col in data.get("collections", []) if isinstance(data, dict) else []:
                names.add(col.get("id", ""))
                for c in col.get("crs", []):
                    crs.append(normalise_crs(c))
            if isinstance(data, dict) and data.get("id"):
                names.add(data["id"])
        result["capabilities"] = "json"
    elif service == "Download":
        result["capabilities"] = "ok"
        return
    else:
        root = parse_xml(body)
        root_name = local(root.tag)
        if root_name in ("ServiceExceptionReport", "ExceptionReport"):
            raise ValueError("GetCapabilities returned %s" % root_name)
        expected = {
            "WMS": ("WMS_Capabilities", "WMT_MS_Capabilities"),
            "WFS": ("WFS_Capabilities",),
            "WMTS": ("Capabilities",),
            "WMTS_TMS": ("Capabilities", "TileMap", "TileMapService"),
            "WCS": ("Capabilities", "WCS_Capabilities"),
        }.get(service.split("_")[0] if service.startswith("WFS") else service)
        if expected and root_name not in expected:
            raise ValueError("unexpected capabilities root <%s>" % root_name)
        result["capabilities"] = root_name
        for el in root.iter():
            tag = local(el.tag)
            if tag in ("CRS", "SRS", "DefaultCRS", "OtherCRS", "DefaultSRS", "OtherSRS", "SupportedCRS",
                       "nativeCRSs", "requestResponseCRSs") and el.text:
                for part in el.text.split():
                    crs.append(normalise_crs(part))
            elif tag in ("Name", "Identifier", "CoverageId") and el.text:
                names.add(el.text.strip())
    result["crs"] = order_crs(list(dict.fromkeys(crs)), request_crs(entry))
    layer = requested_layer(entry)
    if layer and names:
        known = {n.split(":")[-1].lower() for n in names}
        missing = [l for l in layer.split(",") if l and l.split(":")[-1].lower() not in known]
        if missing:
            result["warnings"].append("layer not in capabilities: %s" % ",".join(missing))


def requested_layer(entry):
    p = query_params(entry.get("serverrequestprefix", ""))
    for key in ("layers", "typename", "typenames", "coverage", "coverageid", "layer"):
        if p.get(key):
            return p[key]
    return None


def tile_for(testbbox, zoom):
    minx, miny, maxx, maxy = [float(v) for v in testbbox.split(",")]
    lon, lat = (minx + maxx) / 2, (miny + maxy) / 2
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def sample_url(entry):
    prefix, bbox, service = entry["serverrequestprefix"], entry["testbbox"], entry["service"]
    if service == "WMTS_TMS":
        zoom = min(int(entry.get("maxzoom", 14)), 14)
        x, y = tile_for(bbox, zoom)
        url = prefix.replace("{s}", "a").replace("{z}", str(zoom)).replace("{x}", str(x))
        return url.replace("{-y}", str(2 ** zoom - 1 - y)).replace("{y}", str(y))
    url = prefix + bbox
    if service in ("WMS", "WCS"):
        url = re.sub(r"(?i)\bwidth=\d+", "width=256", url)
        url = re.sub(r"(?i)\bheight=\d+", "height=256", url)
    if service == "ArcGIS_MapServer":
        url = re.sub(r"(?i)\bsize=\d+,\d+", "size=256,256", url)
    return url


def check_sample(entry, fetcher, result):
    url = sample_url(entry)
    status, headers, body = fetcher.get(url, origin=True)
    if not result.get("cors_checked_on_capabilities"):
        result["cors"] = bool(headers and headers.get("Access-Control-Allow-Origin") in ("*", CORS_ORIGIN))
    ctype = (headers.get("Content-Type", "") if headers else "").lower()
    if status != 200:
        raise ValueError("sample request HTTP %s" % status)
    service = entry["service"]
    if service in ("WMS", "WMTS_TMS", "WMTS", "ArcGIS_MapServer"):
        if not ctype.startswith("image/"):
            raise ValueError("sample request returned %s: %s" % (ctype or "?", body[:150]))
        if Image is not None:
            try:
                img = Image.open(io.BytesIO(body)).convert("RGBA")
                if all(lo == hi for lo, hi in img.getextrema()):
                    result["warnings"].append("sample image is empty (single colour)")
            except Exception as e:
                result["warnings"].append("sample image unreadable: %s" % e)
        result["sample"] = "%s, %d bytes" % (ctype, len(body))
    elif service == "WCS":
        if b"ExceptionReport" in body[:2000] or ctype.startswith("text/html"):
            raise ValueError("sample coverage request failed: %s" % body[:150])
        result["sample"] = "%s, %d bytes" % (ctype, len(body))
    elif service == "Download":
        result["sample"] = "%s, %d bytes" % (ctype, len(body))
    else:  # feature services
        if body.lstrip()[:1] in (b"{", b"["):
            data = json.loads(body)
            if isinstance(data, dict) and "error" in data:
                raise ValueError("sample request error: %s" % str(data["error"])[:150])
            count = len(data.get("features", [])) if isinstance(data, dict) else len(data)
        else:
            root = parse_xml(body)
            if local(root.tag) in ("ExceptionReport", "ServiceExceptionReport"):
                raise ValueError("sample request exception: %s" % body[:200])
            count = sum(1 for el in root if local(el.tag) in ("member", "featureMember", "featureMembers"))
            if root.get("numberReturned"):
                count = int(root.get("numberReturned"))
        if count == 0:
            result["warnings"].append("sample request returned no features")
        result["sample"] = "%d features" % count


def check_entry(entry, fetcher):
    result = {"title": entry.get("title"), "service": entry.get("service"), "status": "ok",
              "warnings": [], "country": entry.get("country", "")}
    service = entry.get("service", "")
    if service in SKIPPED_SERVICES or "serverrequestprefix" not in entry:
        result["status"] = "skipped"
        return result
    try:
        if entry.get("getCapabilities"):
            check_capabilities(entry, fetcher, result)
            result["cors_checked_on_capabilities"] = True
        elif not entry.get("testbbox"):
            result["status"] = "skipped"
            return result
        if entry.get("testbbox"):
            check_sample(entry, fetcher, result)
        else:
            result["warnings"].append("no testbbox, sample request not checked")
    except Exception as e:
        result["status"] = "failed"
        result["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    result.pop("cors_checked_on_capabilities", None)
    return result


def load_entries(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    servers = data.get("GIS2BIMserversRequests", data)
    if isinstance(servers.get("webserverRequests"), list):
        return servers["webserverRequests"]
    entries = []

    def walk(node):
        if isinstance(node, dict):
            if "title" in node and "service" in node:
                entries.append(node)
            else:
                for v in node.values():
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(servers)
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=DEFAULT_FILE, help="JSON file to check (default: GIS2BIM_Data.json)")
    parser.add_argument("--country", action="append", help="only check entries with this country code")
    parser.add_argument("--title", action="append", help="only check entries with this title")
    parser.add_argument("--service", action="append", help="only check entries with this service type")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=40)
    parser.add_argument("--insecure", action="store_true", help="do not verify TLS certificates")
    parser.add_argument("--report", help="write the results as JSON to this file")
    parser.add_argument("--quiet", action="store_true", help="only print failures and warnings")
    args = parser.parse_args()

    entries = load_entries(args.file)
    if args.country:
        entries = [e for e in entries if e.get("country") in args.country]
    if args.title:
        entries = [e for e in entries if e.get("title") in args.title]
    if args.service:
        entries = [e for e in entries if e.get("service") in args.service]

    fetcher = Fetcher(args.timeout, args.insecure)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda e: check_entry(e, fetcher), entries))

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if args.quiet and r["status"] != "failed" and not r["warnings"]:
            continue
        line = "%-7s %-10s %s" % (r["status"].upper(), r["service"], r["title"])
        if r.get("sample"):
            line += "  [%s]" % r["sample"]
        if "cors" in r:
            line += "  cors=%s" % ("yes" if r["cors"] else "no")
        print(line)
        if r.get("error"):
            print("        error: " + r["error"])
        for w in r["warnings"]:
            print("        warning: " + w)
    print("\n%d entries: %s" % (len(results), ", ".join("%s %d" % kv for kv in sorted(counts.items()))))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1, ensure_ascii=False)
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
