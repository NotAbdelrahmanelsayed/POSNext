<template>
	<kbd
		:class="[
			'hidden md:inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold font-mono rounded border whitespace-nowrap pointer-events-none select-none',
			variant === 'overlay'
				? 'text-white/90 bg-white/20 border-white/30'
				: 'text-gray-500 bg-gray-100 border-gray-300',
		]"
	>
		{{ keys }}
	</kbd>
</template>

<script setup>
/**
 * Small keyboard-shortcut badge shown next to controls (desktop only).
 * Use variant="overlay" on colored/solid buttons.
 */
defineProps({
	keys: { type: String, required: true },
	variant: { type: String, default: "light" },
})
</script>
