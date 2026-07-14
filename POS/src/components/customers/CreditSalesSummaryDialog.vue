<template>
	<!-- Full Page Overlay -->
	<Transition name="fade">
		<div
			v-if="show"
			class="fixed inset-0 bg-black bg-opacity-50 z-[290]"
			@click.self="handleClose"
		>
			<div class="fixed inset-0 flex items-center justify-center p-4">
				<div class="w-full h-full max-w-[95vw] max-h-[95vh] bg-white rounded-lg shadow-2xl overflow-hidden flex flex-col">

					<!-- Header -->
					<div class="flex items-center justify-between px-6 py-4 border-b bg-white flex-shrink-0">
						<div class="flex items-center gap-3">
							<div class="p-2 bg-gray-100 rounded-lg">
								<svg class="w-6 h-6 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z"/>
								</svg>
							</div>
							<div>
								<h2 class="text-xl font-bold text-gray-900">{{ __('Credit Sales') }}</h2>
								<p class="text-sm text-gray-600 mt-0.5">{{ __('Customers who owe money') }}</p>
							</div>
						</div>
						<div class="flex items-center gap-2">
							<button
								type="button"
								@click="loadSummary"
								:disabled="loading"
								class="p-2 text-gray-500 hover:bg-gray-100 active:bg-gray-200 rounded-lg transition-colors"
								:title="__('Refresh')"
							>
								<svg class="w-5 h-5" :class="{ 'animate-spin': loading }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
								</svg>
							</button>
							<button
								type="button"
								@click="handleClose"
								class="p-2 text-gray-500 hover:bg-gray-100 active:bg-gray-200 rounded-lg transition-colors"
								:title="__('Close')"
							>
								<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
								</svg>
							</button>
						</div>
					</div>

					<!-- Body -->
					<div class="flex-1 overflow-y-auto">

						<!-- Skeleton -->
						<div v-if="loading" class="p-6 space-y-4">
							<div class="bg-gray-100 rounded-xl h-24 animate-pulse"/>
							<div class="space-y-3 mt-6">
								<div v-for="i in 6" :key="i" class="bg-gray-100 rounded-xl h-16 animate-pulse"/>
							</div>
						</div>

						<!-- Content -->
						<div v-else-if="summary" class="p-6 space-y-6">

							<!-- Total card -->
							<div class="bg-orange-50 border-2 border-orange-300 rounded-xl p-5 text-center">
								<div class="text-xs font-medium text-orange-600 mb-1">{{ __('Total Owed') }}</div>
								<div class="text-3xl font-bold text-orange-700 tabular-nums">{{ formatCurrency(summary.totals.net_balance) }}</div>
								<div class="text-xs text-orange-500 mt-1">
									{{ __('{0} customer(s) owe money', [summary.totals.customer_count]) }}
								</div>
							</div>

							<!-- Search + sort -->
							<div v-if="summary.customers.length > 0" class="flex flex-wrap items-center gap-2">
								<div class="relative flex-1 min-w-[160px]">
									<svg class="absolute start-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
									</svg>
									<input
										v-model="searchTerm"
										type="text"
										:placeholder="__('Search customers...')"
										class="w-full ps-9 pe-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-orange-400 focus:border-orange-400"
									/>
								</div>
								<select
									v-model="sortOrder"
									class="text-xs font-medium border border-gray-300 rounded-lg px-2 py-2.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-orange-400"
								>
									<option value="amount">{{ __('Sort: Amount') }}</option>
									<option value="name">{{ __('Sort: Name') }}</option>
								</select>
							</div>

							<!-- Empty state -->
							<div v-if="summary.customers.length === 0" class="text-center py-12">
								<div class="text-5xl mb-3">✓</div>
								<p class="text-lg font-semibold text-green-700">{{ __('No customers owe money') }}</p>
								<p class="text-sm text-gray-500 mt-1">{{ __('Everyone is settled up.') }}</p>
							</div>

							<!-- No search results -->
							<div v-else-if="filteredCustomers.length === 0" class="text-center py-8 text-gray-500 text-sm">
								{{ __('No customers match your search.') }}
							</div>

							<!-- Customer list -->
							<div v-else class="space-y-3">
								<div
									v-for="row in filteredCustomers"
									:key="row.customer"
									role="button"
									tabindex="0"
									@click="$emit('select-customer', row.customer)"
									@keydown.enter="$emit('select-customer', row.customer)"
									:class="[
										'w-full bg-white border rounded-xl p-4 text-start transition-colors flex items-center justify-between gap-4 group cursor-pointer',
										row.net_balance > 0
											? 'border-gray-200 hover:border-orange-300 hover:bg-orange-50'
											: 'border-blue-100 bg-blue-50/40 hover:border-blue-300 hover:bg-blue-50',
									]"
								>
									<div class="flex-1 min-w-0">
										<div class="text-sm font-bold text-gray-900 truncate">{{ row.customer_name }}</div>
										<div class="text-xs text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
											<span>{{ __('{0} invoice(s)', [row.due_count]) }}</span>
											<span v-if="row.total_credit > 0" class="text-blue-600 font-medium tabular-nums">
												{{ __('Credit: {0}', [formatCurrency(row.total_credit)]) }}
											</span>
										</div>
									</div>
									<div class="text-end flex-shrink-0">
										<div
											:class="[
												'text-base font-bold tabular-nums',
												row.net_balance > 0 ? 'text-orange-600' : 'text-blue-600',
											]"
										>
											{{ formatCurrency(row.net_balance > 0 ? row.net_balance : row.total_outstanding) }}
										</div>
										<div v-if="row.net_balance <= 0" class="text-xs text-blue-600 mt-0.5">
											{{ __('Has credit') }}
										</div>
									</div>
									<button
										type="button"
										@click.stop="shareViaWhatsApp(row)"
										:disabled="sharingCustomer === row.customer || isOffline()"
										class="p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
										:title="__('Send via WhatsApp')"
									>
										<LoadingIndicator v-if="sharingCustomer === row.customer" class="w-4 h-4"/>
										<svg v-else class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
											<path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
											<path d="M12.001 2C6.478 2 2 6.477 2 12c0 1.876.512 3.633 1.404 5.14L2 22l4.995-1.378A9.955 9.955 0 0012.001 22C17.523 22 22 17.523 22 12S17.523 2 12.001 2zm0 18.09a8.05 8.05 0 01-4.29-1.238l-.307-.183-3.076.849.83-3.023-.2-.311A8.05 8.05 0 013.91 12c0-4.462 3.63-8.091 8.091-8.091 4.462 0 8.091 3.63 8.091 8.091 0 4.462-3.629 8.09-8.091 8.09z"/>
										</svg>
									</button>
									<svg
										:class="[
											'w-4 h-4 flex-shrink-0 rtl-flip',
											row.net_balance > 0 ? 'text-gray-300 group-hover:text-orange-400' : 'text-blue-300 group-hover:text-blue-500',
										]"
										fill="none" stroke="currentColor" viewBox="0 0 24 24"
									>
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
									</svg>
								</div>
							</div>
						</div>

						<!-- Error state -->
						<div v-else class="flex flex-col items-center justify-center py-16 text-gray-500 gap-3">
							<svg class="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
							</svg>
							<p>{{ __('Failed to load credit sales. Try refreshing.') }}</p>
							<button type="button" @click="loadSummary" class="text-orange-600 text-sm font-semibold hover:underline">
								{{ __('Retry') }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>
	</Transition>
</template>

<script setup>
import { useToast } from "@/composables/useToast"
import { useWhatsAppStatement } from "@/composables/useWhatsAppStatement"
import {
	DEFAULT_CURRENCY,
	formatCurrency as formatCurrencyUtil,
} from "@/utils/currency"
import { isOffline } from "@/utils/offline/offlineState"
import { normalizeSearchText } from "@/utils/searchText"
import { __ } from "@/utils/translation"
import { call, LoadingIndicator } from "frappe-ui"
import { computed, ref, watch } from "vue"
import { useDialogSubmit } from "@/composables/useDialogSubmit"

const props = defineProps({
	modelValue: Boolean,
	posProfile: String,
	company: {
		type: String,
		default: "",
	},
	currency: {
		type: String,
		default: DEFAULT_CURRENCY,
	},
})

const emit = defineEmits(["update:modelValue", "select-customer"])

const { showError } = useToast()
const { sharingCustomer, shareStatement } = useWhatsAppStatement()

const show = computed({
	get: () => props.modelValue,
	set: (val) => emit("update:modelValue", val),
})

const loading = ref(false)
const summary = ref(null)
const searchTerm = ref("")
const sortOrder = ref("amount")

const filteredCustomers = computed(() => {
	if (!summary.value) return []
	const term = normalizeSearchText(searchTerm.value).trim()
	let list = term
		? summary.value.customers.filter((c) =>
				normalizeSearchText(c.customer_name || c.customer).includes(term),
		  )
		: summary.value.customers
	list = [...list]
	if (sortOrder.value === "name") {
		list.sort((a, b) => (a.customer_name || a.customer).localeCompare(b.customer_name || b.customer))
	} else {
		list.sort((a, b) => Math.abs(b.net_balance) - Math.abs(a.net_balance))
	}
	return list
})

watch(
	() => props.modelValue,
	(val) => {
		if (val) {
			summary.value = null
			searchTerm.value = ""
			loadSummary()
		}
	},
)

async function loadSummary() {
	loading.value = true
	try {
		const result = await call(
			"pos_next.api.customer_dues.get_credit_customers_summary",
			{
				pos_profile: props.posProfile || undefined,
				company: props.company || undefined,
			},
		)
		summary.value = result
	} catch (error) {
		showError(error.message || __("Failed to load credit sales"))
		summary.value = null
	} finally {
		loading.value = false
	}
}

function shareViaWhatsApp(row) {
	shareStatement(row.customer, {
		company: props.company,
		posProfile: props.posProfile,
		currency: summary.value?.currency || props.currency,
		customerName: row.customer_name,
	})
}

function handleClose() {
	show.value = false
}

useDialogSubmit({
	isOpen: show,
	onSubmit: () => {},
	enter: false,
	ctrlS: false,
	onEscape: handleClose,
})

function formatCurrency(amount) {
	const cur = summary.value?.currency || props.currency
	return formatCurrencyUtil(Number.parseFloat(amount || 0), cur)
}
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
	transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
	opacity: 0;
}
[dir="rtl"] .rtl-flip {
	transform: scaleX(-1);
}
</style>
