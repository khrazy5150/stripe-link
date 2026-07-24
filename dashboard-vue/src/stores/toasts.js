import { defineStore } from "pinia";

// Transient toast pop-ups for critical events (sale, refund request, set up Stripe). Separate from the
// persistent bell notifications — a toast is a one-time nudge; the bell remains the durable record.
let seq = 0;

export const useToastsStore = defineStore("toasts", {
  state: () => ({ items: [] }),
  actions: {
    push(toast) {
      const id = ++seq;
      // `key` de-dupes: pushing the same key twice (e.g. the setup nudge) won't stack.
      if (toast.key && this.items.some((t) => t.key === toast.key)) return null;
      this.items.push({ id, severity: "info", sticky: false, icon: "", message: "", route: "", ...toast });
      return id;
    },
    dismiss(id) {
      this.items = this.items.filter((t) => t.id !== id);
    },
    clear() {
      this.items = [];
    },
  },
});
