import { describe, expect, it } from "vitest"
import { canCreateReturn } from "@/utils/invoice"

describe("canCreateReturn", () => {
	it.each([
		{ status: "Unpaid", outstanding_amount: 100 },
		{ status: "Partly Paid", outstanding_amount: 40 },
		{ status: "Paid", outstanding_amount: 0 },
	])("allows submitted non-return $status invoices", (invoice) => {
		expect(canCreateReturn({ ...invoice, docstatus: 1, is_return: 0 })).toBe(true)
	})

	it("allows statement invoices without docstatus because the endpoint filters submissions", () => {
		expect(canCreateReturn({ status: "Paid", is_return: 0 })).toBe(true)
	})

	it.each([
		{ docstatus: 0, is_return: 0, status: "Unpaid" },
		{ docstatus: 2, is_return: 0, status: "Paid" },
		{ docstatus: 1, is_return: 1, status: "Return" },
		{ docstatus: 1, is_return: 0, status: "Credit Note Issued" },
	])("rejects ineligible invoice %#", (invoice) => {
		expect(canCreateReturn(invoice)).toBe(false)
	})
})
