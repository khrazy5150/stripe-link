import { defineStore } from "pinia";
import { SESSION_ENDED_EVENT, apiRequest, clearAuthSession, getAuthSession, setAuthSession } from "../api/client";

// Which tab a visitor lands on. The homepage's "Start for free" sends people here to SIGN UP, and
// landing them on Login asks them to do the one thing they cannot yet do. Read from the URL rather than
// held in the homepage's own state, because the two are separate deployments and the link is the only
// thing that crosses between them.
//
// Anything unrecognised falls back to login: the tab is a hint from a URL, and a URL is not trusted
// input. "register" and "forgot" are the only other screens that exist.
function tabFromUrl() {
  try {
    const asked = new URLSearchParams(window.location.search).get("tab")
      || String(window.location.hash || "").replace(/^#/, "");
    return ["register", "forgot"].includes(asked) ? asked : "login";
  } catch {
    return "login";   // no window, or a URL the browser will not parse
  }
}

export const useAuthStore = defineStore("auth", {
  state: () => ({
    session: getAuthSession(),
    activeTab: tabFromUrl(),
    loading: false,
    _sessionEndBound: false,
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
          anonymous: true,
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
          anonymous: true,
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
          anonymous: true,
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
          anonymous: true,
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
          anonymous: true,
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
      // Read back rather than storing the argument: setAuthSession stamps expires_at, and the store holding a
      // copy WITHOUT it would report a session that never looks due for renewal.
      this.session = getAuthSession();
    },

    /**
     * The API layer ended the session -- no token, or a refresh Cognito refused.
     *
     * Storage is already cleared by the time this runs; what is left is the store's own copy, which is what
     * App.vue gates on. Without this the dashboard stays rendered and every screen fails instead of returning
     * to the login form.
     */
    sessionEnded() {
      // "Ended" presupposes one existed. A visitor who has never signed in reaches this on the FIRST
      // authenticated request of the page load -- refreshSession finds no refresh_token and ends a
      // session that was never started -- and before this guard that did two wrong things to someone
      // who had just clicked "Start for free": it stole the Register tab they asked for, about half a
      // second after the form rendered, and it told them a session they never had has expired.
      //
      // The absence of a session is not an event. Only the loss of one is.
      const hadSession = !!this.session;
      this.session = null;
      if (!hadSession) return;
      this.error = "";
      this.message = "Your session has ended. Please sign in again.";
      this.activeTab = "login";
    },

    bindSessionEnd() {
      if (this._sessionEndBound) return;
      this._sessionEndBound = true;
      window.addEventListener(SESSION_ENDED_EVENT, () => this.sessionEnded());
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
