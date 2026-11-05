from flask import Flask, send_from_directory, request, jsonify, send_file
from io import BytesIO
from pathlib import Path
import os, re, datetime, logging
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_OK = True
except Exception:
    TRANSLATOR_OK = False

try:
    from weasyprint import HTML
    WEASYPRINT_OK = True
except Exception:
    HTML = None
    WEASYPRINT_OK = False

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

env = Environment(loader=FileSystemLoader(str(BASE_DIR)), autoescape=select_autoescape(("html", "xml")))

# Cache dictionary
CACHE = {}

def _translate(text, lang):
    if not text or not lang or lang == "en" or not TRANSLATOR_OK:
        return text
    cache_key = f"tr:{lang}:{text}"
    if cache_key in CACHE:
        return CACHE[cache_key]
    try:
        out = GoogleTranslator(source="auto", target=lang).translate(text)
        CACHE[cache_key] = out
        return out
    except Exception:
        return text

LABELS_EN = {
    "contact": "Contact Details", "personal": "Personal Details", "family": "Family Details", "skills": "Skills",
    "additional": "Additional Details", "profile": "Profile / Objective", "education": "Education", "experience": "Work Experience",
    "declaration": "Declaration", "dob": "Date of Birth", "gender": "Gender", "height": "Height", "weight": "Weight",
    "blood": "Blood Group", "marital": "Marital Status", "religion": "Religion", "caste": "Caste / Community",
    "gotra": "Gotra", "rashi": "Rashi", "nakshatra": "Nakshatra", "manglik": "Manglik", "phone": "Mobile Number",
    "email": "Email", "address": "Address", "father": "Father", "mother": "Mother", "brothers": "Brothers",
    "sisters": "Sisters", "languages": "Languages", "hobbies": "Hobbies", "place": "Place", "date": "Date", "signature": "Signature"
}

def _labels_for(lang):
    if not lang or lang == "en":
        return LABELS_EN
    cache_key = f"labels:{lang}"
    if cache_key in CACHE:
        return CACHE[cache_key]
    
    out = {}
    for k, v in LABELS_EN.items():
        out[k] = _translate(v, lang)
    CACHE[cache_key] = out
    return out

def _preprocess(payload):
    data = dict(payload or {})
    lang = str(data.get("language") or "en").lower()
    
    theme = data.get("theme") or {}
    if not isinstance(theme, dict) or not theme.get("primary"):
        theme = {"layout": "classic", "primary": "#6B0F1A", "accent": "#D4A853", "tint": "#FAF4E2", "ink": "#30242A", "displayFont": "Playfair Display", "bodyFont": "Lato", "name": "Default"}
    data["theme"] = theme

    skills = []
    for raw in str(data.get("skills") or "").splitlines():
        if "|" in raw:
            n, lvl = raw.split("|", 1)
            try: lv = max(0, min(100, int(float(lvl.strip()))))
            except: lv = 80
            if n.strip(): skills.append({"name": _translate(n.strip(), lang), "level": lv})
    data["skills_list"] = skills

    translate_keys = ["gender", "height", "blood", "marital", "religion", "caste", "gotra", "rashi", "nakshatra", "manglik", "profile", "address", "father_job", "mother_job", "brothers", "sisters", "education_simple", "experience", "languages", "hobbies", "declaration"]
    for k in translate_keys:
        data[k] = _translate(str(data.get(k) or "").strip(), lang)

    for k in ("name", "dob", "weight", "phone", "email", "father", "mother", "place", "date"):
        data[k] = str(data.get(k) or "").strip()

    # Translate Name fields if needed (optional, usually names are kept as is)

    data["dob"] = _translate(data.get("dob"), lang)
    data["date"] = _translate(data.get("date"), lang)

    edu_mode = str(data.get("education_mode") or "simple").lower()
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

    data["labels"] = _labels_for(lang)
    data["photo"] = str(data.get("photo") or "")
    data["watermark"] = bool(data.get("watermark"))
    data["watermark_text"] = str(data.get("watermark_text") or "Biodata")[:50]
    data["show_pagenum"] = bool(data.get("show_pagenum", True))
    data["page_size"] = str(data.get("page_size") or "A4").upper()

    return data

@app.route("/")
def index(): return send_from_directory(BASE_DIR, "index.html")

@app.route("/api/preview", methods=["POST"])
def preview():
    try:
        payload = request.get_json(silent=True) or {}
        payload.pop("photo", None)
        data = _preprocess(payload)
        return env.get_template("pdf_template.html").render(**data)
    except Exception as e:
        return f"<html><body><h1>Preview Error</h1><pre>{str(e)}</pre></body></html>", 500

@app.route("/api/pdf", methods=["POST"])
def pdf():
    if not WEASYPRINT_OK: return jsonify(error="PDF unavailable"), 503
    try:
        data = _preprocess(request.get_json(silent=True) or {})
        html_str = env.get_template("pdf_template.html").render(**data)
        pdf_bytes = HTML(string=html_str, base_url=request.url_root).write_pdf()
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", (data.get("name") or "Biodata").replace(" ", "_")) or "Biodata"
        return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=f"{safe}_Biodata.pdf")
    except Exception as e:
        return jsonify(error=str(e)), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
