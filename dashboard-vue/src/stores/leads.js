import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

export const LEAD_STATUSES = ["new", "contacted", "qualified", "archived"];

export function leadStatusLabel(status) {
  return {
    new: "New",
    contacted: "Contacted",
    qualified: "Qualified",
    archived: "Archived",
  }[status] || status || "New";
}

export function leadStatusClass(status) {
  return {
    new: "warning",
    contacted: "active",
    qualified: "active",
    archived: "archived",
  }[status] || "inactive";
}

export function leadPrimaryContact(lead) {
  const fields = lead?.fields || {};
  return fields.name || fields.email || fields.phone || "Anonymous lead";
}

export const useLeadsStore = defineStore("leads", {
  state: () => ({
    leads: [],
    loading: false,
    loaded: false,
    saving: "",
    error: "",
    message: "Loading leads…",
    filterStatus: "all",
  }),

  getters: {
    filteredLeads(state) {
      if (state.filterStatus === "all") return state.leads;
      return state.leads.filter((lead) => lead.status === state.filterStatus);
    },
  },

  actions: {
    reset() {
      this.leads = [];
      this.loading = false;
      this.loaded = false;
      this.error = "";
      this.message = "Loading leads…";
      this.filterStatus = "all";
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/leads");
        this.leads = Array.isArray(body.leads) ? body.leads : [];
        this.loaded = true;
        this.message = this.leads.length
          ? `${this.leads.length} lead${this.leads.length === 1 ? "" : "s"}.`
          : "No leads captured yet.";
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.loading = false;
      }
    },

    async setStatus(lead, status) {
      this.saving = lead.lead_id;
      this.error = "";
      try {
        const result = await apiRequest(`/leads/${encodeURIComponent(lead.lead_id)}`, {
          method: "PATCH",
          body: { status },
        });
        if (result.lead) this._replace(result.lead);
        this.message = `Marked ${leadStatusLabel(status).toLowerCase()}.`;
        return result;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
        throw error;
      } finally {
        this.saving = "";
      }
    },

    _replace(lead) {
      const index = this.leads.findIndex((item) => item.lead_id === lead.lead_id);
      if (index >= 0) this.leads.splice(index, 1, lead);
      else this.leads.unshift(lead);
    },
  },
});
