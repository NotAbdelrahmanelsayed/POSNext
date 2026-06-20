import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, h, ref } from "vue"
import { useDialogSubmit } from "@/composables/useDialogSubmit"

// Mounts a throwaway component that wires useDialogSubmit, so the composable
// runs inside a real component instance (it relies on onBeforeUnmount + watch).
function mountDialog(options) {
	const isOpen = options.isOpen ?? ref(false)
	const wrapper = mount(
		defineComponent({
			setup() {
				useDialogSubmit({ ...options, isOpen })
				return () => h("div")
			},
		}),
	)
	return { wrapper, isOpen }
}

function press(key, { ctrl = false, meta = false, target = null } = {}) {
	const event = new KeyboardEvent("keydown", {
		key,
		ctrlKey: ctrl,
		metaKey: meta,
		bubbles: true,
		cancelable: true,
	})
	if (target) {
		Object.defineProperty(event, "target", { value: target })
	}
	window.dispatchEvent(event)
	return event
}

describe("useDialogSubmit", () => {
	beforeEach(() => {
		// Each test starts with a clean window listener state.
		vi.restoreAllMocks()
	})

	it("does nothing while the dialog is closed", () => {
		const onSubmit = vi.fn()
		mountDialog({ isOpen: ref(false), onSubmit })
		press("Enter")
		press("s", { ctrl: true })
		expect(onSubmit).not.toHaveBeenCalled()
	})

	it("Enter submits when open and Ctrl+S submits too", async () => {
		const onSubmit = vi.fn()
		const isOpen = ref(false)
		mountDialog({ isOpen, onSubmit })
		isOpen.value = true
		await Promise.resolve()

		press("Enter")
		expect(onSubmit).toHaveBeenCalledTimes(1)

		press("s", { ctrl: true })
		expect(onSubmit).toHaveBeenCalledTimes(2)

		press("S", { meta: true })
		expect(onSubmit).toHaveBeenCalledTimes(3)
	})

	it("Ctrl+S always prevents the browser save, even when guarded off", async () => {
		const onSubmit = vi.fn()
		const isOpen = ref(true)
		mountDialog({ isOpen, onSubmit, canSubmit: () => false })
		await Promise.resolve()

		const event = press("s", { ctrl: true })
		expect(event.defaultPrevented).toBe(true)
		expect(onSubmit).not.toHaveBeenCalled()
	})

	it("respects enter:false (Ctrl+S only)", async () => {
		const onSubmit = vi.fn()
		const isOpen = ref(true)
		mountDialog({ isOpen, onSubmit, enter: false })
		await Promise.resolve()

		press("Enter")
		expect(onSubmit).not.toHaveBeenCalled()

		press("s", { ctrl: true })
		expect(onSubmit).toHaveBeenCalledTimes(1)
	})

	it("skips Enter inside a textarea but still allows Ctrl+S", async () => {
		const onSubmit = vi.fn()
		const isOpen = ref(true)
		mountDialog({ isOpen, onSubmit })
		await Promise.resolve()

		const textarea = document.createElement("textarea")
		press("Enter", { target: textarea })
		expect(onSubmit).not.toHaveBeenCalled()

		press("s", { ctrl: true, target: textarea })
		expect(onSubmit).toHaveBeenCalledTimes(1)
	})

	it("honors the canSubmit guard for Enter", async () => {
		const onSubmit = vi.fn()
		const isOpen = ref(true)
		const allowed = ref(false)
		mountDialog({ isOpen, onSubmit, canSubmit: () => allowed.value })
		await Promise.resolve()

		press("Enter")
		expect(onSubmit).not.toHaveBeenCalled()

		allowed.value = true
		press("Enter")
		expect(onSubmit).toHaveBeenCalledTimes(1)
	})

	it("only the top-most dialog reacts when two are stacked", async () => {
		const parent = vi.fn()
		const child = vi.fn()
		const parentOpen = ref(true)
		const childOpen = ref(false)
		mountDialog({ isOpen: parentOpen, onSubmit: parent })
		mountDialog({ isOpen: childOpen, onSubmit: child })
		await Promise.resolve()

		// Only parent open → parent reacts.
		press("Enter")
		expect(parent).toHaveBeenCalledTimes(1)
		expect(child).not.toHaveBeenCalled()

		// Child opens on top → only child reacts.
		childOpen.value = true
		await Promise.resolve()
		press("Enter")
		expect(child).toHaveBeenCalledTimes(1)
		expect(parent).toHaveBeenCalledTimes(1)

		// Child closes → parent is top again.
		childOpen.value = false
		await Promise.resolve()
		press("Enter")
		expect(parent).toHaveBeenCalledTimes(2)
		expect(child).toHaveBeenCalledTimes(1)
	})

	it("ignores a plain Enter once unmounted", async () => {
		const onSubmit = vi.fn()
		const isOpen = ref(true)
		const { wrapper } = mountDialog({ isOpen, onSubmit })
		await Promise.resolve()
		wrapper.unmount()
		press("Enter")
		expect(onSubmit).not.toHaveBeenCalled()
	})
})
