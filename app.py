from flask import Flask, send_from_directory, request, jsonify, send_file
from io import BytesIO
from pathlib import Path
import os, re, datetime, logging
import requests
import urllib.parse
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from weasyprint import HTML
    WEASYPRINT_OK = True
except Exception:
    HTML = None
    WEASYPRINT_OK = False

try:
    import google.generativeai as genai
    GENAI_OK = True
except Exception:
    GENAI_OK = False

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

env = Environment(loader=FileSystemLoader(str(BASE_DIR)), autoescape=select_autoescape(("html", "xml")))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
gemini_model = None
if GEMINI_API_KEY and GENAI_OK:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    except Exception:
        pass

TRANS_CACHE = {}

NAME_PREFIX_MAP = {
    "hi": "मेरा नाम", "mr": "माझे नाव", "kn": "ನನ್ನ ಹೆಸರು",
    "ta": "என் பெயர்", "te": "నా పేరు", "gu": "મારું નામ",
    "bn": "আমার নাম", "ml": "എന്റെ പേര്", "pa": "ਮੇਰਾ ਨਾਮ", "or": "ମୋର ନାମ"
}

def _transliterate_name(text, lang):
    if not text or not lang or lang == "en":
        return text
    if not text.isascii():
        return text
    cache_key = f"{lang}:name_rm:{text}"
    if cache_key in TRANS_CACHE:
        return TRANS_CACHE[cache_key]
    try:
        url = (f"https://translate.googleapis.com/translate_a/single"
               f"?client=gtx&sl=en&tl={lang}&dt=rm&q={urllib.parse.quote(text)}")
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and data and isinstance(data[0], list):
                out = data[0][0] if data[0] else ""
                if out and out != text and any(ord(c) > 127 for c in out):
                    TRANS_CACHE[cache_key] = out.strip()
                    return out.strip()
    except Exception:
        pass
    return None

def _translate(text, lang, is_name=False):
    if not text or not lang or lang == "en":
        return text
    text = str(text).strip()
    if not text:
        return text
    if not text.isascii():
        return text

    if is_name:
        tr = _transliterate_name(text, lang)
        if tr:
            return tr

    cache_key = f"{lang}:{is_name}:{text}"
    if cache_key in TRANS_CACHE:
        return TRANS_CACHE[cache_key]

    def _api_call(q, sl="auto"):
        try:
            url = (f"https://translate.googleapis.com/translate_a/single"
                   f"?client=gtx&sl={sl}&tl={lang}&dt=t&q={urllib.parse.quote(q)}")
            res = requests.get(url, timeout=6)
            if res.status_code == 200:
                data = res.json()
                return "".join([item[0] for item in data[0]])
        except Exception:
            pass
        return None

    out = _api_call(text + "\u200b")
    if out:
        cleaned = out.replace("\u200b", "").strip()
        if cleaned and cleaned != text:
            TRANS_CACHE[cache_key] = cleaned
            return cleaned

    if is_name and lang in NAME_PREFIX_MAP:
        prefix = NAME_PREFIX_MAP[lang]
        out = _api_call(f"{prefix} {text}")
        if out:
            cleaned = out.strip()
            for word in prefix.split():
                cleaned = cleaned.replace(word, "").strip()
            cleaned = re.sub(r"[\s:：\-—–]+", " ", cleaned).strip()
            if cleaned and cleaned != text and any(ord(c) > 127 for c in cleaned):
                TRANS_CACHE[cache_key] = cleaned
                return cleaned

    out = _api_call(text)
    if out:
        cleaned = out.strip()
        if cleaned and cleaned != text:
            TRANS_CACHE[cache_key] = cleaned
            return cleaned

    TRANS_CACHE[cache_key] = text
    return text

LABELS_MULTI = {
    "en": {"contact": "Contact Details", "personal": "Personal Details", "family": "Family Details", "skills": "Skills", "additional": "Additional Details", "profile": "Profile / Objective", "education": "Education", "experience": "Work Experience", "declaration": "Declaration", "dob": "Date of Birth", "gender": "Gender", "height": "Height", "weight": "Weight", "blood": "Blood Group", "marital": "Marital Status", "religion": "Religion", "caste": "Caste / Community", "gotra": "Gotra", "rashi": "Rashi", "nakshatra": "Nakshatra", "manglik": "Manglik", "phone": "Mobile Number", "email": "Email", "address": "Address", "father": "Father", "mother": "Mother", "brothers": "Brothers", "sisters": "Sisters", "languages": "Languages", "hobbies": "Hobbies", "place": "Place", "date": "Date", "signature": "Signature", "qualification": "Qualification", "institute": "Name of the University/Board/School", "year": "Year of Passing", "score": "% Marks / CGPA / SGPA", "organization": "Organization", "designation": "Designation", "period": "Job Period", "responsibilities": "Responsibilities", "age": "Age", "qr": "Scan for Contact", "occupation": "Occupation", "partner_preferences": "Partner Preferences", "lifestyle": "Lifestyle", "diet": "Diet", "smoking": "Smoking", "drinking": "Drinking", "projects": "Projects / Portfolio", "certifications": "Certifications / Training", "horoscope": "Horoscope Details"},
    "hi": {"contact": "संपर्क विवरण", "personal": "व्यक्तिगत विवरण", "family": "पारिवारिक विवरण", "skills": "कौशल", "additional": "अतिरिक्त विवरण", "profile": "प्रोफ़ाइल / उद्देश्य", "education": "शिक्षा", "experience": "कार्य अनुभव", "declaration": "घोषणा", "dob": "जन्म तिथि", "gender": "लिंग", "height": "ऊंचाई", "weight": "वजन", "blood": "रक्त समूह", "marital": "वैवाहिक स्थिति", "religion": "धर्म", "caste": "जाति", "gotra": "गोत्र", "rashi": "राशि", "nakshatra": "नक्षत्र", "manglik": "मांगलिक", "phone": "मोबाइल नंबर", "email": "ईमेल", "address": "पता", "father": "पिता", "mother": "माता", "brothers": "भाई", "sisters": "बहनें", "languages": "भाषाएं", "hobbies": "शौक", "place": "स्थान", "date": "तिथि", "signature": "हस्ताक्षर", "qualification": "योग्यता", "institute": "विश्वविद्यालय/बोर्ड/स्कूल का नाम", "year": "पास होने का वर्ष", "score": "% अंक / CGPA / SGPA", "organization": "संगठन", "designation": "पद", "period": "कार्यकाल", "responsibilities": "जिम्मेदारियां", "age": "उम्र", "qr": "संपर्क के लिए स्कैन करें", "occupation": "व्यवसाय", "partner_preferences": "जीवनसाथी की प्राथमिकताएं", "lifestyle": "जीवनशैली", "diet": "आहार", "smoking": "धूम्रपान", "drinking": "शराब", "projects": "परियोजनाएं / पोर्टफोलियो", "certifications": "प्रमाणपत्र / प्रशिक्षण", "horoscope": "कुंडली विवरण"}
}

for lang_code in ["kn","ta","te","mr","gu","bn","ml","pa","or"]:
    LABELS_MULTI.setdefault(lang_code, LABELS_MULTI["en"])

def _preprocess(payload):
    data = dict(payload or {})
    lang = str(data.get("language") or "en").lower()
    mode = str(data.get("mode") or "marriage").lower()
    data["mode"] = mode
    data["is_job"] = (mode == "job")

    theme = data.get("theme") or {}
    if not isinstance(theme, dict) or not theme.get("primary"):
        theme = {"layout": "classic", "primary": "#6B0F1A", "accent": "#D4A853", "tint": "#FAF4E2", "ink": "#30242A", "displayFont": "Playfair Display", "bodyFont": "Lato", "name": "Default"}
    data["theme"] = theme

    data["name_font_size"] = str(data.get("name_font_size") or "24")
    data["photo_fit"] = str(data.get("photo_fit") or "cover")
    
    # 🔥 NEW PHOTO SETTINGS
    data["photo_pos"] = str(data.get("photo_pos") or "right") # left, right, center, sidebar
    data["photo_scale"] = str(data.get("photo_scale") or "100")
    data["photo_x"] = str(data.get("photo_x") or "50")
    data["photo_y"] = str(data.get("photo_y") or "50")

    skills = []
    for raw in str(data.get("skills") or "").splitlines():
        if "|" in raw:
            n, lvl = raw.split("|", 1)
            try:
                lv = max(0, min(100, int(float(lvl.strip()))))
            except Exception:
                lv = 80
            if n.strip():
                skills.append({"name": _translate(n.strip(), lang), "level": lv})
    data["skills_list"] = skills

    v_map = {
        "hi": {"Male": "पुरुष", "Female": "महिला", "Other": "अन्य", "Unmarried": "अविवाहित", "Never Married": "कभी शादी नहीं की", "Divorced": "तालाकशुदा", "Widowed": "विधवा/विधुर", "Awaiting Divorce": "तालाक का इंतजार", "Yes": "हाँ", "No": "नहीं", "Partial": "आंशिक", "Hindu": "हिंदू", "Muslim": "मुस्लिम", "Christian": "ईसाई", "Sikh": "सिख", "Buddhist": "बौद्ध", "Jain": "जैन", "Parsi": "पारसी", "Vegetarian": "शाकाहारी", "Non-Vegetarian": "मांसाहारी", "Eggetarian": "अंडाहारी", "Vegan": "वीगन", "Occasionally": "कभी-कभी"}
    }
    v_map.setdefault(lang, {})

    for k in ["gender", "marital", "manglik", "religion", "caste", "diet", "smoking", "drinking"]:
        val = str(data.get(k) or "").strip()
        data[k] = v_map.get(lang, {}).get(val, val)

    name = str(data.get("name") or "").strip()
    data["name"] = _translate(name, lang, is_name=True) if name else ""

    translate_keys = ["address", "profile", "father", "mother", "father_job", "mother_job", "brothers", "sisters", "education_simple", "languages", "hobbies", "declaration", "place", "occupation", "partner_preferences", "projects", "certifications"]
    for k in translate_keys:
        data[k] = _translate(str(data.get(k) or "").strip(), lang)

    for k in ("dob", "weight", "phone", "email", "date"):
        data[k] = str(data.get(k) or "").strip()

    age = ""
    try:
        if data.get("dob"):
            parts = re.split(r"[-/.]", data["dob"])
            if len(parts) == 3:
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                if y > 1000:
                    today = datetime.date.today()
                    age = str(today.year - y - ((today.month, today.day) < (m, d)))
    except Exception:
        pass
    data["age"] = age

    edu_mode = str(data.get("education_mode") or "simple").lower()
    data["education_mode"] = edu_mode
    raw_edu = data.get("education_list", [])
    processed_edu = []
    if edu_mode == "detailed" and isinstance(raw_edu, list):
        for item in raw_edu:
            if item.get("level") or item.get("institute"):
                processed_edu.append({
                    "level": _translate(str(item.get("level", "")).strip(), lang),
                    "board": _translate(str(item.get("board", "")).strip(), lang),
                    "institute": _translate(str(item.get("institute", "")).strip(), lang),
                    "year": str(item.get("year", "")).strip(),
                    "score": str(item.get("score", "")).strip(),
                })
    data["education_list"] = processed_edu

    raw_jobs = data.get("work_experience_list", [])
    processed_jobs = []
    if isinstance(raw_jobs, list):
        for item in raw_jobs:
            if item.get("organization") or item.get("designation"):
                processed_jobs.append({
                    "organization": _translate(str(item.get("organization", "")).strip(), lang),
                    "designation": _translate(str(item.get("designation", "")).strip(), lang),
                    "period": str(item.get("period", "")).strip(),
                    "responsibilities": _translate(str(item.get("responsibilities", "")).strip(), lang),
                })
    data["work_experience_list"] = processed_jobs

    data["labels"] = LABELS_MULTI.get(lang, LABELS_MULTI["en"])
    data["photo"] = str(data.get("photo") or "")
    data["signature"] = str(data.get("signature") or "")
    data["watermark"] = bool(data.get("watermark"))
    data["watermark_text"] = str(data.get("watermark_text") or "Biodata")[:50]
    data["show_pagenum"] = bool(data.get("show_pagenum", True))
    data["show_qr"] = bool(data.get("show_qr", False))
    data["page_size"] = str(data.get("page_size") or "A4").upper()

    qr_parts = []
    if data.get("name"): qr_parts.append(f"N:{data['name']}")
    if data.get("phone"): qr_parts.append(f"TEL:{data['phone']}")
    if data.get("email"): qr_parts.append(f"EMAIL:{data['email']}")
    data["qr_text"] = " | ".join(qr_parts)

    return data

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Biodata Maker Pro", "short_name": "BiodataPro", "start_url": "/", "display": "standalone", "background_color": "#f1f5f9", "theme_color": "#0f172a"})

@app.route("/api/health")
def health():
    return jsonify(status="ok", ai=bool(gemini_model), weasyprint=WEASYPRINT_OK, version="2.4")

@app.route("/api/qr")
def qr():
    text = request.args.get("text", "")
    size = request.args.get("size", "200")
    if not text:
        return jsonify(error="text required"), 400
    try:
        url = f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={urllib.parse.quote(text)}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return send_file(BytesIO(r.content), mimetype="image/png")
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(error="QR failed"), 500

@app.route("/api/generate-profile", methods=["POST"])
def generate_profile():
    if not gemini_model:
        return jsonify(error="AI not configured"), 503
    try:
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "the candidate").strip()
        education = str(data.get("education") or "Graduation").strip()
        skills = str(data.get("skills") or "Good communication").strip()
        lang = str(data.get("language") or "en")
        mode = str(data.get("mode") or "marriage")
        lang_name = {"hi": "Hindi", "kn": "Kannada", "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "gu": "Gujarati", "bn": "Bengali", "ml": "Malayalam", "pa": "Punjabi", "or": "Odia"}.get(lang, "English")
        if mode == "job":
            prompt = f"Write a 3-4 sentence professional career objective in {lang_name} for a job biodata. Name: {name}. Education: {education}. Skills: {skills}. Focus on career goals, achievements. Return plain text only."
        else:
            prompt = f"Write a 3-4 sentence humble biodata profile in {lang_name} language for an Indian marriage profile. Name: {name}. Education: {education}. Skills: {skills}. Focus on family values, career goals. Return plain text only."
        resp = gemini_model.generate_content(prompt)
        return jsonify(profile=(resp.text or "").strip())
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route("/api/suggest-skills", methods=["POST"])
def suggest_skills():
    if not gemini_model:
        return jsonify(error="AI not configured"), 503
    try:
        data = request.get_json(silent=True) or {}
        education = str(data.get("education") or "").strip()
        prompt = f"Suggest 6 relevant skills (as 'Name | Level 0-100') for a candidate with education '{education}'. Return only one skill per line."
        resp = gemini_model.generate_content(prompt)
        return jsonify(skills=(resp.text or "").strip())
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route("/api/preview", methods=["POST"])
def preview():
    try:
        payload = request.get_json(silent=True) or {}
        payload.pop("photo", None)
        data = _preprocess(payload)
        return env.get_template("pdf_template.html").render(**data, zoom_level=1.0)
    except Exception as e:
        logging.exception("Preview error")
        return f"<html><body><h1>Preview Error</h1><pre>{str(e)}</pre></body></html>", 500

@app.route("/api/pdf", methods=["POST"])
def pdf():
    if not WEASYPRINT_OK:
        return jsonify(error="PDF unavailable"), 503
    try:
        payload = request.get_json(silent=True) or {}
        quality = str(payload.get("quality") or "high").lower()
        data = _preprocess(payload)
        
        zoom = 1.0
        max_attempts = 15
        
        for _ in range(max_attempts):
            html_str = env.get_template("pdf_template.html").render(**data, zoom_level=zoom)
            doc = HTML(string=html_str, base_url=request.url_root).render()
            if len(doc.pages) <= 1:
                break
            zoom -= 0.04
            
        pdf_bytes = doc.write_pdf()
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", (data.get("name") or "Biodata").replace(" ", "_")) or "Biodata"
        return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=f"{safe}_Biodata.pdf")
    except Exception as e:
        logging.exception("PDF error")
        return jsonify(error=str(e)), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
