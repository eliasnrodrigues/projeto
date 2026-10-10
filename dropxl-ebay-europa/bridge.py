"""dropXL/eBay worker. Python 3.12+, standard library only."""
import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler


class BridgeError(Exception):
    pass


class ApiError(BridgeError):
    def __init__(self, status, error_ids=()):
        self.status = status
        self.error_ids = error_ids
        super().__init__(f"HTTP {status}; inspect the service dashboard")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Do not forward credentials to redirected endpoints.


def http(method, url, headers, body=None, form=False):
    data = None if body is None else (urlencode(body).encode() if form else json.dumps(body).encode())
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with build_opener(NoRedirect).open(req, timeout=45) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        # API bodies may contain tokens or buyer data; never log them.
        try:
            errors = json.loads(exc.read()).get("errors", [])
            ids = tuple(x.get("errorId") for x in errors)
        except Exception:
            ids = ()
        raise ApiError(exc.code, ids) from None
    except Exception:
        raise BridgeError("API request failed; inspect connection/service dashboard") from None


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise BridgeError(f"Missing setting: {name}")
    return value


class Settings:
    MARKETS = {"ES": ("EBAY_ES", "es-ES"), "DE": ("EBAY_DE", "de-DE"),
               "FR": ("EBAY_FR", "fr-FR"), "IT": ("EBAY_IT", "it-IT"),
               "NL": ("EBAY_NL", "nl-NL")}

    def __init__(self):
        self.country = required("SELL_COUNTRY")
        if self.country not in self.MARKETS:
            raise BridgeError("SELL_COUNTRY must be ES, DE, FR, IT or NL")
        self.market, self.locale = self.MARKETS[self.country]
        self.environment = required("API_ENVIRONMENT")
        if self.environment not in ("sandbox", "production"):
            raise BridgeError("API_ENVIRONMENT must be sandbox or production")
        self.write = os.getenv("ENABLE_WRITES") == "true"
        self.publish = os.getenv("PUBLISH_LISTINGS") == "true"
        if self.environment == "production" and self.write:
            if os.getenv("PRODUCTION_ACK") != "I_CONFIGURED_MY_SELLER_ACCOUNT":
                raise BridgeError("Production writes require PRODUCTION_ACK")
        self.policies = {x: required(env) for x, env in (
            ("paymentPolicyId", "EBAY_PAYMENT_POLICY_ID"),
            ("returnPolicyId", "EBAY_RETURN_POLICY_ID"),
            ("fulfillmentPolicyId", "EBAY_FULFILLMENT_POLICY_ID"))}
        self.location = required("EBAY_LOCATION_KEY")
        self.phone = required("SELLER_PHONE")
        self.fee = Decimal(required("ESTIMATED_FEE_RATE"))
        self.margin = Decimal(required("TARGET_MARGIN_RATE"))
        self.fixed = Decimal(required("FIXED_COST_EUR"))
        self.reserve = Decimal(required("RESERVE_EUR"))
        if not all(x.is_finite() for x in (self.fee, self.margin, self.fixed, self.reserve)):
            raise BridgeError("Cost settings must be finite")
        if min(self.fee, self.margin, self.fixed, self.reserve) < 0 or self.fee + self.margin >= 1:
            raise BridgeError("Invalid margin/fee/cost configuration")
        self.buffer = int(os.getenv("STOCK_BUFFER", "3"))
        self.cap = int(os.getenv("MAX_LISTING_QUANTITY", "5"))
        if min(self.buffer, self.cap) < 0:
            raise BridgeError("Stock limits cannot be negative")


def price(cost, fee, margin, fixed, reserve):
    cost = Decimal(str(cost))
    if not cost.is_finite() or cost < 0:
        raise BridgeError("Invalid supplier cost")
    return str(((cost + fixed + reserve) / (1 - fee - margin)).quantize(Decimal("0.01"), rounding=ROUND_UP))


class Store:
    def __init__(self, path, exclusive=False):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = None
        if exclusive:
            import fcntl  # Cloud/container runtime is Linux.
            self.lock = open(str(path) + ".lock", "a")
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BridgeError("Another worker is using this database") from None
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, status TEXT, supplier_id TEXT, note TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS offers (sku TEXT PRIMARY KEY, offer_id TEXT)")
        self.db.commit()

    def bind(self, namespace):
        self.db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
        row = self.db.execute("SELECT value FROM metadata WHERE key='namespace'").fetchone()
        if row and row[0] != namespace:
            raise BridgeError("Use a separate persistent state volume for each country/environment/seller")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('namespace',?)", (namespace,))
        self.db.commit()

    def status(self, order_id):
        row = self.db.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        return row[0] if row else None

    def set(self, order_id, status, supplier_id="", note=""):
        self.db.execute("INSERT INTO orders VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, supplier_id=excluded.supplier_id, note=excluded.note", (order_id, status, str(supplier_id), note))
        self.db.commit()  # Commit before every remote side effect.

    def report(self):
        return {"counts": dict(Counter(x[0] for x in self.db.execute("SELECT status FROM orders"))),
                "orders": [dict(zip(("order_id", "status", "supplier_id", "note"), row))
                           for row in self.db.execute("SELECT * FROM orders ORDER BY id")]}


class DropXL:
    def __init__(self, settings):
        self.base = "https://b2b.dropxl.com" if settings.environment == "production" else "https://sandbox.b2b.dropxl.com"
        auth = base64.b64encode(f'{required("DROPXL_EMAIL")}:{required("DROPXL_API_TOKEN")}'.encode()).decode()
        self.headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
        self.last_call = 0

    def call(self, method, path, body=None):
        time.sleep(max(0, 1.05 - (time.monotonic() - self.last_call)))
        self.last_call = time.monotonic()
        return http(method, self.base + path, self.headers, body)

    def product(self, code):
        rows = self.call("GET", "/api_customer/products?" + urlencode({"code_eq": code}))
        if not isinstance(rows, list):
            raise BridgeError("Unexpected dropXL product response")
        matches = [x for x in rows if str(x.get("code")) == str(code)]
        return matches[0] if len(matches) == 1 else None

    def find_order(self, reference):
        rows = self.call("GET", "/api_customer/orders?" + urlencode({"customer_order_reference_eq": reference}))
        if not isinstance(rows, list):
            raise BridgeError("Unexpected dropXL order response")
        matches = [x.get("order", x) for x in rows]
        matches = [x for x in matches if x.get("customer_order_reference") == reference]
        if len(matches) > 1:
            raise BridgeError("Multiple supplier orders for one reference; manual review required")
        return matches[0] if matches else None

    def create_order(self, body):
        return self.call("POST", "/api_customer/orders", body).get("order", {})


class Ebay:
    def __init__(self, settings):
        self.base = "https://api.ebay.com" if settings.environment == "production" else "https://api.sandbox.ebay.com"
        self.settings = settings
        self.token = None
        self.expires = 0

    def authorize(self):
        auth = base64.b64encode(f'{required("EBAY_CLIENT_ID")}:{required("EBAY_CLIENT_SECRET")}'.encode()).decode()
        data = http("POST", self.base + "/identity/v1/oauth2/token", {
            "Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}, {
            "grant_type": "refresh_token", "refresh_token": required("EBAY_REFRESH_TOKEN"),
            "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory https://api.ebay.com/oauth/api_scope/sell.fulfillment"}, form=True)
        self.token = data["access_token"]
        self.expires = time.monotonic() + int(data["expires_in"]) - 90

    def call(self, method, path, body=None):
        if method != "GET" and not self.settings.write:
            raise BridgeError("Writes are disabled")
        if time.monotonic() >= self.expires:
            self.authorize()
        return http(method, self.base + path, {"Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json", "Content-Language": self.settings.locale}, body)

    def orders(self, days=30):
        start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        offset = 0
        while True:
            query = urlencode({"filter": f"lastmodifieddate:[{start}..]", "limit": 100, "offset": offset})
            data = self.call("GET", "/sell/fulfillment/v1/order?" + query)
            yield from data.get("orders", [])
            if not data.get("next"):
                break
            offset += 100


def load_catalog(path):
    catalog = json.loads(Path(path).read_text())
    if not isinstance(catalog, list):
        raise BridgeError("Catalog must be a list")
    seen = set()
    for p in catalog:
        code = str(p["supplier_code"])
        if not re.fullmatch(r"\d+", code) or code in seen:
            raise BridgeError("Supplier codes must be numeric and unique")
        seen.add(code)
        if p.get("approved"):
            if not p.get("title") or len(p["title"]) > 80 or not p.get("category_id") or not p.get("description"):
                raise BridgeError("Approved items require title <=80 chars, category and description")
            if not p.get("image_urls") or not all(x.startswith("https://") for x in p["image_urls"]):
                raise BridgeError("Approved items require supplier-authorized HTTPS images")
            if "landed_cost_factor" not in p or "shipping_cost_eur" not in p:
                raise BridgeError("Confirm total cost basis for each item before approving it")
            factor, shipping = Decimal(str(p["landed_cost_factor"])), Decimal(str(p["shipping_cost_eur"]))
            if not factor.is_finite() or not shipping.is_finite() or factor < 1 or shipping < 0:
                raise BridgeError("Invalid landed cost configuration")
    return catalog


def sync_catalog(settings, store, supplier, ebay, catalog):
    summary = Counter()
    for p in catalog:
        if not p.get("approved"):
            summary["not_approved"] += 1
            continue
        code = str(p["supplier_code"])
        sku = "DXL-" + code
        current = supplier.product(code)
        qty = max(0, min(settings.cap, int(Decimal(str(current["quantity"]))) - settings.buffer)) if current else 0
        cost = Decimal(str(current["price"])) if current else Decimal("0")
        cost = cost * Decimal(str(p["landed_cost_factor"])) + Decimal(str(p["shipping_cost_eur"]))
        amount = price(cost, settings.fee, settings.margin, settings.fixed, settings.reserve)
        if not settings.write:
            summary["planned"] += 1
            print(json.dumps({"sku": sku, "quantity": qty, "price_eur": amount}))
            continue
        product = {"title": p["title"], "description": p["description"], "imageUrls": p["image_urls"], "aspects": p.get("aspects", {})}
        if p.get("ean"):
            product["ean"] = [p["ean"]]
        # Availability updated even if a supplier product disappears.
        ebay.call("PUT", "/sell/inventory/v1/inventory_item/" + quote(sku, safe=""), {
            "availability": {"shipToLocationAvailability": {"quantity": qty}}, "condition": "NEW", "product": product})
        try:
            offers = ebay.call("GET", "/sell/inventory/v1/offer?" + urlencode({"sku": sku, "marketplace_id": settings.market})).get("offers", [])
        except ApiError as exc:
            if exc.status == 404 and 25713 in exc.error_ids:
                offers = []
            else:
                raise
        if len(offers) > 1:
            raise BridgeError("Multiple eBay offers for SKU; review manually")
        if not offers and qty == 0:
            summary["out_of_stock"] += 1
            continue
        if not offers:
            previous = store.db.execute("SELECT offer_id FROM offers WHERE sku=?", (sku,)).fetchone()
            if previous:
                raise BridgeError("Previously recorded offer is unavailable; review before recreating")
            # Creation is followed by a GET on the next cycle if response is lost.
            payload = {"sku": sku, "marketplaceId": settings.market, "format": "FIXED_PRICE", "availableQuantity": qty,
                       "categoryId": str(p["category_id"]), "merchantLocationKey": settings.location,
                       "listingPolicies": settings.policies, "listingDuration": "GTC",
                       "pricingSummary": {"price": {"value": amount, "currency": "EUR"}}}
            if p.get("regulatory"):
                payload["regulatory"] = p["regulatory"]
            store.db.execute("INSERT INTO offers VALUES (?,?)", (sku, "CREATING_REVIEW_IF_MISSING"))
            store.db.commit()
            offer_id = ebay.call("POST", "/sell/inventory/v1/offer", payload)["offerId"]
            status = "UNPUBLISHED"
        else:
            offer_id, status = offers[0]["offerId"], offers[0].get("status")
            if status == "PUBLISHED":
                update = {"offerId": offer_id, "availableQuantity": qty}
                if current:
                    update["price"] = {"value": amount, "currency": "EUR"}
                result = ebay.call("POST", "/sell/inventory/v1/bulk_update_price_quantity", {"requests": [{
                    "sku": sku, "shipToLocationAvailability": {"quantity": qty}, "offers": [update]}]})
                if not result.get("responses") or any(x.get("errors") or int(x.get("statusCode", 500)) >= 300 for x in result["responses"]):
                    raise BridgeError("eBay bulk update failed; inspect listing stock before continuing")
            else:
                payload = {"availableQuantity": qty, "categoryId": str(p["category_id"]),
                           "merchantLocationKey": settings.location, "listingPolicies": settings.policies,
                           "listingDuration": "GTC", "pricingSummary": {"price": {"value": amount, "currency": "EUR"}}}
                if p.get("regulatory"):
                    payload["regulatory"] = p["regulatory"]
                ebay.call("PUT", "/sell/inventory/v1/offer/" + quote(offer_id, safe=""), payload)
        store.db.execute("INSERT INTO offers VALUES (?,?) ON CONFLICT(sku) DO UPDATE SET offer_id=excluded.offer_id", (sku, offer_id))
        store.db.commit()
        if settings.publish and status != "PUBLISHED" and qty > 0:
            ebay.call("POST", f"/sell/inventory/v1/offer/{quote(offer_id, safe='')}/publish", {})
            summary["published"] += 1
        else:
            summary["updated"] += 1
    return dict(summary)


def order_payload(order, catalog, settings):
    if order.get("orderPaymentStatus") != "PAID" or order.get("orderFulfillmentStatus") != "NOT_STARTED":
        raise BridgeError("Order is unpaid or already partially/fully fulfilled")
    if order.get("cancelStatus", {}).get("cancelState") != "NONE_REQUESTED":
        raise BridgeError("Cancellation requested or status unavailable")
    steps = order.get("fulfillmentStartInstructions", [])
    if len(steps) != 1 or steps[0].get("fulfillmentInstructionsType") != "SHIP_TO":
        raise BridgeError("Only a single shipping destination is supported")
    to = steps[0]["shippingStep"]["shipTo"]
    a = to["contactAddress"]
    if a.get("countryCode") != settings.country:
        raise BridgeError("Destination outside configured dropXL country")
    address = a.get("addressLine1", "")
    if not address or len(address) > 30 or not re.search(r"\d", address):
        raise BridgeError("Review street address (dropXL: <=30 characters and house number)")
    book = {"address": address, "address2": a.get("addressLine2", ""), "city": a.get("city", ""),
            "province": a.get("stateOrProvince", ""), "postal_code": a.get("postalCode", ""),
            "country": a["countryCode"], "name": to.get("fullName", ""),
            "phone": to.get("primaryPhone", {}).get("phoneNumber") or settings.phone}
    if not all(book[x] for x in ("city", "postal_code", "name", "phone")):
        raise BridgeError("Incomplete recipient address")
    approved = {"DXL-" + str(p["supplier_code"]) for p in catalog if p.get("approved")}
    products = []
    for item in order.get("lineItems", []):
        quantity = item.get("quantity")
        if item.get("sku") not in approved or type(quantity) is not int or quantity <= 0:
            raise BridgeError("Order contains an unapproved SKU or invalid quantity")
        if item.get("refunds") or item.get("lineItemFulfillmentStatus") not in (None, "NOT_STARTED"):
            raise BridgeError("Refund/fulfillment needs manual review")
        products.append({"product_code": item["sku"][4:], "quantity": item["quantity"], "addressbook": book})
    if not products:
        raise BridgeError("Empty order")
    return {"customer_order_reference": "EBAY-" + order["orderId"], "addressbook": {"country": settings.country}, "order_products": products}


def sync_orders(settings, store, supplier, ebay, catalog):
    summary = Counter()
    for snapshot in ebay.orders():
        order_id = snapshot["orderId"]
        if not any(str(x.get("sku", "")).startswith("DXL-") for x in snapshot.get("lineItems", [])):
            continue
        previous = store.status(order_id)
        if previous in ("submitted_unpaid", "shipped", "manual_review"):
            continue
        # Reconcile before creation and after any ambiguous response.
        reference = "EBAY-" + order_id
        remote = supplier.find_order(reference)
        if remote:
            store.set(order_id, "submitted_unpaid", remote["id"], "Check payment/status in dropXL")
            continue
        if previous in ("submitting", "unknown"):
            store.set(order_id, "unknown", note="Check supplier by reference; do not automatically resubmit")
            continue
        order = ebay.call("GET", "/sell/fulfillment/v1/order/" + quote(order_id, safe=""))
        try:
            payload = order_payload(order, catalog, settings)
            catalog_by_code = {str(p["supplier_code"]): p for p in catalog if p.get("approved")}
            total_cost = Decimal("0")
            for line in payload["order_products"]:
                p = supplier.product(line["product_code"])
                if not p or Decimal(str(p["quantity"])) < line["quantity"]:
                    raise BridgeError("Supplier stock unavailable")
                spec = catalog_by_code[line["product_code"]]
                total_cost += (Decimal(str(p["price"])) * Decimal(str(spec["landed_cost_factor"])) + Decimal(str(spec["shipping_cost_eur"]))) * line["quantity"]
            total = order.get("pricingSummary", {}).get("total", {})
            if total.get("currency") != "EUR" or Decimal(str(total.get("value", "0"))) < Decimal(price(total_cost, settings.fee, settings.margin, settings.fixed, settings.reserve)):
                raise BridgeError("Review order margin: paid amount below configured minimum")
        except BridgeError as exc:
            # Unpaid orders remain eligible for a later check after payment.
            state = "waiting" if order.get("orderPaymentStatus") != "PAID" else "manual_review"
            store.set(order_id, state, note=str(exc))
            summary[state] += 1
            continue
        if not settings.write:
            summary["planned"] += 1
            continue
        store.set(order_id, "submitting")
        try:
            remote = supplier.create_order(payload)
            if not remote.get("id"):
                raise BridgeError("Supplier did not return an order ID")
        except Exception:
            store.set(order_id, "unknown", note="Ambiguous create result; reconcile by reference")
            raise BridgeError("Supplier order outcome uncertain; automatic retry blocked") from None
        store.set(order_id, "submitted_unpaid", remote["id"], "Manual payment required in dropXL")
        summary["submitted_unpaid"] += 1
    return dict(summary)


def sync_tracking(settings, store, supplier, ebay, carriers):
    summary = Counter()
    rows = store.db.execute("SELECT id FROM orders WHERE status IN ('submitted_unpaid','tracking_pending')").fetchall()
    for (order_id,) in rows:
        remote = supplier.find_order("EBAY-" + order_id)
        if not remote:
            continue
        if int(remote.get("status_order_id", 0)) in (7, 8, 9):
            store.set(order_id, "manual_review", remote["id"], "Supplier cancelled/refunded/replaced; review eBay")
            continue
        if int(remote.get("status_order_id", 0)) != 5:
            continue
        number = str(remote.get("shipping_tracking") or "").strip()
        carrier = carriers.get(str(remote.get("shipping_option_id")))
        if not number or not re.fullmatch(r"[A-Za-z0-9-]+", number) or not carrier:
            store.set(order_id, "manual_review", remote["id"], "Confirm carrier/parcel tracking in supplier dashboard")
            continue
        order = ebay.call("GET", "/sell/fulfillment/v1/order/" + quote(order_id, safe=""))
        items = order.get("lineItems", [])
        # Multi-item or multi-parcel mapping must be confirmed by a human.
        if len(items) != 1 or items[0].get("quantity") != 1 or len(remote.get("shipping_tracking_urls_by_number", [])) > 1:
            store.set(order_id, "manual_review", remote["id"], "Multiple items/parcels: confirm line-to-parcel mapping")
            continue
        path = "/sell/fulfillment/v1/order/" + quote(order_id, safe="") + "/shipping_fulfillment"
        fulfillments = ebay.call("GET", path).get("fulfillments", [])
        if any(x.get("trackingNumber") == number and x.get("shippingCarrierCode") == carrier for x in fulfillments):
            store.set(order_id, "shipped", remote["id"])
            continue
        if fulfillments:
            store.set(order_id, "manual_review", remote["id"], "Existing fulfillment differs; review tracking")
            continue
        if not settings.write:
            summary["planned"] += 1
            continue
        if store.status(order_id) == "tracking_pending":
            store.set(order_id, "manual_review", remote["id"], "Ambiguous tracking result; do not automatically duplicate")
            continue
        store.set(order_id, "tracking_pending", remote["id"])
        ebay.call("POST", path, {"trackingNumber": number, "shippingCarrierCode": carrier,
                  "lineItems": [{"lineItemId": items[0]["lineItemId"], "quantity": 1}]})
        store.set(order_id, "shipped", remote["id"])
        summary["shipped"] += 1
    return dict(summary)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="dropXL + eBay Europe")
    parser.add_argument("command", choices=["demo", "check", "catalog", "orders", "tracking", "run", "worker", "status"])
    parser.add_argument("--catalog", default="catalog.json")
    parser.add_argument("--state", default=os.getenv("STATE_DB", "state/bridge.sqlite"))
    args = parser.parse_args()
    if args.command == "demo":
        from demo import run
        run()
        return
    if args.command == "status":
        print(json.dumps(Store(args.state).report(), indent=2))
        return
    settings = Settings()
    catalog = load_catalog(args.catalog)
    supplier, ebay, store = DropXL(settings), Ebay(settings), Store(args.state, exclusive=True)
    store.bind(settings.environment + ':' + settings.country + ':' + required("DROPXL_EMAIL") + ':' + required("EBAY_CLIENT_ID"))
    carriers = json.loads(Path(os.getenv("CARRIERS_FILE", "carriers.json")).read_text())
    if args.command == "check":
        ebay.authorize()
        supplier.call("GET", "/api_customer/products?limit=1&offset=0")
        print(json.dumps({"connections": "OK", "country": settings.country, "environment": settings.environment,
                          "writes": settings.write, "publish": settings.publish}))
        return
    while True:
        result = {}
        try:
            if args.command in ("catalog", "run", "worker"):
                result["catalog"] = sync_catalog(settings, store, supplier, ebay, catalog)
            if args.command in ("orders", "run", "worker"):
                result["orders"] = sync_orders(settings, store, supplier, ebay, catalog)
            if args.command in ("tracking", "run", "worker"):
                result["tracking"] = sync_tracking(settings, store, supplier, ebay, carriers)
            print(json.dumps(result), flush=True)
        except BridgeError:
            if args.command != "worker":
                raise
            print("Cycle failed; inspect state with 'status' and service dashboards", flush=True)
        if args.command != "worker":
            break
        time.sleep(max(60, int(os.getenv("POLL_SECONDS", "900"))))


if __name__ == "__main__":
    try:
        main()
    except (BridgeError, KeyError, ValueError, OSError):
        # Generic output avoids leaking PII from API payload validation.
        print("Configuration/API error. Verify settings and dashboards; no credentials or buyer details were logged.")
        raise SystemExit(1)
