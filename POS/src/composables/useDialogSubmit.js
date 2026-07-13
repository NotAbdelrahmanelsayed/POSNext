import { onBeforeUnmount, unref, watch } from "vue"

/**
 * Consistent keyboard confirm/close for dialogs.
 *
 * Wires a window-level `keydown` listener (bubble phase) while a dialog is open and
 * invokes the dialog's primary action on **Ctrl/Cmd+S** (universal) and optionally
 * **Enter**, and its close handler on **Esc** when `onEscape` is supplied.
 *
 * Bubble phase matters: it runs *after* any local element handler, so a local
 * `@keydown.enter.prevent` can suppress this listener (via `event.defaultPrevented`)
 * and `@keydown.enter.stop` can keep it from ever seeing the event. Only `onEscape`
 * should be passed for hand-rolled overlay dialogs — frappe-ui `Dialog` already closes
 * on Esc natively (reka-ui), so passing it there would double-close.
 *
 * A focused BUTTON only blocks Enter once the user has actually tabbed to it. Dialogs
 * auto-focus their first focusable element on open (usually the header × close button,
 * not an input) — treating that auto-focus as "intentional" would make Enter silently
 * re-click the close button instead of confirming, on every dialog with no input.
 *
 * Why a module-level stack: dialogs can stack (CustomerDialog → CreateCustomerDialog,
 * PartialPayments → PaymentDialog). Only the top-most open instance should react to a
 * keypress, otherwise a parent dialog would submit/close at the same time as its child.
 * This is intentionally independent of `useDialogState` (which has no ordering).
 *
 * @example
 * useDialogSubmit({
 *   isOpen: show,
 *   onSubmit: handleCreate,
 *   canSubmit: () => !!customerData.customer_name && hasPermission,
 *   onEscape: handleClose, // only for hand-rolled dialogs; omit for frappe-ui Dialog
 *   enter: true,   // default
 *   ctrlS: true,   // default
 * })
 */

// Module-level ordered stack of open dialog instance ids (last = top-most).
const openDialogStack = []
let nextInstanceId = 0

// Registry of instance id → its keydown config, so the single shared listener can
// dispatch to whichever instance is currently on top of the stack.
const instances = new Map()

let listenerAttached = false

// Elements whose native Enter behaviour (activate, pick, insert newline) must win.
const ENTER_HIJACK_TAGS = new Set(["TEXTAREA", "BUTTON", "SELECT", "A"])

function isEditableTarget(target) {
	if (!target || !target.tagName) return false
	if (ENTER_HIJACK_TAGS.has(target.tagName)) return true
	if (typeof target.closest === "function" && target.closest("[contenteditable]")) return true
	return false
}

function handleKeydown(event) {
	if (openDialogStack.length === 0) return
	// IME candidate commit — never treat as submit/close.
	if (event.isComposing || event.keyCode === 229) return

	const topId = openDialogStack[openDialogStack.length - 1]
	const instance = instances.get(topId)
	if (!instance) return

	// Dialogs auto-focus their first focusable element on open (frappe-ui/reka-ui puts
	// that on the header close ×, not an input). Track real Tab navigation so a BUTTON
	// only counts as "intentionally focused" — and therefore off-limits to Enter — once
	// the user has actually tabbed to it. Otherwise Enter would silently just re-click
	// whatever button happened to receive that initial auto-focus.
	if (event.key === "Tab") {
		instance.tabbed = true
		return
	}

	const { onSubmit, canSubmit, enter, ctrlS, onEscape } = instance

	const isCtrlS =
		(event.ctrlKey || event.metaKey) && (event.key === "s" || event.key === "S")
	const isEnter = event.key === "Enter"
	const isEscape = event.key === "Escape"

	const allowed = () => !canSubmit || canSubmit()

	if (isCtrlS) {
		// Always suppress the browser "Save page" dialog, regardless of guard.
		event.preventDefault()
		if (ctrlS && allowed()) {
			onSubmit()
		}
		return
	}

	if (isEscape) {
		if (onEscape) onEscape()
		return
	}

	if (isEnter) {
		if (!enter) return
		const target = event.target
		if (isEditableTarget(target)) {
			// A BUTTON only wins over us if the user actually tabbed to it; an
			// auto-focused button (dialog just opened, nobody navigated yet) shouldn't
			// silently eat Enter instead of confirming.
			const isUnnavigatedAutoFocusButton = target.tagName === "BUTTON" && !instance.tabbed
			if (!isUnnavigatedAutoFocusButton) return
			// Stop the native click this Enter would otherwise trigger on that button.
			event.preventDefault()
		} else if (event.defaultPrevented) {
			return
		}
		if (allowed()) {
			onSubmit()
		}
	}
}

function attachListener() {
	if (listenerAttached) return
	window.addEventListener("keydown", handleKeydown)
	listenerAttached = true
}

function detachListener() {
	if (!listenerAttached) return
	window.removeEventListener("keydown", handleKeydown)
	listenerAttached = false
}

export function useDialogSubmit(options) {
	const {
		isOpen,
		onSubmit,
		canSubmit = null,
		enter = true,
		ctrlS = true,
		onEscape = null,
	} = options

	const id = nextInstanceId++

	const pushToStack = () => {
		instances.set(id, { onSubmit, canSubmit, enter, ctrlS, onEscape, tabbed: false })
		// Remove any stale entry, then push to top.
		const existing = openDialogStack.indexOf(id)
		if (existing !== -1) openDialogStack.splice(existing, 1)
		openDialogStack.push(id)
		attachListener()
	}

	const removeFromStack = () => {
		const existing = openDialogStack.indexOf(id)
		if (existing !== -1) openDialogStack.splice(existing, 1)
		instances.delete(id)
		if (openDialogStack.length === 0) detachListener()
	}

	const stop = watch(
		() => unref(isOpen),
		(open) => {
			if (open) {
				pushToStack()
			} else {
				removeFromStack()
			}
		},
		{ immediate: true },
	)

	onBeforeUnmount(() => {
		stop()
		removeFromStack()
	})
}
