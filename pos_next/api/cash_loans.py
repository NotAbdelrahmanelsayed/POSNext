# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""
POS Cash Loan API

Thin POS-side wrapper around easy_entry's Cash Loan ledger. pos_next never
builds its own accounting for this -- it validates shift/profile rules
(mirrors pos_next/api/expenses.py) and delegates the actual Journal Entry /
Payment Entry work to easy_entry.api.cash_loan.give_loan / get_customer_loan_dues.

Degrades gracefully when easy_entry is not installed: every function here
returns the "no cash loans" shape instead of raising. bootstrap.py already
forces posa_allow_cash_loan to False client-side when easy_entry is absent,
so the POS button stays hidden, not just disabled.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt

from pos_next.api.expenses import validate_mode_of_payment, validate_open_shift


def _easy_entry_installed():
	return "easy_entry" in frappe.get_installed_apps()


def _require_easy_entry():
	if not _easy_entry_installed():
		frappe.throw(_("Cash loans require the easy_entry app to be installed."))


@frappe.whitelist()
def get_loan_dialog_data(pos_profile, pos_opening_shift):
	"""Return payment methods and shift loan totals for the cash loan dialog."""
	if not _easy_entry_installed():
		return {
			"payment_methods": [],
			"maximum_loan_amount": 0,
			"shift_loan_total": 0,
			"remaining_loan_amount": 0,
			"currency": frappe.defaults.get_global_default("currency") or "EGP",
		}

	validate_cash_loan_enabled(pos_profile)
	shift = validate_open_shift(pos_opening_shift, pos_profile)

	from pos_next.api.pos_profile import get_payment_methods

	maximum_loan_amount = flt(frappe.db.get_value("POS Profile", pos_profile, "posa_maximum_loan_amount"))
	shift_loan_total = get_shift_loan_total(pos_opening_shift)
	remaining_loan_amount = _get_remaining_shift_loan_amount(maximum_loan_amount, shift_loan_total)

	return {
		"payment_methods": get_payment_methods(pos_profile),
		"maximum_loan_amount": maximum_loan_amount,
		"shift_loan_total": shift_loan_total,
		"remaining_loan_amount": remaining_loan_amount,
		"currency": frappe.get_cached_value("Company", shift.company, "default_currency"),
	}


@frappe.whitelist()
def create_pos_cash_loan(pos_opening_shift, pos_profile, customer, amount, mode_of_payment, remarks=None):
	"""Give cash to a customer as a loan; the ledger entry is easy_entry's job."""
	_require_easy_entry()

	amount = flt(amount)
	customer = cstr(customer).strip()
	remarks = (remarks or "").strip()

	validate_cash_loan_enabled(pos_profile)
	shift = validate_open_shift(pos_opening_shift, pos_profile)
	validate_cash_loan_amount(amount, pos_profile, pos_opening_shift)
	validate_mode_of_payment(mode_of_payment, pos_profile, shift.company)

	if not customer:
		frappe.throw(_("Customer is required"))
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} does not exist").format(customer))

	from easy_entry.api.cash_loan import give_loan

	result = give_loan(
		borrower=customer,
		amount=amount,
		mode_of_payment=mode_of_payment,
		company=shift.company,
		remarks=remarks or None,
		pos_opening_shift=pos_opening_shift,
		pos_profile=pos_profile,
	)

	return {
		"name": result["name"],
		"journal_entry": result["journal_entry"],
		"amount": amount,
		"message": _("Cash loan recorded in Journal Entry {0}").format(result["journal_entry"]),
	}


def validate_cash_loan_enabled(pos_profile):
	if not pos_profile:
		frappe.throw(_("POS Profile is required"))

	if not frappe.db.get_value("POS Profile", pos_profile, "posa_allow_cash_loan"):
		frappe.throw(
			_("Cash Loan is not enabled for POS Profile {0}").format(frappe.bold(pos_profile)),
			title=_("Cash Loan Disabled"),
		)


def validate_cash_loan_amount(amount, pos_profile, pos_opening_shift=None):
	if flt(amount) <= 0:
		frappe.throw(_("Amount must be greater than zero"))

	maximum_amount = flt(frappe.db.get_value("POS Profile", pos_profile, "posa_maximum_loan_amount"))
	if maximum_amount <= 0:
		return

	shift_total = get_shift_loan_total(pos_opening_shift) if pos_opening_shift else 0
	new_shift_total = shift_total + flt(amount)
	if new_shift_total > maximum_amount:
		remaining = _get_remaining_shift_loan_amount(maximum_amount, shift_total)
		frappe.throw(
			_(
				"This loan would exceed the shift loan limit of {0}. "
				"Lent this shift: {1}. Remaining allowance: {2}"
			).format(
				frappe.format_value(maximum_amount, {"fieldtype": "Currency"}),
				frappe.format_value(shift_total, {"fieldtype": "Currency"}),
				frappe.format_value(remaining, {"fieldtype": "Currency"}),
			),
			title=_("Shift Loan Limit Exceeded"),
		)


def get_shift_loan_total(pos_opening_shift):
	"""Total submitted cash-loan amount given out this opening shift."""
	if not pos_opening_shift or not frappe.db.has_column("Journal Entry", "posa_is_cash_loan"):
		return 0

	total = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(posa_loan_amount), 0)
		FROM `tabJournal Entry`
		WHERE posa_is_cash_loan = 1
		  AND posa_pos_opening_shift = %s
		  AND docstatus = 1
		""",
		pos_opening_shift,
	)
	return flt(total[0][0] if total else 0)


def _get_remaining_shift_loan_amount(maximum_amount, shift_loan_total):
	if flt(maximum_amount) <= 0:
		return 0
	return max(0, flt(maximum_amount) - flt(shift_loan_total))


def get_shift_cash_loans(pos_opening_shift):
	"""Submitted cash-loan Journal Entries for a shift.

	Server-internal (not whitelisted) -- the twin of expenses.get_pos_expenses,
	used by pos_closing_shift.make_closing_shift_from_opening to reduce
	expected cash for the drawer reconciliation.
	"""
	if not frappe.db.has_column("Journal Entry", "posa_is_cash_loan"):
		return []

	loans = frappe.get_all(
		"Journal Entry",
		filters={
			"posa_is_cash_loan": 1,
			"posa_pos_opening_shift": pos_opening_shift,
			"docstatus": 1,
		},
		fields=["name", "posa_loan_amount", "posa_loan_mode_of_payment", "user_remark"],
		order_by="creation asc",
	)

	rows = []
	for loan in loans:
		# The borrower lives on the JE's party-tagged debit row, not a posa_* field.
		party = frappe.db.get_value(
			"Journal Entry Account",
			{"parent": loan.name, "party_type": "Customer"},
			"party",
		)
		customer_name = frappe.db.get_value("Customer", party, "customer_name") if party else None
		rows.append(
			frappe._dict(
				name=loan.name,
				journal_entry=loan.name,
				customer=party,
				customer_name=customer_name or party,
				amount=flt(loan.posa_loan_amount),
				mode_of_payment=loan.posa_loan_mode_of_payment,
				remarks=(loan.user_remark or "").strip(),
			)
		)
	return rows


@frappe.whitelist()
def get_customer_loans(customer, company=None):
	"""Open loan balance for a customer -- the single call every credit/AR
	surface in pos_next uses. Returns the empty shape when easy_entry is
	absent, so callers never need their own installed-app guard."""
	if not customer or not _easy_entry_installed():
		return {"total_outstanding": 0, "loans": []}

	from easy_entry.api.cash_loan import get_customer_loan_dues

	return get_customer_loan_dues(customer, company)
