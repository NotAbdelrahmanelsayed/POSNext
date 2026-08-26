# Copyright (c) 2025, BrainWise and contributors
# For license information, please see license.txt

"""
Customer Statement Sharing API

Renders a customer's credit-items statement as a PNG (via wkhtmltoimage) and
stores it as a public File, so it can be shared as an image attachment or a
public link over WhatsApp.
"""

import os
import shutil
import subprocess
import tempfile

import frappe
from frappe import _
from frappe.utils import flt, get_url, now_datetime

from pos_next.api.customer_dues import get_customer_due_statement

WKHTMLTOIMAGE_BIN = "wkhtmltoimage"


@frappe.whitelist()
def share_customer_statement(customer, pos_profile=None, company=None):
	"""
	Render *customer*'s credit-items statement as a PNG, store it as a public
	File, and return everything the frontend needs to share it over WhatsApp.

	Returns:
		{
		    image_url: str,       # public https URL to the PNG
		    file_name: str,
		    mobile_no: str | None,
		    customer_name: str,
		    total_amount: float,  # total value of items on credit
		    paid: float,
		    returned: float,
		    outstanding: float,
		    currency: str,
		}
	"""
	if not frappe.has_permission("Sales Invoice", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	statement = get_customer_due_statement(customer, pos_profile=pos_profile, company=company)

	customer_name, mobile_no = frappe.db.get_value(
		"Customer", customer, ["customer_name", "mobile_no"]
	)

	credit_items = _aggregate_credit_items(statement["due_invoices"], statement.get("loans"))
	currency = statement["currency"]

	if not company and pos_profile:
		company = frappe.db.get_value("POS Profile", pos_profile, "company")
	company_name = frappe.db.get_value("Company", company, "company_name") if company else (company or "")

	total_amount = sum(flt(item["total_amount"]) for item in credit_items)
	outstanding = flt(statement["summary"].get("total_due", statement["summary"]["total_outstanding"]))
	# Use the same return-aware breakdown as the customer dues dialog. The
	# previous implementation inferred every reduction from outstanding as paid,
	# which incorrectly classified linked merchandise returns.
	paid = flt(statement["summary"].get("total_paid"))
	returned = flt(statement["summary"].get("total_returned"))

	def fmt(val):
		# frappe.utils.fmt_money pulls its symbol from the Currency master, which on
		# this site has a garbled EGP symbol ("£ or ج.م"). The frontend avoids this by
		# deriving the symbol from Intl.NumberFormat instead — mirror that here with
		# the plain ISO code so the statement image never renders the garbled value.
		return f"{flt(val):,.2f} {currency}"

	for item in credit_items:
		item["total_amount_formatted"] = fmt(item["total_amount"])

	is_rtl = (frappe.local.lang or "en").startswith("ar")

	html = frappe.render_template(
		"pos_next/templates/customer_statement.html",
		{
			"dir": "rtl" if is_rtl else "ltr",
			"lang": "ar" if is_rtl else "en",
			"text_align": "right" if is_rtl else "left",
			"text_align_end": "left" if is_rtl else "right",
			"company_name": company_name,
			"customer_name": customer_name or customer,
			"statement_date": now_datetime().strftime("%Y-%m-%d"),
			"items": credit_items,
			"total_amount_formatted": fmt(total_amount),
			"paid_formatted": fmt(paid),
			"returned_formatted": fmt(returned),
			"outstanding_formatted": fmt(outstanding),
			"paid_amount": paid,
			"returned_amount": returned,
		},
		is_path=True,
	)

	png_bytes = _render_png(html)

	_delete_previous_statement_files(customer)

	# ASCII-only, random filename — the customer's raw name may contain non-ASCII
	# characters (Arabic) that break unencoded links, and attached_to_name already
	# scopes the file to this customer so no identifying slug is needed here.
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"statement-{frappe.generate_hash(length=20)}.png",
			"is_private": 0,
			"content": png_bytes,
			"attached_to_doctype": "Customer",
			"attached_to_name": customer,
		}
	).insert(ignore_permissions=True)

	return {
		"image_url": get_url(file_doc.file_url),
		"file_name": file_doc.file_name,
		"mobile_no": mobile_no,
		"customer_name": customer_name or customer,
		"total_amount": total_amount,
		"paid": paid,
		"returned": returned,
		"outstanding": outstanding,
		"currency": currency,
	}


def _aggregate_credit_items(due_invoices, loans=None):
	"""Server-side port of the `creditItems` computed in CustomerDuesDialog.vue —
	group due-invoice line items by item_code, summing qty and amount. A Partly
	Paid invoice contributes its full line qty, matching the dialog's semantics.

	Cash loans have no item lines -- they render as one pseudo-item row (blank
	qty, amount = total outstanding loan balance) appended at the end, mirrored
	in customer_statement.html / printCustomerStatement.js / whatsapp.js. Keep
	all four in sync -- they silently drift if only one is edited."""
	by_item = {}
	for inv in due_invoices:
		for item in inv.get("items", []):
			key = item["item_code"]
			qty = flt(item.get("qty"))
			amount = flt(item.get("amount"))
			existing = by_item.get(key)
			if existing:
				existing["total_qty"] += qty
				existing["total_amount"] += amount
			else:
				by_item[key] = {
					"item_code": item["item_code"],
					"item_name": item.get("item_name"),
					"uom": item.get("uom"),
					"total_qty": qty,
					"total_amount": amount,
				}
	items = list(by_item.values())

	loan_total = sum(flt(loan.get("outstanding")) for loan in (loans or []))
	if loan_total > 0:
		items.append(
			{
				"item_code": "__cash_loan__",
				"item_name": _("Cash loan"),
				"uom": None,
				"total_qty": None,
				"total_amount": loan_total,
				"is_cash_loan": True,
			}
		)

	return items


def _render_png(html):
	binary = shutil.which(WKHTMLTOIMAGE_BIN)
	if not binary:
		frappe.throw(_("wkhtmltoimage is not installed on the server"))

	with tempfile.TemporaryDirectory() as tmp_dir:
		html_path = os.path.join(tmp_dir, "statement.html")
		png_path = os.path.join(tmp_dir, "statement.png")

		with open(html_path, "w", encoding="utf-8") as f:
			f.write(html)

		result = subprocess.run(
			[
				binary,
				"--enable-local-file-access",
				"--width",
				"800",
				"--format",
				"png",
				"--quality",
				"90",
				html_path,
				png_path,
			],
			capture_output=True,
			text=True,
		)

		if result.returncode != 0 or not os.path.exists(png_path):
			frappe.log_error(
				title="Customer Statement PNG Render Failed",
				message=f"stdout: {result.stdout}\nstderr: {result.stderr}",
			)
			frappe.throw(_("Failed to render statement image"))

		with open(png_path, "rb") as f:
			return f.read()


def _delete_previous_statement_files(customer):
	"""Delete the customer's previous statement files — keeps the File table
	bounded and revokes stale public links on every re-send."""
	old_files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Customer",
			"attached_to_name": customer,
			"file_name": ["like", "statement-%"],
		},
		pluck="name",
	)
	for name in old_files:
		frappe.delete_doc("File", name, ignore_permissions=True, delete_permanently=True)
