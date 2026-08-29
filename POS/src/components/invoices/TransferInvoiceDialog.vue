<template>
	<Dialog v-model="open" :options="{ title: __('Move Invoice to Another Customer'), size: 'lg' }">
		<template #body-content>
			<div class="pos-transfer-invoice-dialog-fields flex flex-col gap-5">
				<div v-if="eligibilityResource.loading" class="text-center py-8">
					<div class="inline-block animate-spin rounded-full h-10 w-10 border-b-4 border-blue-600"></div>
					<p class="mt-3 text-sm text-gray-600">{{ __("Checking invoice...") }}</p>
				</div>

				<template v-else>
					<div
						v-if="isOffline"
						class="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-start gap-3"
					>
						<div
							class="flex-shrink-0 w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center"
						>
							<FeatherIcon name="wifi-off" class="w-5 h-5 text-amber-600" />
						</div>
						<div class="flex-1 min-w-0 text-start">
							<h4 class="text-sm font-bold text-amber-900">{{ __("Offline Mode") }}</h4>
							<p class="text-xs text-amber-700 mt-1">
								{{
									__(
										"Invoices cannot be moved while offline. Please connect to the internet and try again.",
									)
								}}
							</p>
						</div>
					</div>

					<!-- Invoice summary -->
					<div class="rounded-lg border border-gray-200 bg-gray-50 p-4 text-start">
						<div class="flex items-center justify-between gap-3 mb-3">
							<span class="font-semibold text-gray-900">{{ invoiceName }}</span>
							<span class="text-xs text-gray-500">{{ formatDate(summary.posting_date) }}</span>
						</div>
						<dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
							<dt class="text-gray-500">{{ __("Current Customer") }}</dt>
							<dd class="text-gray-900 font-medium truncate">
								{{ summary.customer_name || summary.customer || "-" }}
							</dd>
							<dt class="text-gray-500">{{ __("Total") }}</dt>
							<dd class="text-gray-900">{{ formatCurrency(summary.grand_total || 0) }}</dd>
							<dt class="text-gray-500">{{ __("Paid") }}</dt>
							<dd class="text-gray-900">{{ formatCurrency(paidAmount) }}</dd>
							<dt class="text-gray-500">{{ __("Remaining") }}</dt>
							<dd class="font-semibold" :class="outstanding > 0 ? 'text-red-600' : 'text-green-600'">
								{{ formatCurrency(outstanding) }}
							</dd>
							<template v-if="summary.due_date">
								<dt class="text-gray-500">{{ __("Due Date") }}</dt>
								<dd class="text-gray-900">{{ formatDate(summary.due_date) }}</dd>
							</template>
						</dl>
					</div>

					<!-- Blocked -->
					<div
						v-if="!isEligible"
						class="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 text-start"
					>
						{{ blockMessage }}
					</div>

					<template v-else>
						<div>
							<label class="block text-start text-sm font-medium text-gray-700 mb-2">
								{{ __("Move to Customer") }} <span class="text-red-500">*</span>
							</label>
							<AutocompleteSelect
								v-model="form.customer"
								:options="customerOptions"
								:placeholder="__('Search customer')"
								icon="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
								required
							/>
						</div>

						<div>
							<label class="block text-start text-sm font-medium text-gray-700 mb-2">
								{{ __("Reason") }}
							</label>
							<textarea
								v-model="form.reason"
								rows="2"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-start"
								:placeholder="__('Optional - why is this invoice being moved?')"
							></textarea>
						</div>

						<div
							class="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800 text-start"
						>
							<p class="font-semibold mb-1">{{ __("This cannot be undone automatically") }}</p>
							<p class="text-xs leading-relaxed">
								{{
									__(
										"Invoice {0} will be cancelled and re-issued under the new customer with a new number. The remaining balance, the due date and any payments already made will move with it.",
										{ 0: invoiceName },
									)
								}}
							</p>
						</div>
					</template>

					<div
						v-if="validationError"
						class="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700 text-start"
					>
						{{ validationError }}
					</div>
				</template>
			</div>
		</template>

		<template #actions>
			<div class="flex justify-end gap-2 w-full">
				<Button variant="subtle" :disabled="transferResource.loading" @click="open = false">
					{{ __("Cancel") }}
				</Button>
				<Button
					v-if="isEligible"
					variant="solid"
					theme="red"
					:loading="transferResource.loading"
					:disabled="eligibilityResource.loading || isOffline || !form.customer"
					@click="submitTransfer"
				>
					{{ __("Move Invoice") }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import AutocompleteSelect from "@/components/common/AutocompleteSelect.vue"
import { useDialogSubmit } from "@/composables/useDialogSubmit"
import { useFormatters } from "@/composables/useFormatters"
import {
	DEFAULT_CURRENCY,
	formatCurrency as formatCurrencyUtil,
} from "@/utils/currency"
import { useOfflineStatus } from "@/composables/useOfflineStatus"
import { useToast } from "@/composables/useToast"
import { parseError } from "@/utils/errorHandler"
import { Button, Dialog, FeatherIcon, createResource } from "frappe-ui"
import { computed, reactive, ref, watch } from "vue"

const props = defineProps({
	modelValue: Boolean,
	// Either a plain invoice name or an invoice-like object with a `name` key.
	invoice: {
		type: [String, Object],
		default: null,
	},
	posProfile: {
		type: String,
		default: "",
	},
	currency: {
		type: String,
		default: DEFAULT_CURRENCY,
	},
})

const emit = defineEmits(["update:modelValue", "transferred"])

const { formatDate } = useFormatters()
const { showSuccess } = useToast()
const { isOffline } = useOfflineStatus()

const form = reactive({ customer: "", reason: "" })
const validationError = ref("")

const open = computed({
	get: () => props.modelValue,
	set: (value) => emit("update:modelValue", value),
})

const invoiceName = computed(() => {
	if (!props.invoice) return ""
	return typeof props.invoice === "string"
		? props.invoice
		: props.invoice.name || ""
})

// Prefer the server's snapshot; fall back to whatever the parent handed us so the
// summary is populated while the eligibility check is still in flight.
const summary = computed(() => {
	const fromServer = eligibilityResource.data?.invoice
	if (fromServer) return fromServer
	return typeof props.invoice === "object" && props.invoice ? props.invoice : {}
})

const outstanding = computed(
	() => Number.parseFloat(summary.value.outstanding_amount) || 0,
)
const paidAmount = computed(
	() => (Number.parseFloat(summary.value.grand_total) || 0) - outstanding.value,
)

// useFormatters' formatCurrency drops the symbol; the rest of the POS shows
// "E£ 100.00", so format against the invoice's own currency here too.
function formatCurrency(amount) {
	return formatCurrencyUtil(
		Number.parseFloat(amount || 0),
		summary.value.currency || props.currency || DEFAULT_CURRENCY,
	)
}

const isEligible = computed(() => eligibilityResource.data?.eligible === true)
const blockMessage = computed(
	() =>
		eligibilityResource.data?.message || __("This invoice cannot be moved."),
)

const eligibilityResource = createResource({
	url: "pos_next.api.invoice_transfer.check_invoice_transfer_eligibility",
	makeParams() {
		return { invoice_name: invoiceName.value }
	},
	auto: false,
	onError(error) {
		validationError.value = parseError(normalizeError(error)).message
	},
})

const customersResource = createResource({
	url: "pos_next.api.customers.get_customers",
	makeParams() {
		return {
			search_term: "",
			pos_profile: props.posProfile || null,
			limit: 500,
		}
	},
	auto: false,
})

const transferResource = createResource({
	url: "pos_next.api.invoice_transfer.transfer_invoice_to_customer",
	makeParams() {
		return {
			invoice_name: invoiceName.value,
			new_customer: form.customer,
			reason: form.reason || null,
		}
	},
	auto: false,
	onSuccess(data) {
		showSuccess(
			__("Invoice moved to {0}. New invoice: {1}", {
				0: data?.new_customer_name || data?.new_customer,
				1: data?.new_invoice,
			}),
		)
		emit("transferred", data)
		open.value = false
		resetForm()
	},
	onError(error) {
		validationError.value = parseError(normalizeError(error)).message
	},
})

function normalizeError(error) {
	if (error instanceof Error) {
		return {
			message: error.message,
			...(error.cause && typeof error.cause === "object" ? error.cause : {}),
		}
	}
	return error || {}
}

// The invoice's current owner is never a valid destination.
const customerOptions = computed(() =>
	(customersResource.data || [])
		.filter((customer) => customer.name !== summary.value.customer)
		.map((customer) => ({
			label: customer.customer_name || customer.name,
			subtitle:
				customer.customer_name && customer.customer_name !== customer.name
					? customer.name
					: "",
			value: customer.name,
		})),
)

watch(open, async (isOpen) => {
	if (!isOpen) {
		validationError.value = ""
		return
	}

	resetForm()

	if (!invoiceName.value) {
		validationError.value = __("No invoice selected")
		return
	}

	await Promise.all([eligibilityResource.submit(), customersResource.submit()])
})

function resetForm() {
	form.customer = ""
	form.reason = ""
	validationError.value = ""
}

async function submitTransfer() {
	if (isOffline.value) {
		validationError.value = __(
			"Invoices cannot be moved while offline. Please connect to the internet and try again.",
		)
		return
	}

	if (!form.customer) {
		validationError.value = __(
			"Please select the customer to move this invoice to",
		)
		return
	}

	validationError.value = ""

	try {
		await transferResource.submit()
	} catch (error) {
		validationError.value = parseError(normalizeError(error)).message
	}
}

// Cancelling and re-issuing an invoice must never fire from a keyboard shortcut.
// Registering with both disabled also stops this dialog forwarding Enter/Ctrl+S
// to whatever dialog sits underneath it (same reasoning as CashLoanDialog).
useDialogSubmit({
	isOpen: open,
	onSubmit: () => {},
	canSubmit: () => false,
	enter: false,
	ctrlS: false,
})
</script>

<style scoped>
:global(.dialog-content:has(.pos-transfer-invoice-dialog-fields)) {
	overflow: visible !important;
}
</style>
