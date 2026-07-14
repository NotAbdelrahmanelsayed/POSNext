import { ref } from "vue"
import { call } from "frappe-ui"
import { useToast } from "@/composables/useToast"
import { formatCurrency } from "@/utils/currency"
import { __ } from "@/utils/translation"
import {
	buildStatementMessage,
	shareStatementImage,
	toWhatsAppNumber,
} from "@/utils/whatsapp"

/**
 * Shared "Send via WhatsApp" logic for CustomerDuesDialog and CreditSalesSummaryDialog.
 * Attaches the real statement image where the Web Share API supports it, otherwise
 * falls back to a wa.me link carrying the message and a public image URL.
 */
export function useWhatsAppStatement() {
	const { showError } = useToast()
	const sharingCustomer = ref(null)

	async function shareStatement(
		customer,
		{ company, posProfile, currency, customerName } = {},
	) {
		if (sharingCustomer.value) return

		const customerId =
			typeof customer === "object"
				? customer.name || customer.customer
				: customer
		sharingCustomer.value = customerId

		// Must open synchronously, before any await, or popup blockers kill it.
		const windowHandle = window.open("", "_blank")
		if (!windowHandle) {
			sharingCustomer.value = null
			showError(__("Popup blocked — check your browser settings."))
			return
		}

		try {
			const result = await call(
				"pos_next.api.customer_statement.share_customer_statement",
				{
					customer: customerId,
					pos_profile: posProfile || undefined,
					company: company || undefined,
				},
			)

			const phone = toWhatsAppNumber(result.mobile_no)
			const message = buildStatementMessage({
				customerName: result.customer_name || customerName || customerId,
				companyName: company,
				outstanding: formatCurrency(
					result.outstanding,
					result.currency || currency,
				),
			})

			await shareStatementImage({
				imageUrl: result.image_url,
				fileName: result.file_name,
				message,
				phone,
				windowHandle,
			})
		} catch (error) {
			windowHandle.close()
			showError(error.message || __("Failed to share statement"))
		} finally {
			sharingCustomer.value = null
		}
	}

	return { sharingCustomer, shareStatement }
}
