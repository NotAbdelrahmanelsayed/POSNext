import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, h, ref } from "vue"
import { useSearchInput } from "@/composables/useSearchInput"

// Minimal `__()` translator stub (interpolates {0} placeholders) so
// processBarcodeScan's "not found" warning can run without the real i18n layer.
beforeEach(() => {
	globalThis.__ = (str, args = []) =>
		str.replace(/\{(\d+)\}/g, (_, i) => args[Number(i)] ?? "")
})

// Mounts a throwaway component so useSearchInput runs inside a real instance
// (it relies on onUnmounted + watch). Returns the composable's public API plus
// the spies wired into it.
function mountSearchInput({
	searchTerm = "",
	filteredItems = [],
	searchByBarcode,
} = {}) {
	const itemStore = {
		searchTerm,
		filteredItems,
		clearSearch: vi.fn(),
		searchByBarcode: searchByBarcode ?? vi.fn().mockResolvedValue(null),
	}
	const onItemFound = vi.fn().mockReturnValue(true)
	const showWarning = vi.fn()
	const isAnyDialogOpen = ref(false)

	let api
	const wrapper = mount(
		defineComponent({
			setup() {
				api = useSearchInput({
					itemStore,
					onItemFound,
					showWarning,
					isAnyDialogOpen,
				})
				return () => h("div")
			},
		}),
	)
	return { wrapper, api, itemStore, onItemFound, showWarning }
}

function pressEnter(api) {
	api.handleKeyDown({ key: "Enter", preventDefault: vi.fn() })
}

describe("useSearchInput — Enter: barcode-first with top-result fallback", () => {
	beforeEach(() => {
		vi.restoreAllMocks()
	})

	it("adds the exact item when the barcode lookup hits", async () => {
		const exact = { item_code: "EXACT-1", item_name: "Exact Match" }
		const top = { item_code: "TOP-1", item_name: "Top Result" }
		const { api, onItemFound, showWarning } = mountSearchInput({
			searchTerm: "12345",
			filteredItems: [top],
			searchByBarcode: vi.fn().mockResolvedValue(exact),
		})

		pressEnter(api)
		await flushPromises()

		expect(onItemFound).toHaveBeenCalledTimes(1)
		expect(onItemFound).toHaveBeenCalledWith(exact, expect.any(Boolean))
		expect(showWarning).not.toHaveBeenCalled()
	})

	it("falls back to the snapshotted top result when the barcode misses", async () => {
		const top = { item_code: "TOP-1", item_name: "Coca Cola" }
		const { api, onItemFound, showWarning } = mountSearchInput({
			searchTerm: "coca",
			filteredItems: [top],
			searchByBarcode: vi.fn().mockResolvedValue(null),
		})

		pressEnter(api)
		await flushPromises()

		expect(onItemFound).toHaveBeenCalledTimes(1)
		expect(onItemFound).toHaveBeenCalledWith(top, expect.any(Boolean))
		expect(showWarning).not.toHaveBeenCalled()
	})

	it("warns when the barcode misses and there is no fallback item", async () => {
		const { api, onItemFound, showWarning } = mountSearchInput({
			searchTerm: "zzz-no-match",
			filteredItems: [],
			searchByBarcode: vi.fn().mockResolvedValue(null),
		})

		pressEnter(api)
		await flushPromises()

		expect(onItemFound).not.toHaveBeenCalled()
		expect(showWarning).toHaveBeenCalledTimes(1)
	})
})
