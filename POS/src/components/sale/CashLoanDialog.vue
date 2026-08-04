<template>
	<Dialog v-model="open" :options="{ title: __('Cash Loan'), size: 'md' }">
		<template #body-content>
			<div class="flex border-b border-gray-200 mb-4 -mt-1">
				<button
					v-for="tab in tabs"
					:key="tab.id"
					@click="activeTab = tab.id"
					:class="[
						'px-4 py-2 text-sm font-semibold border-b-2 transition-colors',
						activeTab === tab.id
							? 'text-blue-600 border-blue-600'
							: 'text-gray-500 border-transparent hover:text-gray-700',
					]"
				>
					{{ tab.label }}
				</button>
			</div>

			<div v-if="dialogDataResource.loading" class="text-center py-8">
				<div class="inline-block animate-spin rounded-full h-10 w-10 border-b-4 border-blue-600"></div>
				<p class="mt-3 text-sm text-gray-600">{{ __("Loading cash loan data...") }}</p>
			</div>

			<div v-else class="pos-cash-loan-dialog-fields flex flex-col gap-5">
				<div
					v-if="isOffline"
					class="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-start gap-3"
				>
					<div class="flex-shrink-0 w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center">
						<FeatherIcon name="wifi-off" class="w-5 h-5 text-amber-600" />
					</div>
					<div class="flex-1 min-w-0 text-start">
						<h4 class="text-sm font-bold text-amber-900">{{ __("Offline Mode") }}</h4>
						<p class="text-xs text-amber-700 mt-1">
							{{ __("Cash loans cannot be recorded while offline. Please connect to the internet and try again.") }}
						</p>
					</div>
				</div>

				<template v-if="activeTab === 'give'">
					<div>
						<label class="block text-start text-sm font-medium text-gray-700 mb-2">
							{{ __("Person's Name") }} <span class="text-red-500">*</span>
						</label>
						<Input
							v-model="giveForm.party_name"
							type="text"
							:placeholder="__('Who is receiving the cash?')"
						/>
					</div>

					<div>
						<label class="block text-start text-sm font-medium text-gray-700 mb-2">
							{{ __("Amount") }} <span class="text-red-500">*</span>
						</label>
						<Input
							v-model="giveForm.amount"
							type="number"
							min="0"
							step="0.01"
							:placeholder="__('Enter amount')"
						/>
					</div>

					<div>
						<label class="block text-start text-sm font-medium text-gray-700 mb-2">
							{{ __("Mode of Payment") }} <span class="text-red-500">*</span>
						</label>
						<AutocompleteSelect
							v-model="giveForm.mode_of_payment"
							:options="paymentMethodOptions"
							:placeholder="__('Search payment method...')"
							icon="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z"
							required
						/>
					</div>

					<div>
						<label class="block text-start text-sm font-medium text-gray-700 mb-2">
							{{ __("Remarks") }}
						</label>
						<textarea
							v-model="giveForm.remarks"
							rows="3"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-start"
							:placeholder="__('Optional remarks')"
						></textarea>
					</div>
				</template>

				<template v-else>
					<div v-if="outstandingLoans.length === 0" class="text-center py-6 text-sm text-gray-500">
						{{ __("No outstanding cash loans") }}
					</div>

					<div v-else class="flex flex-col gap-2">
						<label class="block text-start text-sm font-medium text-gray-700">
							{{ __("Select Loan to Repay") }} <span class="text-red-500">*</span>
						</label>
						<button
							v-for="loan in outstandingLoans"
							:key="loan.name"
							type="button"
							@click="repayForm.loan_journal_entry = loan.name"
							:class="[
								'w-full text-start rounded-lg border px-3 py-2 transition-colors',
								repayForm.loan_journal_entry === loan.name
									? 'border-blue-500 bg-blue-50'
									: 'border-gray-200 hover:border-gray-300',
							]"
						>
							<div class="flex justify-between items-center">
								<span class="text-sm font-medium text-gray-800">{{ loan.party_name }}</span>
								<span class="text-sm font-semibold text-gray-900">{{ formatCurrency(loan.amount) }}</span>
							</div>
							<div class="text-xs text-gray-500 mt-0.5">{{ loan.posting_date }}</div>
						</button>
					</div>

					<div v-if="outstandingLoans.length > 0">
						<label class="block text-start text-sm font-medium text-gray-700 mb-2">
							{{ __("Mode of Payment") }} <span class="text-red-500">*</span>
						</label>
						<AutocompleteSelect
							v-model="repayForm.mode_of_payment"
							:options="paymentMethodOptions"
							:placeholder="__('Search payment method...')"
							icon="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z"
							required
						/>
					</div>

					<div v-if="outstandingLoans.length > 0">
						<label class="block text-start text-sm font-medium text-gray-700 mb-2">
							{{ __("Remarks") }}
						</label>
						<textarea
							v-model="repayForm.remarks"
							rows="3"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-start"
							:placeholder="__('Optional remarks')"
						></textarea>
					</div>
				</template>

				<div
					v-if="validationError"
					class="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700 text-start"
				>
					{{ validationError }}
				</div>
			</div>
		</template>

		<template #actions>
			<div class="flex justify-end gap-2 w-full">
				<Button
					variant="subtle"
					:disabled="submitResource.loading"
					@click="open = false"
				>
					{{ __("Cancel") }}
				</Button>
				<Button
					v-if="activeTab === 'give'"
					variant="solid"
					:loading="submitResource.loading"
					:disabled="dialogDataResource.loading || isOffline"
					@click="submitGiveLoan"
				>
					{{ __("Give Loan") }}
				</Button>
				<Button
					v-else
					variant="solid"
					:loading="submitResource.loading"
					:disabled="dialogDataResource.loading || isOffline || outstandingLoans.length === 0"
					@click="submitRepayLoan"
				>
					{{ __("Mark as Repaid") }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import AutocompleteSelect from "@/components/common/AutocompleteSelect.vue"
import { useFormatters } from "@/composables/useFormatters"
import { useOfflineStatus } from "@/composables/useOfflineStatus"
import { useToast } from "@/composables/useToast"
import { parseError } from "@/utils/errorHandler"
import { Button, Dialog, FeatherIcon, Input, createResource } from "frappe-ui"
import { computed, reactive, ref, watch } from "vue"

const props = defineProps({
	modelValue: Boolean,
	posProfile: String,
	posOpeningShift: String,
	currency: {
		type: String,
		default: "USD",
	},
})

const emit = defineEmits(["update:modelValue", "cash-loan-created", "cash-loan-repaid"])

const { formatCurrency } = useFormatters()
const { showSuccess } = useToast()
const { isOffline } = useOfflineStatus()

const tabs = [
	{ id: "give", label: __("Give Loan") },
	{ id: "repay", label: __("Repay Loan") },
]
const activeTab = ref("give")

const giveForm = reactive({
	party_name: "",
	amount: "",
	mode_of_payment: "",
	remarks: "",
})

const repayForm = reactive({
	loan_journal_entry: "",
	mode_of_payment: "",
	remarks: "",
})

const validationError = ref("")

const open = computed({
	get: () => props.modelValue,
	set: (value) => emit("update:modelValue", value),
})

const dialogDataResource = createResource({
	url: "pos_next.api.cash_loans.get_cash_loan_dialog_data",
	makeParams() {
		return {
			pos_profile: props.posProfile,
			pos_opening_shift: props.posOpeningShift,
		}
	},
	auto: false,
	onError(error) {
		validationError.value =
			error?.messages?.[0] || error?.message || __("Unable to load cash loan data")
	},
})

const giveResource = createResource({
	url: "pos_next.api.cash_loans.create_cash_loan",
	makeParams() {
		return {
			pos_opening_shift: props.posOpeningShift,
			pos_profile: props.posProfile,
			party_name: giveForm.party_name,
			amount: Number.parseFloat(giveForm.amount),
			mode_of_payment: giveForm.mode_of_payment,
			remarks: giveForm.remarks || null,
		}
	},
	auto: false,
	onSuccess(data) {
		showSuccess(data?.message || __("Cash loan recorded successfully"))
		emit("cash-loan-created", data)
		open.value = false
		resetForms()
	},
	onError(error) {
		const parsed = parseError(normalizeSubmitError(error))
		validationError.value = parsed.message
	},
})

const repayResource = createResource({
	url: "pos_next.api.cash_loans.repay_cash_loan",
	makeParams() {
		return {
			loan_journal_entry: repayForm.loan_journal_entry,
			pos_opening_shift: props.posOpeningShift,
			pos_profile: props.posProfile,
			mode_of_payment: repayForm.mode_of_payment,
			remarks: repayForm.remarks || null,
		}
	},
	auto: false,
	onSuccess(data) {
		showSuccess(data?.message || __("Cash loan repayment recorded successfully"))
		emit("cash-loan-repaid", data)
		open.value = false
		resetForms()
	},
	onError(error) {
		const parsed = parseError(normalizeSubmitError(error))
		validationError.value = parsed.message
	},
})

const submitResource = computed(() => (activeTab.value === "give" ? giveResource : repayResource))

function normalizeSubmitError(error) {
	if (error instanceof Error) {
		return {
			message: error.message,
			...(error.cause && typeof error.cause === "object" ? error.cause : {}),
		}
	}

	return error || {}
}

const paymentMethodOptions = computed(() =>
	(dialogDataResource.data?.payment_methods || []).map((method) => ({
		label: method.mode_of_payment,
		value: method.mode_of_payment,
	})),
)

const outstandingLoans = computed(() => dialogDataResource.data?.outstanding_loans || [])

watch(open, async (isOpen) => {
	if (!isOpen) {
		validationError.value = ""
		return
	}

	if (!props.posProfile || !props.posOpeningShift) {
		validationError.value = __("An active POS shift is required")
		return
	}

	activeTab.value = "give"
	resetForms()
	await dialogDataResource.submit()
})

watch(activeTab, () => {
	validationError.value = ""
})

function resetForms() {
	giveForm.party_name = ""
	giveForm.amount = ""
	giveForm.mode_of_payment = ""
	giveForm.remarks = ""
	repayForm.loan_journal_entry = ""
	repayForm.mode_of_payment = ""
	repayForm.remarks = ""
	validationError.value = ""
}

function validateGiveForm() {
	if (!giveForm.party_name?.trim()) {
		return __("Person's name is required")
	}

	const amount = Number.parseFloat(giveForm.amount)
	if (!Number.isFinite(amount) || amount <= 0) {
		return __("Amount must be greater than zero")
	}

	if (!giveForm.mode_of_payment) {
		return __("Mode of Payment is required")
	}

	return ""
}

function validateRepayForm() {
	if (!repayForm.loan_journal_entry) {
		return __("Please select a loan to repay")
	}

	if (!repayForm.mode_of_payment) {
		return __("Mode of Payment is required")
	}

	return ""
}

async function submitGiveLoan() {
	if (isOffline.value) {
		validationError.value = __(
			"Cash loans cannot be recorded while offline. Please connect to the internet and try again.",
		)
		return
	}

	validationError.value = validateGiveForm()
	if (validationError.value) {
		return
	}

	try {
		await giveResource.submit()
	} catch (error) {
		const parsed = parseError(normalizeSubmitError(error))
		validationError.value = parsed.message
	}
}

async function submitRepayLoan() {
	if (isOffline.value) {
		validationError.value = __(
			"Cash loans cannot be recorded while offline. Please connect to the internet and try again.",
		)
		return
	}

	validationError.value = validateRepayForm()
	if (validationError.value) {
		return
	}

	try {
		await repayResource.submit()
	} catch (error) {
		const parsed = parseError(normalizeSubmitError(error))
		validationError.value = parsed.message
	}
}
</script>

<style scoped>
:global(.dialog-content:has(.pos-cash-loan-dialog-fields)) {
	overflow: visible !important;
}

.pos-cash-loan-dialog-fields :deep(.dropdown-menu) {
	z-index: 1000;
}
</style>
