// The AI image library and the credits that bound it.
//
// EVERYTHING RENDERABLE COMES FROM THE SERVER. The quality options and the style presets are lists the
// API returns, never arrays typed here: the quality list is one entry long today, a one-entry list
// renders no control, and that is why there is no quality selector without anyone having decided there
// would not be one. When a tier lifts the ceiling the list grows and the control appears, with this
// file and the picker untouched.
//
// The refusal sentence comes from the server too, for the same reason the usage block already carries
// one: a screen that writes its own copy ends up promising something the route refuses.
import { defineStore } from "pinia";

import { apiRequest } from "../api/client";

// Generation measured ~10-30s per image. A 2.5s poll is a handful of reads; the ceiling is generous
// because a job that outlives it has failed in a way that never reached the record.
const POLL_MS = 2500;
const GIVE_UP_MS = 180000;

export const useAiImagesStore = defineStore("aiImages", {
  state: () => ({
    loaded: false,
    loading: false,
    generating: false,
    error: "",
    jobs: [],
    libraryUnavailable: false,
    // Server-supplied. Empty until loaded, which is why the picker renders nothing rather than
    // guessing a default it would then have to unlearn.
    credits: null,
    styles: [],
    qualities: [],
  }),

  getters: {
    canGenerate: (state) => Boolean(state.credits?.can_generate),
    remaining: (state) => state.credits?.remaining ?? 0,
    // -1 is the exempt sentinel. A number nobody can count down from should read as a word.
    remainingLabel: (state) => {
      const left = state.credits?.remaining ?? 0;
      if (state.credits?.allowance === -1) return "Unlimited";
      return `${left} left`;
    },
    // Only images that actually produced something. A failed job is noise in a picker.
    images: (state) => state.jobs
      .filter((job) => job.status === "done" && (job.images || []).length)
      .map((job) => ({
        jobId: job.job_id,
        prompt: job.prompt || "",
        createdAt: Number(job.created_at || 0),
        images: job.images || [],
      })),
  },

  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const [config, library] = await Promise.all([
          apiRequest("/ai/config"),
          apiRequest("/ai/jobs"),
        ]);
        this.credits = config.images || null;
        this.styles = config.images?.styles || [];
        this.qualities = config.images?.qualities || [];
        this.jobs = library.jobs || [];
        this.libraryUnavailable = Boolean(library.unavailable);
        this.loaded = true;
      } catch (error) {
        this.error = error.message || "Could not load your AI images.";
      } finally {
        this.loading = false;
      }
    },

    async refreshCredits() {
      try {
        const config = await apiRequest("/ai/config");
        this.credits = config.images || this.credits;
      } catch {
        // A stale credit count is not worth an error message over the picker.
      }
    },

    async generate({ prompt, style = "", count = 2 }) {
      this.generating = true;
      this.error = "";
      try {
        const queued = await apiRequest("/ai/generate", {
          method: "POST",
          body: { operation: "image", prompt, style, count },
        });
        const finished = await this.awaitJob(queued.job?.job_id);
        await this.refreshCredits();
        if (finished) {
          // Prepend rather than reload: the library read is a proxied call and the tenant is looking
          // at the thing they just made.
          this.jobs = [finished, ...this.jobs.filter((j) => j.job_id !== finished.job_id)];
        }
        return finished;
      } catch (error) {
        this.error = error.message || "The image could not be generated.";
        await this.refreshCredits();
        return null;
      } finally {
        this.generating = false;
      }
    },

    async awaitJob(jobId) {
      if (!jobId) return null;
      const started = Date.now();
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        const body = await apiRequest(`/ai/jobs/${encodeURIComponent(jobId)}`);
        const job = body.job || {};
        if (job.status === "done") return job;
        if (job.status === "failed") {
          // The service says WHOSE problem it is, so the advice can be true. A prompt the safety
          // system refused is something the tenant can act on; ours is not.
          const blame = job.error?.blame || "transient";
          const advice = blame === "tenant" ? "Try describing it differently."
            : blame === "service" ? "That one is on us — it needs looking at, not another attempt."
            : "Something went wrong at the provider. Try again shortly.";
          this.error = `${job.error?.message || "The image could not be generated."} ${advice}`;
          return null;
        }
        if (Date.now() - started > GIVE_UP_MS) {
          this.error = "That took longer than expected. Check back in a moment — it may have finished.";
          return null;
        }
      }
    },

    async remove(jobId) {
      // The job id the SERVICE knows. Deleting by this stack's local id finds nothing and reports a
      // perfectly truthful "nothing to take down", which is the wrong kind of success to show someone
      // who asked for a picture to come down.
      const entry = this.jobs.find((job) => job.job_id === jobId);
      if (!entry) return false;
      try {
        await apiRequest(`/ai/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
        this.jobs = this.jobs.filter((job) => job.job_id !== jobId);
        return true;
      } catch (error) {
        this.error = error.message || "That image could not be removed.";
        return false;
      }
    },
  },
});
