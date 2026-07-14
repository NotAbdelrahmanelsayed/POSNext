import { __ } from "@/utils/translation"

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
 * Build the WhatsApp message text for a customer statement.
 * The URL line is omitted when the image is being attached natively (Web Share API) —
 * it would be redundant noise in the chat since the image is already attached.
 */
export function buildStatementMessage({
	customerName,
	companyName,
	outstanding,
	url,
}) {
	const lines = [
		__("Hello {0}", [customerName]),
		__("Statement from {0}", [companyName]),
		__("Outstanding balance: {0}", [outstanding]),
	]
	if (url) {
		lines.push(url)
	}
	return lines.join("\n")
}

/**
 * Share a customer statement over WhatsApp: attach the real PNG via the Web Share API
 * where supported, otherwise fall back to a wa.me link carrying the message + public URL.
 *
 * @param windowHandle - a window opened synchronously in the click handler (popup-blocker workaround).
 *   Navigated to the wa.me fallback, or closed once native sharing takes over.
 */
export async function shareStatementImage({
	imageUrl,
	fileName,
	message,
	phone,
	windowHandle,
}) {
	if (navigator.canShare) {
		try {
			const response = await fetch(imageUrl)
			const blob = await response.blob()
			const file = new File([blob], fileName || "statement.png", {
				type: blob.type || "image/png",
			})

			if (navigator.canShare({ files: [file] })) {
				windowHandle?.close()
				await navigator.share({ files: [file], text: message })
				return
			}
		} catch (error) {
			if (error?.name === "AbortError") {
				// User dismissed the share sheet — not a failure.
				return
			}
			// Fall through to the wa.me fallback below.
		}
	}

	const text = encodeURIComponent(`${message}\n${imageUrl}`)
	const waUrl = phone
		? `https://wa.me/${phone}?text=${text}`
		: `https://wa.me/?text=${text}`

	if (windowHandle) {
		windowHandle.location.href = waUrl
	} else {
		window.open(waUrl, "_blank")
	}
}
