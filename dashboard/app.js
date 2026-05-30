const output = document.querySelector("#output");
const apiBaseInput = document.querySelector("#apiBase");
const savedApiBase = localStorage.getItem("stripeLinkApiBase") || "";
apiBaseInput.value = savedApiBase;

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
  localStorage.setItem("stripeLinkApiBase", apiBaseInput.value.trim());
  writeOutput({ saved_api_base: apiBaseInput.value.trim() });
});

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`[data-panel="${button.dataset.view}"]`).classList.add("active");
  });
});

document.querySelectorAll("form").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
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
  const apiBase = apiBaseInput.value.trim();
  const path = `/stripe/connect/start?tenant_id=${encodeURIComponent(values.tenant_id)}&mode=${encodeURIComponent(values.mode || "test")}`;
  if (!apiBase) {
    writeOutput({ error: "Set API Base URL before calling the API.", path });
    return;
  }
  const response = await fetch(`${apiBase}${path}`);
  const body = await response.json();
  writeOutput(body);
  if (body.connect_url) {
    window.open(body.connect_url, "_blank", "noopener,noreferrer");
  }
}

async function submitJsonForm(form) {
  const apiBase = apiBaseInput.value.trim();
  const endpoint = form.dataset.endpoint;
  const method = form.dataset.method || "PUT";
  const payload = buildPayload(form.dataset.payload, formValues(form));
  if (!apiBase) {
    writeOutput({ error: "Set API Base URL before calling the API.", endpoint, payload });
    return;
  }
  const response = await fetch(`${apiBase}${endpoint}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  writeOutput(await response.json());
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
    return {
      schema_version: "2026-05-29",
      document_type: "stripe_keys",
      tenant_id: values.tenant_id,
      mode: values.mode,
      publishable_key: values.publishable_key,
      secret_key_ref: values.secret_key_ref,
      webhook_secret_ref: values.webhook_secret_ref,
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
  document.querySelector("#login-section").classList.add("hidden");
  document.querySelector("#main-app").classList.remove("hidden");
  document.querySelector("#summaryTenant").textContent = session.tenant_id || "-";
  document.querySelector("#summaryUser").textContent = session.email || "-";
  document.querySelector("#summaryStatus").textContent = session.status || "active";
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
