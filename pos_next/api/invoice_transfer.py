# Copyright (c) 2025, BrainWise and contributors
# For license information, please see license.txt

"""
Invoice Customer Transfer API

Moves a submitted Sales Invoice from one customer to another by cancelling the
original and re-issuing it as an amended invoice under the new customer. This is
the only approach that keeps the GL, AR ageing and customer statements correct:
the new customer genuinely owns the invoice, and the outstanding balance moves
with it.

Preserved across the move: posting date/time, due date, items, rates, discounts,
taxes, POS profile and POS opening shift (so shift totals stay neutral - the
cancelled invoice drops out and the replacement takes its place).

Payments follow the invoice. POS payment rows (Sales Invoice Payment) travel with
the document itself; separately-created Payment Entries are cancelled and
re-created against the replacement via partial_payments.create_payment_entry.

Blocked cases (see check_invoice_transfer_eligibility): returns, invoices with a
submitted return against them, invoices paid with redeemed customer credit, and
consolidated POS invoices.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from pos_next.api.credit_sales import get_credit_redeem_remark
from pos_next.api.partial_payments import AMOUNT_TOLERANCE, create_payment_entry

# Fields shown to the UI in the eligibility pre-flight
_INVOICE_FIELDS = [
	"name",
	"customer",
	"customer_name",
	"posting_date",
	"due_date",
	"grand_total",
	"paid_amount",
	"outstanding_amount",
	"currency",
	"status",
	"docstatus",
	"is_return",
	"return_against",
	"is_pos",
	"pos_profile",
	"redeem_loyalty_points",
	"company",
]


# =============================================================================
# Eligibility
# =============================================================================


def _get_blocking_reason(invoice):
	"""Return (reason, message) if the invoice cannot be moved, else (None, None)."""
	if cint(invoice.docstatus) != 1:
		return (
			"not_submitted",
			_("Only submitted invoices can be moved to another customer."),
		)

	if cint(invoice.is_return):
		return (
			"is_return",
			_("This is a return invoice. Move the original invoice instead."),
		)

	if invoice.get("consolidated_invoice"):
		return (
			"consolidated",
			_("This invoice has been consolidated and can no longer be moved."),
		)

	linked_return = frappe.db.exists(
		"Sales Invoice",
		{"return_against": invoice.name, "docstatus": 1, "is_return": 1},
	)
	if linked_return:
		return (
			"has_return",
			_("Invoice {0} has a return against it ({1}). Cancel the return before moving it.").format(
				invoice.name, linked_return
			),
		)

	if cint(invoice.get("redeem_loyalty_points")):
		return (
			"used_loyalty_points",
			_(
				"Invoice {0} was partly paid with the customer's loyalty points, which cannot be "
				"transferred. Reverse the redemption first."
			).format(invoice.name),
		)

	credit_je = frappe.db.exists(
		"Journal Entry",
		{"docstatus": 1, "user_remark": get_credit_redeem_remark(invoice.name)},
	)
	if credit_je:
		return (
			"used_customer_credit",
			_(
				"Invoice {0} was paid using the customer's credit, which cannot be transferred. "
				"Reverse the credit redemption first."
			).format(invoice.name),
		)

	blocking_link = _get_blocking_link(invoice.name)
	if blocking_link:
		return (
			"linked_documents",
			_("Invoice {0} is linked to {1} {2}. Cancel that document before moving the invoice.").format(
				invoice.name, _(blocking_link["reference_doctype"]), blocking_link["reference_docname"]
			),
		)

	return None, None


def _get_blocking_link(invoice_name):
	"""Find a submitted document that would block cancellation of the invoice.

	Payment Entries are excluded - the transfer cancels and re-creates those
	itself, so they are not blockers.
	"""
	from frappe.model.delete_doc import get_linked_docs

	try:
		doc = frappe.get_doc("Sales Invoice", invoice_name)
		links = get_linked_docs(doc, "Cancel") or []
	except Exception:
		# Never let the pre-flight itself break the dialog; cancel() will still
		# raise a clear LinkExistsError if something really is linked.
		return None

	for link in links:
		# Both are handled by the transfer itself: Payment Entries are cancelled
		# and re-created, and the closing shift's row is re-pointed at the
		# replacement invoice.
		if link.get("reference_doctype") in ("Payment Entry", "POS Closing Shift"):
			continue
		return link

	return None


@frappe.whitelist()
def check_invoice_transfer_eligibility(invoice_name):
	"""
	Read-only pre-flight so the UI can explain why an invoice can't be moved
	before the user commits to it.

	Args:
		invoice_name: Sales Invoice name

	Returns:
		dict: {eligible, reason, message, invoice}
	"""
	if not invoice_name:
		frappe.throw(_("Invoice name is required"))

	if not frappe.has_permission("Sales Invoice", "read", invoice_name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	invoice = frappe.db.get_value("Sales Invoice", invoice_name, _INVOICE_FIELDS, as_dict=True)
	if not invoice:
		return {
			"eligible": False,
			"reason": "not_found",
			"message": _("Invoice {0} does not exist").format(invoice_name),
			"invoice": None,
		}

	reason, message = _get_blocking_reason(invoice)
	if reason:
		return {"eligible": False, "reason": reason, "message": message, "invoice": invoice}

	return {"eligible": True, "reason": None, "message": "", "invoice": invoice}


# =============================================================================
# Transfer
# =============================================================================


def _snapshot_payment_entries(invoice_name):
	"""Capture submitted Payment Entries allocated to this invoice so they can be
	re-created against the replacement invoice."""
	per = frappe.qb.DocType("Payment Entry Reference")
	pe = frappe.qb.DocType("Payment Entry")

	rows = (
		frappe.qb.from_(per)
		.inner_join(pe)
		.on(per.parent == pe.name)
		.select(
			pe.name.as_("payment_entry"),
			per.allocated_amount.as_("amount"),
			pe.mode_of_payment,
			pe.paid_to,
			pe.posting_date,
			pe.reference_no,
			pe.remarks,
		)
		.where(
			(per.reference_doctype == "Sales Invoice")
			& (per.reference_name == invoice_name)
			& (pe.docstatus == 1)
		)
		.orderby(pe.posting_date)
	).run(as_dict=True)

	return [r for r in rows if flt(r.amount) > 0]


def _get_closing_shift_rows(invoice_name):
	"""Rows on submitted POS Closing Shifts that point at this invoice.

	A closed shift links its invoices through Sales Invoice Reference child rows.
	Frappe refuses to cancel a linked invoice, so the transfer detaches these rows,
	then re-points them at the replacement - which keeps the closing shift accurate,
	since the replacement carries identical amounts and the same opening shift.
	"""
	return frappe.get_all(
		"Sales Invoice Reference",
		filters={
			"sales_invoice": invoice_name,
			"parenttype": "POS Closing Shift",
			"parentfield": "pos_transactions",
		},
		fields=["name", "parent"],
	)


def _repoint_closing_shift_rows(rows, invoice_name, customer):
	"""Point detached closing-shift rows at the given invoice (or None to detach)."""
	for row in rows:
		frappe.db.set_value(
			"Sales Invoice Reference",
			row["name"],
			{"sales_invoice": invoice_name, "customer": customer},
			update_modified=False,
		)


def _build_replacement(original, new_customer):
	"""Copy the cancelled invoice into a new amended document for new_customer.

	set_missing_values() is deliberately never called - it would re-fetch the new
	customer's price list and tax template and silently re-rate the invoice.
	"""
	new_doc = frappe.copy_doc(original)

	new_doc.amended_from = original.name
	new_doc.customer = new_customer
	new_doc.customer_name = frappe.db.get_value("Customer", new_customer, "customer_name") or new_customer

	# Party-scoped details belong to the old customer - clear them so ERPNext does
	# not reject a contact/address that isn't linked to the new customer.
	for field in (
		"customer_address",
		"address_display",
		"contact_person",
		"contact_display",
		"contact_mobile",
		"contact_email",
		"shipping_address_name",
		"shipping_address",
		"dispatch_address_name",
		"dispatch_address",
		"tax_id",
		"customer_po_no",
		# Points at the pos_next closing shift, which the Link field's own
		# doctype (ERPNext's POS Closing Entry) does not know about - carrying it
		# through insert() fails link validation. Restored raw after submit.
		"pos_closing_entry",
	):
		if new_doc.meta.has_field(field):
			new_doc.set(field, None)

	customer_row = frappe.db.get_value(
		"Customer", new_customer, ["customer_group", "territory", "tax_id"], as_dict=True
	)
	if customer_row:
		new_doc.customer_group = customer_row.customer_group
		new_doc.territory = customer_row.territory
		if new_doc.meta.has_field("tax_id"):
			new_doc.tax_id = customer_row.tax_id

	# Keep the invoice in its original period and receivable account.
	new_doc.set_posting_time = 1
	new_doc.posting_date = original.posting_date
	new_doc.posting_time = original.posting_time
	new_doc.due_date = original.due_date
	new_doc.debit_to = original.debit_to
	new_doc.ignore_pricing_rule = 1

	# no_copy custom fields that must survive the move: keeping the opening shift
	# keeps POS shift totals neutral, and the one-time rule stamp re-records the
	# redemption against the new customer (cancel released it from the old one).
	new_doc.posa_pos_opening_shift = original.get("posa_pos_opening_shift")
	new_doc.pos_applied_one_time_rules = original.get("pos_applied_one_time_rules")

	# copy_doc may drop the POS payment rows if the child table is no_copy.
	if original.get("payments") and not new_doc.get("payments"):
		for row in original.payments:
			new_doc.append("payments", row.as_dict(no_default_fields=True))

	# A POS credit sale legitimately carries no payment rows; re-arm the flag that
	# validate_pos_paid_amount (overrides/sales_invoice.py) checks, or submit fails.
	if cint(original.is_pos) and not original.get("payments") and flt(original.grand_total) > 0:
		new_doc.flags.pos_next_credit_sale = 1

	return new_doc


@frappe.whitelist()
def transfer_invoice_to_customer(invoice_name, new_customer, reason=None):
	"""
	Move a submitted invoice - including its outstanding balance and payments -
	to another customer.

	The original invoice is cancelled and re-issued as an amended invoice
	(SINV-0012 -> SINV-0012-1) owned by new_customer.

	Args:
		invoice_name: Sales Invoice to move
		new_customer: Customer to move it to
		reason: Optional note recorded on both documents

	Returns:
		dict: {success, old_invoice, new_invoice, old_customer, new_customer,
		       grand_total, outstanding_amount, payment_entries}
	"""
	if not invoice_name:
		frappe.throw(_("Invoice name is required"))
	if not new_customer:
		frappe.throw(_("Please select the customer to move this invoice to"))

	if not frappe.has_permission("Sales Invoice", "cancel", invoice_name) or not frappe.has_permission(
		"Sales Invoice", "create"
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if not frappe.db.exists("Customer", new_customer):
		frappe.throw(_("Customer {0} does not exist").format(new_customer))

	original = frappe.get_doc("Sales Invoice", invoice_name)

	# Never trust the client's pre-flight - re-check here.
	reason_code, message = _get_blocking_reason(original)
	if reason_code:
		frappe.throw(message)

	if original.customer == new_customer:
		frappe.throw(_("Invoice {0} already belongs to {1}").format(invoice_name, new_customer))

	customer_currency = frappe.db.get_value("Customer", new_customer, "default_currency")
	if customer_currency and customer_currency != original.currency:
		frappe.throw(
			_("Customer {0} bills in {1} but this invoice is in {2}.").format(
				new_customer, customer_currency, original.currency
			)
		)

	old_customer = original.customer
	original_grand_total = flt(original.grand_total)

	frappe.db.savepoint("transfer_invoice")
	try:
		payment_snapshots = _snapshot_payment_entries(invoice_name)

		# Submitted Payment Entries block invoice cancellation - reverse them first.
		for snapshot in payment_snapshots:
			pe_doc = frappe.get_doc("Payment Entry", snapshot.payment_entry)
			pe_doc.flags.ignore_permissions = True
			pe_doc.cancel()

		# A closed shift's link would otherwise block cancellation - detach it now
		# and re-point it at the replacement once that exists.
		closing_shift_rows = _get_closing_shift_rows(invoice_name)
		if closing_shift_rows:
			_repoint_closing_shift_rows(closing_shift_rows, None, None)

		# Cancelling the Payment Entries rewrote the invoice's outstanding amount
		# and modified timestamp - refresh before cancelling it.
		original.reload()
		original.flags.ignore_permissions = True
		original.cancel()

		new_doc = _build_replacement(original, new_customer)
		new_doc.flags.ignore_permissions = True
		new_doc.insert(ignore_permissions=True)

		if abs(flt(new_doc.grand_total) - original_grand_total) > AMOUNT_TOLERANCE:
			frappe.throw(
				_("Invoice total changed during the move ({0} -> {1}). The move was cancelled.").format(
					frappe.format_value(original_grand_total, {"fieldtype": "Currency"}),
					frappe.format_value(new_doc.grand_total, {"fieldtype": "Currency"}),
				)
			)

		new_doc.submit()

		# validate()/set_due_date() can recompute due_date from the payment
		# schedule - force the original ageing back onto the replacement.
		if str(new_doc.due_date) != str(original.due_date):
			new_doc.db_set("due_date", original.due_date, update_modified=False)

		if closing_shift_rows:
			_repoint_closing_shift_rows(closing_shift_rows, new_doc.name, new_customer)
			# Mirror whatever the original carried; copy_doc drops it and the
			# closing shift sets it the same raw way (no link validation - the
			# field points at ERPNext's POS Closing Entry, not our closing shift).
			if original.meta.has_field("pos_closing_entry") and original.get("pos_closing_entry"):
				frappe.db.set_value(
					"Sales Invoice",
					new_doc.name,
					"pos_closing_entry",
					original.get("pos_closing_entry"),
					update_modified=False,
				)

		# Re-create the external payments against the replacement invoice.
		new_payment_entries = []
		for snapshot in payment_snapshots:
			new_payment_entries.append(
				create_payment_entry(
					new_doc.name,
					flt(snapshot.amount),
					mode_of_payment=snapshot.mode_of_payment,
					payment_account=snapshot.paid_to,
					reference_no=snapshot.reference_no,
					remarks=snapshot.remarks,
					posting_date=str(snapshot.posting_date),
				)
			)

		_record_audit_trail(original, new_doc, old_customer, new_customer, reason)

	except Exception:
		frappe.db.rollback(save_point="transfer_invoice")
		frappe.log_error(
			title="Invoice Customer Transfer Failed",
			message=f"Invoice: {invoice_name}, New customer: {new_customer}\n{frappe.get_traceback()}",
		)
		raise

	new_doc.reload()

	return {
		"success": True,
		"old_invoice": invoice_name,
		"new_invoice": new_doc.name,
		"old_customer": old_customer,
		"new_customer": new_customer,
		"new_customer_name": new_doc.customer_name,
		"grand_total": flt(new_doc.grand_total),
		"paid_amount": flt(new_doc.grand_total) - flt(new_doc.outstanding_amount),
		"outstanding_amount": flt(new_doc.outstanding_amount),
		"due_date": str(new_doc.due_date) if new_doc.due_date else None,
		"currency": new_doc.currency,
		"payment_entries": new_payment_entries,
	}


def _record_audit_trail(original, new_doc, old_customer, new_customer, reason):
	"""Leave a readable trail on both documents."""
	suffix = _(" Reason: {0}").format(reason) if reason else ""

	original.add_comment(
		"Comment",
		_("Moved to customer {0} as invoice {1}.").format(new_customer, new_doc.name) + suffix,
	)
	new_doc.add_comment(
		"Comment",
		_("Moved from customer {0} (invoice {1}).").format(old_customer, original.name) + suffix,
	)
