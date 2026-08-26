# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pos_next.api import cash_loans


def _raise_runtime_error(message, *args, **kwargs):
	raise RuntimeError(str(message))


class TestPOSCashLoans(unittest.TestCase):
	"""Unit tests for the pos_next POS-side wrapper. The actual ledger entry
	(Journal Entry / Payment Entry) is easy_entry's job -- see
	easy_entry/api/test_cash_loan.py for the accounting-correctness tests."""

	# -- validate_cash_loan_enabled -------------------------------------------

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	def test_validate_cash_loan_enabled_requires_profile(self, _mock_throw):
		with self.assertRaisesRegex(RuntimeError, "POS Profile is required"):
			cash_loans.validate_cash_loan_enabled(None)

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	@patch("pos_next.api.cash_loans.frappe.db.get_value", return_value=0)
	def test_validate_cash_loan_enabled_rejects_disabled_profile(self, _mock_get_value, _mock_throw):
		with self.assertRaisesRegex(RuntimeError, "not enabled"):
			cash_loans.validate_cash_loan_enabled("Test POS Profile")

	@patch("pos_next.api.cash_loans.frappe.db.get_value", return_value=1)
	def test_validate_cash_loan_enabled_passes_when_allowed(self, _mock_get_value):
		cash_loans.validate_cash_loan_enabled("Test POS Profile")  # must not raise

	# -- validate_cash_loan_amount ---------------------------------------------

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	def test_validate_cash_loan_amount_rejects_zero(self, _mock_throw):
		with self.assertRaisesRegex(RuntimeError, "greater than zero"):
			cash_loans.validate_cash_loan_amount(0, "Test POS Profile")

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	@patch("pos_next.api.cash_loans.frappe.format_value", side_effect=lambda value, _options: str(value))
	@patch("pos_next.api.cash_loans.get_shift_loan_total", return_value=400)
	@patch("pos_next.api.cash_loans.frappe.db.get_value", return_value=500)
	def test_validate_cash_loan_amount_rejects_over_shift_cap(
		self, _mock_get_value, _mock_shift_total, _mock_format_value, _mock_throw
	):
		# cap=500, already lent 400 this shift -> a further 200 exceeds the cap
		with self.assertRaisesRegex(RuntimeError, "exceed the shift loan limit"):
			cash_loans.validate_cash_loan_amount(200, "Test POS Profile", "POS-OS-0001")

	@patch("pos_next.api.cash_loans.get_shift_loan_total", return_value=100)
	@patch("pos_next.api.cash_loans.frappe.db.get_value", return_value=500)
	def test_validate_cash_loan_amount_allows_within_cap(self, _mock_get_value, _mock_shift_total):
		cash_loans.validate_cash_loan_amount(200, "Test POS Profile", "POS-OS-0001")  # must not raise

	@patch("pos_next.api.cash_loans.frappe.db.get_value", return_value=0)
	def test_validate_cash_loan_amount_no_cap_means_unlimited(self, _mock_get_value):
		cash_loans.validate_cash_loan_amount(1_000_000, "Test POS Profile")  # must not raise

	# -- get_shift_loan_total ---------------------------------------------------

	@patch("pos_next.api.cash_loans.frappe.db.has_column", return_value=False)
	def test_get_shift_loan_total_zero_when_column_absent(self, _mock_has_column):
		self.assertEqual(cash_loans.get_shift_loan_total("POS-OS-0001"), 0)

	def test_get_shift_loan_total_zero_when_no_shift(self):
		self.assertEqual(cash_loans.get_shift_loan_total(None), 0)

	@patch("pos_next.api.cash_loans.frappe.db.has_column", return_value=True)
	@patch("pos_next.api.cash_loans.frappe.db.sql", return_value=[[350]])
	def test_get_shift_loan_total_sums_submitted_loans(self, _mock_sql, _mock_has_column):
		self.assertEqual(cash_loans.get_shift_loan_total("POS-OS-0001"), 350)

	# -- create_pos_cash_loan: delegates to easy_entry, never builds its own JE -

	@patch("pos_next.api.cash_loans.frappe.db.exists", return_value=True)
	@patch("pos_next.api.cash_loans.validate_mode_of_payment")
	@patch("pos_next.api.cash_loans.validate_cash_loan_amount")
	@patch("pos_next.api.cash_loans.validate_cash_loan_enabled")
	@patch("pos_next.api.cash_loans.validate_open_shift")
	@patch("pos_next.api.cash_loans._require_easy_entry")
	def test_create_pos_cash_loan_delegates_to_easy_entry(
		self,
		_mock_require,
		mock_validate_shift,
		_mock_validate_enabled,
		_mock_validate_amount,
		_mock_validate_mode,
		_mock_exists,
	):
		mock_validate_shift.return_value = SimpleNamespace(company="Test Company")

		with patch("easy_entry.api.cash_loan.give_loan") as mock_give_loan:
			mock_give_loan.return_value = {"ok": True, "name": "CL-00042", "journal_entry": "ACC-JV-0002"}

			result = cash_loans.create_pos_cash_loan(
				"POS-OS-0001", "Test POS Profile", "CUST-0001", 500, "Cash", remarks="For the day"
			)

		mock_give_loan.assert_called_once_with(
			borrower="CUST-0001",
			amount=500,
			mode_of_payment="Cash",
			company="Test Company",
			remarks="For the day",
			pos_opening_shift="POS-OS-0001",
			pos_profile="Test POS Profile",
		)
		self.assertEqual(result["name"], "CL-00042")
		self.assertEqual(result["journal_entry"], "ACC-JV-0002")

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	@patch("pos_next.api.cash_loans._easy_entry_installed", return_value=False)
	def test_create_pos_cash_loan_requires_easy_entry(self, _mock_installed, _mock_throw):
		with self.assertRaisesRegex(RuntimeError, "easy_entry"):
			cash_loans.create_pos_cash_loan("POS-OS-0001", "Test POS Profile", "CUST-0001", 500, "Cash")

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	@patch("pos_next.api.cash_loans.frappe.db.exists", return_value=False)
	@patch("pos_next.api.cash_loans.validate_mode_of_payment")
	@patch("pos_next.api.cash_loans.validate_cash_loan_amount")
	@patch("pos_next.api.cash_loans.validate_cash_loan_enabled")
	@patch("pos_next.api.cash_loans.validate_open_shift")
	@patch("pos_next.api.cash_loans._require_easy_entry")
	def test_create_pos_cash_loan_rejects_missing_customer(
		self,
		_mock_require,
		mock_validate_shift,
		_mock_validate_enabled,
		_mock_validate_amount,
		_mock_validate_mode,
		_mock_exists,
		_mock_throw,
	):
		mock_validate_shift.return_value = SimpleNamespace(company="Test Company")
		with self.assertRaisesRegex(RuntimeError, "does not exist"):
			cash_loans.create_pos_cash_loan(
				"POS-OS-0001", "Test POS Profile", "CUST-NOPE", 500, "Cash"
			)

	# -- get_shift_cash_loans: server-internal, drawer reconciliation ----------

	@patch("pos_next.api.cash_loans.frappe.db.has_column", return_value=False)
	def test_get_shift_cash_loans_empty_when_column_absent(self, _mock_has_column):
		self.assertEqual(cash_loans.get_shift_cash_loans("POS-OS-0001"), [])

	@patch("pos_next.api.cash_loans.frappe.db.get_value")
	@patch("pos_next.api.cash_loans.frappe.get_all")
	@patch("pos_next.api.cash_loans.frappe.db.has_column", return_value=True)
	def test_get_shift_cash_loans_reads_party_from_je_account(
		self, _mock_has_column, mock_get_all, mock_get_value
	):
		mock_get_all.return_value = [
			SimpleNamespace(
				name="ACC-JV-0002",
				posa_loan_amount=500,
				posa_loan_mode_of_payment="Cash",
				user_remark="Loan for the day",
			)
		]
		# First get_value call resolves the party off Journal Entry Account,
		# second resolves the customer's display name.
		mock_get_value.side_effect = ["CUST-0001", "Ali"]

		result = cash_loans.get_shift_cash_loans("POS-OS-0001")

		self.assertEqual(len(result), 1)
		self.assertEqual(result[0].journal_entry, "ACC-JV-0002")
		self.assertEqual(result[0].customer, "CUST-0001")
		self.assertEqual(result[0].customer_name, "Ali")
		self.assertEqual(result[0].amount, 500)
		self.assertEqual(result[0].mode_of_payment, "Cash")

	# -- get_customer_loans: degrades gracefully without easy_entry ------------

	@patch("pos_next.api.cash_loans._easy_entry_installed", return_value=False)
	def test_get_customer_loans_empty_shape_when_easy_entry_absent(self, _mock_installed):
		result = cash_loans.get_customer_loans("CUST-0001")
		self.assertEqual(result, {"total_outstanding": 0, "loans": []})

	def test_get_customer_loans_empty_shape_when_no_customer(self):
		result = cash_loans.get_customer_loans(None)
		self.assertEqual(result, {"total_outstanding": 0, "loans": []})

	@patch("pos_next.api.cash_loans._easy_entry_installed", return_value=True)
	def test_get_customer_loans_delegates_to_easy_entry(self, _mock_installed):
		with patch("easy_entry.api.cash_loan.get_customer_loan_dues") as mock_dues:
			mock_dues.return_value = {"total_outstanding": 250, "loans": [{"name": "CL-00001"}]}
			result = cash_loans.get_customer_loans("CUST-0001", "Test Company")

		mock_dues.assert_called_once_with("CUST-0001", "Test Company")
		self.assertEqual(result["total_outstanding"], 250)
