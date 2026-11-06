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
    ownedByYou: false,
    reason: "",
    suggestions: [],
    checking: false,
    checked: false,
    // A check that could not be MADE, as opposed to one that came back negative. They were the same
    // state until 2026-11-06, and that is how a network blip disabled Save until the tenant happened to
    // retype the address: an error was being stored as a verdict, and nothing downstream could tell.
    failed: false,
  });
  let timer = null;
  let seq = 0;

  function clear() {
    if (timer) clearTimeout(timer);
    state.input = state.normalized = state.hostname = state.reason = "";
    state.available = state.ownedByYou = state.checking = state.checked = state.failed = false;
    state.suggestions = [];
  }

  function check(name, siteId = "") {
    state.input = name;
    if (timer) clearTimeout(timer);
    const trimmed = String(name || "").trim();
    if (!trimmed) {
      state.checking = state.checked = state.available = state.ownedByYou = state.failed = false;
      state.reason = "";
      state.suggestions = [];
      state.normalized = state.hostname = "";
      return;
    }
    state.checking = true;
    state.failed = false;
    const mine = ++seq;
    timer = setTimeout(async () => {
      try {
        const res = await store.checkSubdomain(trimmed, siteId);
        if (mine !== seq) return; // a newer keystroke superseded this one
        state.normalized = res.normalized || "";
        state.hostname = res.hostname || "";
        state.available = !!res.available;
        state.ownedByYou = !!res.owned_by_you;
        state.reason = res.reason || "";
        state.suggestions = Array.isArray(res.suggestions) ? res.suggestions : [];
        state.checked = true;
        state.failed = false;
      } catch (error) {
        if (mine !== seq) return;
        // NOT `checked`. We did not learn that the address is taken, we learned nothing -- and the
        // caller gates Save on `checked && !available`, so claiming a verdict here locked the tenant out
        // of saving an address that was never in question.
        state.available = state.ownedByYou = state.checked = false;
        state.reason = error.message || "Could not check availability.";
        state.suggestions = [];
        state.failed = true;
      } finally {
        if (mine === seq) state.checking = false;
      }
    }, 350);
  }

  return { state, check, clear };
}
