import { formatCurrency } from "@/utils/currency"
import { __ } from "@/utils/translation"

export function printCustomerStatement({ companyName, customerName, currency, summary, creditItems }) {
	const isRTL = document.documentElement.dir === "rtl"
	const dir = isRTL ? "rtl" : "ltr"
	const textAlign = isRTL ? "right" : "left"
	const textAlignEnd = isRTL ? "left" : "right"

	const fmt = (val) => formatCurrency(Number.parseFloat(val || 0), currency)

	const totalAmount = creditItems.reduce((sum, item) => sum + Number.parseFloat(item.total_amount || 0), 0)

	const itemRows = creditItems
		.map(
			(item) => `
		<tr>
			<td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;">${item.item_name || item.item_code}</td>
			<td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;text-align:${textAlignEnd};white-space:nowrap;">${item.total_qty} ${item.uom || ""}</td>
			<td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;text-align:${textAlignEnd};font-weight:600;">${fmt(item.total_amount)}</td>
		</tr>`,
		)
		.join("")

	const paid = Math.max(0, totalAmount - Number.parseFloat(summary.total_outstanding || 0))

	const summaryHtml = [
		`<div class="summary-row"><span class="summary-label">${__("Total")}</span><span class="summary-value">${fmt(totalAmount)}</span></div>`,
		`<div class="summary-row"><span class="summary-label">${__("Paid")}</span><span class="summary-value">${fmt(paid)}</span></div>`,
		`<div class="summary-row net"><span class="summary-label">${__("Remaining")}</span><span class="summary-value">${fmt(summary.total_outstanding)}</span></div>`,
	].join("\n    ")

	const html = `<!DOCTYPE html>
<html dir="${dir}" lang="${isRTL ? "ar" : "en"}">
<head>
<meta charset="UTF-8">
<title>${__("Customer Statement")}</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Tahoma','Segoe UI','Arial',sans-serif; color: #1a1a1a; background: #fff; padding: 0; }
.page { max-width: 780px; margin: 0 auto; padding: 20px; }
.header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 2px solid #e5e7eb; }
.company { font-size: 20px; font-weight: 700; color: #111; }
.doc-title { font-size: 14px; color: #6b7280; margin-top: 4px; }
.meta { text-align: ${textAlignEnd}; font-size: 13px; color: #374151; }
.meta strong { display: block; font-size: 15px; font-weight: 700; margin-bottom: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 0; }
thead tr { background: #f9fafb; }
th { padding: 10px 12px; text-align: ${textAlign}; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; border-bottom: 1px solid #e5e7eb; }
th:not(:first-child) { text-align: ${textAlignEnd}; }
.table-wrapper { border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin-bottom: 16px; }
.total-row td { padding: 10px 12px; font-weight: 700; background: #f9fafb; border-top: 2px solid #e5e7eb; }
.summary { border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin-top: 16px; }
.summary-row { display: flex; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.summary-row:last-child { border-bottom: none; }
.summary-row.net { font-weight: 700; font-size: 15px; background: #fff7ed; }
.summary-label { color: #6b7280; }
.summary-value { font-weight: 600; }
.doc-footer { margin-top: 24px; padding-top: 16px; border-top: 1px solid #e5e7eb; text-align: center; font-size: 11px; color: #9ca3af; }
@page { size: A4; margin: 14mm; }
@media print { body { padding: 0; } .page { padding: 0; max-width: none; } }
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div>
      <div class="company">${companyName || ""}</div>
      <div class="doc-title">${__("Customer Statement")}</div>
    </div>
    <div class="meta">
      <strong>${customerName || ""}</strong>
      ${new Date().toLocaleDateString()}
    </div>
  </div>
  <div class="table-wrapper">
    <table>
      <thead>
        <tr>
          <th>${__("Item")}</th>
          <th style="text-align:${textAlignEnd};">${__("Qty")}</th>
          <th style="text-align:${textAlignEnd};">${__("Amount")}</th>
        </tr>
      </thead>
      <tbody>
        ${itemRows}
      </tbody>
    </table>
  </div>
  <div class="summary">
    ${summaryHtml}
  </div>
  <div class="doc-footer">Powered by <strong>Abdelrahman Elsayed 01000488181</strong></div>
</div>
</body>
</html>`

	const printWindow = window.open("", "_blank", "width=850,height=700")
	if (!printWindow) {
		throw new Error(__("Popup blocked — check your browser settings."))
	}
	printWindow.document.write(html)
	printWindow.document.close()
	printWindow.onload = () => {
		setTimeout(() => printWindow.print(), 250)
	}
}
