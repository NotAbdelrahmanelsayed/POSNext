# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pos_next.api import cash_loans


def _raise_runtime_error(message, *args, **kwargs):
	raise RuntimeError(str(message))


class TestPOSCashLoans(unittest.TestCase):
	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	def test_validate_cash_loan_party_rejects_empty(self, _mock_throw):
		with self.assertRaisesRegex(RuntimeError, "Party name is required"):
			cash_loans.validate_cash_loan_party("")

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	def test_validate_cash_loan_amount_rejects_zero(self, _mock_throw):
		with self.assertRaisesRegex(RuntimeError, "greater than zero"):
			cash_loans.validate_cash_loan_amount(0)

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	@patch("pos_next.api.cash_loans.frappe.db.get_value", return_value=None)
	def test_validate_open_cash_loan_rejects_missing(self, _mock_get_value, _mock_throw):
		with self.assertRaisesRegex(RuntimeError, "does not exist"):
			cash_loans.validate_open_cash_loan("ACC-JV-0001", "Test Company")

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	@patch("pos_next.api.cash_loans.frappe.db.get_value")
	def test_validate_open_cash_loan_rejects_other_company(self, mock_get_value, _mock_throw):
		mock_get_value.return_value = SimpleNamespace(
			name="ACC-JV-0001",
			company="Other Company",
			docstatus=1,
			posa_is_cash_loan=1,
			posa_cash_loan_status="Open",
			posa_cash_loan_party_name="Ali",
			posa_cash_loan_amount=500,
		)

		with self.assertRaisesRegex(RuntimeError, "does not belong to company"):
			cash_loans.validate_open_cash_loan("ACC-JV-0001", "Test Company")

	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	@patch("pos_next.api.cash_loans.frappe.db.get_value")
	def test_validate_open_cash_loan_rejects_already_repaid(self, mock_get_value, _mock_throw):
		mock_get_value.return_value = SimpleNamespace(
			name="ACC-JV-0001",
			company="Test Company",
			docstatus=1,
			posa_is_cash_loan=1,
			posa_cash_loan_status="Repaid",
			posa_cash_loan_party_name="Ali",
			posa_cash_loan_amount=500,
		)

		with self.assertRaisesRegex(RuntimeError, "already been repaid"):
			cash_loans.validate_open_cash_loan("ACC-JV-0001", "Test Company")

	@patch("pos_next.api.cash_loans.frappe.db.get_value")
	def test_validate_open_cash_loan_returns_open_loan(self, mock_get_value):
		mock_get_value.return_value = SimpleNamespace(
			name="ACC-JV-0001",
			company="Test Company",
			docstatus=1,
			posa_is_cash_loan=1,
			posa_cash_loan_status="Open",
			posa_cash_loan_party_name="Ali",
			posa_cash_loan_amount=500,
		)

		loan = cash_loans.validate_open_cash_loan("ACC-JV-0001", "Test Company")

		self.assertEqual(loan.name, "ACC-JV-0001")
		self.assertEqual(loan.posa_cash_loan_amount, 500)

	@patch("pos_next.api.cash_loans.frappe.db.get_value")
	def test_get_or_create_cash_loan_account_reuses_existing(self, mock_get_value):
		mock_get_value.return_value = "Cash Loans Receivable - TC"

		account = cash_loans.get_or_create_cash_loan_account("Test Company")

		self.assertEqual(account, "Cash Loans Receivable - TC")

	@patch("pos_next.api.cash_loans.frappe.get_doc")
	@patch("pos_next.api.cash_loans.frappe.throw", side_effect=_raise_runtime_error)
	@patch("pos_next.api.cash_loans.frappe.db.get_value")
	def test_get_or_create_cash_loan_account_requires_current_assets_parent(
		self, mock_get_value, _mock_throw, mock_get_doc
	):
		mock_get_value.side_effect = [None, None]

		with self.assertRaisesRegex(RuntimeError, "Current Assets"):
			cash_loans.get_or_create_cash_loan_account("Test Company")

		mock_get_doc.assert_not_called()

	@patch("pos_next.api.cash_loans.frappe.format_value", side_effect=lambda value, _options: str(value))
	@patch("pos_next.api.cash_loans._create_cash_loan_journal_entry", return_value="ACC-JV-0002")
	@patch("pos_next.api.cash_loans.get_or_create_cash_loan_account", return_value="Cash Loans Receivable - TC")
	@patch("pos_next.api.cash_loans.validate_mode_of_payment")
	@patch("pos_next.api.cash_loans.validate_open_shift")
	@patch("pos_next.api.cash_loans._resolve_payment_account", return_value="Cash - TC")
	@patch("pos_next.api.cash_loans.frappe.db.get_value")
	def test_create_cash_loan_creates_journal_entry_only(
		self,
		mock_db_get_value,
		_mock_resolve_payment_account,
		mock_validate_shift,
		_mock_validate_mode,
		_mock_get_or_create_account,
		mock_create_je,
		_mock_format_value,
	):
		mock_validate_shift.return_value = SimpleNamespace(company="Test Company")
		mock_db_get_value.return_value = "Main - TC"

		result = cash_loans.create_cash_loan(
			"POS-OS-0001",
			"Test POS Profile",
			"Ali",
			500,
			"Cash",
			remarks="Loan for the day",
		)

		self.assertEqual(result["name"], "ACC-JV-0002")
		self.assertEqual(result["journal_entry"], "ACC-JV-0002")
		self.assertEqual(result["amount"], 500)
		mock_create_je.assert_called_once()

	@patch("pos_next.api.cash_loans.frappe.format_value", side_effect=lambda value, _options: str(value))
	@patch("pos_next.api.cash_loans.frappe.db.set_value")
	@patch("pos_next.api.cash_loans._create_cash_loan_journal_entry", return_value="ACC-JV-0003")
	@patch("pos_next.api.cash_loans.get_or_create_cash_loan_account", return_value="Cash Loans Receivable - TC")
	@patch("pos_next.api.cash_loans.validate_mode_of_payment")
	@patch("pos_next.api.cash_loans.validate_open_cash_loan")
	@patch("pos_next.api.cash_loans.validate_open_shift")
	@patch("pos_next.api.cash_loans._resolve_payment_account", return_value="Cash - TC")
	@patch("pos_next.api.cash_loans.frappe.db.get_value")
	def test_repay_cash_loan_creates_reversal_and_closes_loan(
		self,
		mock_db_get_value,
		_mock_resolve_payment_account,
		mock_validate_shift,
		mock_validate_loan,
		_mock_validate_mode,
		_mock_get_or_create_account,
		mock_create_je,
		mock_set_value,
		_mock_format_value,
	):
		mock_validate_shift.return_value = SimpleNamespace(company="Test Company")
		mock_validate_loan.return_value = SimpleNamespace(
			name="ACC-JV-0001",
			posa_cash_loan_party_name="Ali",
			posa_cash_loan_amount=500,
		)
		mock_db_get_value.return_value = "Main - TC"

		result = cash_loans.repay_cash_loan(
			"ACC-JV-0001",
			"POS-OS-0001",
			"Test POS Profile",
			"Cash",
		)

		self.assertEqual(result["name"], "ACC-JV-0003")
		self.assertEqual(result["amount"], 500)
		mock_create_je.assert_called_once()
		mock_set_value.assert_called_once_with(
			"Journal Entry", "ACC-JV-0001", "posa_cash_loan_status", "Repaid"
		)

	@patch("pos_next.api.cash_loans.frappe.get_all")
	def test_get_outstanding_cash_loans_reads_journal_entries(self, mock_get_all):
		mock_get_all.return_value = [
			SimpleNamespace(
				name="ACC-JV-0001",
				posa_cash_loan_party_name="Ali",
				posa_cash_loan_amount=500,
				posting_date="2026-08-04",
				user_remark="Loan for the day",
			)
		]

		result = cash_loans.get_outstanding_cash_loans("Test Company")

		self.assertEqual(result[0].journal_entry, "ACC-JV-0001")
		self.assertEqual(result[0].party_name, "Ali")
		self.assertEqual(result[0].amount, 500)
		mock_get_all.assert_called_once_with(
			"Journal Entry",
			filters={
				"posa_is_cash_loan": 1,
				"posa_cash_loan_status": "Open",
				"company": "Test Company",
				"docstatus": 1,
			},
			fields=[
				"name",
				"posa_cash_loan_party_name",
				"posa_cash_loan_amount",
				"posting_date",
				"user_remark",
			],
			order_by="creation asc",
			ignore_permissions=True,
		)
