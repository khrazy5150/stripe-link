const output = document.querySelector("#output");
const apiBaseInput = document.querySelector("#apiBase");
const mainApp = document.querySelector("#main-app");
const environmentLabel = document.querySelector("#environmentLabel");
const environmentToggle = document.querySelector("#environmentToggle");
let currentEnvironment = localStorage.getItem("stripeLinkEnvironment") || "test";
const defaultApiBaseByEnvironment = {
  test: "https://dev.juniorbay.com",
  live: "https://prod.juniorbay.com",
};
const defaultPlatformFeeConfig = {
  basic: {
    physical: 0.10,
    digital: 0.15,
    "tip-jar": 0.05,
  },
  standard: {
    physical: 0.08,
    digital: 0.13,
    "tip-jar": 0.04,
  },
  pro: {
    physical: 0.05,
    digital: 0.10,
    "tip-jar": 0.02,
  },
};
const STRIPE_PERCENT_FEE = 0.029;
const STRIPE_FIXED_FEE_CENTS = 30;
const SNOWFLAKE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const SNOWFLAKE_EPOCH_MS = 1735689600000n;
const SNOWFLAKE_WORKER_ID_KEY = "stripeLinkSnowflakeWorkerId";
let snowflakeLastMs = 0n;
let snowflakeSeq = 0n;
apiBaseInput.value = configuredApiBase(currentEnvironment);
const appState = {
  tenantId: localStorage.getItem("stripeLinkTenantId") || "tenant_demo",
  userId: localStorage.getItem("stripeLinkUserId") || "keithdecosta@gmail.com",
  tenantPlan: localStorage.getItem("stripeLinkTenantPlan") || "basic",
  platformFee: defaultPlatformFeeConfig,
  session: null,
  products: [],
  productUploadedImages: [],
  leadCaptureAction: "capture_email",
  priceCalculationCache: new Map(),
};
applyEnvironment(currentEnvironment);
loadAppConfigApiBase(currentEnvironment);

function toBase62(value) {
  if (value === 0n) return "0";
  let remaining = value;
  let result = "";
  const base = BigInt(SNOWFLAKE_ALPHABET.length);
  while (remaining > 0n) {
    result = SNOWFLAKE_ALPHABET[Number(remaining % base)] + result;
    remaining /= base;
  }
  return result;
}

function dashboardWorkerId() {
  const stored = sessionStorage.getItem(SNOWFLAKE_WORKER_ID_KEY);
  if (stored && /^\d+$/.test(stored)) return BigInt(Number(stored) & 0x3ff);

  let value = 1;
  if (window.crypto?.getRandomValues) {
    const bytes = new Uint32Array(1);
    window.crypto.getRandomValues(bytes);
    value = bytes[0] & 0x3ff;
  }
  sessionStorage.setItem(SNOWFLAKE_WORKER_ID_KEY, String(value));
  return BigInt(value);
}

function generateSnowflakeId() {
  const workerId = dashboardWorkerId();
  let now = BigInt(Date.now());

  if (now < snowflakeLastMs) {
    const drift = snowflakeLastMs - now;
    if (drift >= 50n) throw new Error(`Clock moved backwards. Rejecting ID generation for ${drift}ms.`);
    while (now < snowflakeLastMs) now = BigInt(Date.now());
  }

  if (now === snowflakeLastMs) {
    snowflakeSeq = (snowflakeSeq + 1n) & 0x1fffn;
    while (snowflakeSeq === 0n && now <= snowflakeLastMs) now = BigInt(Date.now());
  } else {
    snowflakeSeq = 0n;
  }

  snowflakeLastMs = now;
  const timePart = (now - SNOWFLAKE_EPOCH_MS) & 0x1ffffffffffn;
  const value = (timePart << 23n) | (workerId << 13n) | snowflakeSeq;
  return toBase62(value).padStart(11, "0");
}

function generateLocalId() {
  return `local_${generateSnowflakeId()}`;
}

document.querySelectorAll("[data-auth-tab]").forEach((button) => {
  button.addEventListener("click", () => switchAuthTab(button.dataset.authTab));
});

document.querySelector("#btnLogin").addEventListener("click", () => {
  const email = document.querySelector("#loginEmail").value.trim();
  const password = document.querySelector("#loginPass").value;
  if (!email || !password) {
    setAuthMessage("loginMsg", "Email and password required", "error");
    return;
  }
  showApp({ email, status: "signed_in" });
});

document.querySelector("#btnRegister").addEventListener("click", async () => {
  const payload = buildRegistrationPayload();
  if (!payload) return;
  const apiBase = apiBaseInput.value.trim();
  if (!apiBase) {
    localStorage.setItem("stripeLinkPendingTenant", JSON.stringify(payload));
    document.querySelector("#confEmail").value = payload.owner.email;
    setAuthMessage("regMsg", "Registration captured locally. Set API Base URL to save it.", "success");
    showApp({ email: payload.owner.email, tenant_id: payload.tenant_id, status: "pending_confirmation" });
    return;
  }
  const response = await fetch(`${apiBase}/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  writeOutput(body);
  if (response.ok) {
    document.querySelector("#confEmail").value = payload.owner.email;
    setAuthMessage("regMsg", "Sign-up successful. Check your email for the verification code.", "success");
    showApp({ email: payload.owner.email, tenant_id: payload.tenant_id, status: "pending_confirmation" });
  } else {
    setAuthMessage("regMsg", body.message || "Registration failed.", "error");
  }
});

document.querySelector("#btnConfirm").addEventListener("click", () => {
  const email = document.querySelector("#confEmail").value.trim();
  const code = document.querySelector("#confCode").value.trim();
  if (!email || !code) {
    setAuthMessage("regMsg", "Please enter your email and the verification code.", "error");
    return;
  }
  setAuthMessage("regMsg", "Email confirmed. You can sign in now.", "success");
  switchAuthTab("login");
  document.querySelector("#loginEmail").value = email;
});

document.querySelector("#btnResend").addEventListener("click", () => {
  const email = document.querySelector("#confEmail").value.trim();
  setAuthMessage("regMsg", email ? "A new verification code has been sent." : "Enter your email first.", email ? "success" : "error");
});

document.querySelector("#btnForgot").addEventListener("click", () => {
  const email = document.querySelector("#fpEmail").value.trim();
  setAuthMessage("fpMsg", email ? "Reset code sent. Check your email." : "Enter your email first.", email ? "success" : "error");
  if (email) document.querySelector("#fpConfEmail").value = email;
});

document.querySelector("#btnConfirmNew").addEventListener("click", () => {
  const email = document.querySelector("#fpConfEmail").value.trim();
  const code = document.querySelector("#fpCode").value.trim();
  const password = document.querySelector("#fpNewPass").value;
  setAuthMessage(
    "fpMsg",
    email && code && password ? "Password updated. You can sign in now." : "Email, code, and new password are required.",
    email && code && password ? "success" : "error",
  );
});

document.querySelector("#saveApiBase").addEventListener("click", () => {
  const apiBase = apiBaseInput.value.trim();
  localStorage.setItem(apiBaseStorageKey(currentEnvironment), apiBase);
  if (environmentKey(currentEnvironment) === "test") {
    localStorage.setItem("stripeLinkApiBase", apiBase);
  }
  writeOutput({ saved_api_base: apiBase, environment: configEnvironment(currentEnvironment) });
  loadPanelData(mainApp.dataset.view || "dashboard");
});

document.querySelector("#btnLoadSimplePage")?.addEventListener("click", () => {
  loadSimpleLandingExample();
  renderLandingPreviewLocal();
});

document.querySelector("#btnRenderLandingPreview")?.addEventListener("click", () => {
  renderLandingPreviewLocal();
});

document.querySelector("#btnRenderLandingBackend")?.addEventListener("click", async () => {
  await renderLandingPreviewBackend();
});

document.querySelector("#btnSaveLandingDocuments")?.addEventListener("click", async () => {
  await saveLandingDocuments();
});

document.querySelector("#btnToggleLandingForm")?.addEventListener("click", () => {
  const body = document.querySelector("#landingFormBody");
  const button = document.querySelector("#btnToggleLandingForm");
  const hidden = body.classList.toggle("hidden");
  button.textContent = hidden ? "Show Form" : "Hide Form";
});

document.querySelector("#btnDesktopPreview")?.addEventListener("click", () => {
  setLandingPreviewSize("desktop");
});

document.querySelector("#btnMobilePreview")?.addEventListener("click", () => {
  setLandingPreviewSize("mobile");
});

document.querySelector("#landingPageTestForm")?.addEventListener("input", () => {
  renderLandingPreviewLocal();
});

document.querySelector("#btnCreateProductUi")?.addEventListener("click", () => {
  showProductForm();
});

document.querySelector("#productSchemaForm")?.addEventListener("input", () => {
  if (!productIsLeadGen()) updateProductPricePreview();
});

document.querySelector("#productSchemaForm")?.addEventListener("change", async (event) => {
  if (event.target?.name === "product_type") {
    updateProductCategoryOptions();
    updateProductFulfillmentVisibility();
    resetProductRefundPolicyDefaults();
    updateProductIntentVisibility();
  }
  if (event.target?.name === "product_intent") updateProductIntentVisibility();
  if (event.target?.name === "product_canonical") await handleProductCanonicalChange();
  if (event.target?.name === "refund_source") updateProductRefundPolicyVisibility();
  if (["refund_window", "refund_condition", "refund_return_method"].includes(event.target?.name)) {
    refreshProductRefundPolicyPreview();
  }
  if (["enable_item_size", "enable_item_color"].includes(event.target?.name)) {
    updateProductVariantVisibility();
  }
  if (event.target?.dataset.priceField === "default") {
    enforceSingleDefaultPrice(event.target);
  }
  if (!productIsLeadGen()) updateProductPricePreview();
});

document.querySelector("#productSchemaForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveProductFromForm();
});

document.querySelector("#btnAddProductPrice")?.addEventListener("click", () => {
  addProductPriceRow();
});

document.querySelector("#productPriceRows")?.addEventListener("click", (event) => {
  const contextHelpButton = event.target.closest("[data-toggle-context-help]");
  if (contextHelpButton) {
    const row = contextHelpButton.closest(".product-price-row");
    const help = row?.querySelector("[data-price-context-help]");
    if (!help) return;
    const isHidden = help.classList.toggle("hidden");
    contextHelpButton.setAttribute("aria-expanded", String(!isHidden));
    return;
  }

  const removeButton = event.target.closest("[data-remove-price]");
  if (!removeButton) return;
  const row = removeButton.closest(".product-price-row");
  row?.remove();
  renumberProductPriceRows();
  ensureProductDefaultPrice();
  updateProductPricePreview();
});

document.querySelector("#btnAddSizeVariant")?.addEventListener("click", () => {
  addProductVariantItem("size");
});

document.querySelector("#btnAddColorVariant")?.addEventListener("click", () => {
  addProductVariantItem("color");
});

document.querySelector("#productSchemaForm")?.addEventListener("click", (event) => {
  const removeButton = event.target.closest("[data-remove-variant]");
  if (!removeButton) return;
  removeButton.closest(".variant-item")?.remove();
});

document.querySelector("#productImageDropzone")?.addEventListener("click", () => {
  document.querySelector("#productImageFileInput")?.click();
});

document.querySelector("#productImageDropzone")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    document.querySelector("#productImageFileInput")?.click();
  }
});

document.querySelector("#productImageFileInput")?.addEventListener("change", async (event) => {
  await handleProductImageFiles(Array.from(event.target.files || []));
  event.target.value = "";
});

document.querySelector("#productImageDropzone")?.addEventListener("dragover", (event) => {
  event.preventDefault();
  event.currentTarget.classList.add("drag-over");
});

document.querySelector("#productImageDropzone")?.addEventListener("dragleave", (event) => {
  event.currentTarget.classList.remove("drag-over");
});

document.querySelector("#productImageDropzone")?.addEventListener("drop", async (event) => {
  event.preventDefault();
  event.currentTarget.classList.remove("drag-over");
  const files = Array.from(event.dataTransfer?.files || []).filter((file) => file.type.startsWith("image/"));
  await handleProductImageFiles(files);
});

document.querySelector("#btnCloseProductModal")?.addEventListener("click", () => {
  showProductList();
});

document.querySelector("#btnCancelProductModal")?.addEventListener("click", () => {
  showProductList();
});

document.querySelector("#btnOpenLeadIntentModal")?.addEventListener("click", showLeadIntentModal);
document.querySelector("#btnCloseLeadIntentModal")?.addEventListener("click", hideLeadIntentModal);
document.querySelector("#btnCancelLeadIntentModal")?.addEventListener("click", hideLeadIntentModal);
document.querySelector("#btnSelectLeadIntent")?.addEventListener("click", hideLeadIntentModal);
document.querySelector("#leadActionGrid")?.addEventListener("click", (event) => {
  const card = event.target.closest("[data-lead-action]");
  if (card) selectLeadAction(card.dataset.leadAction);
});

document.querySelector("#btnLoadProductsUi")?.addEventListener("click", async () => {
  await loadProducts();
});

document.querySelector("#btnSaveProductUi")?.addEventListener("click", async () => {
  await saveProductFromForm();
});

document.querySelector("#btnResetProductUi")?.addEventListener("click", () => {
  document.querySelector("#productSchemaForm")?.reset();
  resetProductPriceRows();
  resetProductImageUploads();
  resetProductVariants();
  resetProductLeadCapture();
  resetProductRefundPolicyDefaults();
  updateProductFulfillmentVisibility();
  updateProductIntentVisibility();
  if (!productIsLeadGen()) updateProductPricePreview();
});

async function saveProductFromForm() {
  const form = document.querySelector("#productSchemaForm");
  const productName = form?.elements.product_name?.value?.trim() || "";
  if (!productName) {
    setPanelNote("products", "Product name is required.");
    return;
  }
  if (!productIsLeadGen()) {
    try {
      await calculateProductPricesForSave();
    } catch (error) {
      setPanelNote("products", `Can't calculate product prices: ${error.message}`);
      return;
    }
  }
  const product = buildProductDocumentFromForm();
  await saveProduct(product);
}

document.querySelector("#btnRefreshAppConfig")?.addEventListener("click", async () => {
  await loadAppConfigApiBase(currentEnvironment, { updatePanel: true });
});

environmentToggle.addEventListener("click", () => {
  currentEnvironment = currentEnvironment === "test" ? "live" : "test";
  localStorage.setItem("stripeLinkEnvironment", currentEnvironment);
  applyEnvironment(currentEnvironment);
  apiBaseInput.value = configuredApiBase(currentEnvironment);
  loadAppConfigApiBase(currentEnvironment, { updatePanel: mainApp.dataset.view === "config" });
});

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
    button.classList.add("active");
    const panel = document.querySelector(`[data-panel="${button.dataset.view}"]`);
    if (panel) panel.classList.add("active");
    mainApp.dataset.view = button.dataset.view;
    loadPanelData(button.dataset.view);
  });
});

document.querySelectorAll("form").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (form.id === "productSchemaForm") {
      return;
    }
    const action = form.dataset.action;
    if (action === "connect-start") {
      await startConnect(form);
      return;
    }
    await submitJsonForm(form);
  });
});

async function startConnect(form) {
  const values = formValues(form);
  if (!apiBaseInput.value.trim()) {
    writeOutput({ error: "Set API Base URL before calling the API.", path: "/stripe/connect/start" });
    return;
  }
  const body = await apiRequest("/stripe/connect/start", {
    params: {
      mode: values.mode || currentEnvironment,
      tenant_id: values.tenant_id || appState.tenantId,
    },
  });
  writeOutput(body);
  if (body.connect_url) {
    window.open(body.connect_url, "_blank", "noopener,noreferrer");
  }
}

async function submitJsonForm(form) {
  const endpoint = form.dataset.endpoint;
  const method = form.dataset.method || "PUT";
  const payload = buildPayload(form.dataset.payload, formValues(form));
  if (!apiBaseInput.value.trim()) {
    writeOutput({ error: "Set API Base URL before calling the API.", endpoint, payload });
    return;
  }
  const body = await apiRequest(endpoint, {
    method,
    body: payload,
  });
  writeOutput(body);
  loadPanelData(mainApp.dataset.view || "dashboard");
}

async function apiRequest(path, options = {}) {
  const apiBase = apiBaseInput.value.trim();
  if (!apiBase) {
    throw new Error("Set API Base URL before calling the API.");
  }
  const url = new URL(`${apiBase.replace(/\/$/, "")}${path}`);
  const params = {
    tenant_id: appState.tenantId,
    ...(options.params || {}),
  };
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  const response = await fetch(url.toString(), {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      "X-Tenant-Id": appState.tenantId,
      "X-Client-Id": appState.tenantId,
      "X-Environment": currentEnvironment,
      "X-Stripe-Mode": currentEnvironment,
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok && !(options.allowNotFound && response.status === 404)) {
    throw new Error(body.message || body.error || `Request failed with ${response.status}`);
  }
  return body;
}

async function loadPanelData(view) {
  if (!apiBaseInput.value.trim()) return;
  try {
    if (view === "dashboard") {
      await loadDashboardData();
      return;
    }
    const loaders = {
      products: () => prepareProductPanel(),
      offers: () => loadCollection("/offers", "offers"),
      "landing-pages": () => loadCollection("/pages", "pages"),
      services: () => loadCollection("/services", "services"),
      notifications: () => loadCollection("/notifications", "notifications"),
      invoices: () => loadCollection("/invoices", "invoices"),
      shipping: () => loadSingleton("/shipping", "shipping_config"),
      customers: () => loadCollection("/customers", "customers"),
      config: () => loadConfigurationData(),
      profile: () => loadSingleton("/profile", "profile", { user_id: appState.userId }),
      preferences: () => loadSingleton("/preferences", "preferences", { user_id: appState.userId }),
      keys: () => loadStripeKeys(),
      connect: () => loadSingleton("/stripe/connect/status", "stripe_connect"),
      registration: () => loadRegistration(),
    };
    if (loaders[view]) await loaders[view]();
  } catch (error) {
    writeOutput({ error: error.message, view });
  }
}

async function loadDashboardData() {
  setDashboardLoading();
  const [products, customers, invoices, notifications] = await Promise.all([
    apiRequest("/products").catch(() => ({ products: [] })),
    apiRequest("/customers").catch(() => ({ customers: [] })),
    apiRequest("/invoices").catch(() => ({ invoices: [] })),
    apiRequest("/notifications").catch(() => ({ notifications: [] })),
  ]);
  renderDashboard({
    products: products.products || [],
    customers: customers.customers || [],
    invoices: invoices.invoices || [],
    notifications: notifications.notifications || [],
  });
}

async function loadCollection(path, key) {
  const body = await apiRequest(path);
  writeOutput(body);
  const count = Array.isArray(body[key]) ? body[key].length : body.count;
  if (count !== undefined) {
    setPanelNote(key, `${count} ${key.replace("_", " ")} loaded from backend.`);
  }
}

async function loadConfigurationData() {
  await Promise.all([
    loadSingleton("/config", "config").catch((error) => writeOutput({ error: error.message, view: "config" })),
    loadAppConfigApiBase(currentEnvironment, { updatePanel: true }),
  ]);
}

function prepareProductPanel() {
  renderProductTable();
  if (!appState.products.length) {
    setPanelNote("products", 'Click "Load Products" or adjust your filters to see products.');
  }
}

async function loadProducts() {
  const button = document.querySelector("#btnLoadProductsUi");
  const originalText = button?.textContent || "Load Products";
  if (button) {
    button.disabled = true;
    button.textContent = "Loading...";
  }
  if (!apiBaseInput.value.trim()) {
    try {
      renderProductTable();
      setPanelNote("products", appState.products.length
        ? `${appState.products.length} product${appState.products.length === 1 ? "" : "s"} loaded in this UI session.`
        : 'Click "Load Products" or adjust your filters to see products.');
      writeOutput({ products: appState.products, source: "local_ui_session" });
      return;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
    }
  }
  try {
    const body = await apiRequest("/products");
    appState.products = Array.isArray(body.products) ? body.products : [];
    renderProductTable();
    writeOutput(body);
    setPanelNote("products", appState.products.length
      ? `${appState.products.length} product${appState.products.length === 1 ? "" : "s"} loaded from backend.`
      : 'Click "Load Products" or adjust your filters to see products.');
  } catch (error) {
    writeOutput({ error: error.message, action: "load_products" });
    setPanelNote("products", error.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function saveProduct(product) {
  const button = document.querySelector("#btnSaveProductUi");
  const originalText = button?.textContent || "Save Product";
  if (button) {
    button.disabled = true;
    button.textContent = "Saving...";
  }
  try {
    if (!apiBaseInput.value.trim()) {
      upsertLocalProduct(product);
      renderProductTable();
      showProductList();
      writeOutput({ product, ui_only: true, next_step: "Set API Base URL to save products to the database." });
      setPanelNote("products", `${product.name} was added to the local product table.`);
      return;
    }
    const body = await apiRequest("/products", {
      method: "POST",
      body: product,
    });
    const savedProduct = body.product || product;
    upsertLocalProduct(savedProduct);
    renderProductTable();
    showProductList();
    writeOutput(body);
    setPanelNote("products", `${savedProduct.name || product.name} was saved to the products database.`);
  } catch (error) {
    writeOutput({ error: error.message, action: "save_product", product });
    setPanelNote("products", error.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function loadSingleton(path, key, params = {}) {
  const body = await apiRequest(path, { params, allowNotFound: true });
  writeOutput(body);
  setPanelNote(key, body[key] ? `${key.replace("_", " ")} loaded from backend.` : `${key.replace("_", " ")} not found yet.`);
}

async function loadStripeKeys() {
  const body = await apiRequest("/stripe/keys", { allowNotFound: true });
  writeOutput(body);
  renderStripeKeys(body.stripe_keys);
  setPanelNote("stripe_keys", body.stripe_keys ? "Stripe keys loaded" : "No Stripe keys saved yet. Re-enter keys for this environment.");
}

function loadSimpleLandingExample() {
  const form = document.querySelector("#landingPageTestForm");
  if (!form) return;
  form.elements.tenant_id.value = appState.tenantId || "tenant_demo";
  form.elements.page_title.value = "Simple Coffee";
  form.elements.page_description.value = "A clean single-product checkout page for one bag of roasted coffee.";
  form.elements.price_amount.value = "18.00";
  form.elements.currency.value = "usd";
  form.elements.status.value = "draft";
  form.elements.slug.value = "simple-coffee";
  form.elements.accent_color.value = "#15803d";
  form.elements.checkout_url.value = "https://checkout.stripe.com/c/pay/demo";
}

function landingFormValues() {
  const form = document.querySelector("#landingPageTestForm");
  return form ? formValues(form) : {};
}

function buildLandingDocuments() {
  const values = landingFormValues();
  const now = Math.floor(Date.now() / 1000);
  const tenantId = values.tenant_id || appState.tenantId || "tenant_demo";
  const slugValue = pageSlug(values.slug || values.page_title || "simple page");
  const productId = generateLocalId();
  const priceId = generateLocalId();
  const offerId = generateLocalId();
  const pageId = generateLocalId();
  const unitAmount = Math.round(Number(values.price_amount || 0) * 100);
  const currency = (values.currency || "usd").toLowerCase();

  const product = {
    schema_version: "2026-05-29",
    document_type: "product",
    tenant_id: tenantId,
    product_id: productId,
    stripe_mode: currentEnvironment === "live" ? "live" : "test",
    active: true,
    name: values.page_title || "Untitled Product",
    description: values.page_description || "",
    prices: [
      {
        price_id: priceId,
        product_id: productId,
        stripe_mode: currentEnvironment === "live" ? "live" : "test",
        active: true,
        currency,
        unit_amount: unitAmount,
        quantity: 1,
        label: "One Item",
        context: "standard",
      },
    ],
    default_price_id: priceId,
    product_type: "physical",
    product_category: "simple",
    fulfillment: {
      requires_shipping: true,
      ship_from: null,
      weight_oz: null,
    },
    created_at: now,
    updated_at: now,
  };

  const offer = {
    schema_version: "2026-05-29",
    document_type: "offer",
    tenant_id: tenantId,
    offer_id: offerId,
    name: `${values.page_title || "Simple Product"} Offer`,
    active: true,
    context: "standard",
    items: [
      {
        product_id: productId,
        selectable_prices: [
          {
            price_id: priceId,
            quantity: 1,
            label: "One Item",
          },
        ],
        default_price_id: priceId,
        presentation_context: "primary",
      },
    ],
    presentation: {
      cta_label: "Buy Now",
    },
    checkout: {
      mode: "payment",
      allow_promotion_codes: false,
      metadata: {
        offer_id: offerId,
        context: "standard",
      },
    },
    created_at: now,
    updated_at: now,
  };

  const page = {
    schema_version: "2026-05-29",
    document_type: "page",
    tenant_id: tenantId,
    page_id: pageId,
    name: `${values.page_title || "Simple Product"} Checkout Page`,
    status: values.status || "draft",
    published_at: values.status === "published" ? now : null,
    route: {
      slug: slugValue,
    },
    seo: {
      title: values.page_title || "Simple Product",
      description: values.page_description || "",
    },
    offer_id: offerId,
    checkout_url: values.checkout_url || "",
    theme: {
      template: "simple",
      color: {
        background: "#ffffff",
        text: "#111827",
        accent: values.accent_color || "#15803d",
      },
    },
    sections: [
      {
        id: "hero",
        type: "hero",
        headline: values.page_title || "Simple Product",
        subheadline: values.page_description || "",
      },
      {
        id: "price",
        type: "offer_price_selector",
        offer_id: offerId,
      },
      {
        id: "checkout",
        type: "checkout_cta",
        label: "Buy Now",
      },
    ],
    revision: 1,
    created_at: now,
    updated_at: now,
  };

  return { product, offer, page, checkout_url: values.checkout_url || "" };
}

function renderLandingPreviewLocal() {
  const documents = buildLandingDocuments();
  const html = renderSimplePageHtml(documents);
  setLandingPreviewHtml(html, "Local render");
  writeOutput({
    page_test: {
      page: documents.page,
      offer: documents.offer,
      product: documents.product,
      artifact_paths: {
        preview: `preview/${documents.page.tenant_id}/${documents.page.page_id}/index.html`,
        test: `test/${documents.page.tenant_id}/${documents.page.route.slug}/index.html`,
        published: `published/${documents.page.tenant_id}/${documents.page.route.slug}/index.html`,
      },
    },
  });
}

async function renderLandingPreviewBackend() {
  if (!apiBaseInput.value.trim()) {
    renderLandingPreviewLocal();
    setPanelNote("pages", "Set API Base URL to render through /pages/render. Showing local preview.");
    return;
  }
  try {
    const documents = buildLandingDocuments();
    const body = await apiRequest("/pages/render", {
      method: "POST",
      body: {
        page: documents.page,
        offer: documents.offer,
        products: [documents.product],
        checkout_url: documents.checkout_url,
      },
      params: {},
    });
    setLandingPreviewHtml(body.html || "", "Backend render");
    writeOutput(body);
    setPanelNote("pages", "Rendered through /pages/render.");
  } catch (error) {
    writeOutput({ error: error.message, action: "render_landing_preview" });
    setPanelNote("pages", error.message);
  }
}

async function saveLandingDocuments() {
  if (!apiBaseInput.value.trim()) {
    const documents = buildLandingDocuments();
    writeOutput({
      error: "Set API Base URL before saving.",
      documents,
    });
    setPanelNote("pages", "Set API Base URL before saving documents.");
    return;
  }
  try {
    const documents = buildLandingDocuments();
    const [productResult, offerResult, pageResult] = await Promise.all([
      apiRequest("/products", { method: "POST", body: documents.product }),
      apiRequest("/offers", { method: "POST", body: documents.offer }),
      apiRequest("/pages", { method: "POST", body: documents.page }),
    ]);
    writeOutput({
      product: productResult.product,
      offer: offerResult.offer,
      page: pageResult.page,
      stream_pipeline: "PagesTable stream will render preview/test artifacts after page save.",
    });
    setPanelNote("pages", documents.page.status === "published"
      ? "Saved. Stream should publish preview, test, and published artifacts."
      : "Saved. Stream should publish preview and test artifacts.");
  } catch (error) {
    writeOutput({ error: error.message, action: "save_landing_documents" });
    setPanelNote("pages", error.message);
  }
}

function setLandingPreviewHtml(html, mode) {
  const frame = document.querySelector("#landingPreviewFrame");
  const label = document.querySelector("#landingPreviewMode");
  if (label) label.textContent = mode;
  if (frame) frame.srcdoc = html;
}

function setLandingPreviewSize(size) {
  const wrapper = document.querySelector(".landing-preview-frame-wrap");
  wrapper?.classList.toggle("mobile", size === "mobile");
}

function showProductForm() {
  const form = document.querySelector("#productSchemaForm");
  form?.reset();
  if (form?.elements.tenant_id) {
    form.elements.tenant_id.value = appState.tenantId || "tenant_demo";
  }
  updateProductCategoryOptions();
  resetProductPriceRows();
  resetProductImageUploads();
  resetProductVariants();
  resetProductLeadCapture();
  resetProductRefundPolicyDefaults();
  updateProductFulfillmentVisibility();
  updateProductRefundPolicyVisibility();
  updateProductIntentVisibility();
  document.querySelector("#productModal")?.classList.remove("hidden");
  document.body.classList.add("modal-open");
  if (!productIsLeadGen()) updateProductPricePreview();
  setTimeout(() => document.querySelector("[name='product_name']")?.focus(), 0);
}

function showProductList() {
  hideLeadIntentModal();
  document.querySelector("#productModal")?.classList.add("hidden");
  document.body.classList.remove("modal-open");
}

const productCategoryOptionsByType = {
  physical: [
    ["apparel", "Apparel"],
    ["beauty_personal_care", "Beauty and Personal Care"],
    ["books_printed_material", "Books and Printed Material"],
    ["dietary_supplement", "Dietary Supplement"],
    ["electronics", "Electronics"],
    ["toys_games", "Toys and Games"],
    ["other", "Other"],
  ],
  digital: [
    ["course", "Course"],
    ["digital_download", "Digital Download"],
    ["membership", "Membership"],
    ["software", "Software"],
    ["other", "Other"],
  ],
  service: [
    ["consulting", "Consulting"],
    ["professional_services", "Professional Services"],
    ["software_as_a_service", "Software As A Service (SAAS)"],
    ["other", "Other"],
  ],
};

function updateProductCategoryOptions() {
  const form = document.querySelector("#productSchemaForm");
  const select = form?.elements.product_category;
  if (!form || !select) return;
  const productType = form.elements.product_type?.value || "physical";
  const categories = productCategoryOptionsByType[productType] || productCategoryOptionsByType.physical;
  const previousValue = select.value;
  select.innerHTML = '<option value="">Select a category</option>';
  categories.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  });
  select.value = categories.some(([value]) => value === previousValue) ? previousValue : "";
}

const leadActionOptions = [
  {
    value: "capture_email",
    title: "Capture emails",
    description: "Collect email addresses for a list, waitlist, or downloadable resource.",
    icon: "@",
    color: "#3c81f7",
  },
  {
    value: "capture_phone",
    title: "Capture phone numbers",
    description: "Collect phone numbers for calls, SMS follow-up, or appointment outreach.",
    icon: "TEL",
    color: "#14b8a6",
  },
  {
    value: "capture_email_phone",
    title: "Capture emails and phone numbers",
    description: "Collect both primary contact channels from each lead.",
    icon: "ID",
    color: "#8b5cf6",
  },
  {
    value: "call_number",
    title: "Call a number",
    description: "Send the visitor to a phone call action instead of checkout.",
    icon: "CALL",
    color: "#f97316",
  },
  {
    value: "application",
    title: "Create an application",
    description: "Collect application details for review or approval.",
    icon: "APP",
    color: "#ec4899",
  },
  {
    value: "custom",
    title: "Custom lead flow",
    description: "Reserve this product for a custom lead-generation workflow.",
    icon: "*",
    color: "#64748b",
  },
];

function productIntentValue() {
  return document.querySelector("#productSchemaForm")?.elements.product_intent?.value || "transactional";
}

function productIsLeadGen() {
  return productIntentValue() === "lead_gen";
}

function leadActionDefinition(action) {
  return leadActionOptions.find((option) => option.value === action) || leadActionOptions[0];
}

function setProductStripeWarning(message) {
  const box = document.querySelector("#productStripeWarning");
  if (!box) return;
  box.textContent = message || "";
  box.classList.toggle("hidden", !message);
}

function updateLeadCaptureSummary() {
  const summary = document.querySelector("#leadCaptureSummary");
  const text = document.querySelector("#leadCaptureSummaryText");
  const definition = leadActionDefinition(appState.leadCaptureAction);
  if (text) text.textContent = definition.title;
  summary?.classList.toggle("hidden", !productIsLeadGen());
}

function renderLeadActionCards() {
  const grid = document.querySelector("#leadActionGrid");
  if (!grid) return;
  grid.innerHTML = leadActionOptions.map((option) => `
    <button class="lead-action-card" type="button" data-lead-action="${escapeHtml(option.value)}">
      <span class="lead-action-selected" aria-hidden="true">✓</span>
      <span class="lead-action-icon" style="background:${escapeHtml(option.color)}">${escapeHtml(option.icon)}</span>
      <h3>${escapeHtml(option.title)}</h3>
      <p>${escapeHtml(option.description)}</p>
    </button>
  `).join("");
  updateLeadActionSelection();
}

function updateLeadActionSelection() {
  document.querySelectorAll("[data-lead-action]").forEach((card) => {
    card.classList.toggle("selected", card.dataset.leadAction === appState.leadCaptureAction);
  });
}

function selectLeadAction(action) {
  appState.leadCaptureAction = leadActionDefinition(action).value;
  updateLeadActionSelection();
  updateLeadCaptureSummary();
}

function resetProductLeadCapture() {
  appState.leadCaptureAction = "capture_email";
  updateLeadCaptureSummary();
}

function showLeadIntentModal() {
  renderLeadActionCards();
  document.querySelector("#leadIntentModal")?.classList.remove("hidden");
}

function hideLeadIntentModal() {
  document.querySelector("#leadIntentModal")?.classList.add("hidden");
}

async function productStripeGatewayReady() {
  try {
    const status = await apiRequest("/stripe/connect/status", { allowNotFound: true });
    if (status?.connected || status?.stripe_account_id || status?.account_id || status?.details_submitted) {
      return true;
    }
  } catch (error) {
    // Keep this check soft. Some local/API states may not expose connect status yet.
  }
  try {
    const keys = await apiRequest("/stripe/keys", { allowNotFound: true });
    return Boolean(keys?.stripe_keys?.publishable_key || keys?.publishable_key || keys?.configured || keys?.has_keys || keys?.has_secret_key);
  } catch (error) {
    return false;
  }
}

async function handleProductCanonicalChange() {
  const form = document.querySelector("#productSchemaForm");
  if (!form) return;
  if (form.elements.product_canonical?.value !== "true") {
    setProductStripeWarning("");
    return;
  }
  if (productIsLeadGen()) {
    form.elements.product_canonical.value = "false";
    setProductStripeWarning("");
    return;
  }
  const ready = await productStripeGatewayReady();
  if (!ready) {
    form.elements.product_canonical.value = "false";
    setProductStripeWarning("You must first have Stripe set up for this account before enabling the gateway.");
    return;
  }
  setProductStripeWarning("");
}

function updateProductIntentVisibility() {
  const form = document.querySelector("#productSchemaForm");
  const isLeadGen = productIsLeadGen();
  document.querySelectorAll("[data-transactional-section]").forEach((element) => {
    element.classList.toggle("hidden", isLeadGen);
  });
  if (isLeadGen && form?.elements.product_canonical) {
    form.elements.product_canonical.value = "false";
    setProductStripeWarning("");
  }
  updateLeadCaptureSummary();
  if (!isLeadGen) {
    updateProductFulfillmentVisibility();
    updateProductRefundPolicyVisibility();
  }
}

function buildProductLeadCapture() {
  const definition = leadActionDefinition(appState.leadCaptureAction);
  const fieldsByAction = {
    capture_email: [{ name: "email", type: "email", required: true }],
    capture_phone: [{ name: "phone", type: "tel", required: true }],
    capture_email_phone: [
      { name: "email", type: "email", required: true },
      { name: "phone", type: "tel", required: true },
    ],
    call_number: [{ name: "phone_target", type: "tel", required: true }],
    application: [
      { name: "email", type: "email", required: true },
      { name: "application", type: "textarea", required: true },
    ],
    custom: [],
  };
  return {
    action: definition.value,
    title: definition.title,
    description: definition.description,
    fields: fieldsByAction[definition.value] || [],
  };
}

function resetProductPriceRows() {
  const container = document.querySelector("#productPriceRows");
  if (!container) return;
  container.innerHTML = productPriceRowHtml(0, { isDefault: true });
  updateProductPricePreview();
}

function productPriceRowHtml(index, price = {}) {
  const rowNumber = index + 1;
  const priceId = price.priceId || generateLocalId();
  const amount = price.amount ?? "0.00";
  const compareAtAmount = price.compareAtAmount ?? "0.00";
  const currency = (price.currency || "usd").toLowerCase();
  const quantity = price.quantity || 1;
  const pricingModel = price.pricingModel || "one_time";
  const feeHandling = price.feeHandling || "standard";
  const context = price.context || "standard";
  const minAmount = price.minAmount ?? "0.00";
  const suggestedAmount = price.suggestedAmount ?? "0.00";
  return `<div class="modal-pricing-body product-price-row" data-price-index="${index}" data-price-id="${escapeHtml(priceId)}">
    <div class="price-line-header">
      <strong>Price ${rowNumber}</strong>
      <div class="price-line-actions">
        <label class="inline-check"><input data-price-field="default" type="checkbox" ${price.isDefault ? "checked" : ""}><span>Default price</span></label>
        <button type="button" class="danger-action" data-remove-price ${index === 0 ? "disabled" : ""}>Remove</button>
      </div>
    </div>
    <div class="modal-price-grid">
      <label>Sales price<input data-price-field="amount" type="number" min="0" step="0.01" placeholder="0.00" value="${escapeHtml(amount)}"></label>
      <label><span class="label-line">Regular price <button class="field-tooltip" type="button" data-tooltip="Optional. Shown as a struck-through reference price when it is higher than the sales price." aria-label="Regular price help">?</button></span><input data-price-field="compare_at_amount" type="number" min="0" step="0.01" placeholder="0.00" value="${escapeHtml(compareAtAmount)}"></label>
      <label>Currency
        <select data-price-field="currency">
          ${["usd", "eur", "gbp", "cad"].map((code) => `<option value="${code}" ${code === currency ? "selected" : ""}>${code.toUpperCase()}</option>`).join("")}
        </select>
      </label>
      <label>Quantity<input data-price-field="quantity" type="number" min="1" value="${escapeHtml(quantity)}"></label>
    </div>
    <div class="modal-pricing-options">
      <fieldset>
        <legend>Pricing model</legend>
        ${radioOption(`pricing_model_${index}`, "one_time", "One-time", pricingModel)}
        ${radioOption(`pricing_model_${index}`, "recurring", "Recurring", pricingModel)}
        ${radioOption(`pricing_model_${index}`, "customer_chooses", "Customer chooses", pricingModel)}
      </fieldset>
      <fieldset>
        <legend>Fee handling</legend>
        ${radioOption(`fee_handling_${index}`, "standard", "Standard <span>fees deducted</span>", feeHandling)}
        ${radioOption(`fee_handling_${index}`, "net_guaranteed", "Net-guaranteed <span>fees added on top</span>", feeHandling)}
      </fieldset>
    </div>
    <label class="price-context-select">
      <span class="label-line">Price context <button class="field-tooltip" type="button" data-toggle-context-help aria-expanded="false" aria-label="Price context help">?</button></span>
      <select data-price-field="context">
        ${priceContextOptions(context)}
      </select>
    </label>
    <div class="price-context-help hidden" data-price-context-help>
      <p>This option determines the context in which an offer is presented:</p>
      <ul>
        <li><strong>Standard:</strong> normal storefront / landing page price.</li>
        <li><strong>Sale:</strong> discounted price that will be tagged as "sale" on the page.</li>
        <li><strong>Flash sale:</strong> time-sensitive sale price paired with a countdown timer.</li>
        <li><strong>Upsell:</strong> price offered after a purchase is successfully completed.</li>
        <li><strong>Downsell:</strong> price offered after an upsell is declined.</li>
        <li><strong>Order Bump:</strong> a relatively small add-on price shown during checkout.</li>
      </ul>
    </div>
    <div class="customer-chooses-grid">
      <label>Minimum amount<input data-price-field="min_amount" type="number" min="0" step="0.01" placeholder="0.00" value="${escapeHtml(minAmount)}"></label>
      <label>Suggested amount<input data-price-field="suggested_amount" type="number" min="0" step="0.01" placeholder="0.00" value="${escapeHtml(suggestedAmount)}"></label>
    </div>
    <div class="price-preview"><span>Preview:</span><strong>$0.00</strong></div>
  </div>`;
}

function radioOption(name, value, label, selectedValue) {
  return `<label><input name="${name}" type="radio" value="${value}" ${value === selectedValue ? "checked" : ""}> ${label}</label>`;
}

function priceContextOptions(selectedValue) {
  return [
    ["standard", "Standard"],
    ["sale", "Sale"],
    ["flash_sale", "Flash sale"],
    ["upsell", "Upsell"],
    ["downsell", "Downsell"],
    ["order_bump", "Order bump"],
  ].map(([value, label]) => `<option value="${value}" ${value === selectedValue ? "selected" : ""}>${label}</option>`).join("");
}

function addProductPriceRow() {
  const container = document.querySelector("#productPriceRows");
  if (!container) return;
  const index = container.querySelectorAll(".product-price-row").length;
  container.insertAdjacentHTML("beforeend", productPriceRowHtml(index));
  updateProductPricePreview();
}

function renumberProductPriceRows() {
  document.querySelectorAll(".product-price-row").forEach((row, index) => {
    row.dataset.priceIndex = String(index);
    const title = row.querySelector(".price-line-header strong");
    if (title) title.textContent = `Price ${index + 1}`;
    const removeButton = row.querySelector("[data-remove-price]");
    if (removeButton) removeButton.disabled = index === 0;
    row.querySelectorAll("input[type='radio']").forEach((radio) => {
      if (radio.name.startsWith("pricing_model_")) radio.name = `pricing_model_${index}`;
      if (radio.name.startsWith("fee_handling_")) radio.name = `fee_handling_${index}`;
    });
  });
}

function priceFieldValue(row, field) {
  return row.querySelector(`[data-price-field="${field}"]`)?.value || "";
}

function selectedPriceRadio(row, prefix, fallback) {
  return row.querySelector(`input[name^="${prefix}_"]:checked`)?.value || fallback;
}

function productPriceRows() {
  return Array.from(document.querySelectorAll(".product-price-row"));
}

function priceTenantKeyedAmount(row) {
  const pricingModel = selectedPriceRadio(row, "pricing_model", "one_time");
  return pricingModel === "customer_chooses"
    ? moneyToCents(priceFieldValue(row, "suggested_amount")) || moneyToCents(priceFieldValue(row, "amount"))
    : moneyToCents(priceFieldValue(row, "amount"));
}

function productPriceCalculationPayload(row) {
  const pricingModel = selectedPriceRadio(row, "pricing_model", "one_time");
  return {
    tenant_id: appState.tenantId || "tenant_demo",
    tenant_keyed_amount: priceTenantKeyedAmount(row),
    currency: (priceFieldValue(row, "currency") || "usd").toLowerCase(),
    product_type: document.querySelector("#productSchemaForm")?.elements.product_type?.value || "physical",
    pricing_model: pricingModel,
    fee_handling: selectedPriceRadio(row, "fee_handling", "standard"),
    tenant_plan: appState.tenantPlan || "basic",
    stripe_fee_type: "domestic_card",
  };
}

async function calculateProductPrice(row) {
  const payload = productPriceCalculationPayload(row);
  const cacheKey = JSON.stringify(payload);
  if (appState.priceCalculationCache.has(cacheKey)) {
    return appState.priceCalculationCache.get(cacheKey);
  }
  const result = await apiRequest("/prices/calculate", {
    method: "POST",
    body: payload,
  });
  appState.priceCalculationCache.set(cacheKey, result);
  return result;
}

async function calculateProductPricesForSave() {
  await Promise.all(productPriceRows().map(async (row) => {
    const calculation = await calculateProductPrice(row);
    row.dataset.calculatedUnitAmount = String(calculation.unit_amount ?? "");
    row.dataset.calculatedNetPayout = String(calculation.breakdown?.net_payout ?? "");
    row.dataset.feeBreakdown = JSON.stringify(calculation.breakdown || {});
  }));
}

function priceFeeBreakdown(row) {
  if (!row.dataset.feeBreakdown) return null;
  try {
    const parsed = JSON.parse(row.dataset.feeBreakdown);
    const requiredFields = ["tenant_keyed_amount", "stripe_fee", "platform_fee", "net_payout"];
    if (!requiredFields.every((field) => Number.isFinite(Number(parsed[field])))) return null;
    return parsed;
  } catch {
    return null;
  }
}

function enforceSingleDefaultPrice(target) {
  if (!target.checked) {
    ensureProductDefaultPrice();
    return;
  }
  document.querySelectorAll('[data-price-field="default"]').forEach((input) => {
    if (input !== target) input.checked = false;
  });
}

function ensureProductDefaultPrice() {
  const defaults = Array.from(document.querySelectorAll('[data-price-field="default"]'));
  if (!defaults.length) {
    resetProductPriceRows();
    return;
  }
  if (!defaults.some((input) => input.checked)) defaults[0].checked = true;
}

function buildProductPrices(productId) {
  ensureProductDefaultPrice();
  const rows = productPriceRows();
  return rows.map((row, index) => {
    const pricingModel = selectedPriceRadio(row, "pricing_model", "one_time");
    const feeHandling = selectedPriceRadio(row, "fee_handling", "standard");
    const productType = document.querySelector("#productSchemaForm")?.elements.product_type?.value || "physical";
    const tenantKeyedAmount = priceTenantKeyedAmount(row);
    const fallbackUnitAmount = feeHandling === "net_guaranteed"
      ? netGuaranteedCustomerAmount(tenantKeyedAmount, platformFeeRate(productType, pricingModel))
      : tenantKeyedAmount;
    const calculatedUnitAmount = Number(row.dataset.calculatedUnitAmount);
    const unitAmount = Number.isFinite(calculatedUnitAmount) ? calculatedUnitAmount : fallbackUnitAmount;
    const quantity = Math.max(1, Number(priceFieldValue(row, "quantity") || 1));
    const price = {
      price_id: row.dataset.priceId || generateLocalId(),
      stripe_price_id: null,
      product_id: productId,
      stripe_mode: currentEnvironment,
      active: true,
      currency: (priceFieldValue(row, "currency") || "usd").toLowerCase(),
      quantity,
      pricing_model: pricingModel,
      fee_handling: feeHandling,
      context: priceFieldValue(row, "context") || "standard",
      tenant_keyed_amount: tenantKeyedAmount,
      metadata: { items: String(quantity) },
      is_default: Boolean(row.querySelector('[data-price-field="default"]')?.checked),
    };
    const feeBreakdown = priceFeeBreakdown(row);
    if (feeBreakdown) price.fee_breakdown = feeBreakdown;
    if (pricingModel !== "customer_chooses" || unitAmount > 0) price.unit_amount = unitAmount;
    const compareAtAmount = moneyToCents(priceFieldValue(row, "compare_at_amount"));
    if (compareAtAmount > 0) price.compare_at_unit_amount = compareAtAmount;
    const minAmount = moneyToCents(priceFieldValue(row, "min_amount"));
    const suggestedAmount = moneyToCents(priceFieldValue(row, "suggested_amount"));
    if (pricingModel === "customer_chooses") {
      price.min_amount = minAmount;
      price.suggested_amount = suggestedAmount;
    }
    return price;
  });
}

function updateProductFulfillmentVisibility() {
  const form = document.querySelector("#productSchemaForm");
  const isPhysical = !form || form.elements.product_type.value === "physical";
  document.querySelectorAll("[data-physical-only]").forEach((element) => {
    element.classList.toggle("hidden", !isPhysical);
  });
  if (!isPhysical && form) {
    form.elements.enable_item_size.checked = false;
    form.elements.enable_item_color.checked = false;
    resetProductVariants();
  }
  updateProductVariantVisibility();
}

function updateProductRefundPolicyVisibility() {
  const form = document.querySelector("#productSchemaForm");
  const fields = document.querySelector("#productRefundOverrideFields");
  if (!form || !fields) return;
  fields.classList.toggle("hidden", form.elements.refund_source.value !== "product_override");
  refreshProductRefundPolicyPreview();
}

function resetProductRefundPolicyDefaults() {
  const form = document.querySelector("#productSchemaForm");
  if (!form) return;
  const productType = form.elements.product_type?.value || "physical";
  const defaults = productRefundDefaults(productType);
  if (form.elements.refund_window) form.elements.refund_window.value = defaults.refund_window;
  if (form.elements.refund_condition) form.elements.refund_condition.value = defaults.condition;
  if (form.elements.refund_return_method) form.elements.refund_return_method.value = defaults.return_method;
  refreshProductRefundPolicyPreview();
}

function productRefundDefaults(productType) {
  if (productType === "digital") {
    return {
      refund_window: "non_refundable",
      condition: "not_downloaded",
      return_method: "digital_revoke_access",
    };
  }
  if (productType === "service") {
    return {
      refund_window: "72_hours",
      condition: "any",
      return_method: "no_return_customer_keeps",
    };
  }
  return {
    refund_window: "30_days",
    condition: "unused",
    return_method: "no_return_customer_keeps",
  };
}

function refreshProductRefundPolicyPreview() {
  const form = document.querySelector("#productSchemaForm");
  if (!form) return;
  const definition = productRefundPolicyDefinition(
    form.elements.product_type?.value || "physical",
    form.elements.refund_window?.value || "30_days",
    form.elements.refund_condition?.value || "unused",
    form.elements.refund_return_method?.value || "no_return_customer_keeps",
  );
  if (form.elements.refund_short_label) form.elements.refund_short_label.value = definition.short_label;
  if (form.elements.refund_full_policy) form.elements.refund_full_policy.value = definition.full_policy;
}

function productRefundPolicyDefinition(productType, refundWindow, condition, returnMethod) {
  const windowConfig = {
    non_refundable: { label: "Non-refundable", days: null },
    "72_hours": { label: "72 hours (3 days)", days: 3 },
    "7_days": { label: "7-day money-back", days: 7 },
    "14_days": { label: "14-day money-back", days: 14 },
    "30_days": { label: "30-day money-back", days: 30 },
    "60_days": { label: "60-day money-back", days: 60 },
    custom: { label: "Custom refund policy", days: null },
  }[refundWindow] || { label: "30-day money-back", days: 30 };
  if (refundWindow === "non_refundable") {
    return {
      short_label: "Non-refundable",
      full_policy: productType === "digital"
        ? "All sales are final. Digital items cannot be returned, replaced, or refunded after access is delivered."
        : "All sales are final and as such, no item can be returned, replaced, or refunded in full or in part.",
    };
  }
  if (refundWindow === "custom") {
    return {
      short_label: "Custom refund policy",
      full_policy: "This product uses a custom refund policy. Update this text before publishing.",
    };
  }
  const conditionText = {
    any: "any eligible",
    unused: "unused",
    unopened: "unopened",
    defective_only: "defective",
    not_downloaded: "not downloaded",
    custom: "approved",
  }[condition] || "unused";
  const base = `Refunds are available within ${windowConfig.days} days of delivery in ${conditionText} condition.`;
  const returnText = {
    no_return_customer_keeps: "This item does not need to be returned. The customer may keep the item and dispose of it in a responsible way. The seller may still grant a refund.",
    return_required: "A return is required before a refund is granted. Returns are accomplished with a return label that can be affixed to a package.",
    digital_revoke_access: "Digital access may be revoked when the refund is approved.",
    custom: "",
  }[returnMethod] || "";
  return {
    short_label: windowConfig.label,
    full_policy: [base, returnText].filter(Boolean).join("\n\n"),
  };
}

function buildProductRefundPolicy(productType, values) {
  const source = values.refund_source || "user_preference_default";
  const defaults = productRefundDefaults(productType);
  if (source !== "product_override") {
    const inherited = productRefundPolicyDefinition(productType, defaults.refund_window, defaults.condition, defaults.return_method);
    return {
      source,
      refund_window: defaults.refund_window,
      condition: defaults.condition,
      return_method: defaults.return_method,
      short_label: inherited.short_label,
      full_policy: inherited.full_policy,
    };
  }
  const refundWindow = values.refund_window || defaults.refund_window;
  const condition = values.refund_condition || defaults.condition;
  const returnMethod = values.refund_return_method || defaults.return_method;
  const generated = productRefundPolicyDefinition(productType, refundWindow, condition, returnMethod);
  return {
    source,
    refund_window: refundWindow,
    condition,
    return_method: returnMethod,
    short_label: values.refund_short_label || generated.short_label,
    full_policy: values.refund_full_policy || generated.full_policy,
  };
}

function updateProductVariantVisibility() {
  const form = document.querySelector("#productSchemaForm");
  if (!form) return;
  const isPhysical = form.elements.product_type.value === "physical";
  const sizeEnabled = isPhysical && Boolean(form.elements.enable_item_size?.checked);
  const colorEnabled = isPhysical && Boolean(form.elements.enable_item_color?.checked);
  document.querySelector("#itemSizeOptions")?.classList.toggle("hidden", !sizeEnabled);
  document.querySelector("#itemColorOptions")?.classList.toggle("hidden", !colorEnabled);
}

function resetProductVariants() {
  const form = document.querySelector("#productSchemaForm");
  if (form?.elements.enable_item_size) form.elements.enable_item_size.checked = false;
  if (form?.elements.enable_item_color) form.elements.enable_item_color.checked = false;
  const sizeContainer = document.querySelector("#sizeVariantsContainer");
  const colorContainer = document.querySelector("#colorVariantsContainer");
  if (sizeContainer) sizeContainer.innerHTML = "";
  if (colorContainer) colorContainer.innerHTML = "";
  updateProductVariantVisibility();
}

function addProductVariantItem(type, variant = {}) {
  const container = document.querySelector(type === "size" ? "#sizeVariantsContainer" : "#colorVariantsContainer");
  if (!container) return;
  const isColor = type === "color";
  const labelPlaceholder = isColor ? "Black" : "S";
  const descriptionPlaceholder = isColor ? "e.g., Jet black finish" : "e.g., Waist: 30-32in, Hips: 37-39in";
  container.insertAdjacentHTML("beforeend", `
    <div class="variant-item" data-variant-type="${type}">
      <input class="variant-label-input" data-variant-field="label" placeholder="${labelPlaceholder}" value="${escapeHtml(variant.label || "")}" maxlength="${isColor ? 20 : 10}">
      ${isColor ? `<input class="variant-color-preview" data-variant-field="hex_color" type="color" title="Click to pick color" value="${escapeHtml(variant.hex_color || "#000000")}">` : ""}
      <input data-variant-field="description" placeholder="${descriptionPlaceholder}" value="${escapeHtml(variant.description || "")}">
      <button type="button" class="btn-remove-variant" data-remove-variant aria-label="Remove ${type} variant">×</button>
    </div>
  `);
  container.querySelector(".variant-item:last-child input")?.focus();
}

function getProductSizeVariants() {
  return Array.from(document.querySelectorAll('#sizeVariantsContainer [data-variant-type="size"]'))
    .map((row) => ({
      label: row.querySelector('[data-variant-field="label"]')?.value.trim() || "",
      description: row.querySelector('[data-variant-field="description"]')?.value.trim() || "",
    }))
    .filter((variant) => variant.label || variant.description);
}

function getProductColorVariants() {
  return Array.from(document.querySelectorAll('#colorVariantsContainer [data-variant-type="color"]'))
    .map((row) => ({
      label: row.querySelector('[data-variant-field="label"]')?.value.trim() || "",
      hex_color: row.querySelector('[data-variant-field="hex_color"]')?.value || "#000000",
      description: row.querySelector('[data-variant-field="description"]')?.value.trim() || "",
    }))
    .filter((variant) => variant.label || variant.description);
}

function buildProductDocumentFromForm() {
  const form = document.querySelector("#productSchemaForm");
  const values = form ? formValues(form) : {};
  const now = Math.floor(Date.now() / 1000);
  const productId = values.product_id || generateLocalId();
  const productType = values.product_type || "physical";
  const prices = buildProductPrices(productId);
  const defaultPrice = prices.find((price) => price.is_default) || prices[0];
  prices.forEach((price) => delete price.is_default);
  const images = uniqueStrings([...appState.productUploadedImages, ...lines(values.images)]);
  const isPhysical = productType === "physical";
  const sizeEnabled = isPhysical && Boolean(values.enable_item_size);
  const colorEnabled = isPhysical && Boolean(values.enable_item_color);
  const tags = buildProductTags(values);
  return {
    schema_version: "2026-05-29",
    document_type: "product",
    tenant_id: values.tenant_id || appState.tenantId || "tenant_demo",
    product_id: productId,
    stripe_product_id: null,
    stripe_mode: currentEnvironment,
    canonical: false,
    active: Boolean(values.product_active),
    name: values.product_name || "Untitled Product",
    description: values.description || "",
    images,
    product_type: productType,
    product_category: values.product_category || "",
    refund_policy: buildProductRefundPolicy(productType, values),
    variants: {
      size_enabled: sizeEnabled,
      color_enabled: colorEnabled,
      sizes: sizeEnabled ? getProductSizeVariants() : [],
      colors: colorEnabled ? getProductColorVariants() : [],
    },
    prices,
    default_price_id: defaultPrice.price_id,
    fulfillment: {
      requires_shipping: isPhysical,
      ship_from: null,
      weight_lb: isPhysical ? Number(values.package_weight || 0) : null,
      dimensions: {
        length_in: isPhysical ? Number(values.package_length || 0) : null,
        width_in: isPhysical ? Number(values.package_width || 0) : null,
        height_in: isPhysical ? Number(values.package_height || 0) : null,
      },
    },
    sync: {
      status: "pending",
      last_synced_at: null,
      error: null,
    },
    created_at: now,
    updated_at: now,
    tags,
  };
}

function updateProductPricePreview() {
  document.querySelectorAll(".product-price-row").forEach((row) => {
    const preview = row.querySelector(".price-preview");
    if (!preview) return;
    const currency = (priceFieldValue(row, "currency") || "usd").toLowerCase();
    const pricingModel = selectedPriceRadio(row, "pricing_model", "one_time");
    const feeHandling = selectedPriceRadio(row, "fee_handling", "standard");
    const productType = document.querySelector("#productSchemaForm")?.elements.product_type?.value || "physical";
    const saleAmount = pricingModel === "customer_chooses"
      ? moneyToCents(priceFieldValue(row, "suggested_amount")) || moneyToCents(priceFieldValue(row, "amount"))
      : moneyToCents(priceFieldValue(row, "amount"));
    const compareAtAmount = moneyToCents(priceFieldValue(row, "compare_at_amount"));
    const platformRate = platformFeeRate(productType, pricingModel);
    const previewAmount = feeHandling === "net_guaranteed"
      ? netGuaranteedCustomerAmount(saleAmount, platformRate)
      : saleAmount;
    preview.innerHTML = [
      "<span>Preview:</span>",
      `<strong>${escapeHtml(formatCurrency(previewAmount, currency))}</strong>`,
      compareAtAmount > saleAmount ? `<span class="price-preview-compare">${escapeHtml(formatCurrency(compareAtAmount, currency))}</span>` : "",
      feeHandling === "net_guaranteed" && saleAmount > 0
        ? `<span class="price-preview-note">includes Stripe + ${escapeHtml(formatPercent(platformRate))} platform fee</span>`
        : "",
    ].join("");
  });
}

function platformFeeRate(productType, pricingModel) {
  const tier = appState.tenantPlan || "basic";
  const feeClass = pricingModel === "customer_chooses" ? "tip-jar" : productType === "physical" ? "physical" : "digital";
  const configuredRate = appState.platformFee?.[tier]?.[feeClass];
  if (Number.isFinite(Number(configuredRate))) return Number(configuredRate);
  return defaultPlatformFeeConfig.basic[feeClass] || 0;
}

function netGuaranteedCustomerAmount(netAmount, platformRate) {
  if (!netAmount) return 0;
  const variableRate = STRIPE_PERCENT_FEE + platformRate;
  if (variableRate >= 1) return netAmount;
  return Math.ceil((netAmount + STRIPE_FIXED_FEE_CENTS) / (1 - variableRate));
}

function formatPercent(rate) {
  const percent = Number(rate) * 100;
  return `${Number.isInteger(percent) ? percent.toFixed(0) : percent.toFixed(1)}%`;
}

function resetProductImageUploads() {
  appState.productUploadedImages = [];
  const previews = document.querySelector("#productImagePreviews");
  const status = document.querySelector("#productUploadStatus");
  if (previews) previews.innerHTML = "";
  if (status) {
    status.textContent = "";
    status.className = "upload-status";
  }
}

async function handleProductImageFiles(files) {
  if (!files.length) return;
  const validFiles = files.filter((file) => file.type.startsWith("image/") && file.size <= 10 * 1024 * 1024);
  const rejected = files.length - validFiles.length;
  const status = document.querySelector("#productUploadStatus");
  if (rejected && status) {
    status.textContent = `${rejected} file${rejected === 1 ? "" : "s"} skipped. Use image files up to 10MB.`;
    status.className = "upload-status error";
  }
  if (!validFiles.length) return;
  if (uniqueStrings([...appState.productUploadedImages, ...lines(document.querySelector("[name='images']")?.value)]).length + validFiles.length > 8) {
    if (status) {
      status.textContent = "Stripe products support a maximum of 8 images.";
      status.className = "upload-status error";
    }
    return;
  }
  if (status) {
    status.textContent = `Uploading ${validFiles.length} image${validFiles.length === 1 ? "" : "s"}...`;
    status.className = "upload-status uploading";
  }
  let completed = 0;
  for (const file of validFiles) {
    try {
      const url = await uploadProductImage(file);
      completed += 1;
      addProductImageUrl(url);
      if (status) status.textContent = `Uploaded ${completed}/${validFiles.length} image${validFiles.length === 1 ? "" : "s"}...`;
    } catch (error) {
      if (status) {
        status.textContent = `Failed to upload ${file.name}: ${error.message}`;
        status.className = "upload-status error";
      }
      return;
    }
  }
  if (status) {
    status.textContent = `Uploaded ${completed} image${completed === 1 ? "" : "s"}.`;
    status.className = "upload-status success";
  }
}

async function uploadProductImage(file) {
  const apiBase = apiBaseInput.value.trim().replace(/\/$/, "");
  if (!apiBase) throw new Error("API Base URL is required for image uploads");
  const presignResponse = await fetch(`${apiBase}/upload/multiple`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      fileName: file.name,
      contentType: file.type,
      basePrefix: "products",
      targetBucket: "images.juniorbay.net",
    }),
  });
  if (!presignResponse.ok) throw new Error("Failed to get upload URL");
  const presigned = await presignResponse.json();
  const formData = new FormData();
  Object.entries(presigned.upload?.fields || {}).forEach(([key, value]) => formData.append(key, value));
  formData.append("file", file);
  const uploadResponse = await fetch(presigned.upload.url, { method: "POST", body: formData });
  if (!uploadResponse.ok) throw new Error("Failed to upload file");
  return pollProductImageUrl(presigned.id);
}

async function pollProductImageUrl(imageId) {
  const apiBase = apiBaseInput.value.trim().replace(/\/$/, "");
  if (!apiBase) throw new Error("API Base URL is required for image uploads");
  const deadline = Date.now() + 180000;
  let delay = 1200;
  while (Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(8000, Math.ceil(delay * 1.35));
    let body = {};
    try {
      const response = await fetch(`${apiBase}/upload/status/${encodeURIComponent(imageId)}`, { cache: "no-store" });
      body = await response.json().catch(() => ({}));
    } catch {
      continue;
    }
    if (body.status === "failed") throw new Error("Image processing failed");
    for (const url of productImageUrlCandidates(body.urls || {})) {
      if (await imageUrlLoads(url)) return url;
    }
  }
  throw new Error("Timed out waiting for processed image");
}

function preferredProductImageUrl(urls) {
  return productImageUrlCandidates(urls)[0] || "";
}

function productImageUrlCandidates(urls) {
  return uniqueStrings([
    urls.small?.webp,
    urls.small?.jpg,
    urls.medium?.webp,
    urls.medium?.jpg,
    urls.large?.webp,
    urls.large?.jpg,
    urls.original,
  ].filter(Boolean).map(cdnImageUrl));
}

function imageUrlLoads(url, timeoutMs = 4000) {
  if (!url) return Promise.resolve(false);
  return new Promise((resolve) => {
    const image = new Image();
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      image.onload = null;
      image.onerror = null;
      resolve(ok);
    };
    const cacheBuster = url.includes("?") ? "&" : "?";
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.src = `${url}${cacheBuster}_probe=${Date.now()}`;
    setTimeout(() => finish(false), timeoutMs);
  });
}

function cdnImageUrl(url) {
  return url ? String(url).replace("images.juniorbay.net", "images.juniorbay.com") : "";
}

function addProductImageUrl(url) {
  if (!url) return;
  appState.productUploadedImages = uniqueStrings([...appState.productUploadedImages, url]);
  const textarea = document.querySelector("[name='images']");
  if (textarea) textarea.value = uniqueStrings([...lines(textarea.value), url]).join("\n");
  renderProductImagePreviews();
}

function renderProductImagePreviews() {
  const previews = document.querySelector("#productImagePreviews");
  if (!previews) return;
  previews.innerHTML = appState.productUploadedImages.map((url) => `
    <figure class="product-image-preview">
      <img src="${escapeHtml(url)}" alt="Uploaded product image">
      <figcaption>${escapeHtml(shortImageName(url))}</figcaption>
    </figure>
  `).join("");
}

function shortImageName(url) {
  try {
    const parsed = new URL(url);
    return parsed.pathname.split("/").filter(Boolean).pop() || parsed.hostname;
  } catch {
    return url;
  }
}

function uniqueStrings(values) {
  return Array.from(new Set((values || []).map((value) => String(value || "").trim()).filter(Boolean)));
}

function normalizeProductTag(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/[^a-z0-9 ]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function productTagsFromText(value) {
  const normalized = normalizeProductTag(value);
  if (!normalized) return [];
  const stopWords = new Set(["a", "an", "and", "for", "of", "the", "to", "with"]);
  return [
    normalized,
    ...normalized.split(" ").filter((part) => part.length > 2 && !stopWords.has(part)),
  ];
}

function buildProductTags(values) {
  const category = normalizeProductTag(values.product_category || "");
  const productType = normalizeProductTag(values.product_type || "");
  const customTags = String(values.product_tags || "")
    .split(/[,;\n]/)
    .map(normalizeProductTag);
  return uniqueStrings([
    ...productTagsFromText(values.product_name || "Untitled Product"),
    productType,
    category && category !== "other" ? category : "",
    ...customTags,
  ]);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function upsertLocalProduct(product) {
  const existingIndex = appState.products.findIndex((item) => item.product_id === product.product_id);
  if (existingIndex >= 0) {
    appState.products.splice(existingIndex, 1, product);
    return;
  }
  appState.products.push(product);
}

function renderProductTable() {
  const rows = document.querySelector("#productsTableRows");
  const tableWrap = document.querySelector("#productsTableWrap");
  const empty = document.querySelector(".product-empty-state");
  if (!rows || !tableWrap || !empty) return;
  tableWrap.classList.toggle("hidden", !appState.products.length);
  empty.classList.toggle("hidden", Boolean(appState.products.length));
  rows.innerHTML = appState.products.map((product) => productCard(product)).join("");
}

function productCard(product) {
  const price = defaultProductPrice(product);
  const image = product.images?.[0] || "";
  const priceText = price ? formatCurrency(price.unit_amount, price.currency) : "No price";
  const compareAt = price?.compare_at_unit_amount
    ? `<span class="product-card-compare">Regular ${escapeHtml(formatCurrency(price.compare_at_unit_amount, price.currency))}</span>`
    : "";
  const imageMarkup = image
    ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(product.name || "Product image")}">`
    : `<span>${escapeHtml((product.name || "P").slice(0, 1).toUpperCase())}</span>`;
  return `<article class="product-card">
    <div class="product-card-image${image ? "" : " placeholder"}">${imageMarkup}</div>
    <div class="product-card-body">
      <h3>${escapeHtml(product.name || "Untitled Product")}</h3>
      <p>${escapeHtml(product.description || "No description provided.")}</p>
      <div class="product-card-price">
        <strong>${escapeHtml(priceText)}</strong>
        ${compareAt}
      </div>
      <div class="product-card-actions">
        <button type="button" class="secondary-action">Edit</button>
        <button type="button" class="secondary-action">Details</button>
        <button type="button" class="secondary-action">Archive</button>
      </div>
    </div>
  </article>`;
}

function defaultProductPrice(product) {
  const prices = Array.isArray(product.prices) ? product.prices : [];
  return prices.find((price) => price.price_id === product.default_price_id)
    || prices.find((price) => price.active !== false)
    || prices[0]
    || null;
}

function refundSourceLabel(source) {
  const labels = {
    user_preference_default: "User preference",
    tenant_default: "Tenant default",
    product_override: "Product override",
  };
  return labels[source] || source || "Inherited";
}

function renderSimplePageHtml({ page, offer, product, checkout_url: checkoutUrl }) {
  const price = product.prices[0];
  const formattedPrice = formatCurrency(price.unit_amount, price.currency);
  const accent = page.theme.color.accent;
  const href = checkoutUrl || "#checkout";
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(page.seo.title)}</title>
  <style>
    html{font-size:62.5%}
    *{margin:0;padding:0;box-sizing:border-box}
    body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#fff;color:#111827;font-size:1.6rem;padding:3.2rem}
    main{width:min(96rem,100%);margin:0 auto;display:grid;gap:2.4rem}
    h1{font-size:4rem;line-height:1.05;margin-bottom:1rem}
    p{font-size:1.8rem;color:#4b5563}
    .price{border:1px solid ${escapeHtml(accent)};box-shadow:0 0 0 1px ${escapeHtml(accent)};border-radius:.8rem;padding:1.6rem;background:#fff}
    .cta{display:inline-flex;align-items:center;justify-content:center;background:${escapeHtml(accent)};color:#fff;border:0;border-radius:.8rem;padding:1.4rem 1.8rem;font-weight:800;text-decoration:none}
  </style>
</head>
<body>
  <main>
    <section>
      <h1>${escapeHtml(page.sections[0].headline)}</h1>
      <p>${escapeHtml(page.sections[0].subheadline)}</p>
    </section>
    <section class="price">
      <strong>${escapeHtml(offer.items[0].selectable_prices[0].label)}</strong>
      <div>${escapeHtml(formattedPrice)}</div>
    </section>
    <section>
      <a class="cta" href="${escapeHtml(href)}">${escapeHtml(page.sections[2].label)} - ${escapeHtml(formattedPrice)}</a>
    </section>
  </main>
</body>
</html>`;
}

function pageSlug(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "simple-page";
}

function lines(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function commaList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function moneyToCents(value) {
  return Math.round(Number(value || 0) * 100);
}

async function loadRegistration() {
  const body = await apiRequest(`/tenants/${encodeURIComponent(appState.tenantId)}`, { params: {}, allowNotFound: true });
  writeOutput(body);
  if (body.tenant) {
    document.querySelector("#summaryTenant").textContent = body.tenant.tenant_id || appState.tenantId;
    document.querySelector("#summaryStatus").textContent = body.tenant.billing_status || "active";
  }
}

function setDashboardLoading() {
  document.querySelector("#statOrdersValue").textContent = "--";
  document.querySelector("#statRevenueValue").textContent = "--";
  document.querySelector("#statCustomersValue").textContent = "--";
  document.querySelector("#statProductsValue").textContent = "--";
  document.querySelector("#recentOrdersRows").innerHTML = dashboardRow(["Loading", "Backend", "--", "Fetching invoices"]);
  document.querySelector("#activityList").innerHTML = activityItem("Loading activity...", "Fetching notifications");
}

function renderDashboard(data) {
  const paidInvoices = data.invoices.filter((invoice) => invoice.status === "paid" || Number(invoice.amounts?.amount_paid || 0) > 0);
  const revenueCents = paidInvoices.reduce((sum, invoice) => sum + Number(invoice.amounts?.amount_paid || invoice.amounts?.total || 0), 0);
  document.querySelector("#statOrdersValue").textContent = data.invoices.length;
  document.querySelector("#statRevenueValue").textContent = formatCurrency(revenueCents);
  document.querySelector("#statRevenueMeta").textContent = paidInvoices.length ? "From paid invoices" : "No paid invoices yet";
  document.querySelector("#statCustomersValue").textContent = data.customers.length;
  document.querySelector("#statProductsValue").textContent = data.products.length;

  const recentInvoices = [...data.invoices].sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0)).slice(0, 10);
  document.querySelector("#recentOrdersRows").innerHTML = recentInvoices.length
    ? recentInvoices.map((invoice) => dashboardRow([
        formatDate(invoice.created_at),
        invoice.customer?.name || invoice.customer?.email || "N/A",
        formatCurrency(invoice.amounts?.total || invoice.amounts?.amount_due || 0),
        invoice.line_items?.[0]?.description || invoice.description || invoice.invoice_id || "Invoice",
      ])).join("")
    : dashboardRow(["No invoices", "Backend returned 0", "--", "Create invoices to populate this table"], "muted-row");

  const recentActivity = [...data.notifications].sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0)).slice(0, 5);
  document.querySelector("#activityList").innerHTML = recentActivity.length
    ? recentActivity.map((notification) => activityItem(notification.title || notification.message || notification.type, formatDate(notification.created_at))).join("")
    : activityItem("No recent activity", "Notifications endpoint returned 0 items");
  writeOutput({
    dashboard: {
      products: data.products.length,
      customers: data.customers.length,
      invoices: data.invoices.length,
      notifications: data.notifications.length,
      revenue: revenueCents,
    },
  });
}

function dashboardRow(cells, className = "") {
  return `<div class="dashboard-table-row ${className}">${cells.map((cell) => `<span>${escapeHtml(cell)}</span>`).join("")}</div>`;
}

function activityItem(title, time) {
  return `<article class="activity-item"><span class="activity-dot"></span><div><strong>${escapeHtml(title || "Activity")}</strong><span>${escapeHtml(time || "")}</span></div></article>`;
}

function formatCurrency(cents, currency = "usd") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency.toUpperCase() }).format(Number(cents || 0) / 100);
}

function formatDate(epochSeconds) {
  if (!epochSeconds) return "N/A";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "2-digit", year: "numeric" }).format(new Date(Number(epochSeconds) * 1000));
}

function setPanelNote(key, text) {
  const note = document.querySelector(`[data-backend-note="${key}"]`);
  if (note) note.textContent = text;
}

function renderStripeKeys(keys) {
  updateWebhookEndpoints();
  if (!keys) return;
  const mode = keys.mode === "live" ? "live" : "test";
  const publishableInput = document.querySelector(`[name='publishable_key_${mode}']`);
  const secretInput = document.querySelector(`[name='secret_key_${mode}']`);
  const webhookInput = document.querySelector(`[name='webhook_secret_${mode}']`);
  if (publishableInput) publishableInput.value = keys.publishable_key || "";
  if (secretInput) {
    secretInput.value = "";
    secretInput.placeholder = keys.secret_key_ref ? "Saved (hidden)" : `sk_${mode}_...`;
  }
  if (webhookInput) {
    webhookInput.value = "";
    webhookInput.placeholder = keys.webhook_secret_ref ? "Saved (hidden)" : `whsec_${mode}_...`;
  }
  const verifyMode = document.querySelector("[name='verify_mode']");
  if (verifyMode) verifyMode.value = mode;
}

function updateWebhookEndpoints() {
  const tenantId = encodeURIComponent(appState.tenantId || "tenant_demo");
  const testEndpoint = document.querySelector("[name='webhook_endpoint_test']");
  const liveEndpoint = document.querySelector("[name='webhook_endpoint_live']");
  if (testEndpoint) testEndpoint.value = `https://dev.juniorbay.com/webhook/${tenantId}`;
  if (liveEndpoint) liveEndpoint.value = `https://prod.juniorbay.com/webhook/${tenantId}`;
}

function environmentKey(environment = currentEnvironment) {
  return environment === "live" ? "live" : "test";
}

function configEnvironment(environment = currentEnvironment) {
  return environmentKey(environment) === "live" ? "prod" : "dev";
}

function apiBaseStorageKey(environment = currentEnvironment) {
  return `stripeLinkApiBase:${environmentKey(environment)}`;
}

function configuredApiBase(environment = currentEnvironment) {
  const normalized = environmentKey(environment);
  return (
    localStorage.getItem(apiBaseStorageKey(normalized)) ||
    (normalized === "test" ? localStorage.getItem("stripeLinkApiBase") : "") ||
    defaultApiBaseByEnvironment[normalized] ||
    ""
  );
}

async function loadAppConfigApiBase(environment = currentEnvironment, options = {}) {
  const normalized = environmentKey(environment);
  const apiBase = (apiBaseInput.value.trim() || defaultApiBaseByEnvironment[normalized] || "").replace(/\/$/, "");
  updateAppConfigPanel({
    environment: configEnvironment(normalized),
    value: configuredApiBase(normalized),
    status: "Using dashboard fallback until app config is loaded.",
  });
  if (!apiBase) return;
  try {
    const url = new URL(`${apiBase}/app-config/app_config`);
    url.searchParams.set("environment", "global");
    const response = await fetch(url.toString(), {
      headers: {
        "Content-Type": "application/json",
        "X-Environment": normalized,
      },
    });
    const body = await response.json().catch(() => ({}));
    if (body.app_config?.platform_fee) {
      appState.platformFee = normalizedPlatformFee(body.app_config.platform_fee);
      updateProductPricePreview();
    }
    const environmentConfig = body.app_config?.environments?.[configEnvironment(normalized)];
    if (!response.ok || !environmentConfig?.api_base_url) {
      if (options.updatePanel) {
        updateAppConfigPanel({
          environment: configEnvironment(normalized),
          value: configuredApiBase(normalized),
          status: body.message || "No app_config environment block found for this environment.",
        });
      }
      return;
    }
    apiBaseInput.value = environmentConfig.api_base_url;
    localStorage.setItem(apiBaseStorageKey(normalized), environmentConfig.api_base_url);
    updateAppConfigPanel({
      environment: configEnvironment(normalized),
      value: environmentConfig.api_base_url,
      status: `Loaded ${environmentConfig.label || configEnvironment(normalized)} API base URL from app config.`,
    });
  } catch (error) {
    // The dashboard can still run from its environment fallback while config bootstraps.
    if (options.updatePanel) {
      updateAppConfigPanel({
        environment: configEnvironment(normalized),
        value: configuredApiBase(normalized),
        status: "App config endpoint is unavailable. Using dashboard fallback.",
      });
    }
  }
}

function normalizedPlatformFee(platformFee) {
  const normalized = structuredClone(defaultPlatformFeeConfig);
  Object.entries(platformFee || {}).forEach(([tier, fees]) => {
    if (!normalized[tier] || !fees || typeof fees !== "object") return;
    ["physical", "digital", "tip-jar"].forEach((feeClass) => {
      const value = Number(fees[feeClass]);
      if (Number.isFinite(value) && value >= 0 && value <= 1) normalized[tier][feeClass] = value;
    });
  });
  return normalized;
}

function updateAppConfigPanel(config) {
  const environmentInput = document.querySelector("#appConfigEnvironment");
  const apiBaseUrlInput = document.querySelector("#appConfigApiBaseUrl");
  const status = document.querySelector("#appConfigStatus");
  if (environmentInput) environmentInput.value = config.environment || configEnvironment();
  if (apiBaseUrlInput) apiBaseUrlInput.value = config.value || "";
  if (status) status.textContent = config.status || "";
}

function applyEnvironment(environment) {
  const normalized = environment === "live" ? "live" : "test";
  const theme = normalized === "live" ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  mainApp.dataset.theme = theme;
  mainApp.dataset.environment = normalized;
  environmentLabel.textContent = normalized === "live" ? "Live" : "Test";
  environmentLabel.classList.toggle("live", normalized === "live");
  document.querySelectorAll("[data-env-copy]").forEach((node) => {
    node.textContent = normalized === "live" ? "Live" : "Test";
  });
  const verifyMode = document.querySelector("[name='verify_mode']");
  if (verifyMode) verifyMode.value = normalized;
}

function formValues(form) {
  const data = new FormData(form);
  const values = {};
  for (const [key, value] of data.entries()) {
    values[key] = value;
  }
  form.querySelectorAll("input[type='checkbox']").forEach((input) => {
    values[input.name] = input.checked;
  });
  return values;
}

function buildPayload(type, values) {
  const now = Math.floor(Date.now() / 1000);
  if (type === "tenant") {
    return {
      schema_version: "2026-05-29",
      document_type: "tenant_profile",
      tenant_id: values.tenant_id,
      business_name: values.business_name,
      owner_email: values.owner_email,
      support_email: values.support_email,
      tier_id: values.tier_id || "starter",
      billing_status: "trial",
      brand: {
        display_name: values.business_name,
        primary_color: values.primary_color,
      },
      updated_at: now,
      created_at: now,
    };
  }
  if (type === "stripe_keys") {
    const mode = currentEnvironment === "live" ? "live" : "test";
    return {
      schema_version: "2026-05-29",
      document_type: "stripe_keys",
      tenant_id: values.tenant_id,
      mode,
      publishable_key: values[`publishable_key_${mode}`],
      secret_key_ref: values[`secret_key_${mode}`],
      webhook_secret_ref: values[`webhook_secret_${mode}`],
      updated_at: now,
    };
  }
  if (type === "connect") {
    return {
      schema_version: "2026-05-29",
      document_type: "stripe_keys",
      tenant_id: values.tenant_id,
      mode: values.mode,
      connect_account_id: values.connect_account_id,
      connect_status: values.connect_status,
      updated_at: now,
    };
  }
  if (type === "notification") {
    return {
      schema_version: "2026-05-29",
      document_type: "notification",
      tenant_id: values.tenant_id,
      notification_id: `notif_${now}`,
      type: values.notification_type || "paid_invoice",
      severity: values.notification_type === "paid_invoice" ? "success" : "info",
      title: values.notification_title,
      message: values.notification_message,
      status: "unread",
      sort_priority: values.notification_type === "paid_invoice" ? 10 : 0,
      created_at: now,
      read_at: null,
      archived_at: null,
    };
  }
  if (type === "refund_request") {
    return {
      schema_version: "2026-05-29",
      document_type: "refund_request",
      tenant_id: values.tenant_id,
      refund_request_id: `refund_req_${now}`,
      status: values.refund_status || "manual_review",
      risk_level: values.refund_risk_level || "unknown",
      customer: {
        email: values.refund_customer || "customer@example.com",
      },
      order_id: values.refund_order_id,
      page_id: values.refund_page_or_offer && values.refund_page_or_offer.startsWith("page_") ? values.refund_page_or_offer : undefined,
      offer_id: values.refund_page_or_offer && values.refund_page_or_offer.startsWith("offer_") ? values.refund_page_or_offer : undefined,
      reason: "Customer requested a refund from the dashboard.",
      handling: {
        mode: "manual_review",
        sms_notification_sent: false,
      },
      created_at: now,
      updated_at: now,
      resolved_at: null,
    };
  }
  if (type === "shipping") {
    return {
      schema_version: "2026-05-29",
      document_type: "shipping_config",
      tenant_id: values.tenant_id,
      enabled: Boolean(values.shipping_enabled),
      test_mode: Boolean(values.shipping_test_mode),
      auto_fulfill_after_label_purchase: Boolean(values.shipping_auto_fulfill),
      provider: {
        name: values.shipping_provider || "mock",
        api_key_ref: values.shipping_api_key_ref,
        base_url: values.shipping_base_url,
        connection_status: values.shipping_api_key_ref ? "untested" : "not_configured",
      },
      ship_from_address: buildAddress(values, "ship_from"),
      return_address: buildAddress(values, "return"),
      default_parcel: {
        length: Number(values.parcel_length),
        width: Number(values.parcel_width),
        height: Number(values.parcel_height),
        weight: Number(values.parcel_weight),
        distance_unit: values.parcel_distance_unit || "in",
        mass_unit: values.parcel_mass_unit || "oz",
      },
      rate_options: {
        default_service_level: "ground",
        allowed_carriers: [],
        markup_amount: 0,
        free_shipping_threshold: 0,
      },
      label_options: {
        format: "pdf",
        size: "4x6",
      },
      updated_at: now,
    };
  }
  if (type === "customer") {
    const name = values.customer_name || values.customer_search || "Unknown";
    const [firstName, ...rest] = name.split(/\s+/).filter(Boolean);
    return {
      schema_version: "2026-05-29",
      document_type: "customer",
      tenant_id: values.tenant_id,
      customer_id: `cus_local_${(values.customer_email || name).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")}`,
      contact: {
        name,
        first_name: firstName || "",
        last_name: rest.join(" "),
        email: values.customer_email,
        phone: values.customer_phone || "",
      },
      shipping_address: null,
      billing_address: null,
      summary: {
        total_orders: Number(values.customer_total_orders || 0),
        total_spent: Number(values.customer_total_spent || 0),
        currency: values.customer_currency || "usd",
        first_purchase_at: null,
        last_purchase_at: null,
        last_product_name: "",
      },
      product_affinity: [],
      transaction_history: [],
      tags: [],
      metadata: {},
      created_at: now,
      updated_at: now,
    };
  }
  if (type === "service") {
    const serviceId = `svc_${slug(values.service_name || "service")}`;
    return {
      schema_version: "2026-05-29",
      document_type: "service",
      tenant_id: values.tenant_id,
      service_id: serviceId,
      name: values.service_name,
      description: values.service_description,
      duration_minutes: Number(values.service_duration || 60),
      price: {
        currency: "usd",
        unit_amount: Math.round(Number(values.service_price || 0) * 100),
      },
      location_mode: values.service_location_mode || "mobile",
      linked_product: {
        product_id: values.service_product_id || "",
        price_id: values.service_price_id || "",
      },
      presentation: {
        hero_image_url: values.service_hero_image_url || "",
      },
      booking_rules: {
        check_in_required: Boolean(values.service_check_in_required),
        check_in_window_start_minutes: Number(values.service_check_in_start || 15),
        check_in_window_end_minutes: Number(values.service_check_in_end || 5),
        check_in_label: values.service_check_in_label || "Ready on Site",
        completion_required: Boolean(values.service_completion_required),
        completion_label: values.service_completion_label || "Done",
      },
      default_fulfiller_id: values.service_default_fulfiller_id || "",
      allowed_fulfillers: [
        {
          fulfiller_id: values.service_allowed_fulfiller_id || values.service_default_fulfiller_id || "",
          enabled: Boolean(values.service_fulfiller_enabled),
          tips_to_fulfiller: Boolean(values.service_tips_to_fulfiller),
          compensation_override: {
            type: values.service_comp_override_type || "use_fulfiller_default",
            amount: Math.round(Number(values.service_comp_override_amount || 0) * 100),
          },
        },
      ],
      active: Boolean(values.service_active),
      metadata: {},
      created_at: now,
      updated_at: now,
    };
  }
  if (type === "fulfiller") {
    const displayName = values.fulfiller_display_name || `${values.fulfiller_first_name || ""} ${values.fulfiller_last_name || ""}`.trim();
    return {
      schema_version: "2026-05-29",
      document_type: "fulfiller",
      tenant_id: values.tenant_id,
      fulfiller_id: `fulfiller_${slug(displayName || values.fulfiller_email || "person")}`,
      first_name: values.fulfiller_first_name || "",
      last_name: values.fulfiller_last_name || "",
      email: values.fulfiller_email,
      phone: values.fulfiller_phone || "",
      display_name: displayName,
      status: values.fulfiller_status || "active",
      compensation: {
        type: values.fulfiller_comp_type || "flat_fee",
        amount: Math.round(Number(values.fulfiller_comp_amount || 0) * 100),
        tips_to_fulfiller: Boolean(values.fulfiller_tips),
      },
      availability: {
        weekly_hours: defaultWeeklyHours(),
      },
      created_at: now,
      updated_at: now,
    };
  }
  if (type === "tenant_availability") {
    return {
      schema_version: "2026-05-29",
      document_type: "tenant_availability",
      tenant_id: values.tenant_id,
      availability_id: "default",
      timezone: values.availability_timezone || "America/Denver",
      slot_interval_minutes: Number(values.availability_slot_interval || 30),
      lead_time_minutes: Number(values.availability_lead_time || 60),
      buffer_before_minutes: 0,
      buffer_after_minutes: Number(values.availability_buffer_after || 0),
      weekly_hours: defaultWeeklyHours(),
      updated_at: now,
    };
  }
  if (type === "availability_exception") {
    return {
      schema_version: "2026-05-29",
      document_type: "availability_exception",
      tenant_id: values.tenant_id,
      exception_id: `avx_${now}`,
      starts_at: values.exception_start || new Date().toISOString(),
      ends_at: values.exception_end || new Date(Date.now() + 3600000).toISOString(),
      type: values.exception_type || "block",
      reason: values.exception_reason || "",
      fulfiller_scope: values.exception_fulfiller_scope || "all",
      fulfiller_id: values.exception_fulfiller_id || "",
      created_at: now,
      updated_at: now,
    };
  }
  if (type === "appointment") {
    return {
      schema_version: "2026-05-29",
      document_type: "appointment",
      tenant_id: values.tenant_id,
      appointment_id: `appt_${now}`,
      service_id: values.appointment_service_id,
      service_name: "",
      starts_at: values.appointment_start || new Date().toISOString(),
      ends_at: values.appointment_end || new Date(Date.now() + 3600000).toISOString(),
      timezone: "America/Denver",
      status: values.appointment_status || "booked",
      payment_status: "paid",
      assigned_fulfiller_id: values.appointment_fulfiller_id || "",
      customer: {
        email: values.appointment_customer_email,
      },
      price: {
        currency: "usd",
        unit_amount: 0,
      },
      service_location: {},
      rule_snapshot: {},
      manage_token_ref: "",
      checked_in_at: null,
      completed_at: null,
      canceled_at: null,
      created_at: now,
      updated_at: now,
    };
  }
  if (type === "invoice") {
    const unitAmount = Math.round(Number(values.invoice_line_unit_amount || 0) * 100);
    const quantity = Number(values.invoice_line_quantity || 1);
    const total = unitAmount * quantity;
    const dueAt = now + (Number(values.invoice_days_until_due || 0) * 86400);
    return {
      schema_version: "2026-05-29",
      document_type: "invoice",
      tenant_id: values.tenant_id,
      invoice_id: `inv_local_${now}`,
      stripe_invoice_id: "",
      stripe_customer_id: "",
      stripe_mode: "test",
      status: "draft",
      collection_method: "send_invoice",
      customer: {
        name: values.invoice_customer_name,
        email: values.invoice_customer_email,
        phone: values.invoice_customer_phone || "",
        billing_address: null,
        shipping_address: null,
      },
      description: values.invoice_description || "",
      presentation: {
        hero_image_url: values.invoice_hero_image_url || "",
        memo: "Thank you for your business.",
        footer: `Payment is due within ${values.invoice_days_until_due || 0} days.`,
      },
      line_items: [
        {
          line_item_id: `line_${now}`,
          type: "service",
          description: values.invoice_line_description,
          quantity,
          unit_amount: unitAmount,
          amount: total,
          currency: "usd",
          service_id: values.invoice_service_id || "",
          metadata: {},
        },
      ],
      amounts: {
        currency: "usd",
        subtotal: total,
        discount_total: 0,
        tax_total: 0,
        shipping_total: 0,
        total,
        amount_due: total,
        amount_paid: 0,
        amount_remaining: total,
      },
      payment: {
        hosted_invoice_url: "",
        invoice_pdf_url: "",
        receipt_url: "",
        paid_at: null,
      },
      delivery: {
        days_until_due: Number(values.invoice_days_until_due || 0),
        due_at: dueAt,
        sent_at: null,
        last_resent_at: null,
        share_url: "",
        recipient_email: values.invoice_customer_email,
        send_count: 0,
      },
      source: {
        service_id: values.invoice_service_id || "",
        created_from: "dashboard",
      },
      metadata: {},
      created_at: now,
      updated_at: now,
      finalized_at: null,
      voided_at: null,
    };
  }
  if (type === "config") {
    return {
      schema_version: "2026-05-29",
      document_type: "tenant_config",
      tenant_id: values.tenant_id,
      default_currency: values.default_currency || "usd",
      environment: "prod",
      system: {
        api_endpoint: values.api_endpoint,
        environment_label: values.environment_label,
      },
      support: {
        email: values.support_email,
        sms_notification_phone: values.sms_notification_phone,
      },
      page_defaults: {
        upsell: {
          headline: values.upsell_headline,
          subheadline: values.upsell_subheadline,
          accept_button_text: values.upsell_accept_button_text,
          decline_button_text: values.upsell_decline_button_text,
        },
        thank_you: {
          headline: values.thankyou_headline,
          subtitle: values.thankyou_subtitle,
          message: values.thankyou_message,
        },
      },
      checkout: {
        phone_number_collection: {
          enabled: Boolean(values.phone_number_collection_enabled),
          label: values.phone_number_collection_enabled ? "Enabled" : "Disabled",
          description: "When enabled, customers will be asked to provide their phone number at checkout. Useful for physical products to send shipping notifications.",
        },
      },
      custom_domains: {
        enabled: true,
        live_only: true,
        dns_target: "domains.jbay.be",
        domains: values.custom_domain_name ? [
          {
            domain: values.custom_domain_name,
            target_type: "landing_page",
            target_page_id: values.custom_domain_target_page_id,
            status: "pending_dns",
            validation_record: {
              type: values.custom_domain_record_type || "TXT",
              name: values.custom_domain_record_name,
              value: values.custom_domain_record_value,
            },
            created_at: now,
            updated_at: now,
          },
        ] : [],
      },
      legal_defaults: {
        terms_url: values.terms_url,
        privacy_url: values.privacy_url,
        refund_url: values.refund_url,
      },
      analytics_defaults: {
        google_tag_id: values.google_tag_id,
        pixel_id: values.pixel_id,
      },
      updated_at: now,
    };
  }
  if (type === "preferences") {
    return {
      schema_version: "2026-05-29",
      document_type: "user_preferences",
      tenant_id: values.tenant_id,
      user_id: values.user_id,
      theme: values.theme || "system",
      default_stripe_mode: values.default_stripe_mode || "test",
      sidebar_collapsed: Boolean(values.sidebar_collapsed),
      dashboard_home: values.dashboard_home || "dashboard",
      landing_pages: {
        default_template_id: values.default_template_id || "socialite",
        custom_color_themes: [],
      },
      authoring_defaults: {
        refund_policies: {
          physical: buildRefundPolicy(values, "physical"),
          digital: buildRefundPolicy(values, "digital"),
          subscription: buildRefundPolicy(values, "subscription"),
        },
        return_address: {
          instructions: values.return_instructions || "",
          updated_at: now,
        },
        refund_request_handling: {
          mode: values.refund_handling_mode || "manual_review",
          sms_notifications: {
            enabled: Boolean(values.refund_sms_enabled),
            phone_number: values.refund_sms_phone || "",
          },
        },
      },
      updated_at: now,
    };
  }
  if (type === "profile") {
    const displayName = values.display_name || values.email || "User";
    const initials = displayName
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part[0])
      .join("")
      .slice(0, 4)
      .toUpperCase();
    return {
      schema_version: "2026-05-29",
      document_type: "user_profile",
      tenant_id: values.tenant_id,
      user_id: values.user_id,
      email: values.email,
      display_name: displayName,
      role: values.role || "user",
      status: "active",
      avatar: {
        initials,
        background_color: "#514db3",
      },
      profile_images: {
        max_images: 10,
        max_size_bytes: 10485760,
        allowed_mime_types: ["image/png", "image/jpeg", "image/webp"],
        images: [],
      },
      auth: {
        provider: "cognito",
        cognito_username: values.email,
        email_verified: true,
        mfa_enabled: false,
      },
      subscription: {
        account_status: values.account_status || "inactive",
        tier_id: values.tier_id || "starter",
        billing_status: "not_started",
        activation_available: true,
      },
      updated_at: now,
    };
  }
  return values;
}

function buildRefundPolicy(values, prefix) {
  return {
    refund_window: values[`${prefix}_refund_window`],
    condition: values[`${prefix}_condition`] || "any",
    return_method: values[`${prefix}_return_method`],
    short_label: values[`${prefix}_short_label`],
    full_policy: values[`${prefix}_full_policy`],
  };
}

function buildAddress(values, prefix) {
  return {
    name: values[`${prefix}_name`],
    street1: values[`${prefix}_street1`],
    street2: values[`${prefix}_street2`] || "",
    city: values[`${prefix}_city`],
    state: values[`${prefix}_state`],
    postal_code: values[`${prefix}_postal_code`],
    country: values[`${prefix}_country`] || "US",
    phone: values[`${prefix}_phone`] || "",
    email: values[`${prefix}_email`] || "",
  };
}

function defaultWeeklyHours() {
  return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((day, index) => ({
    day,
    enabled: index < 5,
    start_time: "08:00",
    end_time: "18:00",
  }));
}

function slug(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "item";
}

function buildRegistrationPayload() {
  const firstName = document.querySelector("#regFirstName").value.trim();
  const lastName = document.querySelector("#regLastName").value.trim();
  const email = document.querySelector("#regEmail").value.trim();
  const phoneNumber = document.querySelector("#regPhone").value.trim();
  const password = document.querySelector("#regPass").value;
  if (!firstName || !lastName || !email || !phoneNumber || !password) {
    setAuthMessage("regMsg", "Please fill in all required fields.", "error");
    return null;
  }
  if (!/^\+?[1-9]\d{6,14}$/.test(phoneNumber.replace(/[\s().-]/g, ""))) {
    setAuthMessage("regMsg", "Please enter a valid phone number (include country code).", "error");
    return null;
  }
  const tenantId = email.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "tenant_demo";
  const now = Math.floor(Date.now() / 1000);
  return {
    schema_version: "2026-05-29",
    document_type: "tenant_profile",
    tenant_id: tenantId,
    business_name: `${firstName} ${lastName}`,
    owner_email: email,
    owner: {
      first_name: firstName,
      last_name: lastName,
      email,
      phone_number: phoneNumber.startsWith("+") ? phoneNumber : `+${phoneNumber}`,
      email_verified: false,
      phone_verified: false,
    },
    auth: {
      provider: "cognito",
      status: "pending_confirmation",
      confirmed_at: null,
    },
    billing_status: "trial",
    tier_id: "starter",
    created_at: now,
    updated_at: now,
  };
}

function switchAuthTab(tab) {
  document.querySelectorAll("[data-auth-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.authTab === tab);
  });
  document.querySelectorAll(".auth-view").forEach((view) => {
    view.classList.toggle("active", view.id === `auth-${tab}`);
  });
}

function setAuthMessage(id, message, type = "info") {
  const host = document.querySelector(`#${id}`);
  if (!host) return;
  host.innerHTML = message ? `<div class="message ${type}">${escapeHtml(message)}</div>` : "";
}

function showApp(session) {
  appState.session = session;
  appState.tenantId = session.tenant_id || appState.tenantId;
  appState.userId = session.email || appState.userId;
  localStorage.setItem("stripeLinkTenantId", appState.tenantId);
  localStorage.setItem("stripeLinkUserId", appState.userId);
  document.querySelector("#login-section").classList.add("hidden");
  document.querySelector("#main-app").classList.remove("hidden");
  document.querySelector("#summaryTenant").textContent = appState.tenantId || "-";
  document.querySelector("#summaryUser").textContent = appState.userId || "-";
  document.querySelector("#summaryStatus").textContent = session.status || "active";
  document.querySelectorAll("[name='tenant_id']").forEach((input) => {
    input.value = appState.tenantId;
  });
  updateWebhookEndpoints();
  loadPanelData(mainApp.dataset.view || "dashboard");
}

function writeOutput(value) {
  output.textContent = JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

loadSimpleLandingExample();
renderLandingPreviewLocal();
