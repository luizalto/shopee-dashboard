import hashlib
import json
import os
import time
import re
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

SHOPEE_APP_ID   = os.environ.get("SHOPEE_APP_ID", "")
SHOPEE_SECRET   = os.environ.get("SHOPEE_SECRET", "")
SHOPEE_ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
BRT             = timezone(timedelta(hours=-3))

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

def shopee_auth_header(payload):
    timestamp = str(int(time.time()))
    factor    = SHOPEE_APP_ID + timestamp + payload + SHOPEE_SECRET
    signature = hashlib.sha256(factor.encode()).hexdigest()
    return {
        "Content-Type":  "application/json",
        "Authorization": f"SHA256 Credential={SHOPEE_APP_ID}, Timestamp={timestamp}, Signature={signature}"
    }

GQL_QUERY = """{{
  conversionReport(
    purchaseTimeStart: {start},
    purchaseTimeEnd: {end},
    limit: 500
    {scroll}
  ) {{
    nodes {{
      conversionId
      purchaseTime
      utmContent
      totalCommission
      orders {{
        orderId
        orderStatus
      }}
    }}
    pageInfo {{
      hasNextPage
      scrollId
    }}
  }}
}}"""

def extract_external_id(utm):
    if not utm:
        return ""
    s = str(utm).strip()
    idx = s.rfind("ID")
    if idx == -1:
        return s
    after = s[idx + 2:]
    return after if after else s

def fetch_data(date_str, search=""):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        d = (datetime.now(BRT) - timedelta(days=1)).date()

    start = int(datetime(d.year, d.month, d.day,  0,  0,  0, tzinfo=BRT).timestamp())
    end   = int(datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=BRT).timestamp())

    all_nodes = []
    scroll_id = ""
    valid     = {"PENDING", "COMPLETED"}

    while True:
        scroll_part = f', scrollId: "{scroll_id}"' if scroll_id else ""
        query       = GQL_QUERY.format(start=start, end=end, scroll=scroll_part)
        payload_str = json.dumps({"query": query})
        headers     = shopee_auth_header(payload_str)

        resp = requests.post(SHOPEE_ENDPOINT, headers=headers, data=payload_str, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        if "errors" in body:
            return {"error": str(body["errors"])}

        report    = body.get("data", {}).get("conversionReport", {})
        nodes     = report.get("nodes", [])
        page_info = report.get("pageInfo", {})

        for node in nodes:
            orders    = node.get("orders", [])
            has_valid = any(o.get("orderStatus", "").upper() in valid for o in orders)
            if has_valid:
                all_nodes.append(node)

        if not page_info.get("hasNextPage"):
            break
        scroll_id = page_info.get("scrollId", "")
        if not scroll_id:
            break
        time.sleep(2)

    groups = {}
    for node in all_nodes:
        utm    = node.get("utmContent", "") or ""
        sub_id = extract_external_id(utm)

        if search and search.lower() not in sub_id.lower() and search.lower() not in utm.lower():
            continue

        try:
            commission = float(node.get("totalCommission") or 0)
        except (ValueError, TypeError):
            commission = 0.0

        orders       = node.get("orders", [])
        valid_orders = [o for o in orders if o.get("orderStatus", "").upper() in {"PENDING", "COMPLETED"}]

        if sub_id not in groups:
            groups[sub_id] = {"sub_id": sub_id, "commission": 0.0, "orders": 0}
        groups[sub_id]["commission"] += commission
        groups[sub_id]["orders"]     += len(valid_orders)

    items = sorted(groups.values(), key=lambda x: x["commission"], reverse=True)
    for item in items:
        item["commission"] = round(item["commission"], 2)

    return {
        "date":             date_str,
        "total_commission": round(sum(i["commission"] for i in items), 2),
        "total_orders":     sum(i["orders"] for i in items),
        "items":            items
    }


def app(environ, start_response):
    path   = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")

    cors = [
        ("Access-Control-Allow-Origin",  "*"),
        ("Access-Control-Allow-Methods", "GET, OPTIONS"),
    ]

    if method == "OPTIONS":
        start_response("200 OK", cors)
        return [b""]

    # HTML
    if path in ("/", "/index.html"):
        body = open(os.path.join(STATIC_DIR, "index.html"), "rb").read()
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [body]

    # manifest
    if path == "/manifest.json":
        body = open(os.path.join(STATIC_DIR, "manifest.json"), "rb").read()
        start_response("200 OK", [("Content-Type", "application/json")])
        return [body]

    # sw.js
    if path == "/sw.js":
        body = open(os.path.join(STATIC_DIR, "sw.js"), "rb").read()
        start_response("200 OK", [
            ("Content-Type", "application/javascript"),
            ("Service-Worker-Allowed", "/")
        ])
        return [body]

    # API
    if path.startswith("/api"):
        qs       = environ.get("QUERY_STRING", "")
        params   = parse_qs(qs)
        date_str = params.get("date",   [""])[0]
        search   = params.get("search", [""])[0]

        if not date_str:
            date_str = (datetime.now(BRT) - timedelta(days=1)).date().strftime("%Y-%m-%d")

        try:
            result = fetch_data(date_str, search)
            body   = json.dumps(result).encode()
            status = "200 OK"
        except Exception as e:
            body   = json.dumps({"error": str(e)}).encode()
            status = "500 Internal Server Error"

        start_response(status, [("Content-Type", "application/json")] + cors)
        return [body]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"Not found"]
