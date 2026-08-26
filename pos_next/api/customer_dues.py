# Copyright (c) 2025, BrainWise and contributors
# For license information, please see license.txt

"""
Customer Dues API

Provides a full account statement for a customer and FIFO lump-sum payment.
Reuses enrich_invoice_with_payment_history and create_payment_entry from
partial_payments.py and get_customer_balance from credit_sales.py.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

from pos_next.api.credit_sales import get_customer_balance
from pos_next.api.partial_payments import (
	AMOUNT_TOLERANCE,
	create_loan_payment_entry,
	create_payment_entry,
	enrich_invoice_with_payment_history,
)

# Fields fetched for due invoices (enriched with payment history)
_DUE_FIELDS = [
	"name",
	"posting_date",
	"posting_time",
	"due_date",
	"customer",
	"customer_name",
	"grand_total",
	"outstanding_amount",
	"status",
	"currency",
	"is_return",
	"return_against",
]

# Fields fetched for settled/return invoices (no payment-ledger enrichment)
_SETTLED_FIELDS = [
	"name",
	"posting_date",
	"posting_time",
	"customer",
	"customer_name",
	"grand_total",
	"outstanding_amount",
	"status",
	"currency",
	"is_return",
	"return_against",
]


@frappe.whitelist()
def get_customer_due_statement(customer, pos_profile=None, company=None, limit=100):
	"""
	Return a complete account statement for *customer*.

	Args:
		customer: Customer ID
		pos_profile: Optional POS Profile name — used to resolve company when company is omitted
		company: Optional Company filter; resolved from pos_profile when absent
		limit: Max rows for settled/return invoices (default 100)

	Returns:
		{
		    summary: {total_outstanding, total_credit, net_balance,
		              total_paid, total_returned, due_count, settled_count},
		    due_invoices: [...],     # outstanding > 0, oldest first; enriched with payment history
		    settled_invoices: [...], # outstanding <= 0 or is_return, recent first; capped
		    currency: str,
		}
	"""
	if not customer:
		frappe.throw(_("Customer is required"))

	if not frappe.has_permission("Sales Invoice", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} does not exist").format(customer))

	# Resolve company
	if not company and pos_profile:
		company = frappe.db.get_value("POS Profile", pos_profile, "company")

	# ── Summary ──────────────────────────────────────────────────────────────
	# total_outstanding stays invoice-only on purpose: repointing it would
	# silently change the pay_customer_due overpay guard and several UI
	# computeds that were written against "invoices only". Cash loan debt is
	# additive, in total_loans / total_due.
	balance = get_customer_balance(customer, company)
	from pos_next.api.cash_loans import get_customer_loans

	loan_dues = get_customer_loans(customer, company)
	summary = {
		"total_outstanding": balance["total_outstanding"],
		"total_credit": balance["total_credit"],
		"net_balance": balance["net_balance"],
		"total_loans": flt(loan_dues["total_outstanding"]),
	}
	summary["total_due"] = summary["total_outstanding"] + summary["total_loans"]

	# ── Due invoices (oldest first = FIFO display order) ─────────────────────
	due_filters = {
		"customer": customer,
		"docstatus": 1,
		"is_return": 0,
		"outstanding_amount": [">", 0],
	}
	if company:
		due_filters["company"] = company

	due_invoices = frappe.get_all(
		"Sales Invoice",
		filters=due_filters,
		fields=_DUE_FIELDS,
		order_by="posting_date asc, creation asc",
	)

	# Enrich with payment history (payment ledger = source of truth)
	for inv in due_invoices:
		enrich_invoice_with_payment_history(inv)

	# A return is a separate statement component. Only count submitted returns
	# explicitly linked to invoices which are still outstanding.
	due_invoice_names = [inv["name"] for inv in due_invoices]
	total_returned = _get_linked_return_amount(customer, due_invoice_names, company)

	# ── Settled / return invoices (recent first, capped) ─────────────────────
	settled_filters = {
		"customer": customer,
		"docstatus": 1,
	}
	if company:
		settled_filters["company"] = company

	settled_invoices = frappe.get_all(
		"Sales Invoice",
		filters=settled_filters,
		fields=_SETTLED_FIELDS,
		order_by="posting_date desc, creation desc",
		limit=int(limit),
		or_filters={
			"outstanding_amount": ["<=", 0],
			"is_return": 1,
		},
	)

	# ── Batch-fetch items for all invoices (avoids N+1) ─────────────────────
	all_names = [inv["name"] for inv in due_invoices] + [inv["name"] for inv in settled_invoices]
	if all_names:
		rows = frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": ["in", all_names]},
			fields=["parent", "item_code", "item_name", "qty", "rate", "amount", "uom"],
		)
		items_by_invoice = {}
		for row in rows:
			items_by_invoice.setdefault(row["parent"], []).append(row)
		for inv in due_invoices + settled_invoices:
			inv["items"] = items_by_invoice.get(inv["name"], [])

	# Keep the statement total aligned with the item aggregation used by the
	# browser printout and downloadable image. Fall back to invoice totals for
	# legacy/malformed invoices with no item rows.
	total = sum(
		flt(item.get("amount"))
		for inv in due_invoices
		for item in inv.get("items", [])
	)
	if not total and due_invoices:
		total = sum(flt(inv.get("grand_total")) for inv in due_invoices)

	paid, total_returned = _get_statement_breakdown(
		total,
		summary["total_outstanding"],
		total_returned,
	)
	summary["total_paid"] = flt(paid)
	summary["total_returned"] = flt(total_returned)

	# ── Currency (from first invoice or company default) ─────────────────────
	currency = (
		(due_invoices or settled_invoices or [{}])[0].get("currency")
		or frappe.db.get_value("Company", company, "default_currency")
		or "USD"
	)

	summary["due_count"] = len(due_invoices)
	summary["settled_count"] = len(settled_invoices)

	return {
		"summary": summary,
		"due_invoices": due_invoices,
		"settled_invoices": settled_invoices,
		"loans": loan_dues["loans"],
		"currency": currency,
	}


def _get_linked_return_amount(customer, due_invoice_names, company=None):
	"""Return the absolute value of submitted returns linked to due invoices."""
	if not due_invoice_names:
		return 0.0

	filters = {
		"customer": customer,
		"docstatus": 1,
		"is_return": 1,
		"return_against": ["in", due_invoice_names],
	}
	if company:
		filters["company"] = company

	returns = frappe.get_all("Sales Invoice", filters=filters, fields=["grand_total"])
	return sum(abs(flt(row.get("grand_total"))) for row in returns)


def _get_statement_breakdown(total, remaining, returned):
	"""Split a statement reduction into actual payments and linked returns."""
	returned = flt(returned)
	paid = max(0, flt(total) - flt(remaining) - returned)
	if paid < AMOUNT_TOLERANCE:
		paid = 0.0
	if returned < AMOUNT_TOLERANCE:
		returned = 0.0
	return flt(paid), flt(returned)


def _get_loan_outstanding_by_customer(company=None):
	"""{customer: live outstanding balance} for every open/partially-repaid Cash
	Loan, company-wide. Empty dict when easy_entry isn't installed."""
	if "easy_entry" not in frappe.get_installed_apps():
		return {}

	from easy_entry.api.cash_loan import get_loan_outstanding

	filters = {"status": ["!=", "Repaid"]}
	if company:
		filters["company"] = company

	loans = frappe.get_all("Cash Loan", filters=filters, fields=["name", "borrower"])

	totals = {}
	for loan in loans:
		outstanding = flt(get_loan_outstanding(loan.name))
		if outstanding <= 0:
			continue
		totals[loan.borrower] = totals.get(loan.borrower, 0.0) + outstanding
	return totals


@frappe.whitelist()
def get_credit_customers_summary(pos_profile=None, company=None):
	"""
	Aggregate "who owes the shop money" across all company customers.

	Mirrors the math in credit_sales.get_customer_balance but GROUP BY customer:
	- regular (is_return=0) positive outstanding_amount → total_outstanding
	- return  (is_return=1) outstanding_amount < 0      → Abs summed as total_credit
	- net_balance = total_outstanding - total_credit

	Only customers with net_balance > 0 are returned, sorted by net_balance desc.

	Args:
		pos_profile: Optional POS Profile — used to resolve company when company is omitted
		company: Optional Company filter; resolved from pos_profile when absent

	Returns:
		{
		    customers: [{customer, customer_name, total_outstanding,
		                 total_credit, net_balance, due_count}, ...],
		    totals: {net_balance, customer_count},
		    currency: str,
		}
	"""
	if not frappe.has_permission("Sales Invoice", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	# Resolve company
	if not company and pos_profile:
		company = frappe.db.get_value("POS Profile", pos_profile, "company")

	try:
		from frappe.query_builder import DocType
		from frappe.query_builder.functions import Abs, Coalesce, Max, Sum
		from pypika import Case

		SalesInvoice = DocType("Sales Invoice")

		base_filters = SalesInvoice.docstatus == 1
		if company:
			base_filters = base_filters & (SalesInvoice.company == company)

		# Regular invoices: positive outstanding (what customer owes) + due count.
		# Group by customer only (not customer_name) — customer_name can differ across
		# invoices when the customer record was renamed, which would create duplicate rows
		# and cause the credit subtraction to be applied multiple times, pushing
		# some customers' net_balance to ≤ 0 and hiding them from the list.
		regular_query = (
			frappe.qb.from_(SalesInvoice)
			.select(
				SalesInvoice.customer,
				Max(SalesInvoice.customer_name).as_("customer_name"),
				Coalesce(
					Sum(
						Case()
						.when(SalesInvoice.outstanding_amount > 0, SalesInvoice.outstanding_amount)
						.else_(0)
					),
					0,
				).as_("total_outstanding"),
				Coalesce(
					Sum(Case().when(SalesInvoice.outstanding_amount > 0, 1).else_(0)),
					0,
				).as_("due_count"),
			)
			.where(base_filters & (SalesInvoice.is_return == 0))
			.groupby(SalesInvoice.customer)
		)

		# Return invoices: only negative outstanding counts as credit (no cash refund)
		return_query = (
			frappe.qb.from_(SalesInvoice)
			.select(
				SalesInvoice.customer,
				Coalesce(Sum(Abs(SalesInvoice.outstanding_amount)), 0).as_("total_credit"),
			)
			.where(
				base_filters
				& (SalesInvoice.is_return == 1)
				& (SalesInvoice.outstanding_amount < 0)
			)
			.groupby(SalesInvoice.customer)
		)

		regular_rows = regular_query.run(as_dict=True)
		return_rows = return_query.run(as_dict=True)

		credit_by_customer = {r.customer: flt(r.total_credit) for r in return_rows}

		# Cash loans (easy_entry) -- per-customer outstanding, merged in below.
		# Returns {} when easy_entry is absent.
		loan_by_customer = _get_loan_outstanding_by_customer(company)

		customers_by_id = {}
		for r in regular_rows:
			total_outstanding = flt(r.total_outstanding)
			total_credit = credit_by_customer.get(r.customer, 0.0)
			loan_outstanding = loan_by_customer.pop(r.customer, 0.0)
			net_balance = total_outstanding + loan_outstanding - total_credit
			if net_balance <= 0 and total_outstanding <= 0:
				# No unpaid invoices and no outstanding loan -- skip entirely.
				# (Deliberately not gated on total_outstanding alone: that would
				# hide a customer who owes only a loan, with no invoices at all.)
				continue
			customers_by_id[r.customer] = {
				"customer": r.customer,
				"customer_name": r.customer_name or r.customer,
				"total_outstanding": total_outstanding,
				"total_credit": total_credit,
				"total_loans": loan_outstanding,
				"net_balance": net_balance,
				"due_count": int(r.due_count or 0),
			}

		# Customers left in loan_by_customer have a loan but zero Sales Invoices
		# at all -- regular_query's GROUP BY never produced a row for them.
		for cust, loan_outstanding in loan_by_customer.items():
			if loan_outstanding <= 0:
				continue
			customer_name = frappe.db.get_value("Customer", cust, "customer_name") or cust
			customers_by_id[cust] = {
				"customer": cust,
				"customer_name": customer_name,
				"total_outstanding": 0.0,
				"total_credit": 0.0,
				"total_loans": loan_outstanding,
				"net_balance": loan_outstanding,
				"due_count": 0,
			}

		customers = list(customers_by_id.values())

		# Sort: customers who owe net (net_balance > 0) first, then by outstanding amount
		customers.sort(key=lambda c: (-c["net_balance"], -c["total_outstanding"]))

		# Totals reflect only what customers owe net (positive net_balance)
		net_total = sum(c["net_balance"] for c in customers if c["net_balance"] > 0)

		currency = (
			(frappe.db.get_value("Company", company, "default_currency") if company else None)
			or frappe.db.get_default("currency")
			or "USD"
		)

		return {
			"customers": customers,
			"totals": {"net_balance": net_total, "customer_count": len(customers)},
			"currency": currency,
		}

	except Exception:
		frappe.log_error(
			title="Credit Customers Summary Error",
			message=f"pos_profile: {pos_profile}, company: {company}\n{frappe.get_traceback()}",
		)
		raise


def _get_due_loan_docs(customer, company=None):
	"""Open/partially-repaid Cash Loan JEs for a customer, in the same
	{doctype, name, posting_date, creation, outstanding} shape as a Sales
	Invoice row, for the unified FIFO walk in pay_customer_due. Empty list
	when easy_entry isn't installed."""
	if "easy_entry" not in frappe.get_installed_apps():
		return []

	from easy_entry.api.cash_loan import get_loan_outstanding

	filters = {"borrower": customer, "status": ["!=", "Repaid"]}
	if company:
		filters["company"] = company

	loans = frappe.get_all(
		"Cash Loan",
		filters=filters,
		fields=["name", "journal_entry_give", "loan_date", "creation"],
		order_by="loan_date asc, creation asc",
	)

	docs = []
	for loan in loans:
		if not loan.journal_entry_give:
			continue
		outstanding = flt(get_loan_outstanding(loan.name))
		if outstanding <= AMOUNT_TOLERANCE:
			continue
		docs.append(
			{
				"doctype": "Journal Entry",
				"name": loan.journal_entry_give,
				"posting_date": loan.loan_date,
				"creation": loan.creation,
				"outstanding": outstanding,
			}
		)
	return docs


@frappe.whitelist()
def pay_customer_due(
	customer,
	payments,
	pos_profile=None,
	pos_opening_shift=None,
	company=None,
	invoice=None,
):
	"""
	Lump-sum payment across a customer's outstanding invoices (and, unless
	scoped to one invoice, open cash loans), FIFO by default.

	payments: JSON list [{mode_of_payment, amount, account?}]
	invoice: optional Sales Invoice name. When given, allocation is restricted to that
		single invoice instead of walking every outstanding invoice or loan — defense
		in depth so this endpoint can never be reached with single-invoice intent
		(e.g. bug-033's "Pay" on one row) and touch anything else.

	Returns:
		{
		    success: bool,
		    payment_entries_created: int,
		    allocations: [{invoice, mode_of_payment, amount}],
		    summary: <fresh get_customer_balance result>,
		}
	"""
	if not customer:
		frappe.throw(_("Customer is required"))

	if not frappe.has_permission("Sales Invoice", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	# Parse payments
	if isinstance(payments, str):
		try:
			payments = json.loads(payments)
		except json.JSONDecodeError:
			frappe.throw(_("Invalid payments payload: malformed JSON"))

	if not isinstance(payments, list) or not payments:
		frappe.throw(_("At least one payment is required"))

	# Resolve company
	if not company and pos_profile:
		company = frappe.db.get_value("POS Profile", pos_profile, "company")

	# Fetch outstanding invoices oldest-first (FIFO)
	due_filters = {
		"customer": customer,
		"docstatus": 1,
		"is_return": 0,
		"outstanding_amount": [">", 0],
	}
	if company:
		due_filters["company"] = company
	if invoice:
		due_filters["name"] = invoice

	due_invoices = frappe.get_all(
		"Sales Invoice",
		filters=due_filters,
		fields=["name", "posting_date", "creation", "outstanding_amount"],
		order_by="posting_date asc, creation asc",
	)

	# Unified FIFO list: Sales Invoices + open Cash Loan JEs, oldest first.
	# invoice= scopes to that single Sales Invoice only -- loans never enter
	# the walk in that case (bug-033: a single-row "Pay" must never touch
	# anything but the row it was clicked on).
	due_docs = [
		{
			"doctype": "Sales Invoice",
			"name": inv["name"],
			"posting_date": inv["posting_date"],
			"creation": inv["creation"],
			"outstanding": flt(inv["outstanding_amount"]),
		}
		for inv in due_invoices
	]
	if not invoice:
		due_docs.extend(_get_due_loan_docs(customer, company))
	due_docs.sort(key=lambda d: (d["posting_date"], d["creation"]))

	if not due_docs:
		if invoice:
			frappe.throw(_("Invoice {0} has no outstanding balance for customer {1}").format(invoice, customer))
		frappe.throw(_("No outstanding invoices or loans found for customer {0}").format(customer))

	# Total payment vs total outstanding (invoices + loans)
	total_payment = sum(flt(p.get("amount", 0)) for p in payments)
	total_outstanding = sum(d["outstanding"] for d in due_docs)

	if total_payment > total_outstanding + AMOUNT_TOLERANCE:
		frappe.throw(
			_("Total payment {0} exceeds total outstanding {1}").format(
				frappe.format_value(total_payment, {"fieldtype": "Currency"}),
				frappe.format_value(total_outstanding, {"fieldtype": "Currency"}),
			)
		)

	# Savepoint-backed batch
	savepoint = "pay_customer_due_batch"
	allocations = []
	payment_entries_created = 0

	# Track remaining outstanding per document across payment modes
	doc_remaining = {d["name"]: d["outstanding"] for d in due_docs}
	doc_order = [(d["doctype"], d["name"]) for d in due_docs]

	try:
		frappe.db.savepoint(savepoint)

		for payment in payments:
			mode = payment.get("mode_of_payment", "Cash")
			account = payment.get("account")
			remaining_mode = flt(payment.get("amount", 0))

			if remaining_mode <= 0:
				continue

			for doctype, doc_name in doc_order:
				if remaining_mode <= AMOUNT_TOLERANCE:
					break
				doc_due = doc_remaining.get(doc_name, 0)
				if doc_due <= AMOUNT_TOLERANCE:
					continue

				alloc_amount = min(remaining_mode, doc_due)
				if doctype == "Sales Invoice":
					create_payment_entry(
						invoice_name=doc_name,
						amount=alloc_amount,
						mode_of_payment=mode,
						payment_account=account,
						pos_opening_shift=pos_opening_shift,
					)
				else:
					create_loan_payment_entry(
						journal_entry=doc_name,
						customer=customer,
						amount=alloc_amount,
						mode_of_payment=mode,
						payment_account=account,
						pos_opening_shift=pos_opening_shift,
					)
				allocations.append(
					{"invoice": doc_name, "mode_of_payment": mode, "amount": alloc_amount}
				)
				payment_entries_created += 1
				doc_remaining[doc_name] = doc_due - alloc_amount
				remaining_mode -= alloc_amount

	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise

	fresh_summary = get_customer_balance(customer, company)

	return {
		"success": True,
		"payment_entries_created": payment_entries_created,
		"allocations": allocations,
		"summary": fresh_summary,
	}
