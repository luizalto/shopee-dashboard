import hashlib
import json
import os
import time
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

SHOPEE_ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
BRT             = timezone(timedelta(hours=-3))

def shopee_auth_header(payload):
    SHOPEE_APP_ID = "18314810331"
    SHOPEE_SECRET = "LO3QSEG45TYP4NYQBRXLA2YYUL3ZCUPN"
    timestamp = str(int(time.time()))
    factor    = SHOPEE_APP_ID + timestamp + payload + SHOPEE_SECRET
    signature = hashlib.sha256(factor.encode()).hexdigest()
    return {
        "Content-Type":  "application/json",
        "Authorization": f"SHA256 Credential={os.environ.get('SHOPEE_APP_ID', '')}, Timestamp={timestamp}, Signature={signature}"
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
      orders {{ orderStatus }}
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
        resp        = requests.post(SHOPEE_ENDPOINT, headers=shopee_auth_header(payload_str), data=payload_str, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        if "errors" in body:
            return {"error": str(body["errors"])}

        report    = body.get("data", {}).get("conversionReport", {})
        nodes     = report.get("nodes", [])
        page_info = report.get("pageInfo", {})

        for node in nodes:
            if any(o.get("orderStatus", "").upper() in valid for o in node.get("orders", [])):
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
        sub_id = extract_sub_id(utm)

        if search and search.lower() not in sub_id.lower() and search.lower() not in utm.lower():
            continue

        try:
            commission = float(node.get("totalCommission") or 0)
        except Exception:
            commission = 0.0

        valid_orders = [o for o in node.get("orders", []) if o.get("orderStatus", "").upper() in valid]

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
    date_str = request.args.get("date", "")
    search   = request.args.get("search", "")

    if not date_str:
        date_str = (datetime.now(BRT) - timedelta(days=1)).date().strftime("%Y-%m-%d")

    try:
        result = fetch_data(date_str, search)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
