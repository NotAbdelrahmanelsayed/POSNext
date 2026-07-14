import { ref } from "vue"
import { call } from "frappe-ui"
import { useToast } from "@/composables/useToast"
import { __ } from "@/utils/translation"
import {
	buildStatementMessage,
	downloadStatementImage,
	formatMessageAmount,
	shareStatementImage,
	toWhatsAppNumber,
} from "@/utils/whatsapp"

function resolveCustomerId(customer) {
	return typeof customer === "object"
		? customer.name || customer.customer
		: customer
}

/**
 * Shared "Send via WhatsApp" / "Download image" logic for CustomerDuesDialog and
 * CreditSalesSummaryDialog. Attaches the real statement image where the Web Share API
 * supports it, copies it to the clipboard as a next-best option, and always falls back
 * to a wa.me link carrying the message and a public image URL.
 */
export function useWhatsAppStatement() {
	const { showSuccess, showError } = useToast()
	const sharingCustomer = ref(null)
	const downloadingCustomer = ref(null)

	async function fetchStatement(customerId, { company, posProfile }) {
		return call("pos_next.api.customer_statement.share_customer_statement", {
			customer: customerId,
			pos_profile: posProfile || undefined,
			company: company || undefined,
		})
	}

	async function shareStatement(
		customer,
		{ company, posProfile, currency } = {},
	) {
		if (sharingCustomer.value) return

		const customerId = resolveCustomerId(customer)
		sharingCustomer.value = customerId

		// Must open synchronously, before any await, or popup blockers kill it.
		const windowHandle = window.open("", "_blank")
		if (!windowHandle) {
			sharingCustomer.value = null
			showError(__("Popup blocked — check your browser settings."))
			return
		}

		try {
			const result = await fetchStatement(customerId, { company, posProfile })

			const fmt = (val) => formatMessageAmount(val, result.currency || currency)
			const message = buildStatementMessage({
				totalAmount: fmt(result.total_amount),
				paid: fmt(result.paid),
				outstanding: fmt(result.outstanding),
			})

			const { method } = await shareStatementImage({
				imageUrl: result.image_url,
				fileName: result.file_name,
				message,
				phone: toWhatsAppNumber(result.mobile_no),
				windowHandle,
			})

			if (method === "clipboard") {
				showSuccess(__("Image copied — paste it into the chat"))
			}
		} catch (error) {
			windowHandle.close()
			showError(error.message || __("Failed to share statement"))
		} finally {
			sharingCustomer.value = null
		}
	}

	async function downloadStatement(customer, { company, posProfile } = {}) {
		if (downloadingCustomer.value) return

		const customerId = resolveCustomerId(customer)
		downloadingCustomer.value = customerId

		try {
			const result = await fetchStatement(customerId, { company, posProfile })
			await downloadStatementImage(result.image_url, result.file_name)
		} catch (error) {
			showError(error.message || __("Failed to download image"))
		} finally {
			downloadingCustomer.value = null
		}
	}

	return {
		sharingCustomer,
		downloadingCustomer,
		shareStatement,
		downloadStatement,
	}
}
