# Copyright (c) 2025, BrainWise and contributors
# For license information, please see license.txt

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pos_next.api import customer_dues


def _builder_with_result(result):
	"""A query-builder stub whose chained calls return the given rows from .run()."""

	class _Builder:
		def select(self, *_a, **_k):
			return self

		def where(self, *_a, **_k):
			return self

		def groupby(self, *_a, **_k):
			return self

		def run(self, *_a, **_k):
			return result

	return _Builder()


class TestCreditCustomersSummary(unittest.TestCase):
	@patch("pos_next.api.customer_dues.frappe.db.get_value", return_value="EGP")
	@patch("pos_next.api.customer_dues.frappe.qb.from_")
	@patch("pos_next.api.customer_dues.frappe.has_permission", return_value=True)
	def test_summary_nets_returns_against_outstanding(self, _perm, mock_from, _gv):
		# Regular invoices (is_return=0): positive outstanding per customer
		regular_rows = [
			SimpleNamespace(
				customer="CUST-A", customer_name="Mixed Customer",
				total_outstanding=382, due_count=14,
			),
			SimpleNamespace(
				customer="CUST-B", customer_name="Owes Only",
				total_outstanding=150, due_count=1,
			),
			SimpleNamespace(
				customer="CUST-C", customer_name="Fully Credited",
				total_outstanding=50, due_count=1,
			),
		]
		# Return invoices (is_return=1, outstanding<0): credit per customer
		return_rows = [
			SimpleNamespace(customer="CUST-A", total_credit=133),
			SimpleNamespace(customer="CUST-C", total_credit=50),
		]
		mock_from.side_effect = [
			_builder_with_result(regular_rows),
			_builder_with_result(return_rows),
		]

		result = customer_dues.get_credit_customers_summary(company="Sonex")

		# CUST-C still has an unpaid invoice (total_outstanding=50) even though its
		# return credit fully offsets it (net_balance == 0) — it stays in the list so
		# the cashier can see "has credit", it's just excluded from the money totals.
		names = [c["customer"] for c in result["customers"]]
		self.assertEqual(names, ["CUST-A", "CUST-B", "CUST-C"])  # sorted by net_balance desc, then outstanding

		mixed = result["customers"][0]
		self.assertEqual(mixed["total_outstanding"], 382)
		self.assertEqual(mixed["total_credit"], 133)
		self.assertEqual(mixed["net_balance"], 249)
		self.assertEqual(mixed["due_count"], 14)

		fully_credited = result["customers"][2]
		self.assertEqual(fully_credited["net_balance"], 0)

		self.assertEqual(result["totals"]["customer_count"], 3)
		self.assertEqual(result["totals"]["net_balance"], 399)  # 249 + 150, CUST-C's 0 doesn't add
		self.assertEqual(result["currency"], "EGP")

	@patch("pos_next.api.customer_dues.frappe.throw", side_effect=RuntimeError("Not permitted"))
	@patch("pos_next.api.customer_dues.frappe.has_permission", return_value=False)
	def test_summary_requires_read_permission(self, _perm, _throw):
		with self.assertRaisesRegex(RuntimeError, "Not permitted"):
			customer_dues.get_credit_customers_summary(company="Sonex")


class TestCustomerStatementBreakdown(unittest.TestCase):
	def test_paid_and_returned_are_calculated_independently(self):
		for label, total, remaining, returned, expected_paid, expected_returned in [
			("payment only", 240, 140, 0, 100, 0),
			("return only", 240, 140, 100, 0, 100),
			("payment and return", 240, 40, 100, 100, 100),
			("neither", 240, 240, 0, 0, 0),
			("rounding noise", 240, 239.995, 0, 0, 0),
		]:
			with self.subTest(label=label):
				paid, calculated_returned = customer_dues._get_statement_breakdown(
					total, remaining, returned
				)
				self.assertEqual(paid, expected_paid)
				self.assertEqual(calculated_returned, expected_returned)

	@patch("pos_next.api.customer_dues.frappe.get_all")
	def test_returned_amount_uses_only_linked_submitted_returns(self, mock_get_all):
		mock_get_all.return_value = [{"grand_total": -100}, {"grand_total": -25}]

		returned = customer_dues._get_linked_return_amount(
			"CUST-A", ["INV-0001", "INV-0002"], "Sonex"
		)

		self.assertEqual(returned, 125)
		self.assertEqual(
			mock_get_all.call_args.kwargs["filters"],
			{
				"customer": "CUST-A",
				"docstatus": 1,
				"is_return": 1,
				"return_against": ["in", ["INV-0001", "INV-0002"]],
				"company": "Sonex",
			},
		)


class TestPayCustomerDue(unittest.TestCase):
	"""
	Regression coverage for the pay-all bug: a single-invoice payment must never spill
	onto a customer's other outstanding invoices. `invoice=` restricts allocation to
	that one Sales Invoice — defense in depth behind the frontend keyboard-stack fix.
	"""

	@patch("pos_next.api.customer_dues.get_customer_balance", return_value={})
	@patch("pos_next.api.customer_dues.create_payment_entry", return_value="PE-0001")
	@patch("pos_next.api.customer_dues.frappe.get_all")
	@patch("pos_next.api.customer_dues.frappe.db.savepoint")
	@patch("pos_next.api.customer_dues.frappe.has_permission", return_value=True)
	def test_invoice_param_restricts_allocation_to_one_invoice(
		self, _perm, _savepoint, mock_get_all, mock_create_pe, _balance,
	):
		# Customer has three outstanding invoices; only INV-0002 should be touched.
		mock_get_all.return_value = [{"name": "INV-0002", "outstanding_amount": 100}]

		result = customer_dues.pay_customer_due(
			customer="CUST-A",
			payments=[{"mode_of_payment": "Cash", "amount": 100}],
			invoice="INV-0002",
		)

		# The invoices query was filtered to the single named invoice.
		due_filters = mock_get_all.call_args.kwargs["filters"]
		self.assertEqual(due_filters["name"], "INV-0002")

		# Only one Payment Entry, against the chosen invoice.
		self.assertEqual(mock_create_pe.call_count, 1)
		self.assertEqual(mock_create_pe.call_args.kwargs["invoice_name"], "INV-0002")
		self.assertEqual(len(result["allocations"]), 1)
		self.assertEqual(result["allocations"][0]["invoice"], "INV-0002")

	@patch("pos_next.api.customer_dues.frappe.throw", side_effect=RuntimeError("no outstanding"))
	@patch("pos_next.api.customer_dues.frappe.get_all", return_value=[])
	@patch("pos_next.api.customer_dues.frappe.has_permission", return_value=True)
	def test_invoice_param_with_no_balance_raises(self, _perm, _get_all, _throw):
		with self.assertRaisesRegex(RuntimeError, "no outstanding"):
			customer_dues.pay_customer_due(
				customer="CUST-A",
				payments=[{"mode_of_payment": "Cash", "amount": 100}],
				invoice="INV-0002",
			)
