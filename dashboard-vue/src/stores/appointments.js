import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

// Lifecycle actions offered for a given status (must mirror domain/appointments.py).
export function availableActions(status) {
  switch (status) {
    case "reserved":
      return ["cancel"];
    case "booked":
    case "paid":
      return ["check-in", "complete", "cancel", "no-show"];
    case "checked_in":
      return ["complete", "cancel", "no-show"];
    default:
      return []; // completed, canceled, no_show are terminal
  }
}

export function actionLabel(action) {
  return { "check-in": "Check in", complete: "Complete", cancel: "Cancel", "no-show": "No-show", assign: "Assign" }[action] || action;
}

export const useAppointmentsStore = defineStore("appointments", {
  state: () => ({
    appointments: [],
    loading: false,
    loaded: false,
    acting: "",
    error: "",
  }),

  actions: {
    reset() {
      this.appointments = [];
      this.loaded = false;
      this.error = "";
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/services/appointments");
        this.appointments = Array.isArray(body.appointments) ? body.appointments : [];
        this.loaded = true;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    async act(appointmentId, action, payload = null) {
      this.acting = `${appointmentId}:${action}`;
      this.error = "";
      try {
        const body = await apiRequest(
          `/services/appointments/${encodeURIComponent(appointmentId)}/${action}`,
          { method: "POST", body: payload || {} },
        );
        const updated = body.appointment;
        if (updated) {
          const index = this.appointments.findIndex((a) => a.appointment_id === updated.appointment_id);
          if (index >= 0) this.appointments.splice(index, 1, updated);
        }
        return updated;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.acting = "";
      }
    },
  },
});
