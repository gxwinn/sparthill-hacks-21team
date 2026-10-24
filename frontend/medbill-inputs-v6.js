/*
 * Shared by the four MedBill HTML pages.
 * Plain browser JavaScript: no libraries, services, or build tools.
 *
 * These basic variables are available to other classic scripts on the page.
 * Number fields are numbers, or null when empty.
 */
let username = "";
let hospital = "";
let insurance = "";
let annualIncome = null;
let householdSize = null;
let language = "";

// These two values stay in memory only. They are NEVER put into browser storage.
let password = "";
let medicalBill = null; // A File object on the information page, or null.

const medbillStorageKey = "medbillShieldInputs";

function loadSavedVariables() {
  let saved = {};

  try {
    saved = JSON.parse(sessionStorage.getItem(medbillStorageKey) || "{}");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) {
      saved = {};
    }
  } catch {
    // If storage is unavailable or contains invalid JSON, the fields still work.
    saved = {};
  }

  username = typeof saved.username === "string" ? saved.username : "";
  hospital = typeof saved.hospital === "string" ? saved.hospital : "";
  insurance = typeof saved.insurance === "string" ? saved.insurance : "";
  annualIncome = typeof saved.annualIncome === "number" &&
    Number.isFinite(saved.annualIncome) ? saved.annualIncome : null;
  householdSize = typeof saved.householdSize === "number" &&
    Number.isFinite(saved.householdSize) ? saved.householdSize : null;
  language = typeof saved.language === "string" ? saved.language : "";
}

function saveVariables() {
  // Explicit allowlist: password and medicalBill are deliberately excluded.
  const saved = {
    username,
    hospital,
    insurance,
    annualIncome,
    householdSize,
    language
  };

  try {
    sessionStorage.setItem(medbillStorageKey, JSON.stringify(saved));
  } catch {
    // Variables remain usable on this page if the browser blocks storage.
    // Use VS Code Live Server for reliable storage across the four pages.
  }
}

function restoreInputValue(id, value) {
  const input = document.getElementById(id);
  if (input) {
    input.value = value === null ? "" : value;
  }
}

function restoreSavedInputs() {
  loadSavedVariables();
  restoreInputValue("username", username);
  restoreInputValue("hospital", hospital);
  restoreInputValue("insurance", insurance);
  restoreInputValue("annualIncome", annualIncome);
  restoreInputValue("householdSize", householdSize);
  restoreInputValue("language", language);
  // Do not restore a password or a file selection from storage.
}

function updateVariables() {
  // Only read controls on the current page; keep other pages' saved values.
  const usernameInput = document.getElementById("username");
  const passwordInput = document.getElementById("password");
  const hospitalInput = document.getElementById("hospital");
  const insuranceInput = document.getElementById("insurance");
  const incomeInput = document.getElementById("annualIncome");
  const sizeInput = document.getElementById("householdSize");
  const languageInput = document.getElementById("language");
  const billInput = document.getElementById("medicalBill");

  if (usernameInput) username = usernameInput.value;
  if (passwordInput) password = passwordInput.value;
  if (hospitalInput) hospital = hospitalInput.value;
  if (insuranceInput) insurance = insuranceInput.value;
  if (incomeInput) {
    annualIncome = Number.isFinite(incomeInput.valueAsNumber)
      ? incomeInput.valueAsNumber : null;
  }
  if (sizeInput) {
    householdSize = Number.isFinite(sizeInput.valueAsNumber)
      ? sizeInput.valueAsNumber : null;
  }
  if (languageInput) language = languageInput.value;
  if (billInput) medicalBill = billInput.files[0] || null;

  saveVariables();
}

restoreSavedInputs();

document.querySelectorAll("input, select").forEach(function (input) {
  input.addEventListener("input", updateVariables);
  input.addEventListener("change", updateVariables);
});

// Also capture values entered by autofill before a navigation link is followed.
document.addEventListener("click", function (event) {
  if (event.target instanceof Element && event.target.closest("a")) {
    updateVariables();
  }
});

window.addEventListener("pagehide", function () {
  updateVariables();
  password = "";
  medicalBill = null;

  const passwordInput = document.getElementById("password");
  if (passwordInput) passwordInput.value = "";
});

// Back/Forward may restore a cached page instead of running its scripts again.
window.addEventListener("pageshow", function (event) {
  if (event.persisted) {
    restoreSavedInputs();
    password = "";
    const passwordInput = document.getElementById("password");
    if (passwordInput) passwordInput.value = "";
  }
});
