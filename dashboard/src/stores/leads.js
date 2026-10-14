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
    filterSession: "all",
  }),

  getters: {
    filteredLeads(state) {
      let rows = state.leads;
      if (state.filterStatus !== "all") rows = rows.filter((lead) => lead.status === state.filterStatus);
      // A webinar registration is a lead carrying its session (plans/WEBINAR.md §4). "Who is coming on
      // Wednesday" is the question a host asks on the morning of a session, and without this the two
      // sittings of one event are indistinguishable in the list.
      if (state.filterSession === "registrations") {
        rows = rows.filter((lead) => lead.event_id);
      } else if (state.filterSession !== "all") {
        const [eventId, occurrenceId] = String(state.filterSession).split("::");
        rows = rows.filter((lead) => lead.event_id === eventId
          && (!occurrenceId || lead.occurrence_id === occurrenceId));
      }
      return rows;
    },
  },

  actions: {
    reset() {
      this.leads = [];
      this.loading = false;
      this.loaded = false;
      this.error = "";
      this.filterSession = "all";
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
