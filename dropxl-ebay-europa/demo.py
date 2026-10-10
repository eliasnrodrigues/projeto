"""Offline integration rehearsal: no network requests and no real buyer data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from decimal import Decimal
import json
from bridge import Store, sync_orders, sync_tracking


def settings():
    return SimpleNamespace(country="ES", write=True, fee=Decimal("0.15"), margin=Decimal("0.20"),
                           fixed=Decimal("0.35"), reserve=Decimal("2"), phone="+34000000000")


def sample_order():
    return {"orderId": "DEMO-001", "orderPaymentStatus": "PAID", "orderFulfillmentStatus": "NOT_STARTED",
            "cancelStatus": {"cancelState": "NONE_REQUESTED"},
            "pricingSummary": {"total": {"value": "150.00", "currency": "EUR"}},
            "fulfillmentStartInstructions": [{"fulfillmentInstructionsType": "SHIP_TO", "shippingStep": {
                "shipTo": {"fullName": "Cliente de demonstração", "contactAddress": {
                    "addressLine1": "Rua de Teste 10", "city": "Madrid", "postalCode": "28001", "countryCode": "ES"}}}}],
            "lineItems": [{"lineItemId": "DEMO-LINE", "sku": "DXL-100058", "quantity": 1}]}


def sample_catalog():
    return [{"supplier_code": "100058", "approved": True, "landed_cost_factor": 1, "shipping_cost_eur": 0}]


class FakeSupplier:
    def __init__(self):
        self.remote = None
        self.creates = 0

    def product(self, code):
        return {"code": code, "price": "75.00", "quantity": "10.0"}

    def find_order(self, ref):
        return self.remote

    def create_order(self, body):
        self.creates += 1
        self.remote = {"id": "DEMO-DROPXL", "status_order_id": 1,
                       "customer_order_reference": body["customer_order_reference"]}
        return self.remote


class FakeEbay:
    def __init__(self):
        self.order = sample_order()
        self.fulfillments = []
        self.posts = 0

    def orders(self):
        return [self.order]

    def call(self, method, path, body=None):
        if path.endswith("shipping_fulfillment"):
            if method == "POST":
                self.posts += 1
                self.fulfillments.append(body)
                return {}
            return {"fulfillments": self.fulfillments}
        return self.order


def run():
    with TemporaryDirectory() as d:
        store = Store(Path(d) / "demo.sqlite")
        supplier, ebay = FakeSupplier(), FakeEbay()
        cfg = settings()
        first = sync_orders(cfg, store, supplier, ebay, sample_catalog())
        sync_orders(cfg, store, supplier, ebay, sample_catalog())
        print(json.dumps({"step": "order_created", "result": first, "duplicate_orders": supplier.creates - 1}))
        print("SIMULAÇÃO: pagamento manual no painel dropXL")
        supplier.remote.update(status_order_id=5, shipping_tracking="DEMO123", shipping_option_id=8)
        tracking = sync_tracking(cfg, store, supplier, ebay, {"8": "DPD"})
        print(json.dumps({"step": "tracking_sent", "result": tracking, "final": store.report()}, ensure_ascii=False, indent=2))
