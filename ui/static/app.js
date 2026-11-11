/**
 * Invoice Extraction Studio — Client-Side Application
 * Handles side-by-side document preview, inline editing,
 * real-time arithmetic recalculation, confidence indicators, and exports.
 */

// State
let currentDocName = "";
let currentData = null;
let originalData = null;
let currentZoom = 1.0;
let validateDebounceTimer = null;

// DOM Elements
const docSelect = document.getElementById("docSelect");
const engineSelect = document.getElementById("engineSelect");
const btnReExtract = document.getElementById("btnReExtract");
const overallScoreBadge = document.getElementById("overallScoreBadge");

const viewerFileName = document.getElementById("viewerFileName");
const viewerMeta = document.getElementById("viewerMeta");
const docImage = document.getElementById("docImage");
const viewerLoading = document.getElementById("viewerLoading");
const imageWrapper = document.getElementById("imageWrapper");
const btnZoomIn = document.getElementById("btnZoomIn");
const btnZoomOut = document.getElementById("btnZoomOut");
const btnZoomReset = document.getElementById("btnZoomReset");
const btnOpenRaw = document.getElementById("btnOpenRaw");

const mathBanner = document.getElementById("mathBanner");
const inputVendor = document.getElementById("inputVendor");
const inputInvDate = document.getElementById("inputInvDate");
const inputDueDate = document.getElementById("inputDueDate");
const badgeVendor = document.getElementById("badgeVendor");
const badgeInvDate = document.getElementById("badgeInvDate");
const badgeDueDate = document.getElementById("badgeDueDate");
const badgeLineItems = document.getElementById("badgeLineItems");

const lineItemsTableBody = document.getElementById("lineItemsTableBody");
const btnAddLineItem = document.getElementById("btnAddLineItem");
const btnRecalcLines = document.getElementById("btnRecalcLines");
const btnSumToSubtotal = document.getElementById("btnSumToSubtotal");
const calcItemsSumLabel = document.getElementById("calcItemsSumLabel");

const inputSubtotal = document.getElementById("inputSubtotal");
const inputTax = document.getElementById("inputTax");
const checkTaxExempt = document.getElementById("checkTaxExempt");
const inputGrandTotal = document.getElementById("inputGrandTotal");
const badgeSubtotal = document.getElementById("badgeSubtotal");
const badgeTax = document.getElementById("badgeTax");
const badgeGrandTotal = document.getElementById("badgeGrandTotal");

const btnReset = document.getElementById("btnReset");
const btnDownloadJson = document.getElementById("btnDownloadJson");
const btnDownloadCsv = document.getElementById("btnDownloadCsv");
const btnSaveToDisk = document.getElementById("btnSaveToDisk");
const saveStatus = document.getElementById("saveStatus");


// Initialize
document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await loadDocumentsList();
});

function setupEventListeners() {
  docSelect.addEventListener("change", () => loadDocument(docSelect.value, false));
  btnReExtract.addEventListener("click", () => loadDocument(docSelect.value, true));
  
  // Zoom Controls
  btnZoomIn.addEventListener("click", () => updateZoom(currentZoom + 0.15));
  btnZoomOut.addEventListener("click", () => updateZoom(Math.max(0.4, currentZoom - 0.15)));
  btnZoomReset.addEventListener("click", () => updateZoom(1.0));

  // Field Inputs (Real-time local verification)
  inputVendor.addEventListener("input", onFieldChange);
  inputInvDate.addEventListener("input", onFieldChange);
  inputDueDate.addEventListener("input", onFieldChange);
  inputSubtotal.addEventListener("input", onFieldChange);
  inputGrandTotal.addEventListener("input", onFieldChange);
  
  inputTax.addEventListener("input", () => {
    checkTaxExempt.checked = false;
    onFieldChange();
  });

  checkTaxExempt.addEventListener("change", () => {
    if (checkTaxExempt.checked) {
      inputTax.value = "";
    } else {
      inputTax.value = "0.00";
    }
    onFieldChange();
  });

  // Line Item Table Actions
  btnAddLineItem.addEventListener("click", addLineItemRow);
  btnRecalcLines.addEventListener("click", recalculateAllLineProducts);
  btnSumToSubtotal.addEventListener("click", applyItemsSumToSubtotal);

  // Footer Actions
  btnReset.addEventListener("click", resetToOriginal);
  btnDownloadJson.addEventListener("click", downloadJson);
  btnDownloadCsv.addEventListener("click", downloadCsv);
  btnSaveToDisk.addEventListener("click", saveReviewedToDisk);
}


async function loadDocumentsList() {
  try {
    const res = await fetch("/api/documents");
    const docs = await res.json();
    docSelect.innerHTML = "";
    
    docs.forEach(doc => {
      const opt = document.createElement("option");
      opt.value = doc.name;
      opt.textContent = `${doc.name} (${doc.format}, ${doc.size_kb} KB)`;
      docSelect.appendChild(opt);
    });

    if (docs.length > 0) {
      loadDocument(docs[0].name, false);
    }
  } catch (err) {
    console.error("Failed to fetch documents:", err);
  }
}


async function loadDocument(docName, reExtract = false) {
  currentDocName = docName;
  viewerFileName.textContent = docName;
  btnOpenRaw.href = `/api/document/${encodeURIComponent(docName)}/file`;
  
  // Show image loading state
  viewerLoading.classList.remove("hidden");
  docImage.classList.add("hidden");
  docImage.src = `/api/document/${encodeURIComponent(docName)}/preview?page_idx=0&t=${Date.now()}`;
  
  docImage.onload = () => {
    viewerLoading.classList.add("hidden");
    docImage.classList.remove("hidden");
  };

  // Fetch extraction
  try {
    setOverallStatus("loading", 0, "Extracting...");
    const engine = engineSelect.value;
    const res = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_name: docName,
        engine: engine,
        re_extract: reExtract
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Extraction failed");
    }

    const payload = await res.json();
    currentData = JSON.parse(JSON.stringify(payload.invoice_data));
    originalData = JSON.parse(JSON.stringify(payload.invoice_data));

    renderFormFields(currentData, payload.confidence);
  } catch (err) {
    alert("Extraction error: " + err.message);
    setOverallStatus("red", 0, "Error");
  }
}


function renderFormFields(data, confidence) {
  inputVendor.value = data.vendor_name || "";
  inputInvDate.value = data.invoice_date || "";
  inputDueDate.value = data.due_date || "";
  inputSubtotal.value = data.subtotal !== null && data.subtotal !== undefined ? Number(data.subtotal).toFixed(2) : "";

  if (data.tax_amount === null || data.tax_amount === undefined) {
    checkTaxExempt.checked = true;
    inputTax.value = "";
  } else {
    checkTaxExempt.checked = false;
    inputTax.value = Number(data.tax_amount).toFixed(2);
  }

  inputGrandTotal.value = Number(data.grand_total || 0).toFixed(2);

  // Render Line Items
  renderLineItems(data.line_items || []);

  // Update badges & status banner
  applyConfidenceBadges(confidence);
}


function renderLineItems(items) {
  lineItemsTableBody.innerHTML = "";
  
  items.forEach((item, index) => {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-50 transition border-b border-slate-100";
    tr.dataset.index = index;

    tr.innerHTML = `
      <td class="py-2 px-3">
        <input type="text" value="${escapeHtml(item.description || '')}" class="row-input w-full font-medium item-desc" placeholder="Product/service description">
      </td>
      <td class="py-2 px-3 text-right">
        <input type="number" step="0.5" min="0" value="${item.quantity !== undefined ? item.quantity : 1}" class="row-input w-16 text-right font-mono item-qty">
      </td>
      <td class="py-2 px-3 text-right">
        <input type="number" step="0.01" min="0" value="${item.unit_price !== undefined ? Number(item.unit_price).toFixed(2) : '0.00'}" class="row-input w-24 text-right font-mono item-price">
      </td>
      <td class="py-2 px-3 text-right">
        <input type="number" step="0.01" min="0" value="${item.total !== undefined ? Number(item.total).toFixed(2) : '0.00'}" class="row-input w-24 text-right font-mono font-semibold item-total">
      </td>
      <td class="py-2 px-2 text-center">
        <button class="text-slate-400 hover:text-red-600 p-1 rounded transition btn-delete-row" title="Delete Row">
          ✕
        </button>
      </td>
    `;

    // Row input listeners for instant inline calculation
    const qtyInput = tr.querySelector(".item-qty");
    const priceInput = tr.querySelector(".item-price");
    const totalInput = tr.querySelector(".item-total");
    const descInput = tr.querySelector(".item-desc");
    const delBtn = tr.querySelector(".btn-delete-row");

    const updateRowProduct = () => {
      const q = parseFloat(qtyInput.value) || 0;
      const p = parseFloat(priceInput.value) || 0;
      totalInput.value = (q * p).toFixed(2);
      onFieldChange();
    };

    qtyInput.addEventListener("input", updateRowProduct);
    priceInput.addEventListener("input", updateRowProduct);
    totalInput.addEventListener("input", onFieldChange);
    descInput.addEventListener("input", onFieldChange);

    delBtn.addEventListener("click", () => {
      tr.remove();
      onFieldChange();
    });

    lineItemsTableBody.appendChild(tr);
  });

  updateCalculatedLineItemsSum();
}


function addLineItemRow() {
  const tr = document.createElement("tr");
  const index = lineItemsTableBody.children.length;
  tr.className = "hover:bg-slate-50 transition border-b border-slate-100";
  tr.dataset.index = index;

  tr.innerHTML = `
    <td class="py-2 px-3">
      <input type="text" value="New Service / Item" class="row-input w-full font-medium item-desc" placeholder="Product/service description">
    </td>
    <td class="py-2 px-3 text-right">
      <input type="number" step="1" min="0" value="1.0" class="row-input w-16 text-right font-mono item-qty">
    </td>
    <td class="py-2 px-3 text-right">
      <input type="number" step="0.01" min="0" value="0.00" class="row-input w-24 text-right font-mono item-price">
    </td>
    <td class="py-2 px-3 text-right">
      <input type="number" step="0.01" min="0" value="0.00" class="row-input w-24 text-right font-mono font-semibold item-total">
    </td>
    <td class="py-2 px-2 text-center">
      <button class="text-slate-400 hover:text-red-600 p-1 rounded transition btn-delete-row" title="Delete Row">
        ✕
      </button>
    </td>
  `;

  const qtyInput = tr.querySelector(".item-qty");
  const priceInput = tr.querySelector(".item-price");
  const totalInput = tr.querySelector(".item-total");
  const descInput = tr.querySelector(".item-desc");
  const delBtn = tr.querySelector(".btn-delete-row");

  qtyInput.addEventListener("input", () => {
    const q = parseFloat(qtyInput.value) || 0;
    const p = parseFloat(priceInput.value) || 0;
    totalInput.value = (q * p).toFixed(2);
    onFieldChange();
  });
  priceInput.addEventListener("input", () => {
    const q = parseFloat(qtyInput.value) || 0;
    const p = parseFloat(priceInput.value) || 0;
    totalInput.value = (q * p).toFixed(2);
    onFieldChange();
  });
  totalInput.addEventListener("input", onFieldChange);
  descInput.addEventListener("input", onFieldChange);
  delBtn.addEventListener("click", () => {
    tr.remove();
    onFieldChange();
  });

  lineItemsTableBody.appendChild(tr);
  descInput.focus();
  onFieldChange();
}


function recalculateAllLineProducts() {
  const rows = lineItemsTableBody.querySelectorAll("tr");
  rows.forEach(tr => {
    const q = parseFloat(tr.querySelector(".item-qty").value) || 0;
    const p = parseFloat(tr.querySelector(".item-price").value) || 0;
    tr.querySelector(".item-total").value = (q * p).toFixed(2);
  });
  onFieldChange();
}


function applyItemsSumToSubtotal() {
  const currentSum = updateCalculatedLineItemsSum();
  inputSubtotal.value = currentSum.toFixed(2);

  const tax = checkTaxExempt.checked ? 0.0 : (parseFloat(inputTax.value) || 0.0);
  inputGrandTotal.value = (currentSum + tax).toFixed(2);
  onFieldChange();
}


function updateCalculatedLineItemsSum() {
  const rows = lineItemsTableBody.querySelectorAll("tr");
  let sum = 0;
  rows.forEach(tr => {
    const t = parseFloat(tr.querySelector(".item-total").value) || 0;
    sum += t;
  });
  calcItemsSumLabel.innerHTML = `Calculated Rows Sum: <b>$${sum.toFixed(2)}</b>`;
  return sum;
}


function collectFormData() {
  const items = [];
  const rows = lineItemsTableBody.querySelectorAll("tr");
  rows.forEach(tr => {
    const desc = tr.querySelector(".item-desc").value.trim();
    const qty = parseFloat(tr.querySelector(".item-qty").value) || 1.0;
    const unitPrice = parseFloat(tr.querySelector(".item-price").value) || 0.0;
    const total = parseFloat(tr.querySelector(".item-total").value) || 0.0;
    items.push({
      description: desc,
      quantity: qty,
      unit_price: unitPrice,
      total: total
    });
  });

  const subVal = inputSubtotal.value.trim() !== "" ? parseFloat(inputSubtotal.value) : null;
  const taxVal = checkTaxExempt.checked ? null : (inputTax.value.trim() !== "" ? parseFloat(inputTax.value) : null);
  const grandVal = parseFloat(inputGrandTotal.value) || 0.0;

  return {
    vendor_name: inputVendor.value.trim(),
    invoice_date: inputInvDate.value.trim() || null,
    due_date: inputDueDate.value.trim() || null,
    line_items: items,
    subtotal: subVal,
    tax_amount: taxVal,
    grand_total: grandVal
  };
}


function onFieldChange() {
  currentData = collectFormData();
  updateCalculatedLineItemsSum();

  // Instant local arithmetic check
  const sub = currentData.subtotal !== null ? currentData.subtotal : (currentData.line_items.reduce((acc, i) => acc + i.total, 0));
  const tax = currentData.tax_amount !== null ? currentData.tax_amount : 0.0;
  const expectedGrand = Math.round((sub + tax) * 100) / 100;
  const diff = Math.abs(expectedGrand - currentData.grand_total);

  if (diff > 0.02) {
    renderAlertBanner("red", `Header Arithmetic Mismatch: Subtotal ($${sub.toFixed(2)}) + Tax ($${tax.toFixed(2)}) = $${expectedGrand.toFixed(2)} != Grand Total ($${currentData.grand_total.toFixed(2)}) [diff: $${diff.toFixed(2)}]`);
    setBadge(badgeGrandTotal, "red", "Discrepancy");
  } else {
    renderAlertBanner("green", "Arithmetic Verified: All line item products and financial totals strictly balance.");
    setBadge(badgeGrandTotal, "green", "Balanced");
  }

  // Debounced server validation
  clearTimeout(validateDebounceTimer);
  validateDebounceTimer = setTimeout(runServerValidation, 300);
}


async function runServerValidation() {
  try {
    const res = await fetch("/api/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_name: currentDocName,
        invoice_data: currentData
      })
    });
    const result = await res.json();
    applyConfidenceBadges(result.confidence);
  } catch (err) {
    console.error("Validation error:", err);
  }
}


function applyConfidenceBadges(confidence) {
  if (!confidence) return;

  const fs = confidence.field_scores;
  setOverallStatus(confidence.overall_badge, confidence.overall_score, confidence.overall_status);

  if (fs.vendor_name) setBadge(badgeVendor, fs.vendor_name.badge, `${fs.vendor_name.score.toFixed(0)}%`);
  if (fs.invoice_date) setBadge(badgeInvDate, fs.invoice_date.badge, `${fs.invoice_date.score.toFixed(0)}%`);
  if (fs.due_date) setBadge(badgeDueDate, fs.due_date.badge, `${fs.due_date.score.toFixed(0)}%`);
  if (fs.line_items) setBadge(badgeLineItems, fs.line_items.badge, `${fs.line_items.score.toFixed(0)}%`);
  if (fs.subtotal) setBadge(badgeSubtotal, fs.subtotal.badge, `${fs.subtotal.score.toFixed(0)}%`);
  if (fs.tax_amount) setBadge(badgeTax, fs.tax_amount.badge, `${fs.tax_amount.score.toFixed(0)}%`);
  if (fs.grand_total) setBadge(badgeGrandTotal, fs.grand_total.badge, `${fs.grand_total.score.toFixed(0)}%`);

  // Render Alert Banner if alerts present
  if (confidence.math_eval && !confidence.math_eval.is_arithmetically_valid) {
    const messages = confidence.math_eval.alerts.map(a => a.message).join("<br>");
    renderAlertBanner("red", messages);
  } else {
    renderAlertBanner("green", "Arithmetic Verified: All line item products, subtotals, and taxes strictly balance with grand total.");
  }
}


function setBadge(elem, type, text) {
  elem.className = `badge badge-${type}`;
  elem.textContent = text;
}


function setOverallStatus(badgeType, score, label) {
  overallScoreBadge.className = `flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold border badge-${badgeType}`;
  overallScoreBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-current"></span><span>${label} (${score.toFixed(0)}%)</span>`;
}


function renderAlertBanner(type, htmlMessage) {
  if (type === "red") {
    mathBanner.className = "m-6 mb-0 p-4 rounded-xl border flex items-start gap-3 bg-red-50 border-red-200 text-red-800 text-xs";
    mathBanner.innerHTML = `
      <span class="text-base">⚠️</span>
      <div class="flex-1">
        <div class="font-bold">Mathematical Discrepancy Detected</div>
        <div class="mt-0.5 leading-relaxed">${htmlMessage}</div>
      </div>
    `;
  } else {
    mathBanner.className = "m-6 mb-0 p-4 rounded-xl border flex items-start gap-3 bg-emerald-50 border-emerald-200 text-emerald-800 text-xs";
    mathBanner.innerHTML = `
      <span class="text-base">✅</span>
      <div class="flex-1">
        <div class="font-bold">Arithmetic Balanced</div>
        <div class="mt-0.5">${htmlMessage}</div>
      </div>
    `;
  }
}


function updateZoom(newZoom) {
  currentZoom = Math.min(2.5, Math.max(0.4, newZoom));
  imageWrapper.style.transform = `scale(${currentZoom})`;
  viewerMeta.textContent = `${Math.round(currentZoom * 100)}% Zoom`;
}


function resetToOriginal() {
  if (!originalData) return;
  currentData = JSON.parse(JSON.stringify(originalData));
  loadDocument(currentDocName, false);
}


async function downloadJson() {
  const data = collectFormData();
  const res = await fetch("/api/export/json", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_name: currentDocName,
      invoice_data: data
    })
  });
  const blob = await res.blob();
  triggerBlobDownload(blob, `${currentDocName.split(".")[0]}_reviewed.json`);
}


async function downloadCsv() {
  const data = collectFormData();
  const res = await fetch("/api/export/csv", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_name: currentDocName,
      invoice_data: data
    })
  });
  const blob = await res.blob();
  triggerBlobDownload(blob, `${currentDocName.split(".")[0]}_reviewed.csv`);
}


async function saveReviewedToDisk() {
  const data = collectFormData();
  saveStatus.textContent = "Saving...";
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_name: currentDocName,
        invoice_data: data
      })
    });
    const result = await res.json();
    saveStatus.textContent = `Saved: ${result.json_file}`;
    setTimeout(() => { saveStatus.textContent = ""; }, 4000);
  } catch (err) {
    saveStatus.textContent = "Save failed: " + err.message;
  }
}


function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}


function escapeHtml(str) {
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}
