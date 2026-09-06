import { __ } from "@/utils/translation"

export function getShortcutGroups() {
	return [
		{
			title: __("General"),
			shortcuts: [
				{ keys: ["F4"], label: __("Search items") },
				{ keys: ["F8"], label: __("Search customer") },
				{ keys: ["F9"], label: __("Proceed to payment") },
				{ keys: ["Alt", "Q"], label: __("Edit last item quantity") },
				{ keys: ["Alt", "B"], label: __("Show/hide item cost") },
				{ keys: ["?"], label: __("Show shortcuts") },
			],
		},
		{
			title: __("Item search"),
			shortcuts: [
				{ keys: ["Alt", "1–5"], label: __("Select item from results") },
			],
		},
		{
			title: __("Checkout"),
			shortcuts: [
				{ keys: ["Alt", "1–9"], label: __("Select payment method") },
				{ keys: ["0–9"], label: __("Type an amount on the numpad") },
				{ keys: ["Enter"], label: __("Add typed amount, or pay when fully covered") },
				{ keys: ["Alt", "C"], label: __("Pay rest on account") },
			],
		},
		{
			title: __("Dialogs"),
			shortcuts: [
				{ keys: ["Enter"], label: __("Confirm dialog") },
				{ keys: ["Esc"], label: __("Close dialog") },
				{ keys: ["Ctrl", "S"], label: __("Confirm dialog") },
			],
		},
	]
}
