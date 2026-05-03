// ============================================
// ALERTS PANEL — Content Script Module
// ============================================
// Renders alert management UI inside the price
// tracker container on Tesco product pages.
// Communicates with background via messages.
// ============================================

if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

const ALERTS_TRANSLATIONS = {
  en: {
    sectionTitle: "Price Alerts",
    loginPrompt: "Log in to set price alerts for this product",
    loginBtn: "Log in",
    noAlerts: "No alerts set for this product",
    createTitle: "Create Alert",
    typeTarget: "Target Price",
    typeDrop: "Percentage Drop",
    targetLabel: "Alert when price drops to",
    dropLabel: "Alert when price drops by",
    createBtn: "Create Alert",
    deleteBtn: "Delete",
    enabledLabel: "Active",
    disabledLabel: "Paused",
    ftSuffix: "Ft",
    pctSuffix: "%",
    allAlertsTitle: "All My Alerts",
    showAll: "Show all alerts",
    hideAll: "Hide",
    product: "Product",
    loading: "Loading...",
    error: "Error loading alerts",
  },
  hu: {
    sectionTitle: "Ár Riasztások",
    loginPrompt: "Jelentkezz be a termékre vonatkozó árriasztás beállításához",
    loginBtn: "Bejelentkezés",
    noAlerts: "Nincs beállított riasztás erre a termékre",
    createTitle: "Riasztás Létrehozása",
    typeTarget: "Célár",
    typeDrop: "Százalékos csökkenés",
    targetLabel: "Riasztás, ha az ár eléri",
    dropLabel: "Riasztás, ha az ár csökken",
    createBtn: "Létrehozás",
    deleteBtn: "Törlés",
    enabledLabel: "Aktív",
    disabledLabel: "Szüneteltetve",
    ftSuffix: "Ft",
    pctSuffix: "%",
    allAlertsTitle: "Összes Riasztás",
    showAll: "Összes riasztás megtekintése",
    hideAll: "Elrejtés",
    product: "Termék",
    loading: "Betöltés...",
    error: "Hiba a riasztások betöltésekor",
  },
};

function getAlertsStrings() {
  const lang = detectLanguage(); // reuse from content.js global
  return ALERTS_TRANSLATIONS[lang] || ALERTS_TRANSLATIONS.en;
}

// ── Build & Inject Alerts Panel ──────────────

async function buildAlertsPanel(tpnc, currentPrice) {
  const t = getAlertsStrings();
  const panel = document.createElement("div");
  panel.className = "tpt-alerts-panel";
  panel.id = "tpt-alerts-panel";

  // Section header
  const header = document.createElement("div");
  header.className = "tpt-alerts-header";
  header.innerHTML = `
    <div class="tpt-alerts-title">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
      </svg>
      <span>${t.sectionTitle}</span>
    </div>
  `;
  panel.appendChild(header);

  // Check auth
  const authStatus = await browser.runtime.sendMessage({ type: "AUTH_STATUS" });

  if (!authStatus || !authStatus.loggedIn) {
    // Not logged in — show prompt
    const loginSection = document.createElement("div");
    loginSection.className = "tpt-alerts-login";
    loginSection.innerHTML = `
      <p class="tpt-alerts-login-text">${t.loginPrompt}</p>
      <button class="tpt-alerts-login-btn" id="tpt-alerts-login-btn">${t.loginBtn}</button>
    `;
    panel.appendChild(loginSection);

    // Attach login handler after insertion
    setTimeout(() => {
      const btn = document.getElementById("tpt-alerts-login-btn");
      if (btn) {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = t.loading;
          const result = await browser.runtime.sendMessage({ type: "AUTH_LOGIN" });
          if (result.success) {
            // Refresh the panel
            const oldPanel = document.getElementById("tpt-alerts-panel");
            if (oldPanel) {
              const newPanel = await buildAlertsPanel(tpnc, currentPrice);
              oldPanel.replaceWith(newPanel);
            }
          } else {
            btn.disabled = false;
            btn.textContent = t.loginBtn;
          }
        });
      }
    }, 0);

    return panel;
  }

  // Logged in — show alerts for this product
  const content = document.createElement("div");
  content.className = "tpt-alerts-content";
  content.innerHTML = `<div class="tpt-alerts-loading">${t.loading}</div>`;
  panel.appendChild(content);

  // Load alerts async
  loadProductAlerts(content, tpnc, currentPrice, t);

  // All-alerts dropdown
  const allAlertsSection = document.createElement("div");
  allAlertsSection.className = "tpt-all-alerts-section";
  allAlertsSection.innerHTML = `
    <button class="tpt-all-alerts-toggle" id="tpt-all-alerts-toggle">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="6 9 12 15 18 9"/>
      </svg>
      ${t.showAll}
    </button>
    <div class="tpt-all-alerts-list" id="tpt-all-alerts-list" style="display:none;"></div>
  `;
  panel.appendChild(allAlertsSection);

  // Toggle handler
  setTimeout(() => {
    const toggleBtn = document.getElementById("tpt-all-alerts-toggle");
    const listEl = document.getElementById("tpt-all-alerts-list");
    if (toggleBtn && listEl) {
      let expanded = false;
      toggleBtn.addEventListener("click", async () => {
        expanded = !expanded;
        if (expanded) {
          listEl.style.display = "block";
          toggleBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="18 15 12 9 6 15"/>
            </svg>
            ${t.hideAll}
          `;
          await loadAllAlerts(listEl, t);
        } else {
          listEl.style.display = "none";
          toggleBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
            ${t.showAll}
          `;
        }
      });
    }
  }, 0);

  return panel;
}

// ── Load alerts for current product ──────────

async function loadProductAlerts(container, tpnc, currentPrice, t) {
  try {
    const result = await browser.runtime.sendMessage({
      type: "ALERTS_LIST_FOR_PRODUCT",
      productId: tpnc,
    });

    if (result.error) {
      container.innerHTML = `<div class="tpt-alerts-error">${t.error}</div>`;
      return;
    }

    const alerts = result.alerts || [];
    container.innerHTML = "";

    // Existing alerts list
    if (alerts.length > 0) {
      const list = document.createElement("div");
      list.className = "tpt-alerts-list";
      for (const alert of alerts) {
        list.appendChild(createAlertRow(alert, tpnc, currentPrice, t, container));
      }
      container.appendChild(list);
    } else {
      const empty = document.createElement("div");
      empty.className = "tpt-alerts-empty";
      empty.textContent = t.noAlerts;
      container.appendChild(empty);
    }

    // Create alert form
    container.appendChild(createAlertForm(tpnc, currentPrice, t, container));
  } catch (err) {
    container.innerHTML = `<div class="tpt-alerts-error">${t.error}</div>`;
  }
}

// ── Create Alert Row ─────────────────────────

function createAlertRow(alert, tpnc, currentPrice, t, container) {
  const row = document.createElement("div");
  row.className = "tpt-alert-row";
  row.dataset.alertId = alert.id;

  const info = document.createElement("div");
  info.className = "tpt-alert-info";

  let description = "";
  if (alert.alertType === "TARGET_PRICE") {
    description = `${t.typeTarget}: ≤ ${alert.targetPrice?.toLocaleString()} ${t.ftSuffix}`;
  } else {
    description = `${t.typeDrop}: ≥ ${alert.dropPercentage}${t.pctSuffix}`;
  }
  info.textContent = description;

  const actions = document.createElement("div");
  actions.className = "tpt-alert-actions";

  // Toggle button
  const toggleBtn = document.createElement("button");
  toggleBtn.className = `tpt-alert-toggle ${alert.enabled ? "tpt-alert-toggle--on" : ""}`;
  toggleBtn.textContent = alert.enabled ? t.enabledLabel : t.disabledLabel;
  toggleBtn.addEventListener("click", async () => {
    const newEnabled = !alert.enabled;
    const result = await browser.runtime.sendMessage({
      type: "ALERTS_TOGGLE",
      alertId: alert.id,
      enabled: newEnabled,
    });
    if (!result.error) {
      alert.enabled = newEnabled;
      toggleBtn.className = `tpt-alert-toggle ${newEnabled ? "tpt-alert-toggle--on" : ""}`;
      toggleBtn.textContent = newEnabled ? t.enabledLabel : t.disabledLabel;
    }
  });

  // Delete button
  const deleteBtn = document.createElement("button");
  deleteBtn.className = "tpt-alert-delete";
  deleteBtn.textContent = t.deleteBtn;
  deleteBtn.addEventListener("click", async () => {
    const result = await browser.runtime.sendMessage({
      type: "ALERTS_DELETE",
      alertId: alert.id,
    });
    if (!result.error) {
      row.remove();
      // If no more alerts, show empty message
      const list = container.querySelector(".tpt-alerts-list");
      if (list && list.children.length === 0) {
        list.remove();
        const empty = document.createElement("div");
        empty.className = "tpt-alerts-empty";
        empty.textContent = t.noAlerts;
        container.insertBefore(empty, container.querySelector(".tpt-alert-form"));
      }
    }
  });

  actions.appendChild(toggleBtn);
  actions.appendChild(deleteBtn);

  row.appendChild(info);
  row.appendChild(actions);
  return row;
}

// ── Create Alert Form ────────────────────────

function createAlertForm(tpnc, currentPrice, t, container) {
  const form = document.createElement("div");
  form.className = "tpt-alert-form";

  form.innerHTML = `
    <div class="tpt-alert-form-title">${t.createTitle}</div>
    <div class="tpt-alert-form-row">
      <select class="tpt-alert-type-select" id="tpt-alert-type">
        <option value="TARGET_PRICE">${t.typeTarget}</option>
        <option value="PERCENTAGE_DROP">${t.typeDrop}</option>
      </select>
    </div>
    <div class="tpt-alert-form-row" id="tpt-alert-value-row">
      <label class="tpt-alert-form-label" id="tpt-alert-value-label">${t.targetLabel}</label>
      <div class="tpt-alert-input-wrap">
        <input type="number" class="tpt-alert-input" id="tpt-alert-value"
               placeholder="${currentPrice ? Math.round(currentPrice * 0.9) : ''}"
               min="1" step="1"/>
        <span class="tpt-alert-input-suffix" id="tpt-alert-suffix">${t.ftSuffix}</span>
      </div>
    </div>
    <button class="tpt-alert-create-btn" id="tpt-alert-create">${t.createBtn}</button>
  `;

  // Type change handler
  setTimeout(() => {
    const typeSelect = form.querySelector("#tpt-alert-type");
    const valueLabel = form.querySelector("#tpt-alert-value-label");
    const valueInput = form.querySelector("#tpt-alert-value");
    const suffix = form.querySelector("#tpt-alert-suffix");
    const createBtn = form.querySelector("#tpt-alert-create");

    if (typeSelect) {
      typeSelect.addEventListener("change", () => {
        if (typeSelect.value === "TARGET_PRICE") {
          valueLabel.textContent = t.targetLabel;
          valueInput.placeholder = currentPrice ? Math.round(currentPrice * 0.9).toString() : "";
          valueInput.min = "1";
          valueInput.max = "";
          suffix.textContent = t.ftSuffix;
        } else {
          valueLabel.textContent = t.dropLabel;
          valueInput.placeholder = "10";
          valueInput.min = "1";
          valueInput.max = "100";
          suffix.textContent = t.pctSuffix;
        }
      });
    }

    if (createBtn) {
      createBtn.addEventListener("click", async () => {
        const type = typeSelect.value;
        const value = parseFloat(valueInput.value);
        if (!value || value <= 0) {
          valueInput.focus();
          return;
        }

        createBtn.disabled = true;
        createBtn.textContent = t.loading;

        const alertData = {
          productId: tpnc,
          alertType: type,
        };

        if (type === "TARGET_PRICE") {
          alertData.targetPrice = value;
        } else {
          alertData.dropPercentage = value;
          alertData.basePriceAtCreation = currentPrice || 0;
        }

        const result = await browser.runtime.sendMessage({
          type: "ALERTS_CREATE",
          alert: alertData,
        });

        createBtn.disabled = false;
        createBtn.textContent = t.createBtn;

        if (!result.error) {
          // Refresh the alerts list
          valueInput.value = "";
          await loadProductAlerts(container, tpnc, currentPrice, t);
        }
      });
    }
  }, 0);

  return form;
}

// ── Load All Alerts (Dropdown) ───────────────

async function loadAllAlerts(container, t) {
  container.innerHTML = `<div class="tpt-alerts-loading">${t.loading}</div>`;

  try {
    const result = await browser.runtime.sendMessage({ type: "ALERTS_LIST" });
    if (result.error) {
      container.innerHTML = `<div class="tpt-alerts-error">${result.message || t.error}</div>`;
      return;
    }

    const alerts = result.alerts || [];
    if (alerts.length === 0) {
      container.innerHTML = `<div class="tpt-alerts-empty">${t.noAlerts}</div>`;
      return;
    }

    container.innerHTML = "";
    const list = document.createElement("div");
    list.className = "tpt-all-alerts-items";

    for (const alert of alerts) {
      const row = document.createElement("div");
      row.className = "tpt-all-alert-row";

      let desc = "";
      if (alert.alertType === "TARGET_PRICE") {
        desc = `${t.typeTarget}: ≤ ${alert.targetPrice?.toLocaleString()} ${t.ftSuffix}`;
      } else {
        desc = `${t.typeDrop}: ≥ ${alert.dropPercentage}${t.pctSuffix}`;
      }

      const statusClass = alert.enabled ? "tpt-dot--on" : "tpt-dot--off";

      row.innerHTML = `
        <span class="tpt-all-alert-dot ${statusClass}"></span>
        <span class="tpt-all-alert-pid">${t.product} #${alert.productId}</span>
        <span class="tpt-all-alert-desc">${desc}</span>
      `;
      list.appendChild(row);
    }

    container.appendChild(list);
  } catch {
    container.innerHTML = `<div class="tpt-alerts-error">${t.error}</div>`;
  }
}
