# Copyright (c) 2025, BrainWise and contributors
# For license information, please see license.txt

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from pos_next.api import invoice_transfer


def _invoice(**overrides):
	"""A minimal submitted, movable invoice snapshot."""
	data = {
		"name": "SINV-0012",
		"customer": "CUST-A",
		"customer_name": "Customer A",
		"docstatus": 1,
		"is_return": 0,
		"redeem_loyalty_points": 0,
		"consolidated_invoice": None,
		"grand_total": 500,
		"outstanding_amount": 300,
		"currency": "EGP",
	}
	data.update(overrides)
	return frappe._dict(data)


class TestBlockingReasons(unittest.TestCase):
	"""_get_blocking_reason is the single gate both the pre-flight and the
	transfer itself go through, so every refusal is tested here."""

	def _reason(self, invoice, *, has_return=False, credit_je=False, link=None):
		def fake_exists(doctype, filters=None):
			if doctype == "Sales Invoice":
				return "SINV-0012-RET" if has_return else None
			if doctype == "Journal Entry":
				return "JE-0007" if credit_je else None
			return None

		with (
			patch.object(invoice_transfer.frappe.db, "exists", side_effect=fake_exists),
			patch.object(invoice_transfer, "_get_blocking_link", return_value=link),
		):
			return invoice_transfer._get_blocking_reason(invoice)[0]

	def test_movable_invoice_has_no_blocking_reason(self):
		self.assertIsNone(self._reason(_invoice()))

	def test_draft_invoice_is_blocked(self):
		self.assertEqual(self._reason(_invoice(docstatus=0)), "not_submitted")

	def test_cancelled_invoice_is_blocked(self):
		self.assertEqual(self._reason(_invoice(docstatus=2)), "not_submitted")

	def test_return_invoice_is_blocked(self):
		self.assertEqual(self._reason(_invoice(is_return=1)), "is_return")

	def test_consolidated_invoice_is_blocked(self):
		self.assertEqual(
			self._reason(_invoice(consolidated_invoice="POS-INV-01")), "consolidated"
		)

	def test_invoice_with_a_return_against_it_is_blocked(self):
		self.assertEqual(self._reason(_invoice(), has_return=True), "has_return")

	def test_loyalty_redemption_is_blocked(self):
		self.assertEqual(self._reason(_invoice(redeem_loyalty_points=1)), "used_loyalty_points")

	def test_customer_credit_redemption_is_blocked(self):
		self.assertEqual(self._reason(_invoice(), credit_je=True), "used_customer_credit")

	def test_other_linked_document_is_blocked(self):
		link = {"reference_doctype": "Payment Request", "reference_docname": "PRQ-0007"}
		self.assertEqual(self._reason(_invoice(), link=link), "linked_documents")

	def test_docstatus_is_checked_before_anything_else(self):
		# A cancelled invoice that also has a return reports the docstatus problem,
		# which is the one the user can actually act on first.
		self.assertEqual(self._reason(_invoice(docstatus=2), has_return=True), "not_submitted")


class TestEligibilityEndpoint(unittest.TestCase):
	def test_missing_invoice_reports_not_found(self):
		with (
			patch.object(invoice_transfer.frappe, "has_permission", return_value=True),
			patch.object(invoice_transfer.frappe.db, "get_value", return_value=None),
		):
			result = invoice_transfer.check_invoice_transfer_eligibility("SINV-NOPE")

		self.assertFalse(result["eligible"])
		self.assertEqual(result["reason"], "not_found")
		self.assertIsNone(result["invoice"])

	def test_eligible_invoice_returns_its_snapshot(self):
		with (
			patch.object(invoice_transfer.frappe, "has_permission", return_value=True),
			patch.object(invoice_transfer.frappe.db, "get_value", return_value=_invoice()),
			patch.object(invoice_transfer, "_get_blocking_reason", return_value=(None, None)),
		):
			result = invoice_transfer.check_invoice_transfer_eligibility("SINV-0012")

		self.assertTrue(result["eligible"])
		self.assertEqual(result["invoice"]["customer"], "CUST-A")

	def test_read_permission_is_required(self):
		with patch.object(invoice_transfer.frappe, "has_permission", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				invoice_transfer.check_invoice_transfer_eligibility("SINV-0012")


class TestTransferGuards(unittest.TestCase):
	"""Guards that must reject before any document is touched."""

	def test_new_customer_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			invoice_transfer.transfer_invoice_to_customer("SINV-0012", "")

	def test_invoice_name_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			invoice_transfer.transfer_invoice_to_customer("", "CUST-B")

	def test_cancel_permission_is_required(self):
		with patch.object(invoice_transfer.frappe, "has_permission", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				invoice_transfer.transfer_invoice_to_customer("SINV-0012", "CUST-B")

	def test_unknown_customer_is_rejected(self):
		with (
			patch.object(invoice_transfer.frappe, "has_permission", return_value=True),
			patch.object(invoice_transfer.frappe.db, "exists", return_value=False),
		):
			with self.assertRaises(frappe.ValidationError):
				invoice_transfer.transfer_invoice_to_customer("SINV-0012", "CUST-GHOST")

	def test_moving_to_the_same_customer_is_rejected(self):
		doc = _invoice()
		with (
			patch.object(invoice_transfer.frappe, "has_permission", return_value=True),
			patch.object(invoice_transfer.frappe.db, "exists", return_value=True),
			patch.object(invoice_transfer.frappe, "get_doc", return_value=doc),
			patch.object(invoice_transfer, "_get_blocking_reason", return_value=(None, None)),
		):
			with self.assertRaises(frappe.ValidationError):
				invoice_transfer.transfer_invoice_to_customer("SINV-0012", "CUST-A")

	def test_currency_mismatch_is_rejected(self):
		doc = _invoice()
		with (
			patch.object(invoice_transfer.frappe, "has_permission", return_value=True),
			patch.object(invoice_transfer.frappe.db, "exists", return_value=True),
			patch.object(invoice_transfer.frappe, "get_doc", return_value=doc),
			patch.object(invoice_transfer, "_get_blocking_reason", return_value=(None, None)),
			patch.object(invoice_transfer.frappe.db, "get_value", return_value="USD"),
		):
			with self.assertRaises(frappe.ValidationError):
				invoice_transfer.transfer_invoice_to_customer("SINV-0012", "CUST-B")

	def test_blocking_reason_is_re_checked_server_side(self):
		# The client pre-flight is advisory only - the endpoint must refuse again.
		doc = _invoice()
		with (
			patch.object(invoice_transfer.frappe, "has_permission", return_value=True),
			patch.object(invoice_transfer.frappe.db, "exists", return_value=True),
			patch.object(invoice_transfer.frappe, "get_doc", return_value=doc),
			patch.object(
				invoice_transfer,
				"_get_blocking_reason",
				return_value=("has_return", "Invoice has a return against it"),
			),
		):
			with self.assertRaises(frappe.ValidationError):
				invoice_transfer.transfer_invoice_to_customer("SINV-0012", "CUST-B")


class TestPaymentSnapshot(unittest.TestCase):
	def test_zero_and_negative_allocations_are_dropped(self):
		rows = [
			frappe._dict({"payment_entry": "PE-1", "amount": 200}),
			frappe._dict({"payment_entry": "PE-2", "amount": 0}),
			frappe._dict({"payment_entry": "PE-3", "amount": -50}),
		]
		builder = MagicMock()
		builder.inner_join.return_value = builder
		builder.on.return_value = builder
		builder.select.return_value = builder
		builder.where.return_value = builder
		builder.orderby.return_value = builder
		builder.run.return_value = rows

		with patch.object(invoice_transfer.frappe.qb, "from_", return_value=builder):
			result = invoice_transfer._snapshot_payment_entries("SINV-0012")

		self.assertEqual([r["payment_entry"] for r in result], ["PE-1"])


class TestBlockingLink(unittest.TestCase):
	def test_payment_entries_are_not_blockers(self):
		# The transfer cancels and re-creates Payment Entries itself.
		links = [
			{"reference_doctype": "Payment Entry", "reference_docname": "PE-1"},
			{"reference_doctype": "Payment Request", "reference_docname": "PRQ-1"},
		]
		with (
			patch.object(invoice_transfer.frappe, "get_doc", return_value=SimpleNamespace()),
			patch("frappe.model.delete_doc.get_linked_docs", return_value=links),
		):
			link = invoice_transfer._get_blocking_link("SINV-0012")

		self.assertEqual(link["reference_doctype"], "Payment Request")

	def test_only_payment_entries_means_no_blocker(self):
		links = [{"reference_doctype": "Payment Entry", "reference_docname": "PE-1"}]
		with (
			patch.object(invoice_transfer.frappe, "get_doc", return_value=SimpleNamespace()),
			patch("frappe.model.delete_doc.get_linked_docs", return_value=links),
		):
			self.assertIsNone(invoice_transfer._get_blocking_link("SINV-0012"))

	def test_a_failing_link_lookup_never_blocks_the_dialog(self):
		with patch.object(invoice_transfer.frappe, "get_doc", side_effect=Exception("boom")):
			self.assertIsNone(invoice_transfer._get_blocking_link("SINV-0012"))


if __name__ == "__main__":
	unittest.main()
