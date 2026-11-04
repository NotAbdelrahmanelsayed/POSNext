import json

import frappe
from frappe import _
from frappe.core.api.file import get_max_file_size
from frappe.model.naming import make_autoname
from frappe.utils import cint, cstr, flt

from pos_next.api.items import _get_pos_profile_allowed_item_groups

# Image types this screen can render. The site's own allowed_file_extensions
# list covers every file type (CSV, PDF, ...), so it is intersected with this
# rather than used directly — a PDF is a valid attachment but not a product
# image.
SUPPORTED_IMAGE_TYPES = {
	"JPG": "image/jpeg",
	"JPEG": "image/jpeg",
	"PNG": "image/png",
	"GIF": "image/gif",
	"WEBP": "image/webp",
}

DEFAULT_PAGE_LENGTH = 20
MAX_PAGE_LENGTH = 100
POS_ITEM_CODE_SERIES = "POS-ITEM-.#####"
ALLOWED_IMAGE_PREFIXES = ("/files/", "/private/files/")

# Per-site opt-in (site_config.json) that adds the buying price and the date
# prices last changed to the product form. Off by default so other sites see
# the stock form.
BUYING_PRICE_SITE_FLAG = "pos_next_product_buying_price"


def _validate_pos_profile_access(pos_profile: str) -> None:
	"""Ensure the session user may act through this POS Profile.

	Every endpoint here scopes what the caller can read or change to the
	profile's allowed item groups, so an unvalidated profile name would let a
	caller pick any profile — including one with no group restriction at all,
	which disables the scoping entirely. Mirrors the check used in
	`api/invoices.py` and `api/credit_sales.py`.
	"""
	if not pos_profile:
		frappe.throw(_("POS Profile is required"))

	is_assigned = frappe.db.exists("POS Profile User", {"parent": pos_profile, "user": frappe.session.user})
	# Users who can administer POS Profiles are not constrained by them.
	if not is_assigned and not frappe.has_permission("POS Profile", "write"):
		frappe.throw(_("You don't have access to this POS Profile"))


@frappe.whitelist()
def get_product_management_permissions() -> dict:
	"""Return permissions required to show and use POS Product Management."""
	can_read_item = frappe.has_permission("Item", "read")
	can_create_item = frappe.has_permission("Item", "create")
	can_write_item = frappe.has_permission("Item", "write")
	can_read_price = frappe.has_permission("Item Price", "read")
	can_create_price = frappe.has_permission("Item Price", "create")
	can_write_price = frappe.has_permission("Item Price", "write")

	return {
		"read_item": can_read_item,
		"create_item": can_create_item,
		"write_item": can_write_item,
		"read_item_price": can_read_price,
		"create_item_price": can_create_price,
		"write_item_price": can_write_price,
		"can_access": can_read_item
		and can_read_price
		and (can_create_item or can_write_item)
		and (can_create_price or can_write_price),
	}


def _get_buying_price_list() -> str | None:
	"""Buying Price List to edit from the product form, or None when the site
	has not opted in or the user cannot read Item Prices."""
	if not cint(frappe.conf.get(BUYING_PRICE_SITE_FLAG)):
		return None
	if not frappe.has_permission("Item Price", "read"):
		return None
	return frappe.db.get_single_value("Buying Settings", "buying_price_list") or None


@frappe.whitelist()
def get_product_form_settings() -> dict:
	"""Optional product-form fields enabled for this site."""
	buying_price_list = _get_buying_price_list()
	return {
		"show_buying_price": bool(buying_price_list),
		"buying_price_list": buying_price_list,
	}


def _item_price_info(
	item_code: str, buying_price_list: str, selling_price_list: str | None, warehouse: str | None = None
) -> dict:
	"""Buying price, falling back to the valuation rate when the item has no
	row on the buying price list. `buying_price_source` tells the two apart."""
	buying = _get_price_rows([item_code], buying_price_list).get(item_code)
	selling = _get_price_rows([item_code], selling_price_list).get(item_code)
	if buying:
		buying_price, source = buying.price_list_rate, "price_list"
	else:
		buying_price = _get_valuation_rate(item_code, warehouse)
		source = "valuation_rate" if buying_price else None
	return {
		"buying_price": buying_price,
		"buying_price_source": source,
		"price_updated_on": max((row.modified for row in (buying, selling) if row), default=None),
	}


def _get_valuation_rate(item_code: str, warehouse: str | None) -> float:
	"""Warehouse valuation rate (Bin), else the item's own valuation rate."""
	rate = 0.0
	if warehouse:
		rate = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"))
	return rate or flt(frappe.db.get_value("Item", item_code, "valuation_rate"))


def _profile_selling_price_list(pos_profile: str | None) -> str | None:
	if not pos_profile:
		return None
	_validate_pos_profile_access(pos_profile)
	return frappe.get_cached_doc("POS Profile", pos_profile).selling_price_list


@frappe.whitelist()
def get_item_buying_price(
	item_code: str, pos_profile: str | None = None, warehouse: str | None = None
) -> dict:
	"""Buying price and last price change for the cart's item edit dialog."""
	buying_price_list = _get_buying_price_list()
	if not buying_price_list:
		return {"enabled": False}
	return {
		"enabled": True,
		"can_edit": bool(frappe.has_permission("Item Price", "write")),
		**_item_price_info(item_code, buying_price_list, _profile_selling_price_list(pos_profile), warehouse),
	}


@frappe.whitelist(methods=["POST"])
def update_item_buying_price(item_code: str, buying_price: float, pos_profile: str | None = None) -> dict:
	"""Set the item's rate on the buying price list from the cart's item edit dialog."""
	buying_price_list = _get_buying_price_list()
	if not buying_price_list:
		frappe.throw(_("Buying price editing is not enabled on this site"))
	rate = flt(buying_price)
	if rate < 0:
		frappe.throw(_("Buying price must be zero or greater"))
	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("Item {0} not found").format(item_code))
	selling_price_list = _profile_selling_price_list(pos_profile)
	_upsert_item_price(item_code, buying_price_list, rate, "buying")
	return _item_price_info(item_code, buying_price_list, selling_price_list)


@frappe.whitelist()
def get_product_image_settings() -> dict:
	"""Report the site's own upload limits so the client matches the server.

	Both values come from System Settings:

	- `allowed_file_extensions` is newline-separated, uppercase and without
	  dots. Empty means the site imposes no restriction, in which case every
	  image type this screen supports is offered.
	- `max_file_size` is stored in MB; get_max_file_size() resolves it to
	  bytes, falling back to site_config and then to Frappe's 25 MB default.

	Hardcoding these client-side lets the picker accept a file the server will
	then reject, so they are read rather than assumed.
	"""
	allowed = cstr(frappe.get_system_settings("allowed_file_extensions") or "").strip()

	if allowed:
		site_extensions = {line.strip().upper().lstrip(".") for line in allowed.splitlines() if line.strip()}
		extensions = [ext for ext in SUPPORTED_IMAGE_TYPES if ext in site_extensions]
		restricted = True
	else:
		extensions = list(SUPPORTED_IMAGE_TYPES)
		restricted = False

	return {
		"extensions": extensions,
		"mime_types": sorted({SUPPORTED_IMAGE_TYPES[ext] for ext in extensions}),
		"max_file_size": get_max_file_size(),
		"restricted_by_system_settings": restricted,
	}


@frappe.whitelist()
def get_item_groups(pos_profile: str) -> list:
	"""Get leaf item groups allowed for product management in this POS Profile."""
	if not frappe.has_permission("Item", "read"):
		frappe.throw(_("Not permitted to read Item"))

	_validate_pos_profile_access(pos_profile)
	pos_profile_doc = frappe.get_cached_doc("POS Profile", pos_profile)
	allowed_item_groups = _get_pos_profile_allowed_item_groups(pos_profile_doc)

	filters = {"is_group": 0}
	if allowed_item_groups:
		filters["name"] = ["in", allowed_item_groups]

	return frappe.get_all(
		"Item Group",
		filters=filters,
		fields=["name", "parent_item_group", "is_group"],
		order_by="name asc",
	)


@frappe.whitelist()
def get_products(
	pos_profile: str,
	search_term: str | None = None,
	item_group: str | None = None,
	start: int = 0,
	limit: int = DEFAULT_PAGE_LENGTH,
) -> list:
	"""Get products for management"""
	if not frappe.has_permission("Item", "read"):
		frappe.throw(_("Not permitted to read Item"))

	_validate_pos_profile_access(pos_profile)
	pos_profile_doc = frappe.get_cached_doc("POS Profile", pos_profile)
	limit_start = max(cint(start), 0)
	page_length = min(max(cint(limit) or DEFAULT_PAGE_LENGTH, 1), MAX_PAGE_LENGTH)

	filters = {"is_sales_item": 1}
	allowed_item_groups = _get_pos_profile_allowed_item_groups(pos_profile_doc)
	or_filters = None

	if search_term:
		or_filters = [
			["name", "like", f"%{search_term}%"],
			["item_code", "like", f"%{search_term}%"],
			["item_name", "like", f"%{search_term}%"],
		]

	if item_group:
		if allowed_item_groups and item_group not in allowed_item_groups:
			return []
		filters["item_group"] = item_group
	elif allowed_item_groups:
		filters["item_group"] = ["in", allowed_item_groups]

	items = frappe.get_all(
		"Item",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"item_name",
			"item_group",
			"stock_uom",
			"is_stock_item",
			"image",
			"disabled",
		],
		order_by="creation desc",
		limit_start=limit_start,
		limit_page_length=page_length + 1,
	)
	item_codes = [d.name for d in items]

	if item_codes:
		conversions = frappe.get_all(
			"UOM Conversion Detail",
			filters={"parent": ["in", item_codes]},
			fields=["parent", "uom", "conversion_factor"],
			order_by="idx asc",
		)
		conversion_map = {}
		for row in conversions:
			conversion_map.setdefault(row.parent, []).append(
				{"uom": row.uom, "conversion_factor": row.conversion_factor}
			)
		for item in items:
			item.uom_conversions = conversion_map.get(item.name, [])

	# Fetch prices
	selling_prices = _get_price_rows(item_codes, pos_profile_doc.selling_price_list)
	for item in items:
		item.price = selling_prices[item.name].price_list_rate if item.name in selling_prices else 0.0

	buying_price_list = _get_buying_price_list()
	if buying_price_list:
		buying_prices = _get_price_rows(item_codes, buying_price_list)
		for item in items:
			buying = buying_prices.get(item.name)
			selling = selling_prices.get(item.name)
			item.buying_price = buying.price_list_rate if buying else 0.0
			item.price_updated_on = max(
				(row.modified for row in (buying, selling) if row), default=None
			)

	return items


def _get_price_rows(item_codes: list, price_list: str | None) -> dict:
	"""Map item_code -> Item Price row (rate + modified) for one price list."""
	if not item_codes or not price_list:
		return {}
	prices = frappe.get_all(
		"Item Price",
		filters={"item_code": ["in", item_codes], "price_list": price_list},
		fields=["item_code", "price_list_rate", "modified"],
	)
	return {p.item_code: p for p in prices}


@frappe.whitelist()
def save_product(pos_profile: str, data: str) -> dict:
	"""Create or update a product for POS"""
	data = json.loads(data)
	item_name = (data.get("item_name") or "").strip()
	item_group = (data.get("item_group") or "").strip()
	stock_uom = (data.get("stock_uom") or "").strip()

	if not item_name:
		frappe.throw(_("Product Name is required"))
	if not item_group:
		frappe.throw(_("Item Group is required"))
	if not stock_uom:
		frappe.throw(_("UOM is required"))

	is_new = not data.get("item_code")
	permission_type = "create" if is_new else "write"
	if not frappe.has_permission("Item", permission_type):
		frappe.throw(_("Not permitted to {0} Item").format(permission_type))

	_validate_pos_profile_access(pos_profile)
	pos_profile_doc = frappe.get_cached_doc("POS Profile", pos_profile)
	allowed_item_groups = _get_pos_profile_allowed_item_groups(pos_profile_doc)
	if allowed_item_groups and item_group not in allowed_item_groups:
		frappe.throw(_("Item Group is not allowed for this POS Profile"))

	if is_new:
		item = frappe.new_doc("Item")
		item.item_code = _make_item_code()
		item.item_group = item_group
		item.stock_uom = stock_uom
		item.is_sales_item = 1
		item.is_stock_item = 1
	else:
		item = frappe.get_doc("Item", data.get("item_code"))
		# The incoming group is checked above, but the item's *existing* group
		# must be in scope too — otherwise an item can be pulled out of a
		# group this profile is not allowed to touch and into one it is.
		if allowed_item_groups and item.item_group not in allowed_item_groups:
			frappe.throw(_("This product belongs to an Item Group not allowed for this POS Profile"))

	item.item_name = item_name

	item.item_group = item_group

	item.stock_uom = stock_uom

	if "is_stock_item" in data:
		item.is_stock_item = 1 if data.get("is_stock_item") else 0

	if "image" in data:
		image = str(data.get("image") or "")
		# The client sends a data: URI while a new file is pending upload; the
		# real path is set afterwards. Anything else must be a Frappe file path
		# so an arbitrary external URL cannot be rendered by the POS.
		if not image.startswith("data:"):
			if image and not image.startswith(ALLOWED_IMAGE_PREFIXES):
				frappe.throw(_("Invalid image path"))
			item.image = image

	item.disabled = data.get("disabled", 0)
	_save_uom_conversions(item, data.get("uom_conversions") or [])

	item.save()

	# Handle Price
	price_list = pos_profile_doc.selling_price_list
	if price_list and "price" in data:
		_upsert_item_price(item.name, price_list, flt(data.get("price")), "selling")

	result = {"item_code": item.name}

	buying_price_list = _get_buying_price_list()
	if buying_price_list:
		buying_price = flt(data.get("buying_price"))
		# A blank buying price on a product that has none is not a price.
		has_buying_row = frappe.db.exists("Item Price", {"item_code": item.name, "price_list": buying_price_list})
		if "buying_price" in data and (buying_price or has_buying_row):
			_upsert_item_price(item.name, buying_price_list, buying_price, "buying")
		latest = frappe.get_all(
			"Item Price",
			filters={
				"item_code": item.name,
				"price_list": ["in", [p for p in (price_list, buying_price_list) if p]],
			},
			pluck="modified",
			order_by="modified desc",
			limit=1,
		)
		result["price_updated_on"] = latest[0] if latest else None

	# No explicit frappe.db.commit() — the framework commits at the end of a
	# successful request and rolls back on exception. Committing here would
	# defeat that rollback and also commit unrelated pending work.
	return result


def _upsert_item_price(item_code: str, price_list: str, rate: float, side: str) -> None:
	"""Create or update the item's rate on a price list. An unchanged rate is
	left alone so the row's modified date keeps meaning "price last changed"."""
	existing_price = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list},
		"name",
	)

	if existing_price:
		price_doc = frappe.get_doc("Item Price", existing_price)
		if flt(price_doc.price_list_rate) == rate:
			return
		if not frappe.has_permission("Item Price", "write"):
			frappe.throw(_("Not permitted to write Item Price"))
		price_doc.price_list_rate = rate
		price_doc.save()
	else:
		if not frappe.has_permission("Item Price", "create"):
			frappe.throw(_("Not permitted to create Item Price"))
		price_doc = frappe.new_doc("Item Price")
		price_doc.item_code = item_code
		price_doc.price_list = price_list
		price_doc.price_list_rate = rate
		price_doc.set(side, 1)
		price_doc.save()


@frappe.whitelist()
def update_product_image(pos_profile: str, item_code: str, file_url: str) -> dict:
	"""Update only the image, enforcing the same profile boundary as product saves."""
	_validate_pos_profile_access(pos_profile)
	item = frappe.get_doc("Item", item_code)
	item.check_permission("write")
	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	groups = _get_pos_profile_allowed_item_groups(profile)
	if groups and item.item_group not in groups:
		frappe.throw(_("This product belongs to an Item Group not allowed for this POS Profile"))
	if not file_url or not file_url.startswith(ALLOWED_IMAGE_PREFIXES):
		frappe.throw(_("Invalid image path"))
	file_name = frappe.db.get_value(
		"File",
		{"file_url": file_url, "attached_to_doctype": "Item", "attached_to_name": item.name},
		"name",
	)
	if not file_name:
		frappe.throw(_("Image must be attached to this product"))
	frappe.get_doc("File", file_name).check_permission("read")
	item.image = file_url
	item.save()
	return {"item_code": item.name}


def _save_uom_conversions(item, rows: list) -> None:
	item.set("uoms", [])
	seen = set()
	stock_uom = item.stock_uom
	for row in rows:
		uom = (row.get("uom") or "").strip()
		conversion_factor = flt(row.get("conversion_factor") or 0)
		if not uom or uom == stock_uom or conversion_factor <= 0 or uom in seen:
			continue
		seen.add(uom)
		item.append(
			"uoms",
			{
				"uom": uom,
				"conversion_factor": conversion_factor,
			},
		)


def _make_item_code() -> str:
	return make_autoname(POS_ITEM_CODE_SERIES)
