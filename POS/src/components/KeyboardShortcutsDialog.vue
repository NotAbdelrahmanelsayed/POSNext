<template>
	<Dialog
		v-model="open"
		:options="{ title: __('Keyboard Shortcuts'), size: 'xl' }"
	>
		<template #body-content>
			<div class="flex flex-col gap-5">
				<div v-for="group in shortcutGroups" :key="group.title">
					<h3 class="text-sm font-semibold text-gray-900 mb-2 text-start">
						{{ group.title }}
					</h3>
					<div class="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden">
						<div
							v-for="shortcut in group.shortcuts"
							:key="shortcut.label"
							class="flex items-center justify-between gap-3 px-3 py-2 bg-white"
						>
							<span class="text-sm text-gray-700 text-start">
								{{ shortcut.label }}
							</span>
							<span class="flex items-center gap-1 flex-shrink-0" dir="ltr">
								<kbd
									v-for="key in shortcut.keys"
									:key="key"
									class="inline-flex items-center px-1.5 py-0.5 text-[11px] font-semibold font-mono text-gray-600 bg-gray-100 border border-gray-300 rounded"
								>
									{{ key }}
								</kbd>
							</span>
						</div>
					</div>
				</div>

				<p class="text-xs text-gray-500 text-start">
					{{ __("Shortcuts are disabled while a dialog is open, except inside the payment dialog.") }}
				</p>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
/**
 * Keyboard Shortcuts help dialog.
 * Opened from the "?" header button or by pressing F1 on the sale screen.
 * Visibility is owned by the posUI store so isAnyDialogOpen suppresses other
 * shortcuts while it is shown.
 */
import { useDialogSubmit } from "@/composables/useDialogSubmit"
import { usePOSUIStore } from "@/stores/posUI"
import { Dialog } from "frappe-ui"
import { computed } from "vue"

const uiStore = usePOSUIStore()

const open = computed({
	get: () => uiStore.showShortcutsDialog,
	set: (value) => {
		uiStore.showShortcutsDialog = value
	},
})

// Info-only dialog: Enter or Ctrl/Cmd+S simply closes it.
useDialogSubmit({
	isOpen: open,
	onSubmit: () => {
		open.value = false
	},
})

const shortcutGroups = computed(() => [
	{
		title: __("Sale Screen"),
		shortcuts: [
			{ keys: ["F4"], label: __("Focus item search") },
			{ keys: ["F8"], label: __("Search / change customer") },
			{ keys: ["F9"], label: __("Proceed to payment") },
			{
				keys: ["Alt", "1-5"],
				label: __("Add search result #1-5 to cart"),
			},
			{
				keys: ["Alt", "Q"],
				label: __("Edit quantity of last cart item"),
			},
			{ keys: ["F1"], label: __("Show this help") },
		],
	},
	{
		title: __("Payment Dialog"),
		shortcuts: [
			{
				keys: ["Alt", "1-9"],
				label: __("Pay remaining amount with payment method #1-9"),
			},
			{ keys: ["Alt", "C"], label: __("Pay on Account (credit sale)") },
			{ keys: ["0-9", "."], label: __("Type amount on the numpad") },
			{ keys: ["Backspace"], label: __("Delete last digit") },
			{ keys: ["Enter"], label: __("Confirm entered amount") },
		],
	},
])
</script>
