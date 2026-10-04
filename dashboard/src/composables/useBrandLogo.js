import { onMounted, ref } from "vue";

import { assetUrl, loadAppConfigApiBase } from "../api/client";

const LOGO_PATH = "/icon/favicon.png";

/**
 * The brand mark's URL, which is NOT known at first render.
 *
 * `assetUrl` builds on `public_asset_base_url`, which lives in app_config — fetched at boot and cached in
 * localStorage. Before that resolves it returns `""`, and `<img src="">` does not render nothing: every
 * browser draws its broken-image icon. Which is what a tenant saw on the login screen after their session
 * timed out, reported 2026-10-04 — the timeout path reaches the auth screen with the cache cold or
 * cleared, where a normal visit has it warm from last time.
 *
 * Two things are needed and neither alone is enough:
 *
 * - **Never render an empty src.** The template guards on the value, so the worst case is no logo rather
 *   than a broken one.
 * - **Re-render when it arrives.** `assetUrl()` called in a template is evaluated once, with nothing to
 *   invalidate it, so a URL that shows up a moment later never reaches the DOM. A ref fixes that, and
 *   this composable also kicks the config load itself rather than assuming someone else did.
 */
export function useBrandLogo() {
  const logoUrl = ref(assetUrl(LOGO_PATH));

  onMounted(async () => {
    if (logoUrl.value) return;
    try {
      await loadAppConfigApiBase();
    } catch {
      // No logo is a fine outcome; a broken one is not. The guard in the template covers it.
    }
    logoUrl.value = assetUrl(LOGO_PATH);
  });

  return { logoUrl };
}
