import streamlit as st
import fitz  # PyMuPDF
import io

st.set_page_config(page_title="Smart PDF Compressor", page_icon="📄")
st.title("📄 Smart PDF Compressor")
st.write("Automatically detects content type and applies the best compression strategy.")

def analyze_pdf(doc):
    """Analyze PDF to determine dominant content type."""
    total_pages = len(doc)
    image_heavy_pages = 0
    text_heavy_pages = 0
    mixed_pages = 0

    page_stats = []

    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        text_area = 0
        image_area = 0

        for block in blocks:
            rect = fitz.Rect(block["bbox"])
            area = rect.width * rect.height

            if block["type"] == 0:  # text
                text_area += area
            elif block["type"] == 1:  # image
                image_area += area

        total_area = page.rect.width * page.rect.height
        image_ratio = image_area / total_area if total_area > 0 else 0
        text_ratio = text_area / total_area if total_area > 0 else 0

        if image_ratio > 0.5:
            page_type = "image"
            image_heavy_pages += 1
        elif text_ratio > 0.3 and image_ratio < 0.2:
            page_type = "text"
            text_heavy_pages += 1
        else:
            page_type = "mixed"
            mixed_pages += 1

        page_stats.append({
            "type": page_type,
            "image_ratio": image_ratio,
            "text_ratio": text_ratio
        })

    # Determine dominant type
    if image_heavy_pages / total_pages > 0.6:
        dominant = "image-heavy"
    elif text_heavy_pages / total_pages > 0.6:
        dominant = "text-heavy"
    else:
        dominant = "mixed"

    return {
        "dominant": dominant,
        "total_pages": total_pages,
        "image_heavy_pages": image_heavy_pages,
        "text_heavy_pages": text_heavy_pages,
        "mixed_pages": mixed_pages,
        "page_stats": page_stats
    }


def compress_text_heavy(doc, level):
    """For text PDFs: clean up, remove unused resources, deflate — no re-rendering."""
    output = io.BytesIO()
    doc.save(
        output,
        garbage=4,          # remove unused objects/xrefs
        deflate=True,       # compress streams
        deflate_images=True,
        deflate_fonts=True,
        clean=True,         # clean up content streams
        linear=True         # linearize for fast web view
    )
    return output.getvalue()


def compress_image_heavy(doc, level):
    """For image PDFs: re-render pages at reduced DPI with JPEG compression."""
    dpi_map = {"Low": 150, "Medium": 110, "High": 80}
    quality_map = {"Low": 92, "Medium": 85, "High": 75}
    dpi = dpi_map[level]
    quality = quality_map[level]

    new_doc = fitz.open()
    for page in doc:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("jpeg", jpg_quality=quality)

        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
        rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
        new_page.insert_image(rect, stream=img_bytes)

    output = io.BytesIO()
    new_doc.save(output, garbage=4, deflate=True)
    new_doc.close()
    return output.getvalue()


def compress_mixed(doc, level, page_stats):
    """For mixed PDFs: process each page individually based on its content type."""
    dpi_map = {"Low": 150, "Medium": 110, "High": 80}
    quality_map = {"Low": 92, "Medium": 85, "High": 75}
    dpi = dpi_map[level]
    quality = quality_map[level]

    new_doc = fitz.open()

    for i, page in enumerate(doc):
        ptype = page_stats[i]["type"]
        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)

        if ptype == "text":
            # Copy text content faithfully via SVG round-trip to preserve text
            svg = page.get_svg_image()
            svg_bytes = svg.encode("utf-8")
            new_page.insert_image(
                fitz.Rect(0, 0, page.rect.width, page.rect.height),
                stream=svg_bytes,
                keep_proportion=False
            )
        else:
            # Re-render image/mixed pages at lower DPI
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes("jpeg", jpg_quality=quality)
            new_page.insert_image(
                fitz.Rect(0, 0, page.rect.width, page.rect.height),
                stream=img_bytes,
                keep_proportion=False
            )

    output = io.BytesIO()
    new_doc.save(output, garbage=4, deflate=True)
    new_doc.close()
    return output.getvalue()


def format_size(size_bytes):
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


# UI
uploaded_file = st.file_uploader("Upload a PDF", type="pdf")

compression_level = st.select_slider(
    "Compression Level",
    options=["Low", "Medium", "High"],
    value="Medium",
    help="Only affects image/mixed pages. Text-only PDFs are always losslessly optimized."
)

if uploaded_file:
    input_bytes = uploaded_file.read()
    input_size = len(input_bytes)
    doc = fitz.open(stream=input_bytes, filetype="pdf")

    # Auto-analyze on upload
    with st.spinner("Analyzing PDF content..."):
        analysis = analyze_pdf(doc)

    # Show analysis results
    dominant = analysis["dominant"]
    icon_map = {"text-heavy": "📝", "image-heavy": "🖼️", "mixed": "🔀"}
    strategy_map = {
        "text-heavy": "Lossless optimization (no re-rendering — text & fonts preserved perfectly)",
        "image-heavy": "Image re-compression at reduced DPI",
        "mixed": "Hybrid — text pages preserved losslessly, image pages re-compressed"
    }

    st.info(
        f"{icon_map[dominant]} **Detected: {dominant.replace('-', ' ').title()} PDF**\n\n"
        f"📋 Strategy: {strategy_map[dominant]}"
    )

    with st.expander("📊 Page-by-page breakdown"):
        cols = st.columns(4)
        cols[0].metric("Total Pages", analysis["total_pages"])
        cols[1].metric("📝 Text Pages", analysis["text_heavy_pages"])
        cols[2].metric("🖼️ Image Pages", analysis["image_heavy_pages"])
        cols[3].metric("🔀 Mixed Pages", analysis["mixed_pages"])

    if st.button("⚡ Compress PDF", type="primary"):
        with st.spinner("Compressing..."):
            if dominant == "text-heavy":
                output_bytes = compress_text_heavy(doc, compression_level)
            elif dominant == "image-heavy":
                output_bytes = compress_image_heavy(doc, compression_level)
            else:
                output_bytes = compress_mixed(doc, compression_level, analysis["page_stats"])

        output_size = len(output_bytes)
        reduction = (1 - output_size / input_size) * 100

        st.success("✅ Compression complete!")

        col1, col2, col3 = st.columns(3)
        col1.metric("Original Size", format_size(input_size))
        col2.metric("Compressed Size", format_size(output_size))
        delta_color = "normal" if reduction > 0 else "inverse"
        col3.metric("Size Reduction", f"{reduction:.1f}%", delta_color=delta_color)

        if reduction < 5:
            st.warning(
                "⚠️ This PDF was already well-optimized — not much room to compress further. "
                "Try a higher compression level if you need a smaller file."
            )
        elif reduction > 60:
            st.success("🎉 Excellent compression achieved!")

        st.download_button(
            label="⬇️ Download Compressed PDF",
            data=output_bytes,
            file_name=f"compressed_{uploaded_file.name}",
            mime="application/pdf",
            use_container_width=True
        )

    doc.close()