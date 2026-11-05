from flask import Flask, send_from_directory, request, jsonify, send_file
from io import BytesIO
from pathlib import Path
import os, re, traceback, datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
env = Environment(
    loader=FileSystemLoader(str(BASE_DIR)),
    autoescape=select_autoescape(("html", "xml"))
)

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except Exception as exc:
    HTML = None
    WEASYPRINT_AVAILABLE = False
    print(f"WeasyPrint unavailable; client PDF fallback will be used: {exc}")

VALID_THEMES = {
    # 56 base themes
    "cyan", "orange_sidebar", "navy_classic", "teal_header", "blue_corporate",
    "emerald_sidebar", "rose_card", "midnight_split", "lavender_minimal",
    "forest_timeline", "terracotta_editorial", "plum_sidebar", "sky_banner",
    "charcoal_classic", "sapphire_corporate", "champagne_cards",
    "burgundy_split", "indigo_minimal", "copper_timeline", "ocean_editorial",
    "sage_sidebar", "ruby_banner", "steel_corporate", "mint_cards",
    "sunset_split", "peacock_minimal", "blush_timeline", "olive_editorial",
    "ice_sidebar", "onyx_banner", "mauve_corporate", "amber_cards",
    "crimson_split", "lagoon_minimal", "sandstone_timeline", "orchid_editorial",
    "cobalt_sidebar", "pine_banner", "pearl_corporate", "golden_cards",
    "slate_split", "coral_minimal", "moss_timeline", "wine_editorial",
    "arctic_sidebar", "royal_banner", "graphite_corporate", "peach_cards",
    "denim_split", "lilac_minimal", "bronze_timeline", "jade_editorial",
    "maroon_sidebar", "turquoise_banner", "smoke_corporate", "ivory_cards",
    # 40 backward-compatible aliases
    "royal", "professional", "emerald", "midnight", "rose", "lavender",
    "teal", "charcoal", "minimal", "sky", "forest", "terracotta", "plum",
    "classic", "coral", "sapphire", "champagne", "burgundy", "indigo",
    "copper", "ocean", "sage", "ruby", "steel", "mint", "sunset",
    "peacock", "blush", "olive", "ice", "onyx", "mauve", "amber",
    "crimson", "lagoon", "sandstone", "orchid", "cobalt", "pine", "pearl",
}

def _format_date(value):
    """Accept ISO (YYYY-MM-DD) or legacy DD/MM/YYYY and return DD/MM/YYYY."""
    s = str(value or "").strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s  # unrecognised → leave untouched

def preprocess(payload):
    data = dict(payload or {})
    theme = str(data.get("theme") or "cyan").lower()
    data["theme"] = theme if theme in VALID_THEMES else "cyan"

    skills = []
    for raw in str(data.get("skills") or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "|" in line:
            name, raw_level = line.split("|", 1)
            try:
                level = max(0, min(100, int(raw_level.strip())))
            except (TypeError, ValueError):
                level = 80
        else:
            name, level = line, 80
        name = name.strip()
        if name:
            skills.append({"name": name, "level": level})
    data["skills_list"] = skills

    for key in (
        "name", "dob", "gender", "height", "weight", "blood", "marital",
        "religion", "caste", "gotra", "rashi", "nakshatra", "manglik",
        "profile", "phone", "email", "address", "father", "father_job",
        "mother", "mother_job", "brothers", "sisters", "education",
        "experience", "languages", "hobbies", "declaration", "place", "date"
    ):
        data[key] = str(data.get(key) or "").strip()

    # Normalise dates so "01- 01- 2082" style values never appear in the PDF
    data["dob"] = _format_date(data.get("dob"))
    data["date"] = _format_date(data.get("date"))

    data["photo"] = str(data.get("photo") or "")
    return data

def render_document(payload):
    data = preprocess(payload)
    template = env.get_template("pdf_template.html")
    return template.render(**data)

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.route("/keepalive")
@app.route("/api/health")
def health():
    return jsonify(status="ok", weasyprint=WEASYPRINT_AVAILABLE,
                   service="biodata-maker-pro", templates=len(VALID_THEMES))

@app.route("/api/preview", methods=["POST"])
def preview():
    try:
        payload = request.get_json(silent=True) or {}
        payload.pop("photo", None)  # keep preview requests lightweight
        return render_document(payload)
    except Exception as exc:
        traceback.print_exc()
        return f"<p style='padding:20px;color:#b00'>Preview error: {exc}</p>", 500

@app.route("/api/pdf", methods=["POST"])
def pdf():
    if not WEASYPRINT_AVAILABLE:
        return jsonify(error="Server PDF unavailable. Use browser print or client-side PDF fallback."), 503
    try:
        data = preprocess(request.get_json(silent=True) or {})
        html = env.get_template("pdf_template.html").render(**data)
        pdf_bytes = HTML(string=html, base_url=request.url_root).write_pdf()
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", (data.get("name") or "Biodata").replace(" ", "_")) or "Biodata"
        return send_file(BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=f"{safe}_Biodata.pdf")
    except Exception as exc:
        traceback.print_exc()
        return jsonify(error=str(exc)), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
