/**
 * Invoice Extraction Studio — Client-Side Application
 * Provides robust document preview rendering (PDF and image),
 * inline interactive editing, real-time recalculation, confidence indicators, and exports.
 */

// Global State
let currentDocName = "";
let currentData = null;
let originalData = null;
let currentPageIdx = 0;
let totalPages = 1;
let currentZoomMode = "fit"; // "fit" or numeric zoom factor
let currentZoomFactor = 1.0;
let validateDebounceTimer = null;

// DOM Elements
const docSelect = document.getElementById("docSelect");
const fileUploadInput = document.getElementById("fileUploadInput");
const engineSelect = document.getElementById("engineSelect");
const btnReExtract = document.getElementById("btnReExtract");
const overallScoreBadge = document.getElementById("overallScoreBadge");

const viewerContainer = document.getElementById("viewerContainer");
const formSection = document.getElementById("formSection");
const viewerFileName = document.getElementById("viewerFileName");
const viewerMeta = document.getElementById("viewerMeta");
const docImage = document.getElementById("docImage");
const viewerLoading = document.getElementById("viewerLoading");
const imageWrapper = document.getElementById("imageWrapper");
const bboxOverlay = document.getElementById("bboxOverlay");
let activeBoundingBoxes = [];

const pageControls = document.getElementById("pageControls");
const pageIndicator = document.getElementById("pageIndicator");
const btnPrevPage = document.getElementById("btnPrevPage");
const btnNextPage = document.getElementById("btnNextPage");

const btnFitWidth = document.getElementById("btnFitWidth");
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


// Initialization
document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await loadDocumentsList();
});

function setupEventListeners() {
  docSelect.addEventListener("change", () => {
    currentPageIdx = 0;
    loadDocument(docSelect.value, false);
  });

  fileUploadInput.addEventListener("change", handleFileUpload);
  btnReExtract.addEventListener("click", () => loadDocument(docSelect.value, true));
  
  // Page Navigation for Multi-page Documents
  btnPrevPage.addEventListener("click", () => changePage(-1));
  btnNextPage.addEventListener("click", () => changePage(1));

  // Zoom & Scaling Controls
  btnFitWidth.addEventListener("click", () => setZoomMode("fit"));
  btnZoomReset.addEventListener("click", () => setZoomMode(1.0));
  btnZoomIn.addEventListener("click", () => {
    const next = (currentZoomMode === "fit" ? 1.0 : currentZoomFactor) + 0.2;
    setZoomMode(Math.min(3.0, next));
  });
  btnZoomOut.addEventListener("click", () => {
    const next = (currentZoomMode === "fit" ? 1.0 : currentZoomFactor) - 0.2;
    setZoomMode(Math.max(0.4, next));
  });

  // Form Field Listeners (Immediate local arithmetic & debounced server check)
  inputVendor.addEventListener("input", onFieldChange);
  inputInvDate.addEventListener("input", onFieldChange);
  inputDueDate.addEventListener("input", onFieldChange);
  inputSubtotal.addEventListener("input", onFieldChange);
  inputGrandTotal.addEventListener("input", onFieldChange);

  // Field focus highlight overlay links
  inputVendor.addEventListener("focus", () => highlightField("vendor_name"));
  inputVendor.addEventListener("blur", () => unhighlightField("vendor_name"));
  inputInvDate.addEventListener("focus", () => highlightField("invoice_date"));
  inputInvDate.addEventListener("blur", () => unhighlightField("invoice_date"));
  inputDueDate.addEventListener("focus", () => highlightField("due_date"));
  inputDueDate.addEventListener("blur", () => unhighlightField("due_date"));
  inputSubtotal.addEventListener("focus", () => highlightField("subtotal"));
  inputSubtotal.addEventListener("blur", () => unhighlightField("subtotal"));
  inputTax.addEventListener("focus", () => highlightField("tax_amount"));
  inputTax.addEventListener("blur", () => unhighlightField("tax_amount"));
  inputGrandTotal.addEventListener("focus", () => highlightField("grand_total"));
  inputGrandTotal.addEventListener("blur", () => unhighlightField("grand_total"));
  
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

  // Table Line Item Actions
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
    console.error("Failed to fetch document catalog:", err);
  }
}


async function handleFileUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  setOverallStatus("loading", 0, "Uploading...");
  try {
    const res = await fetch("/api/upload", {
      method: "POST",
      body: formData
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Upload failed");
    }

    const info = await res.json();

    // Add to dropdown if not already present
    let opt = Array.from(docSelect.options).find(o => o.value === info.name);
    if (!opt) {
      opt = document.createElement("option");
      opt.value = info.name;
      opt.textContent = `★ ${info.name} (Uploaded, ${info.size_kb} KB)`;
      docSelect.insertBefore(opt, docSelect.firstChild);
    }
    docSelect.value = info.name;

    currentPageIdx = 0;
    await loadDocument(info.name, true);
  } catch (err) {
    alert("Upload error: " + err.message);
    setOverallStatus("red", 0, "Upload Failed");
  } finally {
    fileUploadInput.value = "";
  }
}


async function loadDocument(docName, reExtract = false) {
  currentDocName = docName;
  viewerFileName.textContent = docName;
  btnOpenRaw.href = `/api/document/${encodeURIComponent(docName)}/file`;

  // Reset scroll containers to top immediately so document header is in view
  viewerContainer.scrollTop = 0;
  viewerContainer.scrollLeft = 0;
  formSection.scrollTop = 0;

  // Render Left Document Image
  renderDocumentImage(docName, currentPageIdx);

  // Fetch / Extract Form Data
  setOverallStatus("loading", 0, "Extracting...");
  try {
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
      if (res.status === 422 && err.error === "NON_INVOICE_DOCUMENT") {
        renderAlertBanner(
          "red",
          `🛡️ <strong>Document Upload Rejected:</strong> ${escapeHtml(err.message)} <br><span class="text-xs text-red-600 font-mono">Classification: ${escapeHtml(err.reason || err.detected_type || 'Non-Invoice Document')}</span>`
        );
        setOverallStatus("red", 0, "Rejected");
        clearBoundingBoxes();
        renderEmptyFormForRejection(err.message);
        return;
      }
      throw new Error(err.detail || err.message || "Extraction failed");
    }

    const payload = await res.json();
    currentData = JSON.parse(JSON.stringify(payload.invoice_data));
    originalData = JSON.parse(JSON.stringify(payload.invoice_data));

    // Update Multi-page status
    totalPages = payload.page_count || 1;
    updatePageControls();

    renderFormFields(currentData, payload.confidence);
    renderBoundingBoxes(payload.bounding_boxes || []);
  } catch (err) {
    renderAlertBanner("red", `Extraction Error: ${escapeHtml(err.message)}`);
    setOverallStatus("red", 0, "Error");
  }
}


function renderDocumentImage(docName, pageIdx = 0) {
  viewerLoading.classList.remove("hidden");
  docImage.classList.add("hidden");

  // Construct URL with timestamp to bust cache when needed
  const previewUrl = `/api/document/${encodeURIComponent(docName)}/preview?page_idx=${pageIdx}&scale=2.0&t=${Date.now()}`;
  
  // Create fresh image load
  const imgLoader = new Image();
  imgLoader.onload = () => {
    docImage.src = previewUrl;
    viewerLoading.classList.add("hidden");
    docImage.classList.remove("hidden");
    applyZoomStyles();
  };

  imgLoader.onerror = () => {
    viewerLoading.innerHTML = `
      <div class="text-center p-6 bg-slate-900 border border-slate-800 rounded-lg max-w-sm">
        <div class="text-amber-400 text-2xl mb-2">⚠️</div>
        <div class="text-sm font-semibold text-slate-200 mb-1">Preview Generation Failed</div>
        <div class="text-xs text-slate-400 mb-4">The document could not be converted to a preview frame.</div>
        <a href="/api/document/${encodeURIComponent(docName)}/file" target="_blank" class="inline-block text-xs bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded font-medium">
          Open Raw Document ↗
        </a>
      </div>
    `;
    viewerLoading.classList.remove("hidden");
    docImage.classList.add("hidden");
  };

  imgLoader.src = previewUrl;
}


function updatePageControls() {
  if (totalPages > 1) {
    pageControls.classList.remove("hidden");
    pageIndicator.textContent = `Page ${currentPageIdx + 1} / ${totalPages}`;
    btnPrevPage.disabled = (currentPageIdx <= 0);
    btnNextPage.disabled = (currentPageIdx >= totalPages - 1);
  } else {
    pageControls.classList.add("hidden");
  }
}


function changePage(delta) {
  const newPage = currentPageIdx + delta;
  if (newPage >= 0 && newPage < totalPages) {
    currentPageIdx = newPage;
    updatePageControls();
    renderDocumentImage(currentDocName, currentPageIdx);
    viewerContainer.scrollTop = 0;
  }
}


function setZoomMode(mode) {
  currentZoomMode = mode;
  if (typeof mode === "number") {
    currentZoomFactor = mode;
  }
  applyZoomStyles();
}


function applyZoomStyles() {
  if (!docImage) return;

  if (currentZoomMode === "fit") {
    // Fit width: max-w-full guarantees no horizontal overflow while maintaining aspect ratio
    imageWrapper.style.transform = "none";
    imageWrapper.style.width = "100%";
    imageWrapper.style.maxWidth = "800px";
    docImage.style.width = "100%";
    docImage.style.height = "auto";
    docImage.style.maxWidth = "100%";
    viewerMeta.textContent = "Fit Width";
  } else {
    // Explicit zoom factor
    imageWrapper.style.transform = `scale(${currentZoomFactor})`;
    imageWrapper.style.transformOrigin = "top center";
    imageWrapper.style.width = "auto";
    imageWrapper.style.maxWidth = "none";
    docImage.style.width = "auto";
    docImage.style.maxWidth = "none";
    viewerMeta.textContent = `${Math.round(currentZoomFactor * 100)}%`;
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

    tr.addEventListener("mouseenter", () => highlightField(`line_items[${index}]`));
    tr.addEventListener("mouseleave", () => unhighlightField(`line_items[${index}]`));

    lineItemsTableBody.appendChild(tr);
  });

  updateCalculatedLineItemsSum();
}


function clearBoundingBoxes() {
  if (bboxOverlay) {
    bboxOverlay.innerHTML = "";
  }
  activeBoundingBoxes = [];
}


function renderBoundingBoxes(boxes) {
  clearBoundingBoxes();
  if (!bboxOverlay || !boxes || !boxes.length) return;
  activeBoundingBoxes = boxes;

  boxes.forEach(b => {
    if (!b.box || b.status === "not_found") return;
    const [x0, y0, x1, y1] = b.box;
    const w = (x1 - x0) * 100;
    const h = (y1 - y0) * 100;
    const l = x0 * 100;
    const t = y0 * 100;

    const el = document.createElement("div");
    el.className = `bbox-marker bbox-${b.field.replace(/[\[\].]/g, '_')}`;
    el.dataset.field = b.field;
    el.style.position = "absolute";
    el.style.left = `${l}%`;
    el.style.top = `${t}%`;
    el.style.width = `${Math.max(1.5, w)}%`;
    el.style.height = `${Math.max(1.5, h)}%`;
    el.style.pointerEvents = "auto";
    el.style.cursor = "pointer";
    el.style.transition = "all 0.15s ease-in-out";

    if (b.status === "degraded" || b.status === "fallback") {
      el.style.border = "2px dashed #f59e0b";
      el.style.backgroundColor = "rgba(245, 158, 11, 0.14)";
      el.title = `${b.label || b.field} (Degraded / Fallback Scan)`;
    } else {
      el.style.border = "2px solid #3b82f6";
      el.style.backgroundColor = "rgba(59, 130, 246, 0.12)";
      el.title = `${b.label || b.field} (Extracted)`;
    }

    el.addEventListener("mouseenter", () => highlightField(b.field));
    el.addEventListener("mouseleave", () => unhighlightField(b.field));

    bboxOverlay.appendChild(el);
  });
}


function highlightField(fieldName) {
  if (!bboxOverlay) return;
  const safeName = fieldName.replace(/[\[\].]/g, '_');
  const boxes = bboxOverlay.querySelectorAll(`.bbox-${safeName}`);
  boxes.forEach(bx => {
    bx.style.borderColor = "#10b981";
    bx.style.backgroundColor = "rgba(16, 185, 129, 0.25)";
    bx.style.boxShadow = "0 0 12px rgba(16, 185, 129, 0.5)";
    bx.style.zIndex = "20";
  });
}


function unhighlightField(fieldName) {
  if (!bboxOverlay) return;
  const safeName = fieldName.replace(/[\[\].]/g, '_');
  const boxes = bboxOverlay.querySelectorAll(`.bbox-${safeName}`);
  boxes.forEach(bx => {
    const isDegraded = bx.dataset.field && (activeBoundingBoxes.find(b => b.field === bx.dataset.field)?.status === "degraded" || activeBoundingBoxes.find(b => b.field === bx.dataset.field)?.status === "fallback");
    bx.style.borderColor = isDegraded ? "#f59e0b" : "#3b82f6";
    bx.style.backgroundColor = isDegraded ? "rgba(245, 158, 11, 0.14)" : "rgba(59, 130, 246, 0.12)";
    bx.style.boxShadow = "none";
    bx.style.zIndex = "auto";
  });
}


function renderEmptyFormForRejection(reasonText) {
  inputVendor.value = "REJECTED: Non-Invoice Document";
  inputInvDate.value = "";
  inputDueDate.value = "";
  inputSubtotal.value = "";
  inputTax.value = "";
  inputGrandTotal.value = "0.00";
  lineItemsTableBody.innerHTML = `
    <tr>
      <td colspan="5" class="p-6 text-center text-sm text-red-600 bg-red-50/50">
        🛡️ Document was rejected by invoice domain guardrails. No financial table or line items were extracted.
      </td>
    </tr>
  `;
  badgeVendor.className = "badge badge-red";
  badgeVendor.textContent = "Rejected";
  badgeInvDate.className = "badge badge-red";
  badgeInvDate.textContent = "N/A";
  badgeDueDate.className = "badge badge-red";
  badgeDueDate.textContent = "N/A";
  badgeLineItems.className = "badge badge-red";
  badgeLineItems.textContent = "N/A";
  badgeSubtotal.className = "badge badge-red";
  badgeSubtotal.textContent = "N/A";
  badgeTax.className = "badge badge-red";
  badgeTax.textContent = "N/A";
  badgeGrandTotal.className = "badge badge-red";
  badgeGrandTotal.textContent = "Rejected";
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

  // Render Alert Banner
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
  overallScoreBadge.className = `flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border badge-${badgeType}`;
  overallScoreBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-current"></span><span>${label} (${score.toFixed(0)}%)</span>`;
}


function renderAlertBanner(type, htmlMessage) {
  if (type === "red") {
    mathBanner.className = "m-6 mb-0 p-3.5 rounded-xl border flex items-start gap-2.5 bg-red-50 border-red-200 text-red-800 text-xs";
    mathBanner.innerHTML = `
      <span class="text-base leading-none">⚠️</span>
      <div class="flex-1">
        <div class="font-bold">Mathematical Discrepancy Detected</div>
        <div class="mt-0.5 leading-relaxed text-[11px]">${htmlMessage}</div>
      </div>
    `;
  } else {
    mathBanner.className = "m-6 mb-0 p-3.5 rounded-xl border flex items-start gap-2.5 bg-emerald-50 border-emerald-200 text-emerald-800 text-xs";
    mathBanner.innerHTML = `
      <span class="text-base leading-none">✅</span>
      <div class="flex-1">
        <div class="font-bold">Arithmetic Balanced</div>
        <div class="mt-0.5 text-[11px]">${htmlMessage}</div>
      </div>
    `;
  }
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
