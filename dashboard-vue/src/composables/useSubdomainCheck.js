import { reactive } from "vue";
import { useSitesStore } from "../stores/sites";

// Debounced, race-safe live availability check for a desired store subdomain.
// The component owns the input; this owns the "is it free?" question and its display state.
export function useSubdomainCheck() {
  const store = useSitesStore();
  const state = reactive({
    input: "",
    normalized: "",
    hostname: "",
    available: false,
    reason: "",
    suggestions: [],
    checking: false,
    checked: false,
  });
  let timer = null;
  let seq = 0;

  function clear() {
    if (timer) clearTimeout(timer);
    state.input = state.normalized = state.hostname = state.reason = "";
    state.available = state.checking = state.checked = false;
    state.suggestions = [];
  }

  function check(name, siteId = "") {
    state.input = name;
    if (timer) clearTimeout(timer);
    const trimmed = String(name || "").trim();
    if (!trimmed) {
      state.checking = state.checked = state.available = false;
      state.reason = "";
      state.suggestions = [];
      state.normalized = state.hostname = "";
      return;
    }
    state.checking = true;
    const mine = ++seq;
    timer = setTimeout(async () => {
      try {
        const res = await store.checkSubdomain(trimmed, siteId);
        if (mine !== seq) return; // a newer keystroke superseded this one
        state.normalized = res.normalized || "";
        state.hostname = res.hostname || "";
        state.available = !!res.available;
        state.reason = res.reason || "";
        state.suggestions = Array.isArray(res.suggestions) ? res.suggestions : [];
        state.checked = true;
      } catch (error) {
        if (mine !== seq) return;
        state.available = false;
        state.reason = error.message || "Could not check availability.";
        state.suggestions = [];
        state.checked = true;
      } finally {
        if (mine === seq) state.checking = false;
      }
    }, 350);
  }

  return { state, check, clear };
}
