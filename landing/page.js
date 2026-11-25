(() => {
  const list = document.getElementById("slots");
  const error = document.getElementById("config-error");
  const slots = window.GATEWAY_SLOTS;
  let invalid = !Array.isArray(slots) || slots.length === 0;

  if (Array.isArray(slots)) {
    for (const slot of slots) {
      let url;
      try {
        if (!slot || typeof slot.account !== "string" || !slot.account.trim() ||
            typeof slot.url !== "string" || !slot.url.trim()) {
          throw new Error("Invalid slot");
        }
        url = new URL(slot.url, document.baseURI);
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
          throw new Error("Invalid URL");
        }
      } catch {
        invalid = true;
        continue;
      }

      const card = document.createElement("a");
      card.className = "slot";
      card.href = url.href;

      const icon = document.createElement("span");
      icon.className = "slot-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = "+";

      const details = document.createElement("span");
      details.className = "slot-details";
      const status = document.createElement("span");
      status.className = "slot-status";
      status.textContent = "ACCOUNT SLOT";
      const account = document.createElement("strong");
      account.textContent = slot.account;
      const action = document.createElement("span");
      action.className = "slot-action";
      action.textContent = "Open player";
      details.append(status, account, action);

      const arrow = document.createElement("span");
      arrow.className = "arrow";
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "→";
      card.append(icon, details, arrow);
      list.append(card);
    }
  }

  if (invalid) {
    error.hidden = false;
    error.textContent = "One or more slots are missing or invalid. Check the test configuration.";
  }
})();
