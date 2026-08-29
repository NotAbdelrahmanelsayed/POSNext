import frappe


def execute():
	frappe.db.set_value("POS Settings", {}, "allow_amount_only_return", 1, update_modified=False)
