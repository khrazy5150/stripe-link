import { defineStore } from "pinia";
import { apiRequest, clearAuthSession, getAuthSession, setAuthSession } from "../api/client";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    session: getAuthSession(),
    activeTab: "login",
    loading: false,
    message: "",
    error: "",
    loginForm: {
      email: "",
      password: "",
    },
    registerForm: {
      first_name: "",
      last_name: "",
      email: "",
      phone_number: "",
      password: "",
    },
    confirmForm: {
      email: "",
      code: "",
    },
    forgotForm: {
      email: "",
    },
    resetForm: {
      email: "",
      code: "",
      new_password: "",
    },
  }),

  getters: {
    isAuthenticated(state) {
      return Boolean(state.session?.client_id);
    },

    displayName(state) {
      const first = state.session?.first_name || "";
      const last = state.session?.last_name || "";
      return `${first} ${last}`.trim() || state.session?.email || "User";
    },

    initials(state) {
      return this.displayName
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase())
        .join("") || "U";
    },
  },

  actions: {
    setTab(tab) {
      this.activeTab = tab;
      this.message = "";
      this.error = "";
    },

    async login() {
      await this.run(async () => {
        const body = await apiRequest("/auth/login", {
          method: "POST",
          body: this.loginForm,
        });
        this.setSession(body.session);
        this.message = "Signed in.";
      });
    },

    async register() {
      await this.run(async () => {
        const body = await apiRequest("/auth/register", {
          method: "POST",
          body: this.registerForm,
        });
        this.confirmForm.email = this.registerForm.email;
        this.loginForm.email = this.registerForm.email;
        this.message = body.message || "Account created. Check your email for the verification code.";
        this.activeTab = "register";
      });
    },

    async confirm() {
      await this.run(async () => {
        const body = await apiRequest("/auth/confirm", {
          method: "POST",
          body: this.confirmForm,
        });
        if (body.session) this.setSession(body.session);
        this.message = body.message || "Email confirmed. You can sign in now.";
        this.activeTab = "login";
      });
    },

    async forgotPassword() {
      await this.run(async () => {
        const body = await apiRequest("/auth/forgot", {
          method: "POST",
          body: this.forgotForm,
        });
        this.resetForm.email = this.forgotForm.email;
        this.message = body.message || "Password reset code sent.";
      });
    },

    async resetPassword() {
      await this.run(async () => {
        const body = await apiRequest("/auth/reset", {
          method: "POST",
          body: this.resetForm,
        });
        this.loginForm.email = this.resetForm.email;
        this.message = body.message || "Password updated. You can sign in now.";
        this.activeTab = "login";
      });
    },

    logout() {
      clearAuthSession();
      this.session = null;
      this.message = "Signed out.";
      this.error = "";
      this.activeTab = "login";
    },

    setSession(session) {
      setAuthSession(session);
      this.session = session;
    },

    async run(callback) {
      this.loading = true;
      this.error = "";
      this.message = "";
      try {
        await callback();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
  },
});
