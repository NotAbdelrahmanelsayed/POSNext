# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""
POS Cash Loan API

Records interest-free cash handed to a customer/person as a real receivable
(Journal Entry: Dr "Cash Loans Receivable", Cr the payment account) instead of
selling it as a POS Item, so it never inflates Gross Profit. Repayment reverses
the entry (Dr payment account, Cr "Cash Loans Receivable") and closes the loan.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, today

from pos_next.api.expenses import (
	_ensure_account_name,
	_resolve_payment_account,
	validate_mode_of_payment,
	validate_open_shift,
)

CASH_LOAN_ACCOUNT_NAME = "Cash Loans Receivable"


@frappe.whitelist()
def get_cash_loan_dialog_data(pos_profile, pos_opening_shift):
	"""Return payment methods and open loans for the cash loan dialog."""
	shift = validate_open_shift(pos_opening_shift, pos_profile)

	from pos_next.api.pos_profile import get_payment_methods

	return {
		"payment_methods": get_payment_methods(pos_profile),
		"outstanding_loans": get_outstanding_cash_loans(shift.company),
	}


@frappe.whitelist()
def create_cash_loan(
	pos_opening_shift,
	pos_profile,
	party_name,
	amount,
	mode_of_payment,
	remarks=None,
):
	"""Give cash to a person as a loan: Dr Cash Loans Receivable, Cr payment account."""
	amount = flt(amount)
	party_name = cstr(party_name).strip()
	remarks = (remarks or "").strip()

	shift = validate_open_shift(pos_opening_shift, pos_profile)
	validate_cash_loan_party(party_name)
	validate_cash_loan_amount(amount)
	validate_mode_of_payment(mode_of_payment, pos_profile, shift.company)

	cost_center = frappe.db.get_value("POS Profile", pos_profile, "cost_center")
	payment_account = _ensure_account_name(
		_resolve_payment_account(mode_of_payment, shift.company),
		_("Payment Account"),
	)
	loan_account = get_or_create_cash_loan_account(shift.company)

	journal_entry_name = _create_cash_loan_journal_entry(
		company=shift.company,
		loan_account=loan_account,
		payment_account=payment_account,
		amount=amount,
		cost_center=cost_center,
		pos_opening_shift=pos_opening_shift,
		pos_profile=pos_profile,
		mode_of_payment=mode_of_payment,
		party_name=party_name,
		remarks=remarks,
		status="Open",
		repayment_of=None,
	)

	return {
		"name": journal_entry_name,
		"journal_entry": journal_entry_name,
		"amount": amount,
		"message": _("Cash loan of {0} recorded for {1} in Journal Entry {2}").format(
			frappe.format_value(amount, {"fieldtype": "Currency"}),
			party_name,
			journal_entry_name,
		),
	}


@frappe.whitelist()
def repay_cash_loan(
	loan_journal_entry,
	pos_opening_shift,
	pos_profile,
	mode_of_payment,
	remarks=None,
):
	"""Receive a loan back in full: Dr payment account, Cr Cash Loans Receivable."""
	remarks = (remarks or "").strip()

	shift = validate_open_shift(pos_opening_shift, pos_profile)
	loan = validate_open_cash_loan(loan_journal_entry, shift.company)
	validate_mode_of_payment(mode_of_payment, pos_profile, shift.company)

	cost_center = frappe.db.get_value("POS Profile", pos_profile, "cost_center")
	payment_account = _ensure_account_name(
		_resolve_payment_account(mode_of_payment, shift.company),
		_("Payment Account"),
	)
	loan_account = get_or_create_cash_loan_account(shift.company)

	journal_entry_name = _create_cash_loan_journal_entry(
		company=shift.company,
		loan_account=loan_account,
		payment_account=payment_account,
		amount=loan.posa_cash_loan_amount,
		cost_center=cost_center,
		pos_opening_shift=pos_opening_shift,
		pos_profile=pos_profile,
		mode_of_payment=mode_of_payment,
		party_name=loan.posa_cash_loan_party_name,
		remarks=remarks,
		status="Repaid",
		repayment_of=loan.name,
		reverse=True,
	)

	frappe.db.set_value("Journal Entry", loan.name, "posa_cash_loan_status", "Repaid")

	return {
		"name": journal_entry_name,
		"journal_entry": journal_entry_name,
		"amount": loan.posa_cash_loan_amount,
		"message": _("Cash loan repayment of {0} from {1} recorded in Journal Entry {2}").format(
			frappe.format_value(loan.posa_cash_loan_amount, {"fieldtype": "Currency"}),
			loan.posa_cash_loan_party_name,
			journal_entry_name,
		),
	}


def validate_cash_loan_party(party_name):
	if not party_name:
		frappe.throw(_("Party name is required"))


def validate_cash_loan_amount(amount):
	if flt(amount) <= 0:
		frappe.throw(_("Amount must be greater than zero"))


def validate_open_cash_loan(loan_journal_entry, company):
	if not loan_journal_entry:
		frappe.throw(_("Loan is required"))

	loan = frappe.db.get_value(
		"Journal Entry",
		loan_journal_entry,
		[
			"name",
			"company",
			"docstatus",
			"posa_is_cash_loan",
			"posa_cash_loan_status",
			"posa_cash_loan_party_name",
			"posa_cash_loan_amount",
		],
		as_dict=True,
	)

	if not loan or not loan.posa_is_cash_loan or loan.docstatus != 1:
		frappe.throw(_("Cash loan {0} does not exist").format(loan_journal_entry))

	if loan.company != company:
		frappe.throw(_("Cash loan {0} does not belong to company {1}").format(loan_journal_entry, company))

	if loan.posa_cash_loan_status != "Open":
		frappe.throw(_("Cash loan {0} has already been repaid").format(loan_journal_entry))

	return loan


def get_or_create_cash_loan_account(company):
	"""Return the company's 'Cash Loans Receivable' asset account, creating it if missing."""
	account_name = frappe.db.get_value(
		"Account",
		{"company": company, "account_name": CASH_LOAN_ACCOUNT_NAME},
		"name",
	)
	if account_name:
		return account_name

	parent_account = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"account_name": ["like", "Current Assets%"],
			"is_group": 1,
			"root_type": "Asset",
		},
		"name",
	)
	if not parent_account:
		frappe.throw(
			_("Could not find a 'Current Assets' parent account for company {0} to create {1} under").format(
				company, CASH_LOAN_ACCOUNT_NAME
			)
		)

	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": CASH_LOAN_ACCOUNT_NAME,
			"parent_account": parent_account,
			"company": company,
			"is_group": 0,
			"root_type": "Asset",
			"report_type": "Balance Sheet",
		}
	)
	account.flags.ignore_permissions = True
	account.insert()

	return account.name


def get_outstanding_cash_loans(company):
	"""Return open (unrepaid) cash loan Journal Entries for a company."""
	loans = frappe.get_all(
		"Journal Entry",
		filters={
			"posa_is_cash_loan": 1,
			"posa_cash_loan_status": "Open",
			"company": company,
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

	return [
		frappe._dict(
			name=loan.name,
			journal_entry=loan.name,
			party_name=loan.posa_cash_loan_party_name,
			amount=flt(loan.posa_cash_loan_amount),
			posting_date=loan.posting_date,
			remarks=(loan.user_remark or "").strip(),
		)
		for loan in loans
	]


def _create_cash_loan_journal_entry(
	company,
	loan_account,
	payment_account,
	amount,
	cost_center,
	pos_opening_shift,
	pos_profile,
	mode_of_payment,
	party_name,
	remarks,
	status,
	repayment_of,
	reverse=False,
):
	if status == "Open":
		default_remark = _("Cash loan given to {0}").format(party_name)
	else:
		default_remark = _("Cash loan repaid by {0}").format(party_name)
	user_remark = remarks or default_remark

	loan_account = _ensure_account_name(loan_account, _("Cash Loans Receivable Account"))
	payment_account = _ensure_account_name(payment_account, _("Payment Account"))

	jv_doc = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"posting_date": today(),
			"company": company,
			"user_remark": user_remark,
			"cheque_no": pos_opening_shift,
			"cheque_date": today(),
			"posa_is_cash_loan": 1,
			"posa_cash_loan_status": status,
			"posa_cash_loan_party_name": party_name,
			"posa_cash_loan_amount": amount,
			"posa_cash_loan_mode_of_payment": mode_of_payment,
			"posa_cash_loan_pos_opening_shift": pos_opening_shift,
			"posa_cash_loan_pos_profile": pos_profile,
			"posa_cash_loan_repayment_of": repayment_of,
		}
	)

	loan_row = jv_doc.append("accounts", {})
	payment_row = jv_doc.append("accounts", {})

	if not reverse:
		loan_row.update(
			{
				"account": loan_account,
				"debit_in_account_currency": amount,
				"credit_in_account_currency": 0,
				"cost_center": cost_center,
			}
		)
		payment_row.update(
			{
				"account": payment_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": amount,
				"cost_center": cost_center,
			}
		)
	else:
		payment_row.update(
			{
				"account": payment_account,
				"debit_in_account_currency": amount,
				"credit_in_account_currency": 0,
				"cost_center": cost_center,
			}
		)
		loan_row.update(
			{
				"account": loan_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": amount,
				"cost_center": cost_center,
			}
		)

	jv_doc.flags.ignore_permissions = True
	jv_doc.insert()
	jv_doc.submit()

	return jv_doc.name
