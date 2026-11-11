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

import base64
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
import pypdfium2 as pdfium
import streamlit as st

from pipeline.extractor import extract_invoice
from schema.invoice_schema import Invoice, LineItem, MathematicalDiscrepancyError
from ui.confidence import compute_confidence_scores, evaluate_invoice_math
from ui.exporter import export_invoice_files, invoice_to_csv_string

# Page Configuration
st.set_page_config(
    page_title="Invoice Extraction Studio",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling for Badges and Layout
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
UI_ASSETS_DIR = ROOT_DIR / "ui_assets"

# Initialize Session State
if "current_doc_name" not in st.session_state:
    st.session_state.current_doc_name = "doc_01_clean_digital_single_item.pdf"
if "invoice_data" not in st.session_state:
    st.session_state.invoice_data = {}
if "line_items_data" not in st.session_state:
    st.session_state.line_items_data = []
if "is_modified" not in st.session_state:
    st.session_state.is_modified = False


def render_confidence_badge(badge_type: str, score: float, label: str = "") -> str:
    """Renders HTML markup for confidence badge."""
    text = f"{label} ({score:.0f}%)" if label else f"{score:.0f}%"
    if badge_type == "green":
        return f'<span class="badge-green">● {text}</span>'
    elif badge_type == "amber":
        return f'<span class="badge-amber">▲ {text}</span>'
    else:
        return f'<span class="badge-red">✖ {text}</span>'


def load_document_data(doc_path: Path) -> Dict[str, Any]:
    """Loads existing extracted JSON or extracts fresh from document."""
    extracted_file = OUTPUTS_DIR / f"{doc_path.stem}_extracted.json"
    if extracted_file.exists():
        try:
            return json.loads(extracted_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Fallback to fresh extraction
    invoice = extract_invoice(
        doc_path, engine="local_ocr", save_output=True, strict_math=False
    )
    return invoice.model_dump()


def render_document_preview(file_path: Path):
    """Renders PDF pages or image directly into the left column."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        try:
            doc = pdfium.PdfDocument(file_path)
            num_pages = len(doc)
            page_select = 0
            if num_pages > 1:
                page_select = st.selectbox(
                    f"Page (Total {num_pages})",
                    options=list(range(num_pages)),
                    format_func=lambda x: f"Page {x + 1} of {num_pages}",
                )
            page = doc[page_select]
            pil_image = page.render(scale=2.0).to_pil()
            st.image(
                pil_image,
                caption=f"{file_path.name} (Page {page_select + 1})",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Error rendering PDF: {e}")
            st.download_button(
                "Download Original PDF",
                data=file_path.read_bytes(),
                file_name=file_path.name,
                mime="application/pdf",
            )
    elif suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        try:
            img = Image.open(file_path)
            st.image(
                img,
                caption=f"{file_path.name} ({img.width}x{img.height})",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Error loading image: {e}")
    else:
        st.warning(f"Preview unavailable for {suffix} format.")


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
    available_docs = sorted(available_docs) if available_docs else test_docs

    selected_doc = st.selectbox(
        "Choose Benchmark Document:",
        options=available_docs,
        index=available_docs.index(st.session_state.current_doc_name)
        if st.session_state.current_doc_name in available_docs
        else 0,
    )

    uploaded_file = st.file_uploader(
        "Or Upload Custom Document",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
    )

    engine_choice = st.radio(
        "Extraction Engine:",
        options=["auto", "local_ocr", "gemini"],
        index=0,
        help="'auto' uses Gemini if API key is present, else robust local OCR.",
    )

    # Re-extract or load document
    load_needed = False
    active_path = TEST_PACK_DIR / selected_doc

    if uploaded_file is not None:
        save_uploaded_path = OUTPUTS_DIR / uploaded_file.name
        save_uploaded_path.write_bytes(uploaded_file.getvalue())
        active_path = save_uploaded_path
        if st.session_state.current_doc_name != uploaded_file.name:
            st.session_state.current_doc_name = uploaded_file.name
            load_needed = True
    elif selected_doc != st.session_state.current_doc_name:
        st.session_state.current_doc_name = selected_doc
        load_needed = True

    if st.button("🔄 Re-Extract Document", use_container_width=True) or load_needed:
        with st.spinner("Extracting invoice entities..."):
            extracted = extract_invoice(
                active_path,
                engine=engine_choice,
                save_output=True,
                strict_math=False,
                output_dir=OUTPUTS_DIR,
            )
            st.session_state.invoice_data = extracted.model_dump()
            st.session_state.line_items_data = [
                dict(item) for item in st.session_state.invoice_data.get("line_items", [])
            ]
            st.session_state.is_modified = False
            st.rerun()

    # Load initial data if empty
    if not st.session_state.invoice_data:
        st.session_state.invoice_data = load_document_data(active_path)
        st.session_state.line_items_data = [
            dict(item) for item in st.session_state.invoice_data.get("line_items", [])
        ]

    st.markdown("---")
    st.subheader("Benchmark Information")
    st.markdown(
        """
        - **Green (>90%)**: High confidence.
        - **Amber (70-90%)**: Verification recommended.
        - **Red (<70%)**: Flagged or arithmetic discrepancy.
        """
    )


# ---------------- MAIN SIDE-BY-SIDE LAYOUT ----------------
col_left, col_right = st.columns([1, 1], gap="large")

# Compute live confidences and math integrity
conf_eval = compute_confidence_scores(st.session_state.invoice_data)
field_scores = conf_eval["field_scores"]
math_eval = conf_eval["math_eval"]


# ================ LEFT COLUMN: ORIGINAL VIEWER ================
with col_left:
    st.markdown(
        f"<div class='viewer-header'>📄 Original Document: <code>{active_path.name}</code></div>",
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        render_document_preview(active_path)

    st.caption(
        f"File: `{active_path.name}` | Size: {active_path.stat().st_size / 1024.0:.1f} KB"
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

    # Editable Fields Form
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
                help=field_scores["vendor_name"]["reason"],
            )
        with col_v2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.markdown(v_badge, unsafe_allow_html=True)

        if new_vendor != st.session_state.invoice_data.get("vendor_name"):
            st.session_state.invoice_data["vendor_name"] = new_vendor
            st.session_state.is_modified = True

        # Invoice Date & Due Date
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
                label_visibility="collapsed",
                placeholder="YYYY-MM-DD",
            )
            if new_inv_date != (st.session_state.invoice_data.get("invoice_date") or ""):
                st.session_state.invoice_data["invoice_date"] = (
                    new_inv_date if new_inv_date.strip() else None
                )
                st.session_state.is_modified = True

        with col_d2:
            due_badge = render_confidence_badge(
                field_scores["due_date"]["badge"],
                field_scores["due_date"]["score"],
            )
            st.markdown(f"**Due Date** {due_badge}", unsafe_allow_html=True)
            new_due_date = st.text_input(
                "Due Date",
                value=st.session_state.invoice_data.get("due_date") or "",
                label_visibility="collapsed",
                placeholder="YYYY-MM-DD",
            )
            if new_due_date != (st.session_state.invoice_data.get("due_date") or ""):
                st.session_state.invoice_data["due_date"] = (
                    new_due_date if new_due_date.strip() else None
                )
                st.session_state.is_modified = True

        st.markdown("---")
        st.markdown("#### Itemized Line Items")

        items_badge = render_confidence_badge(
            field_scores["line_items"]["badge"],
            field_scores["line_items"]["score"],
            label=field_scores["line_items"]["reason"],
        )
        st.markdown(items_badge, unsafe_allow_html=True)

        # Interactive Data Editor for Line Items
        line_items_list = st.session_state.invoice_data.get("line_items", [])
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
            key="line_items_editor",
        )

        # Update session state if edited
        if edited_items != line_items_list:
            st.session_state.invoice_data["line_items"] = edited_items
            st.session_state.is_modified = True
            st.rerun()

        # Helper button to auto-recompute totals from qty * price
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("⚡ Recalculate Line Item Totals (`qty * unit_price`)"):
                for it in st.session_state.invoice_data.get("line_items", []):
                    q = float(it.get("quantity") or 0.0)
                    p = float(it.get("unit_price") or 0.0)
                    it["total"] = round(q * p, 2)
                st.session_state.is_modified = True
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
                st.session_state.is_modified = True
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
            st.session_state.is_modified = True

        # Tax Amount
        col_t1, col_t2 = st.columns([3, 1])
        with col_t1:
            tax_val = st.session_state.invoice_data.get("tax_amount")
            is_tax_exempt = st.checkbox(
                "Tax Exempt / Not Specified",
                value=(tax_val is None),
            )
            if not is_tax_exempt:
                new_tax = st.number_input(
                    "Tax Amount ($)",
                    value=float(tax_val) if tax_val is not None else 0.0,
                    step=0.5,
                    format="%.2f",
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
            st.session_state.is_modified = True

        # Grand Total
        col_g1, col_g2 = st.columns([3, 1])
        with col_g1:
            gt_val = float(st.session_state.invoice_data.get("grand_total") or 0.0)
            new_gt = st.number_input(
                "Grand Total ($) *",
                value=gt_val,
                step=1.0,
                format="%.2f",
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
            st.session_state.is_modified = True

    # ---------------- EXPORT FUNCTIONALITY ----------------
    st.markdown("### 📤 Export & Save Reviewed Invoice")

    # Validate against Pydantic schema
    try:
        validated_invoice = Invoice.model_validate(
            st.session_state.invoice_data, context={"strict_math": False}
        )
        json_output = validated_invoice.to_deterministic_json(indent=2)
        csv_output = invoice_to_csv_string(st.session_state.invoice_data)
        schema_valid = True
    except Exception as e:
        st.error(f"Pydantic Validation Error: {e}")
        json_output = json.dumps(st.session_state.invoice_data, indent=2)
        csv_output = invoice_to_csv_string(st.session_state.invoice_data)
        schema_valid = False

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
