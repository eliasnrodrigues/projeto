import copy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from bridge import (ApiError, BridgeError, Store, load_catalog, order_payload, price,
                    sync_catalog, sync_orders, sync_tracking)
from demo import FakeEbay, FakeSupplier, sample_catalog, sample_order, settings


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state.sqlite')
        self.addCleanup(self.store.db.close)
        self.cfg = settings()
        self.supplier, self.ebay = FakeSupplier(), FakeEbay()
        self.catalog = sample_catalog()

    def test_price_rounds_up_and_preserves_target(self):
        result = Decimal(price('75', Decimal('.15'), Decimal('.20'), Decimal('.35'), Decimal('2')))
        self.assertEqual(result, Decimal('119.00'))
        self.assertGreaterEqual(result * Decimal('.65'), Decimal('77.35'))

    def test_success_and_restart_do_not_duplicate(self):
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.assertEqual(self.supplier.creates, 1)
        self.assertEqual(self.store.status('DEMO-001'), 'submitted_unpaid')

    def test_unpaid_can_be_revisited_when_paid(self):
        self.ebay.order['orderPaymentStatus'] = 'PENDING'
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.assertEqual(self.supplier.creates, 0)
        self.assertEqual(self.store.status('DEMO-001'), 'waiting')
        self.ebay.order['orderPaymentStatus'] = 'PAID'
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.assertEqual(self.supplier.creates, 1)

    def test_cancel_country_unapproved_address_blocked(self):
        changes = [lambda o: o['cancelStatus'].update(cancelState='CANCEL_REQUESTED'),
                   lambda o: o['lineItems'][0].update(sku='OTHER'),
                   lambda o: o['fulfillmentStartInstructions'][0]['shippingStep']['shipTo']['contactAddress'].update(countryCode='DE'),
                   lambda o: o['fulfillmentStartInstructions'][0]['shippingStep']['shipTo']['contactAddress'].update(addressLine1='Rua sem número')]
        for change in changes:
            order = copy.deepcopy(sample_order())
            change(order)
            with self.assertRaises(BridgeError):
                order_payload(order, self.catalog, self.cfg)

    def test_stock_or_negative_margin_requires_review(self):
        self.ebay.order['pricingSummary']['total']['value'] = '1.00'
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.assertEqual(self.store.status('DEMO-001'), 'manual_review')
        self.assertEqual(self.supplier.creates, 0)

    def test_lost_create_response_reconciles(self):
        original = self.supplier.create_order
        def timeout(body):
            original(body)
            raise TimeoutError('lost response')
        self.supplier.create_order = timeout
        with self.assertRaises(BridgeError):
            sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.assertEqual(self.store.status('DEMO-001'), 'unknown')
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.assertEqual(self.supplier.creates, 1)
        self.assertEqual(self.store.status('DEMO-001'), 'submitted_unpaid')

    def test_unknown_without_remote_never_reposts(self):
        self.store.set('DEMO-001', 'submitting')
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.assertEqual(self.supplier.creates, 0)
        self.assertEqual(self.store.status('DEMO-001'), 'unknown')

    def test_read_only_has_no_remote_writes(self):
        self.cfg.write = False
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.assertEqual(self.supplier.creates, 0)
        self.assertIsNone(self.store.status('DEMO-001'))

    def shipped(self):
        sync_orders(self.cfg, self.store, self.supplier, self.ebay, self.catalog)
        self.supplier.remote.update(status_order_id=5, shipping_tracking='TRACK123', shipping_option_id=8)

    def test_tracking_and_duplicate_protection(self):
        self.shipped()
        sync_tracking(self.cfg, self.store, self.supplier, self.ebay, {'8': 'DPD'})
        sync_tracking(self.cfg, self.store, self.supplier, self.ebay, {'8': 'DPD'})
        self.assertEqual(self.ebay.posts, 1)
        self.assertEqual(self.store.status('DEMO-001'), 'shipped')

    def test_tracking_timeout_reconciles_without_posting_again(self):
        self.shipped()
        original = self.ebay.call
        def lost(method, path, body=None):
            result = original(method, path, body)
            if method == 'POST':
                raise BridgeError('response lost')
            return result
        self.ebay.call = lost
        with self.assertRaises(BridgeError):
            sync_tracking(self.cfg, self.store, self.supplier, self.ebay, {'8': 'DPD'})
        self.ebay.call = original
        sync_tracking(self.cfg, self.store, self.supplier, self.ebay, {'8': 'DPD'})
        self.assertEqual(self.ebay.posts, 1)
        self.assertEqual(self.store.status('DEMO-001'), 'shipped')

    def test_multi_parcel_requires_manual_review(self):
        self.shipped()
        self.supplier.remote['shipping_tracking_urls_by_number'] = ['a', 'b']
        sync_tracking(self.cfg, self.store, self.supplier, self.ebay, {'8': 'DPD'})
        self.assertEqual(self.ebay.posts, 0)
        self.assertEqual(self.store.status('DEMO-001'), 'manual_review')

    def test_cross_environment_database_is_rejected(self):
        self.store.bind('sandbox:ES:seller')
        with self.assertRaises(BridgeError):
            self.store.bind('production:ES:seller')

    def test_catalog_missing_supplier_product_sets_offer_stock_zero(self):
        self.cfg.cap, self.cfg.buffer, self.cfg.market, self.cfg.publish = 5, 3, 'EBAY_ES', False
        p = dict(self.catalog[0], title='Item', description='Text', image_urls=['https://example.com/a.jpg'])
        calls = []
        def api(method, path, body=None):
            calls.append((method, path, body))
            if method == 'GET':
                return {'offers': [{'offerId': 'O1', 'status': 'PUBLISHED'}]}
            if 'bulk_update' in path:
                return {'responses': [{'statusCode': 200}]}
            return {}
        self.supplier.product = lambda code: None
        self.ebay.call = api
        sync_catalog(self.cfg, self.store, self.supplier, self.ebay, [p])
        update = [x[2] for x in calls if 'bulk_update' in x[1]][0]
        self.assertEqual(update['requests'][0]['offers'][0]['availableQuantity'], 0)
        self.assertNotIn('price', update['requests'][0]['offers'][0])

    def test_bulk_partial_failure_is_not_success(self):
        self.cfg.cap, self.cfg.buffer, self.cfg.market, self.cfg.publish = 5, 3, 'EBAY_ES', False
        p = dict(self.catalog[0], title='Item', description='Text', image_urls=['https://example.com/a.jpg'])
        def api(method, path, body=None):
            if method == 'GET':
                return {'offers': [{'offerId': 'O1', 'status': 'PUBLISHED'}]}
            if 'bulk_update' in path:
                return {'responses': [{'statusCode': 400, 'errors': [{'errorId': 1}]}]}
            return {}
        self.ebay.call = api
        with self.assertRaises(BridgeError):
            sync_catalog(self.cfg, self.store, self.supplier, self.ebay, [p])

    def test_lost_offer_creation_response_blocks_recreation(self):
        self.cfg.cap, self.cfg.buffer, self.cfg.market, self.cfg.publish = 5, 3, 'EBAY_ES', False
        self.cfg.location, self.cfg.policies = 'LOC', {}
        p = dict(self.catalog[0], title='Item', description='Text', category_id='1', image_urls=['https://example.com/a.jpg'])
        creates = []
        def api(method, path, body=None):
            if method == 'GET':
                raise ApiError(404, (25713,))
            if method == 'POST' and path == '/sell/inventory/v1/offer':
                creates.append(body)
                raise BridgeError('lost response')
            return {}
        self.ebay.call = api
        for _ in range(2):
            with self.assertRaises(BridgeError):
                sync_catalog(self.cfg, self.store, self.supplier, self.ebay, [p])
        self.assertEqual(len(creates), 1)

    def test_unpublished_offer_uses_update_offer(self):
        self.cfg.cap, self.cfg.buffer, self.cfg.market, self.cfg.publish = 5, 3, 'EBAY_ES', False
        self.cfg.location, self.cfg.policies = 'LOC', {}
        p = dict(self.catalog[0], title='Item', description='Text', category_id='1', image_urls=['https://example.com/a.jpg'])
        calls = []
        def api(method, path, body=None):
            calls.append((method, path, body))
            if method == 'GET':
                return {'offers': [{'offerId': 'O1', 'status': 'UNPUBLISHED'}]}
            return {}
        self.ebay.call = api
        sync_catalog(self.cfg, self.store, self.supplier, self.ebay, [p])
        self.assertTrue(any(method == 'PUT' and path.endswith('/offer/O1') for method, path, _ in calls))
        self.assertFalse(any('bulk_update' in path for _, path, _ in calls))


if __name__ == '__main__':
    unittest.main()
