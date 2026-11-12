"""
Streamlit Web UI for Invoice Extraction Studio
==============================================
Provides an interactive side-by-side invoice review and auditing workspace:
- Left Pane: Original invoice document viewer (PDF and high-res image rendering).
- Right Pane: Extracted editable form fields (Pydantic schema) with real-time
  mathematical recalculation and confidence scoring indicators (Green, Amber, Red).
- Export: Instant download as standardized JSON and CSV.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
import streamlit as st

from pipeline.extractor import NonInvoiceDocumentError, extract_invoice
from schema.invoice_schema import Invoice, LineItem
from ui.confidence import compute_confidence_scores, evaluate_invoice_math
from ui.converter import (
    get_document_page_count,
    is_image_blank,
    render_document_to_pil,
)
from ui.exporter import export_invoice_files, invoice_to_csv_string

# Page Configuration
st.set_page_config(
    page_title="Invoice Extraction Studio",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .badge-green {
        background-color: #dcfce7;
        color: #15803d;
        border: 1px solid #86efac;
        border-radius: 9999px;
        padding: 3px 10px;
        font-size: 12px;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }
    .badge-amber {
        background-color: #fef3c7;
        color: #b45309;
        border: 1px solid #fcd34d;
        border-radius: 9999px;
        padding: 3px 10px;
        font-size: 12px;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }
    .badge-red {
        background-color: #fee2e2;
        color: #b91c1c;
        border: 1px solid #fca5a5;
        border-radius: 9999px;
        padding: 3px 10px;
        font-size: 12px;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }
    .alert-box-red {
        background-color: #fef2f2;
        border-left: 4px solid #ef4444;
        padding: 12px 16px;
        border-radius: 4px;
        color: #991b1b;
        margin-bottom: 12px;
        font-size: 13px;
    }
    .alert-box-green {
        background-color: #f0fdf4;
        border-left: 4px solid #22c55e;
        padding: 12px 16px;
        border-radius: 4px;
        color: #166534;
        margin-bottom: 12px;
        font-size: 13px;
    }
    .viewer-header {
        font-size: 16px;
        font-weight: 600;
        color: #1e293b;
        margin-bottom: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
TEST_PACK_DIR = ROOT_DIR / "test_pack"
OUTPUTS_DIR = ROOT_DIR / "outputs"
UPLOADS_DIR = OUTPUTS_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Session State Initialization
if "current_doc_name" not in st.session_state:
    st.session_state.current_doc_name = "doc_01_clean_digital_single_item.pdf"
if "invoice_data" not in st.session_state:
    st.session_state.invoice_data = {}
if "selected_page" not in st.session_state:
    st.session_state.selected_page = 0


def render_confidence_badge(badge_type: str, score: float, label: str = "") -> str:
    """Renders HTML markup for confidence badge."""
    text = f"{label} ({score:.0f}%)" if label else f"{score:.0f}%"
    if badge_type == "green":
        return f'<span class="badge-green">● {text}</span>'
    elif badge_type == "amber":
        return f'<span class="badge-amber">▲ {text}</span>'
    else:
        return f'<span class="badge-red">✖ {text}</span>'


def load_document_data(doc_path: Path, engine: str = "local_ocr", force: bool = False) -> Dict[str, Any]:
    """Loads existing extracted JSON or extracts fresh from document with non-invoice guardrails."""
    extracted_file = OUTPUTS_DIR / f"{doc_path.stem}_extracted.json"
    if not force and extracted_file.exists():
        try:
            return json.loads(extracted_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    try:
        invoice = extract_invoice(
            doc_path, engine=engine, save_output=True, strict_math=False, output_dir=OUTPUTS_DIR
        )
        return invoice.model_dump()
    except NonInvoiceDocumentError as e:
        st.error(f"⚠️ Document Upload Rejected by Guardrails: {e}")
        return {
            "vendor_name": "Rejected: Non-Invoice Document",
            "invoice_date": None,
            "due_date": None,
            "line_items": [],
            "subtotal": None,
            "tax_amount": None,
            "grand_total": 0.0,
            "rejection_error": str(e),
        }
    except Exception as e:
        st.error(f"❌ Extraction Error: {e}")
        return {
            "vendor_name": "Extraction Error",
            "invoice_date": None,
            "due_date": None,
            "line_items": [],
            "subtotal": None,
            "tax_amount": None,
            "grand_total": 0.0,
            "rejection_error": str(e),
        }


# ---------------- SIDEBAR NAVIGATION ----------------
with st.sidebar:
    st.title("🧾 Extraction Studio")
    st.markdown("Auditing & human-in-the-loop review workbench.")

    st.subheader("1. Document Selector")

    test_docs = [
        "doc_01_clean_digital_single_item.pdf",
        "doc_02_clean_digital_multi_item.pdf",
        "doc_03_photo_crumpled_receipt.png",
        "doc_04_photo_low_light_blurry.png",
        "doc_05_missing_tax_field.pdf",
        "doc_06_missing_dates_partial.pdf",
        "doc_07_complex_multi_page_table.pdf",
        "doc_08_decimal_edge_case.png",
    ]

    available_docs = [f.name for f in TEST_PACK_DIR.iterdir() if f.name in test_docs]
    if UPLOADS_DIR.exists():
        for uf in UPLOADS_DIR.iterdir():
            if uf.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
                available_docs.append(uf.name)

    available_docs = sorted(list(set(available_docs)))

    current_idx = (
        available_docs.index(st.session_state.current_doc_name)
        if st.session_state.current_doc_name in available_docs
        else 0
    )

    selected_doc = st.selectbox(
        "Choose Invoice Document:",
        options=available_docs,
        index=current_idx,
    )

    uploaded_file = st.file_uploader(
        "Or Upload New Document",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
    )

    engine_choice = st.radio(
        "Extraction Engine:",
        options=["auto", "local_ocr", "gemini"],
        index=0,
        help="'auto' uses Gemini if API key is present, else robust local OCR.",
    )

    # Determine active document path
    active_path = TEST_PACK_DIR / selected_doc
    if not active_path.exists():
        active_path = UPLOADS_DIR / selected_doc

    if uploaded_file is not None:
        saved_upload = UPLOADS_DIR / uploaded_file.name
        saved_upload.write_bytes(uploaded_file.getvalue())
        active_path = saved_upload
        if st.session_state.current_doc_name != uploaded_file.name:
            st.session_state.current_doc_name = uploaded_file.name
            st.session_state.selected_page = 0
            st.session_state.invoice_data = load_document_data(active_path, engine=engine_choice, force=True)
            st.rerun()

    # Instant synchronization when switching dropdown
    if selected_doc != st.session_state.current_doc_name:
        st.session_state.current_doc_name = selected_doc
        st.session_state.selected_page = 0
        st.session_state.invoice_data = load_document_data(active_path, engine=engine_choice, force=False)
        st.rerun()

    if st.button("🔄 Re-Extract Document", use_container_width=True):
        with st.spinner("Extracting fresh invoice entities..."):
            st.session_state.invoice_data = load_document_data(active_path, engine=engine_choice, force=True)
            st.rerun()

    # Initial data load if empty
    if not st.session_state.invoice_data:
        st.session_state.invoice_data = load_document_data(active_path, engine=engine_choice, force=False)

    st.markdown("---")
    st.subheader("Indicator Legend")
    st.markdown(
        """
        - 🟢 **Green (>90%)**: High confidence.
        - 🟡 **Amber (70-90%)**: Review recommended.
        - 🔴 **Red (<70%)**: Mismatch / discrepancy.
        """
    )


# ---------------- MAIN SIDE-BY-SIDE LAYOUT ----------------
col_left, col_right = st.columns([1, 1], gap="large")

# Compute live confidences and math integrity
conf_eval = compute_confidence_scores(st.session_state.invoice_data)
field_scores = conf_eval["field_scores"]
math_eval = conf_eval["math_eval"]
num_pages = get_document_page_count(active_path)


# ================ LEFT COLUMN: ORIGINAL VIEWER ================
with col_left:
    st.markdown(
        f"<div class='viewer-header'>📄 Original Document: <code>{active_path.name}</code></div>",
        unsafe_allow_html=True,
    )

    # Multi-page Controls if > 1 page
    if num_pages > 1:
        col_p1, col_p2 = st.columns([2, 1])
        with col_p1:
            st.session_state.selected_page = st.selectbox(
                f"Page Selector (Total {num_pages} Pages)",
                options=list(range(num_pages)),
                index=st.session_state.selected_page if st.session_state.selected_page < num_pages else 0,
                format_func=lambda x: f"Page {x + 1} of {num_pages}",
            )
        with col_p2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.download_button(
                "📥 Raw PDF",
                data=active_path.read_bytes(),
                file_name=active_path.name,
                mime="application/pdf",
                use_container_width=True,
            )

    # Render Document Image with Multi-tier Converter
    with st.container(border=True):
        try:
            pil_image = render_document_to_pil(
                active_path,
                page_idx=st.session_state.selected_page,
                scale=2.0,
            )
            st.image(
                pil_image,
                caption=f"{active_path.name} (Page {st.session_state.selected_page + 1}/{num_pages})",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Error rendering preview: {e}")
            st.download_button(
                "Download Original File",
                data=active_path.read_bytes(),
                file_name=active_path.name,
            )

    st.caption(
        f"Format: `{active_path.suffix.upper()}` | Size: {active_path.stat().st_size / 1024.0:.1f} KB | Pages: {num_pages}"
    )


# ================ RIGHT COLUMN: EDITABLE FORM ================
with col_right:
    st.markdown(
        "<div class='viewer-header'>✍️ Extracted Form Fields & Verification</div>",
        unsafe_allow_html=True,
    )

    # Document-Level Status Banner
    overall_badge_html = render_confidence_badge(
        conf_eval["overall_badge"],
        conf_eval["overall_score"],
        label=conf_eval["overall_status"],
    )
    st.markdown(
        f"**Audit Status:** {overall_badge_html}",
        unsafe_allow_html=True,
    )

    # Mathematical Discrepancy Alerts
    if not math_eval["is_arithmetically_valid"]:
        for alert in math_eval["alerts"]:
            st.markdown(
                f"<div class='alert-box-red'>⚠️ <b>Discrepancy:</b> {alert['message']}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            "<div class='alert-box-green'>✅ <b>Arithmetic Verified:</b> All line item products, subtotals, and taxes strictly balance with grand total.</div>",
            unsafe_allow_html=True,
        )

    # Editable Form Fields
    with st.container(border=True):
        st.markdown("#### Header Metadata")

        # Vendor Name
        v_badge = render_confidence_badge(
            field_scores["vendor_name"]["badge"],
            field_scores["vendor_name"]["score"],
        )
        col_v1, col_v2 = st.columns([3, 1])
        with col_v1:
            new_vendor = st.text_input(
                "Vendor Name *",
                value=st.session_state.invoice_data.get("vendor_name", ""),
                key=f"vendor_{st.session_state.current_doc_name}",
            )
        with col_v2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.markdown(v_badge, unsafe_allow_html=True)

        if new_vendor != st.session_state.invoice_data.get("vendor_name"):
            st.session_state.invoice_data["vendor_name"] = new_vendor

        # Dates
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            d_badge = render_confidence_badge(
                field_scores["invoice_date"]["badge"],
                field_scores["invoice_date"]["score"],
            )
            st.markdown(f"**Invoice Date** {d_badge}", unsafe_allow_html=True)
            new_inv_date = st.text_input(
                "Invoice Date",
                value=st.session_state.invoice_data.get("invoice_date") or "",
                placeholder="YYYY-MM-DD",
                label_visibility="collapsed",
                key=f"inv_date_{st.session_state.current_doc_name}",
            )
            if new_inv_date != (st.session_state.invoice_data.get("invoice_date") or ""):
                st.session_state.invoice_data["invoice_date"] = new_inv_date.strip() or None

        with col_d2:
            due_badge = render_confidence_badge(
                field_scores["due_date"]["badge"],
                field_scores["due_date"]["score"],
            )
            st.markdown(f"**Due Date** {due_badge}", unsafe_allow_html=True)
            new_due_date = st.text_input(
                "Due Date",
                value=st.session_state.invoice_data.get("due_date") or "",
                placeholder="YYYY-MM-DD",
                label_visibility="collapsed",
                key=f"due_date_{st.session_state.current_doc_name}",
            )
            if new_due_date != (st.session_state.invoice_data.get("due_date") or ""):
                st.session_state.invoice_data["due_date"] = new_due_date.strip() or None

        st.markdown("---")
        st.markdown("#### Itemized Line Items")

        items_badge = render_confidence_badge(
            field_scores["line_items"]["badge"],
            field_scores["line_items"]["score"],
            label=field_scores["line_items"]["reason"],
        )
        st.markdown(items_badge, unsafe_allow_html=True)

        # Dynamic Data Editor keyed by document name to prevent cross-doc stale state
        line_items_list = st.session_state.invoice_data.get("line_items", [])
        editor_key = f"line_items_editor_{st.session_state.current_doc_name}"
        
        edited_items = st.data_editor(
            line_items_list,
            column_config={
                "description": st.column_config.TextColumn(
                    "Description", required=True, width="large"
                ),
                "quantity": st.column_config.NumberColumn(
                    "Quantity", min_value=0.01, step=1.0, format="%.2f"
                ),
                "unit_price": st.column_config.NumberColumn(
                    "Unit Price ($)", min_value=0.0, step=0.5, format="$%.2f"
                ),
                "total": st.column_config.NumberColumn(
                    "Total ($)", min_value=0.0, step=0.5, format="$%.2f"
                ),
            },
            num_rows="dynamic",
            use_container_width=True,
            key=editor_key,
        )

        if edited_items != line_items_list:
            st.session_state.invoice_data["line_items"] = edited_items
            st.rerun()

        # Recalculate and Auto-sum helpers
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("⚡ Recalculate Line Item Totals (`qty * unit_price`)"):
                for it in st.session_state.invoice_data.get("line_items", []):
                    q = float(it.get("quantity") or 0.0)
                    p = float(it.get("unit_price") or 0.0)
                    it["total"] = round(q * p, 2)
                st.rerun()

        with col_btn2:
            if st.button("⚡ Auto-Sum Subtotal from Line Items"):
                item_sum = round(
                    sum(
                        float(it.get("total") or 0.0)
                        for it in st.session_state.invoice_data.get("line_items", [])
                    ),
                    2,
                )
                st.session_state.invoice_data["subtotal"] = item_sum
                tax = float(st.session_state.invoice_data.get("tax_amount") or 0.0)
                st.session_state.invoice_data["grand_total"] = round(item_sum + tax, 2)
                st.rerun()

        st.markdown("---")
        st.markdown("#### Financial Totals & Taxes")

        # Subtotal
        col_s1, col_s2 = st.columns([3, 1])
        with col_s1:
            sub_val = st.session_state.invoice_data.get("subtotal")
            new_sub = st.number_input(
                "Subtotal ($)",
                value=float(sub_val) if sub_val is not None else 0.0,
                step=1.0,
                format="%.2f",
                key=f"subtotal_{st.session_state.current_doc_name}",
            )
        with col_s2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            sub_badge = render_confidence_badge(
                field_scores["subtotal"]["badge"],
                field_scores["subtotal"]["score"],
            )
            st.markdown(sub_badge, unsafe_allow_html=True)

        if new_sub != (sub_val if sub_val is not None else 0.0):
            st.session_state.invoice_data["subtotal"] = new_sub

        # Tax Amount
        col_t1, col_t2 = st.columns([3, 1])
        with col_t1:
            tax_val = st.session_state.invoice_data.get("tax_amount")
            is_tax_exempt = st.checkbox(
                "Tax Exempt / Not Specified",
                value=(tax_val is None),
                key=f"tax_exempt_{st.session_state.current_doc_name}",
            )
            if not is_tax_exempt:
                new_tax = st.number_input(
                    "Tax Amount ($)",
                    value=float(tax_val) if tax_val is not None else 0.0,
                    step=0.5,
                    format="%.2f",
                    key=f"tax_{st.session_state.current_doc_name}",
                )
            else:
                new_tax = None
        with col_t2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            tax_badge = render_confidence_badge(
                field_scores["tax_amount"]["badge"],
                field_scores["tax_amount"]["score"],
            )
            st.markdown(tax_badge, unsafe_allow_html=True)

        if new_tax != tax_val:
            st.session_state.invoice_data["tax_amount"] = new_tax

        # Grand Total
        col_g1, col_g2 = st.columns([3, 1])
        with col_g1:
            gt_val = float(st.session_state.invoice_data.get("grand_total") or 0.0)
            new_gt = st.number_input(
                "Grand Total ($) *",
                value=gt_val,
                step=1.0,
                format="%.2f",
                key=f"grand_total_{st.session_state.current_doc_name}",
            )
        with col_g2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            gt_badge = render_confidence_badge(
                field_scores["grand_total"]["badge"],
                field_scores["grand_total"]["score"],
            )
            st.markdown(gt_badge, unsafe_allow_html=True)

        if new_gt != gt_val:
            st.session_state.invoice_data["grand_total"] = new_gt

    # ---------------- EXPORT FUNCTIONALITY ----------------
    st.markdown("### 📤 Export & Save Reviewed Invoice")

    try:
        validated_invoice = Invoice.model_validate(
            st.session_state.invoice_data, context={"strict_math": False}
        )
        json_output = validated_invoice.to_deterministic_json(indent=2)
    except Exception:
        json_output = json.dumps(st.session_state.invoice_data, indent=2)

    csv_output = invoice_to_csv_string(st.session_state.invoice_data)

    col_exp1, col_exp2, col_exp3 = st.columns(3)

    with col_exp1:
        st.download_button(
            "📥 Download JSON",
            data=json_output,
            file_name=f"{active_path.stem}_reviewed.json",
            mime="application/json",
            use_container_width=True,
        )

    with col_exp2:
        st.download_button(
            "📊 Download CSV",
            data=csv_output,
            file_name=f"{active_path.stem}_reviewed.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col_exp3:
        if st.button("💾 Save to outputs/", use_container_width=True):
            saved = export_invoice_files(
                st.session_state.invoice_data,
                active_path.name,
                output_dir=OUTPUTS_DIR,
            )
            st.success(f"Saved: {saved['json'].name} & {saved['csv'].name}")
