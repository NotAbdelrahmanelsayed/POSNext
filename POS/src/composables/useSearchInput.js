import { ref, watch, nextTick, onUnmounted } from "vue"
import { QueuedMutex } from "@/utils/mutex"

/**
 * Composable for search input, barcode scanning, and auto-add logic.
 *
 * Owns all search-input state, timers, and event handlers with proper
 * concurrency control.  Extracted from ItemsSelector.vue.
 *
 * Concurrency model:
 *   - On Enter (or auto-add timeout), the barcode is **snapshotted** from the
 *     DOM input immediately, then the input is cleared so the next scan starts
 *     into a clean field.
 *   - The snapshot is pushed into a {@link QueuedMutex}-backed queue
 *     (`processBarcodeScan`), which processes barcode lookups sequentially.
 *   - This guarantees no barcode is ever lost, even when scanning different
 *     items faster than the API can respond (~50 ms between scans).
 *
 * @param {Object} options
 * @param {Object} options.itemStore          - Pinia item-search store
 * @param {(item: Object, autoAdd: boolean) => boolean} options.onItemFound
 *        Component's selectItem(). Returns true if item was accepted.
 * @param {Object} options.showWarning        - useToast().showWarning
 * @param {import('vue').Ref<boolean>} options.isAnyDialogOpen
 */
export function useSearchInput({
	itemStore,
	onItemFound,
	showWarning,
	isAnyDialogOpen,
}) {
	// --- Reactive state (exposed) ---
	const searchInputRef = ref(null)
	const scannerEnabled = ref(true)
	const autoAddEnabled = ref(false)

	// --- Internal (non-reactive) ---
	let autoSearchTimer = null
	const barcodeQueue = new QueuedMutex({
		timeout: 10000,
		name: "BarcodeSearch",
	})

	// ---- Timer helpers ----

	function clearAutoSearchTimer() {
		if (autoSearchTimer) {
			clearTimeout(autoSearchTimer)
			autoSearchTimer = null
		}
	}

	// ---- Focus ----

	function focusSearchInput() {
		nextTick(() => {
			if (searchInputRef.value) {
				searchInputRef.value.focus()
			}
		})
	}

	// ---- Clear ----

	/** Atomic clear: timer -> store -> DOM input.value -> refocus */
	function clearSearchAndResetInput() {
		clearAutoSearchTimer()
		itemStore.clearSearch()
		if (searchInputRef.value) {
			searchInputRef.value.value = ""
		}
		if (scannerEnabled.value || autoAddEnabled.value) {
			focusSearchInput()
		}
	}

	// ---- Event handlers ----

	function handleKeyDown(event) {
		if (event.key === "Enter") {
			event.preventDefault()
			clearAutoSearchTimer()

			// Snapshot the barcode NOW from the DOM input, before anything overwrites it
			const barcode =
				searchInputRef.value?.value?.trim() || itemStore.searchTerm?.trim()
			if (!barcode) return

			// Snapshot the top search result NOW, before clearSearch() resets
			// filteredItems to the full cached list. The searchTerm guard ensures
			// this is a real search result, not the browse list — filteredItems
			// sources from searchResults when a term is set (stores/itemSearch.js).
			const firstResult =
				(itemStore.searchTerm && itemStore.filteredItems?.[0]) || null

			// If search results are visible and NOT in scanner mode, add the first one directly.
			// In scanner mode always fall through to exact barcode lookup — cache results
			// can arrive before the scanner's Enter event and cause the wrong item to be added.
			if (firstResult && !scannerEnabled.value) {
				onItemFound(firstResult, autoAddEnabled.value)
				clearSearchAndResetInput()
				focusSearchInput()
				return
			}

			// Scanner path: barcode-first, then top-result fallback. Exact barcode
			// scans stay correct; if no barcode matches, the snapshotted top result
			// is added (same item Alt+1 adds).
			itemStore.clearSearch()
			if (searchInputRef.value) searchInputRef.value.value = ""
			processBarcodeScan(barcode, autoAddEnabled.value, firstResult)
			return
		}
		// All other keys: no special handling needed.
	}

	/**
	 * Handles the `input` event on the search <input>.
	 *
	 * Two independent timers exist by design:
	 *   1. itemStore.setSearchTerm() triggers the store's own debounce for
	 *      updating the displayed item grid.
	 *   2. autoSearchTimer (500 ms) triggers auto-add behaviour — completely
	 *      separate from display.
	 */
	function handleSearchInput(event) {
		const value = event.target.value

		// Guard: ignore stale empty events after search was already cleared
		if (!value && !itemStore.searchTerm) {
			return
		}

		itemStore.setSearchTerm(value)

		clearAutoSearchTimer()

		// Auto-add: after user stops typing for 500 ms, trigger barcode search
		if (autoAddEnabled.value && value.trim().length > 0) {
			autoSearchTimer = setTimeout(() => {
				const barcode =
					searchInputRef.value?.value?.trim() || itemStore.searchTerm?.trim()
				if (barcode) {
					// Snapshot the top result before clearSearch() so typed names
					// auto-add instead of warning "not found".
					const fallbackItem =
						(itemStore.searchTerm && itemStore.filteredItems?.[0]) || null
					itemStore.clearSearch()
					if (searchInputRef.value) searchInputRef.value.value = ""
					processBarcodeScan(barcode, true, fallbackItem)
				}
			}, 500)
		}
	}

	/** Clicking the search input clears search + timer atomically. */
	function handleSearchClick() {
		clearSearchAndResetInput()
	}

	/**
	 * Queue a barcode scan for sequential processing.
	 *
	 * The barcode string is already captured (snapshotted) by the caller —
	 * it is never read from shared state here. The {@link QueuedMutex}
	 * ensures scans execute one at a time so every scan is resolved before
	 * the next begins, preventing double-adds and lost barcodes.
	 *
	 * Lookup: exact barcode match via `itemStore.searchByBarcode()`.
	 * Barcode-first, then top-result fallback: if the exact barcode lookup
	 * misses and the caller passed a `fallbackItem` (the snapshotted top search
	 * result — the same item Alt+1 would add), that item is added instead of
	 * warning. Known scanned barcodes always resolve exactly, so the fallback
	 * only fires for non-barcode (typed) input. The "not found" warning shows
	 * only when there is no fallback item.
	 *
	 * @param {string}      barcode      - Pre-captured barcode value
	 * @param {boolean}     forceAutoAdd - When true, item is added without user click
	 * @param {Object|null} fallbackItem - Snapshotted top search result, captured
	 *        by the caller before clearSearch() (since clearSearch() resets
	 *        filteredItems to the full cached list). Added when the barcode misses.
	 */
	function processBarcodeScan(barcode, forceAutoAdd, fallbackItem = null) {
		const shouldAutoAdd =
			forceAutoAdd || (scannerEnabled.value && autoAddEnabled.value)

		barcodeQueue.withLock(async () => {
			try {
				const item = await itemStore.searchByBarcode(barcode)
				if (item) {
					onItemFound(item, shouldAutoAdd)
					focusSearchInput()
					return
				}
			} catch (error) {
				console.error("Barcode API error:", error)
			}

			// Barcode not found → fall back to the snapshotted top search result
			// (same item Alt+1 adds) when the caller provided one.
			if (fallbackItem) {
				onItemFound(fallbackItem, shouldAutoAdd)
				focusSearchInput()
				return
			}

			// No barcode match and no fallback — show clear "not found" message.
			showWarning(
				__("Item Not Found: No item found with barcode: {0}", [barcode]),
			)
			focusSearchInput()
		})
	}

	// ---- Toggles ----

	function toggleBarcodeScanner() {
		scannerEnabled.value = !scannerEnabled.value
		if (scannerEnabled.value) {
			focusSearchInput()
		}
	}

	function toggleAutoAdd() {
		autoAddEnabled.value = !autoAddEnabled.value

		if (autoAddEnabled.value && !scannerEnabled.value) {
			scannerEnabled.value = true
		}

		if (!autoAddEnabled.value) {
			clearAutoSearchTimer()
		}

		if (autoAddEnabled.value) {
			focusSearchInput()
		}
	}

	// ---- Dialog-close watcher ----
	// Refocuses the search bar when all dialogs close (scanner/auto-add modes)
	const stopDialogWatcher = watch(isAnyDialogOpen, (isOpen, wasOpen) => {
		if (wasOpen && !isOpen && (scannerEnabled.value || autoAddEnabled.value)) {
			focusSearchInput()
		}
	})

	// ---- Cleanup ----
	function cleanup() {
		clearAutoSearchTimer()
		stopDialogWatcher()
	}

	onUnmounted(cleanup)

	return {
		// State
		searchInputRef,
		scannerEnabled,
		autoAddEnabled,

		// Event handlers
		handleSearchInput,
		handleKeyDown,
		handleSearchClick,

		// Toggles
		toggleBarcodeScanner,
		toggleAutoAdd,

		// Utilities
		focusSearchInput,
		clearSearchAndResetInput,
		cleanup,
	}
}
