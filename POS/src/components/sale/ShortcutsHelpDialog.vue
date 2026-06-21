<template>
	<Teleport to="body">
		<Transition
			enter-active-class="transition-opacity duration-150"
			enter-from-class="opacity-0"
			enter-to-class="opacity-100"
			leave-active-class="transition-opacity duration-100"
			leave-from-class="opacity-100"
			leave-to-class="opacity-0"
		>
			<div
				v-if="modelValue"
				class="fixed inset-0 z-[200] flex items-center justify-center p-4"
				@click.self="close"
				@keydown.escape="close"
				role="dialog"
				aria-modal="true"
				:aria-label="__('Keyboard shortcuts')"
			>
				<!-- Backdrop -->
				<div class="absolute inset-0 bg-black/40" />

				<!-- Modal -->
				<div
					class="relative bg-white rounded-xl shadow-2xl w-full max-w-md max-h-[80vh] overflow-y-auto"
					ref="panelRef"
					tabindex="-1"
				>
					<!-- Header -->
					<div class="flex items-center justify-between px-5 py-4 border-b border-gray-100">
						<div class="flex items-center gap-2">
							<svg class="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
									d="M12 4v1m0 14v1M4 12H3m18 0h-1m-2.05-6.95-.71.71M6.76 17.24l-.71.71M17.24 17.24l.71.71M6.76 6.76l-.71-.71M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
							</svg>
							<h2 class="text-base font-semibold text-gray-800">{{ __("Keyboard shortcuts") }}</h2>
						</div>
						<button
							@click="close"
							class="p-1 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors"
							:aria-label="__('Close')"
						>
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
							</svg>
						</button>
					</div>

					<!-- Groups -->
					<div class="p-5 flex flex-col gap-5">
						<div v-for="group in shortcutGroups" :key="group.title">
							<h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
								{{ group.title }}
							</h3>
							<div class="flex flex-col gap-2">
								<div
									v-for="shortcut in group.shortcuts"
									:key="shortcut.label"
									class="flex items-center justify-between"
								>
									<span class="text-sm text-gray-700">{{ shortcut.label }}</span>
									<div class="flex items-center gap-1 flex-shrink-0">
										<kbd
											v-for="(key, i) in shortcut.keys"
											:key="i"
											class="font-mono text-[11px] leading-none bg-gray-100 text-gray-700 border border-gray-300 rounded px-1.5 py-1 select-none"
										>{{ key }}</kbd>
									</div>
								</div>
							</div>
						</div>
					</div>

					<!-- Footer hint -->
					<div class="px-5 pb-4 text-center">
						<span class="text-xs text-gray-400">{{ __("Press") }} <kbd class="font-mono text-[10px] bg-gray-100 border border-gray-300 rounded px-1 py-0.5">?</kbd> {{ __("or Esc to close") }}</span>
					</div>
				</div>
			</div>
		</Transition>
	</Teleport>
</template>

<script setup>
import { getShortcutGroups } from "@/config/shortcuts"
import { __ } from "@/utils/translation"
import { nextTick, ref, watch } from "vue"

const props = defineProps({
	modelValue: Boolean,
})

const emit = defineEmits(["update:modelValue"])

const panelRef = ref(null)
const shortcutGroups = getShortcutGroups()

function close() {
	emit("update:modelValue", false)
}

watch(
	() => props.modelValue,
	async (val) => {
		if (val) {
			await nextTick()
			panelRef.value?.focus()
		}
	},
)
</script>
