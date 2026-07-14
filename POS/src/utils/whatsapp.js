import { formatCurrency } from "@/utils/currency"
import { __ } from "@/utils/translation"

// The shared formatCurrency() util renders EGP as "E£", matching the rest of the POS UI.
// A WhatsApp message read by an Egyptian customer reads more naturally with the spelled-out
// "جنيه" instead — scoped to this message only, not a site-wide currency display change.
const MESSAGE_CURRENCY_NAMES = {
	EGP: "جنيه",
}

/** Format an amount for the WhatsApp message text (spelled-out currency name where we have one). */
export function formatMessageAmount(value, currency) {
	const name = MESSAGE_CURRENCY_NAMES[currency]
	if (!name) return formatCurrency(value, currency)
	const amount = Number.parseFloat(value || 0).toLocaleString("en-US", {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	})
	return `${amount} ${name}`
}

/**
 * Normalize a raw phone number into digits-only, WhatsApp-ready form.
 *
 * Handles the shapes this codebase actually produces/stores:
 *  - PhoneInput.vue's "ISD-NUMBER" format, e.g. "20-1000488181", or with the ISD
 *    written as "+20" and/or the number still carrying its local trunk 0 — real
 *    stored data includes shapes like "+20-01117221447"
 *  - International prefixes without a hyphen: "+201000488181", "00201000488181"
 *  - A local number with a leading trunk 0: "01000488181" → "201000488181"
 *  - A number that already carries the country code: "201000488181" (left as-is)
 *
 * @returns digits-only number ready for wa.me, or "" if it doesn't look like a phone number
 */
export function toWhatsAppNumber(raw, defaultCountryCode = "20") {
	if (!raw) return ""

	let digits

	if (raw.includes("-")) {
		// ISD-NUMBER format written by PhoneInput.vue. The number part may still carry
		// its local trunk 0 (e.g. "+20-01117221447") — drop it so the country code isn't
		// followed by a stray 0.
		const [isd, ...rest] = raw.split("-")
		const isdDigits = isd.replace(/\D/g, "")
		let numberDigits = rest.join("").replace(/\D/g, "")
		if (numberDigits.startsWith("0")) {
			numberDigits = numberDigits.slice(1)
		}
		digits = `${isdDigits}${numberDigits}`
	} else {
		digits = raw.replace(/\D/g, "")
		if (raw.trim().startsWith("+")) {
			// already international, digits already carry the country code
		} else if (digits.startsWith("00")) {
			digits = digits.slice(2)
		} else if (digits.startsWith("0")) {
			// local trunk-prefixed number, e.g. 01000488181 → 201000488181
			digits = `${defaultCountryCode}${digits.slice(1)}`
		} else if (!digits.startsWith(defaultCountryCode)) {
			// bare local number with no trunk 0, e.g. 1000488181 → 201000488181
			digits = `${defaultCountryCode}${digits}`
		}
	}

	return digits.length >= 7 ? digits : ""
}

/**
 * Build the WhatsApp message text for a customer statement, with the same
 * total/paid/remaining breakdown shown on the statement image itself.
 */
export function buildStatementMessage({
	customerName,
	companyName,
	totalAmount,
	paid,
	outstanding,
}) {
	return [
		__("Hello {0}", [customerName]),
		__("Statement from {0}", [companyName]),
		__("Total taken: {0}", [totalAmount]),
		__("Total paid: {0}", [paid]),
		__("Total remaining: {0}", [outstanding]),
	].join("\n")
}

/** Copy an image blob to the clipboard so it can be pasted (Ctrl+V) directly into a chat. */
async function copyImageToClipboard(blob) {
	if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined")
		return false
	try {
		await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })])
		return true
	} catch {
		return false
	}
}

/**
 * Share a customer statement over WhatsApp, trying the best available attachment method:
 *  1. Web Share API with the real file — attaches the actual image (mobile/some desktop browsers).
 *  2. Clipboard image copy — the image isn't attached to the wa.me link, but the cashier can
 *     paste (Ctrl+V) it straight into the chat once WhatsApp opens.
 *  3. Plain link — always included as a fallback so the customer can open the statement
 *     even if the image was never attached or pasted.
 *
 * @param windowHandle - a window opened synchronously in the click handler (popup-blocker workaround).
 *   Navigated to the wa.me fallback, or closed once native sharing takes over.
 * @returns {Promise<{method: "share" | "clipboard" | "link" | "cancelled"}>}
 */
export async function shareStatementImage({
	imageUrl,
	fileName,
	message,
	phone,
	windowHandle,
}) {
	let blob = null
	try {
		const response = await fetch(imageUrl)
		blob = await response.blob()
	} catch {
		// Image fetch failed — fall through to a link-only message, nothing to attach.
	}

	if (blob && navigator.canShare) {
		try {
			const file = new File([blob], fileName || "statement.png", {
				type: blob.type || "image/png",
			})

			// canShare() can return true even when the OS has no working share target for
			// this content, so don't close the fallback window until share() actually
			// succeeds — otherwise a failed share leaves nothing to fall back to.
			if (navigator.canShare({ files: [file] })) {
				await navigator.share({ files: [file], text: message })
				windowHandle?.close()
				return { method: "share" }
			}
		} catch (error) {
			if (error?.name === "AbortError") {
				// User dismissed the share sheet — not a failure, don't fall back.
				windowHandle?.close()
				return { method: "cancelled" }
			}
			// Real failure (share rejected, etc.) — fall through to the link/clipboard path.
		}
	}

	const copied = blob ? await copyImageToClipboard(blob) : false

	const text = encodeURIComponent(
		`${message}\n${__("For details: {0}", [imageUrl])}`,
	)
	const waUrl = phone
		? `https://wa.me/${phone}?text=${text}`
		: `https://wa.me/?text=${text}`

	if (windowHandle && !windowHandle.closed) {
		windowHandle.location.href = waUrl
	} else {
		window.open(waUrl, "_blank")
	}

	return { method: copied ? "clipboard" : "link" }
}

/** Download a statement image to the cashier's device as a real file (not just a browser tab). */
export async function downloadStatementImage(imageUrl, fileName) {
	const response = await fetch(imageUrl)
	const blob = await response.blob()
	const objectUrl = URL.createObjectURL(blob)

	const link = document.createElement("a")
	link.href = objectUrl
	link.download = fileName || "statement.png"
	document.body.appendChild(link)
	link.click()
	link.remove()
	URL.revokeObjectURL(objectUrl)
}
