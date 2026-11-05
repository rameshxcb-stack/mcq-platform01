from flask import Flask, send_from_directory, request, jsonify, send_file
from io import BytesIO
from pathlib import Path
import os, re, traceback, datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
env = Environment(loader=FileSystemLoader(str(BASE_DIR)), autoescape=select_autoescape(("html", "xml")))

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except Exception as exc:
    HTML = None
    WEASYPRINT_AVAILABLE = False

VALID_THEMES = {
    "cyan", "orange_sidebar", "navy_classic", "teal_header", "blue_corporate", "emerald_sidebar", 
    "rose_card", "midnight_split", "lavender_minimal", "forest_timeline", "terracotta_editorial", 
    "plum_sidebar", "sky_banner", "charcoal_classic", "sapphire_corporate", "champagne_cards", 
    "burgundy_split", "indigo_minimal", "copper_timeline", "ocean_editorial", "sage_sidebar", 
    "ruby_banner", "steel_corporate", "mint_cards", "sunset_split", "peacock_minimal", "blush_timeline", 
    "olive_editorial", "ice_sidebar", "onyx_banner", "mauve_corporate", "amber_cards", "crimson_split", 
    "lagoon_minimal", "sandstone_timeline", "orchid_editorial", "cobalt_sidebar", "pine_banner", 
    "pearl_corporate", "golden_cards", "slate_split", "coral_minimal", "moss_timeline", "wine_editorial", 
    "arctic_sidebar", "royal_banner", "graphite_corporate", "peach_cards", "denim_split", "lilac_minimal", 
    "bronze_timeline", "jade_editorial", "maroon_sidebar", "turquoise_banner", "smoke_corporate", "ivory_cards",
    "royal", "professional", "emerald", "midnight", "rose", "lavender", "teal", "charcoal", "minimal", 
    "sky", "forest", "terracotta", "plum", "classic", "coral", "sapphire", "champagne", "burgundy", 
    "indigo", "copper", "ocean", "sage", "ruby", "steel", "mint", "sunset", "peacock", "blush", "olive", 
    "ice", "onyx", "mauve", "amber", "crimson", "lagoon", "sandstone", "orchid", "cobalt", "pine", "pearl"
}

def _format_date(value):
    s = str(value or "").strip()
    if not s: return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try: return datetime.datetime.strptime(s, fmt).strftime("%d/%m/%Y")
        except ValueError: continue
    return s

def preprocess(payload):
    data = dict(payload or {})
    theme = str(data.get("theme") or "cyan").lower()
    data["theme"] = theme if theme in VALID_THEMES else "cyan"

    # Skills
    skills = []
    for raw in str(data.get("skills") or "").splitlines():
        if "|" in raw:
            name, lvl = raw.split("|", 1)
            try: level = max(0, min(100, int(lvl.strip())))
            except: level = 80
            if name.strip(): skills.append({"name": name.strip(), "level": level})
        elif raw.strip():
            skills.append({"name": raw.strip(), "level": 80})
    data["skills_list"] = skills

    # Strings
    for key in ("name", "dob", "gender", "height", "weight", "blood", "marital", "religion", "caste", 
                "gotra", "rashi", "nakshatra", "manglik", "profile", "phone", "email", "address", 
                "father", "father_job", "mother", "mother_job", "brothers", "sisters", "education_simple", 
                "experience", "languages", "hobbies", "declaration", "place", "date"):
        data[key] = str(data.get(key) or "").strip()

    # Dates
    data["dob"] = _format_date(data.get("dob"))
    data["date"] = _format_date(data.get("date"))

    # Education parsing
    edu_mode = data.get("education_mode", "simple")
    data["education_mode"] = edu_mode
    data["education_list"] = []
    
    if edu_mode == "detailed" and isinstance(data.get("education_list"), list):
        for item in data["education_list"]:
            if item.get("level") or item.get("institute"):
                data["education_list"].append({
                    "level": str(item.get("level", "")).strip(),
                    "board": str(item.get("board", "")).strip(),
                    "institute": str(item.get("institute", "")).strip(),
                    "year": str(item.get("year", "")).strip(),
                    "score": str(item.get("score", "")).strip()
                })

    data["photo"] = str(data.get("photo") or "")
    return data

def render_document(payload):
    data = preprocess(payload)
    return env.get_template("pdf_template.html").render(**data)

@app.route("/")
def index(): return send_from_directory(BASE_DIR, "index.html")

@app.route("/favicon.ico")
def favicon(): return "", 204

@app.route("/keepalive")
@app.route("/api/health")
def health():
    return jsonify(status="ok", weasyprint=WEASYPRINT_AVAILABLE, service="biodata-maker-pro", templates=len(VALID_THEMES))

@app.route("/api/preview", methods=["POST"])
def preview():
    try:
        payload = request.get_json(silent=True) or {}
        payload.pop("photo", None)
        return render_document(payload)
    except Exception as exc:
        traceback.print_exc()
        return f"<p>Error: {exc}</p>", 500

@app.route("/api/pdf", methods=["POST"])
def pdf():
    if not WEASYPRINT_AVAILABLE: return jsonify(error="PDF unavailable"), 503
    try:
        data = preprocess(request.get_json(silent=True) or {})
        html = env.get_template("pdf_template.html").render(**data)
        pdf_bytes = HTML(string=html, base_url=request.url_root).write_pdf()
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", (data.get("name") or "Biodata").replace(" ", "_")) or "Biodata"
        return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=f"{safe}_Biodata.pdf")
    except Exception as exc:
        traceback.print_exc()
        return jsonify(error=str(exc)), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
