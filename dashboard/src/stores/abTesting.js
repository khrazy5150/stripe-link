import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

export function formatCurrencyCents(cents, currency = "usd") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: String(currency || "usd").toUpperCase(),
  }).format(Number(cents || 0) / 100);
}

export function formatConversionRate(rate) {
  return `${(Number(rate || 0) * 100).toFixed(1)}%`;
}

export function statusLabel(status) {
  return {
    draft: "Draft",
    running: "Running",
    paused: "Paused",
    completed: "Completed",
  }[status] || "Draft";
}

export function totalWeight(variants) {
  return (variants || []).reduce((sum, variant) => sum + Number(variant.weight || 0), 0);
}

function buildExperimentPayload(form) {
  return {
    name: String(form.name || "").trim(),
    control_page_id: form.control_page_id,
    variants: (form.variants || [])
      .filter((variant) => variant.page_id)
      .map((variant) => ({
        page_id: variant.page_id,
        weight: Math.max(0, Math.round(Number(variant.weight || 0))),
        label: String(variant.label || "").trim(),
      })),
  };
}

export const useAbTestingStore = defineStore("abTesting", {
  state: () => ({
    experiments: [],
    pages: [],
    loading: false,
    loaded: false,
    saving: false,
    error: "",
    message: "Loading experiments…",
    results: {},
  }),

  getters: {
    publishedPages(state) {
      return state.pages.filter((page) => page.status === "published");
    },
    pageName(state) {
      const byId = Object.fromEntries(state.pages.map((page) => [page.page_id, page]));
      return (pageId) => byId[pageId]?.name || pageId;
    },
  },

  actions: {
    reset() {
      this.experiments = [];
      this.pages = [];
      this.loading = false;
      this.loaded = false;
      this.saving = false;
      this.error = "";
      this.message = "Loading experiments…";
      this.results = {};
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const [experiments, pages] = await Promise.all([
          apiRequest("/experiments"),
          apiRequest("/pages"),
        ]);
        this.experiments = Array.isArray(experiments.experiments) ? experiments.experiments : [];
        this.pages = Array.isArray(pages.pages) ? pages.pages : [];
        this.loaded = true;
        this.message = this.experiments.length
          ? `${this.experiments.length} experiment${this.experiments.length === 1 ? "" : "s"}.`
          : "No experiments yet. Create one to start split-testing your pages.";
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.loading = false;
      }
    },

    async create(form) {
      return this._mutate(async () => {
        const body = await apiRequest("/experiments", { method: "POST", body: buildExperimentPayload(form) });
        if (body.experiment) this.experiments.unshift(body.experiment);
        return body.experiment;
      }, "Experiment created.");
    },

    async update(experimentId, form) {
      return this._mutate(async () => {
        const body = await apiRequest(`/experiments/${encodeURIComponent(experimentId)}`, {
          method: "PUT",
          body: buildExperimentPayload(form),
        });
        this._replace(body.experiment);
        return body.experiment;
      }, "Experiment updated.");
    },

    async start(experimentId) {
      return this._mutate(async () => {
        const body = await apiRequest(`/experiments/${encodeURIComponent(experimentId)}/start`, { method: "POST" });
        this._replace(body.experiment);
        return body.experiment;
      }, "Experiment started.");
    },

    async pause(experimentId) {
      return this._mutate(async () => {
        const body = await apiRequest(`/experiments/${encodeURIComponent(experimentId)}/pause`, { method: "POST" });
        this._replace(body.experiment);
        return body.experiment;
      }, "Experiment paused.");
    },

    async complete(experimentId, winnerPageId) {
      return this._mutate(async () => {
        const body = await apiRequest(`/experiments/${encodeURIComponent(experimentId)}/complete`, {
          method: "POST",
          body: { winner_page_id: winnerPageId },
        });
        this._replace(body.experiment);
        return body.experiment;
      }, "Winner selected. Experiment completed.");
    },

    async remove(experimentId) {
      return this._mutate(async () => {
        await apiRequest(`/experiments/${encodeURIComponent(experimentId)}`, { method: "DELETE" });
        this.experiments = this.experiments.filter((item) => item.experiment_id !== experimentId);
        delete this.results[experimentId];
      }, "Experiment deleted.");
    },

    async loadResults(experimentId) {
      this.error = "";
      try {
        const body = await apiRequest(`/experiments/${encodeURIComponent(experimentId)}`);
        if (body.experiment) this._replace(body.experiment);
        this.results = { ...this.results, [experimentId]: Array.isArray(body.results) ? body.results : [] };
        return body.results;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
        throw error;
      }
    },

    _replace(experiment) {
      if (!experiment) return;
      const index = this.experiments.findIndex((item) => item.experiment_id === experiment.experiment_id);
      if (index >= 0) this.experiments.splice(index, 1, experiment);
      else this.experiments.unshift(experiment);
    },

    async _mutate(operation, successMessage) {
      this.saving = true;
      this.error = "";
      try {
        const result = await operation();
        this.message = successMessage;
        return result;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
        throw error;
      } finally {
        this.saving = false;
      }
    },
  },
});
