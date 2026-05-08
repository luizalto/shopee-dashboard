import hashlib
import json
import os
import time
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

SHOPEE_APP_ID   = "18314810331"
SHOPEE_SECRET   = "LO3QSEG45TYP4NYQBRXLA2YYUL3ZCUPN"
SHOPEE_ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
BRT             = timezone(timedelta(hours=-3))

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
      utmContent
      totalCommission
      orders {{
        orderStatus
      }}
    }}
    pageInfo {{ hasNextPage scrollId }}
  }}
}}"""

def extract_sub_id(utm):
    if not utm:
        return ""
    s = str(utm).strip()
    idx = s.rfind("ID")
    if idx == -1:
        return s
    after = s[idx + 2:]
    return after if after else s

def fetch_data(date_start, date_end, search=""):
    try:
        d_start = datetime.strptime(date_start, "%Y-%m-%d").date()
        d_end   = datetime.strptime(date_end,   "%Y-%m-%d").date()
    except Exception:
        d_start = (datetime.now(BRT) - timedelta(days=1)).date()
        d_end   = d_start

    start = int(datetime(d_start.year, d_start.month, d_start.day,  0,  0,  0, tzinfo=BRT).timestamp())
    end   = int(datetime(d_end.year,   d_end.month,   d_end.day,   23, 59, 59, tzinfo=BRT).timestamp())

    VALID   = {"PENDING", "COMPLETED"}
    INVALID = {"CANCELLED", "UNPAID"}

    all_nodes = []
    scroll_id = ""

    while True:
        scroll_part = f', scrollId: "{scroll_id}"' if scroll_id else ""
        query       = GQL_QUERY.format(start=start, end=end, scroll=scroll_part)
        payload_str = json.dumps({"query": query})
        resp        = requests.post(SHOPEE_ENDPOINT, headers=shopee_auth_header(payload_str), data=payload_str, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        if "errors" in body:
            return {"error": str(body["errors"])}

        report    = body.get("data", {}).get("conversionReport", {})
        nodes     = report.get("nodes", [])
        page_info = report.get("pageInfo", {})
        all_nodes.extend(nodes)

        if not page_info.get("hasNextPage"):
            break
        scroll_id = page_info.get("scrollId", "")
        if not scroll_id:
            break
        time.sleep(2)

    groups = {}
    for node in all_nodes:
        utm    = node.get("utmContent", "") or ""
        sub_id = extract_sub_id(utm)

        if search and search.lower() not in sub_id.lower() and search.lower() not in utm.lower():
            continue

        try:
            commission = float(node.get("totalCommission") or 0)
        except Exception:
            commission = 0.0

        orders = node.get("orders", [])
        valid_count   = sum(1 for o in orders if o.get("orderStatus","").upper() in VALID)
        invalid_count = sum(1 for o in orders if o.get("orderStatus","").upper() in INVALID)
        other_count   = sum(1 for o in orders if o.get("orderStatus","").upper() not in VALID and o.get("orderStatus","").upper() not in INVALID)
        all_other     = invalid_count + other_count

        has_valid   = valid_count > 0
        has_invalid = all_other > 0

        if not has_valid and not has_invalid:
            continue

        if sub_id not in groups:
            groups[sub_id] = {
                "sub_id":             sub_id,
                "commission_valid":   0.0,
                "orders_valid":       0,
                "commission_other":   0.0,
                "orders_other":       0,
            }

        if has_valid:
            groups[sub_id]["commission_valid"] += commission
            groups[sub_id]["orders_valid"]     += valid_count
        if has_invalid:
            groups[sub_id]["commission_other"] += commission
            groups[sub_id]["orders_other"]     += all_other

    items = sorted(groups.values(), key=lambda x: x["commission_valid"], reverse=True)
    for item in items:
        item["commission_valid"] = round(item["commission_valid"], 2)
        item["commission_other"] = round(item["commission_other"], 2)

    total_comm_valid   = round(sum(i["commission_valid"] for i in items), 2)
    total_orders_valid = sum(i["orders_valid"] for i in items)
    total_comm_other   = round(sum(i["commission_other"] for i in items), 2)
    total_orders_other = sum(i["orders_other"] for i in items)

    return {
        "date_start":         date_start,
        "date_end":           date_end,
        "total_comm_valid":   total_comm_valid,
        "total_orders_valid": total_orders_valid,
        "total_comm_other":   total_comm_other,
        "total_orders_other": total_orders_other,
        "items":              items
    }


@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")

@app.route("/sw.js")
def sw():
    resp = send_from_directory("static", "sw.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp

@app.route("/api/shopee")
def api_shopee():
    date_start = request.args.get("date_start", "")
    date_end   = request.args.get("date_end",   "")
    search     = request.args.get("search",     "")

    if not date_start:
        date_start = (datetime.now(BRT) - timedelta(days=1)).date().strftime("%Y-%m-%d")
    if not date_end:
        date_end = date_start

    try:
        result = fetch_data(date_start, date_end, search)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
