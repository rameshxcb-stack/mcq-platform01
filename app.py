from flask import Flask, send_from_directory, request, jsonify, send_file
from io import BytesIO
from pathlib import Path
import os, re, traceback, datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Translation & AI Imports
from deep_translator import GoogleTranslator
import google.generativeai as genai

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
env = Environment(loader=FileSystemLoader(str(BASE_DIR)), autoescape=select_autoescape(("html", "xml")))

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except Exception:
    HTML = None
    WEASYPRINT_AVAILABLE = False

# Gemini API Setup
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    gemini_model = None

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

def _translate(text, lang_code):
    if not text or not lang_code or lang_code == 'en':
        return text
    try:
        # GoogleTranslator auto-detects source
        return GoogleTranslator(source='auto', target=lang_code).translate(text)
    except Exception as e:
        print(f"Translation error: {e}")
        return text

def preprocess(payload):
    data = dict(payload or {})
    lang = str(data.get("language") or "en").lower()
    theme = str(data.get("theme") or "cyan").lower()
    data["theme"] = theme if theme in VALID_THEMES else "cyan"

    # Skills parsing
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

    # Translate user text (Skip Names, Emails, Dates)
    translate_keys = ["gender", "height", "blood", "marital", "religion", "caste", "gotra", "rashi", 
                      "nakshatra", "manglik", "profile", "address", "father_job", "mother_job", 
                      "brothers", "sisters", "education_simple", "experience", "languages", "hobbies", "declaration"]
    
    for key in translate_keys:
        data[key] = _translate(str(data.get(key) or "").strip(), lang)
        
    for key in ("name", "dob", "weight", "phone", "email", "father", "mother", "place", "date"):
        data[key] = str(data.get(key) or "").strip()

    data["dob"] = _format_date(data.get("dob"))
    data["date"] = _format_date(data.get("date"))

    # Education Parsing & Translation
    edu_mode = data.get("education_mode", "simple")
    data["education_mode"] = edu_mode
    data["education_list"] = []
    
    if edu_mode == "detailed" and isinstance(data.get("education_list"), list):
        for item in data["education_list"]:
            if item.get("level") or item.get("institute"):
                data["education_list"].append({
                    "level": _translate(str(item.get("level", "")).strip(), lang),
                    "board": _translate(str(item.get("board", "")).strip(), lang),
                    "institute": _translate(str(item.get("institute", "")).strip(), lang),
                    "year": str(item.get("year", "")).strip(),
                    "score": str(item.get("score", "")).strip()
                })

    # Static Labels Translation
    labels = {
        "contact": "Contact Details", "personal": "Personal Details", "family": "Family Details",
        "skills": "Skills", "additional": "Additional Details", "profile": "Profile / Objective",
        "education": "Education", "experience": "Work Experience", "declaration": "Declaration",
        "dob": "Date of Birth", "gender": "Gender", "height": "Height", "weight": "Weight",
        "blood": "Blood Group", "marital": "Marital Status", "religion": "Religion", "caste": "Caste / Community",
        "gotra": "Gotra", "rashi": "Rashi", "nakshatra": "Nakshatra", "manglik": "Manglik",
        "phone": "Mobile Number", "email": "Email", "address": "Address",
        "father": "Father", "mother": "Mother", "brothers": "Brothers", "sisters": "Sisters",
        "languages": "Languages", "hobbies": "Hobbies", "place": "Place", "signature": "Signature"
    }
    if lang != 'en':
        for k, v in labels.items():
            labels[k] = _translate(v, lang)
    data["labels"] = labels

    data["photo"] = str(data.get("photo") or "")
    return data

def render_document(payload):
    data = preprocess(payload)
    return env.get_template("pdf_template.html").render(**data)

@app.route("/")
def index(): return send_from_directory(BASE_DIR, "index.html")

@app.route("/favicon.ico")
def favicon(): return "", 204

@app.route("/api/health")
def health():
    return jsonify(status="ok", weasyprint=WEASYPRINT_AVAILABLE, ai=bool(gemini_model))

@app.route("/api/generate-profile", methods=["POST"])
def generate_profile():
    if not gemini_model:
        return jsonify(error="Gemini API key nahi mili. Environment variable set karein."), 500
    try:
        payload = request.get_json(silent=True) or {}
        name = payload.get("name", "The candidate")
        edu = payload.get("education", "Graduation")
        skills = payload.get("skills", "Good communication")
        
        prompt = f"Write a short, humble, and traditional Indian marriage biodata profile (3-4 sentences) for {name}. Education: {edu}. Skills: {skills}. Focus on family values and career goals. Do not add markdown format, just plain text."
        
        response = gemini_model.generate_content(prompt)
        return jsonify(profile=response.text.strip())
    except Exception as exc:
        return jsonify(error=str(exc)), 500

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
