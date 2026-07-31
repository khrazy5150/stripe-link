import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

// Collections — ordered, curated groups of a Site's landing pages (plans/SITE_COLLECTIONS.md). Pure data,
// URL-unaware; a page's catalog_grid embeds one by collection_id. The storefront/category builder reads + writes
// them here so editing a collection-embed edits the Collection, not inline grid config.
export const useCollectionsStore = defineStore("collections", {
  state: () => ({ collections: [], loaded: false, loading: false, error: "" }),
  getters: {
    forSite: (state) => (siteId) => state.collections.filter((c) => c.site_id === siteId),
  },
  actions: {
    async ensureLoaded() {
      if (!this.loaded && !this.loading) await this.load();
    },
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/collections");
        this.collections = Array.isArray(body.collections) ? body.collections : [];
        this.loaded = true;
      } catch (error) {
        this.error = error.message || "Failed to load collections.";
      } finally {
        this.loading = false;
      }
    },
    // The full doc for one collection — from the loaded cache, else fetched.
    async get(collectionId) {
      if (!collectionId) return null;
      return this.collections.find((c) => c.collection_id === collectionId)
        || apiRequest(`/collections/${encodeURIComponent(collectionId)}`).then((b) => b.collection).catch(() => null);
    },
    async save(collection) {
      const body = await apiRequest("/collections", { method: "POST", body: collection });
      const saved = body.collection || collection;
      const index = this.collections.findIndex((c) => c.collection_id === saved.collection_id);
      if (index >= 0) this.collections.splice(index, 1, saved);
      else this.collections.push(saved);
      return saved;
    },
    async remove(collectionId) {
      await apiRequest(`/collections/${encodeURIComponent(collectionId)}`, { method: "DELETE" });
      this.collections = this.collections.filter((c) => c.collection_id !== collectionId);
    },
    reset() {
      this.collections = [];
      this.loaded = false;
      this.error = "";
    },
  },
});
