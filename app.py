"""
Biodata Maker Pro — Backend (Advanced)
Flask API for template rendering, PDF generation, AI, translation, OCR.
"""

from flask import Flask, send_from_directory, request, jsonify, send_file, make_response
from io import BytesIO
from pathlib import Path
import os, re, json, time, hashlib, datetime, logging
from functools import wraps
from threading import Lock
from collections import defaultdict

# Jinja
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Optional imports
try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_OK = True
except Exception:
    TRANSLATOR_OK = False

try:
    import google.generativeai as genai
    GENAI_OK = True
except Exception:
    GENAI_OK = False

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_OK = True
except Exception:
    HTML = None
    WEASYPRINT_OK = False

try:
    import pytesseract
    from PIL import Image
    OCR_OK = True
except Exception:
    OCR_OK = False

# ------------------------------------------------------------------
# APP SETUP
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

env = Environment(
    loader=FileSystemLoader(str(BASE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
)

# ------------------------------------------------------------------
# CACHE
# ------------------------------------------------------------------
class SimpleCache:
    def __init__(self, maxsize=512, ttl=3600):
        self._d = {}
        self._l = Lock()
        self._max = maxsize
        self._ttl = ttl

    def get(self, k):
        with self._l:
            v = self._d.get(k)
            if not v:
                return None
            val, exp = v
            if time.time() > exp:
                del self._d[k]
                return None
            return val

    def set(self, k, v, ttl=None):
        with self._l:
            if len(self._d) >= self._max:
                oldest = min(self._d.items(), key=lambda x: x[1][1])
                del self._d[oldest[0]]
            self._d[k] = (v, time.time() + (ttl or self._ttl))

    def clear(self):
        with self._l:
            self._d.clear()

cache = SimpleCache()

# ------------------------------------------------------------------
# RATE LIMITER
# ------------------------------------------------------------------
class RateLimiter:
    def __init__(self, max_requests=120, window=60):
        self._r = defaultdict(list)
        self._l = Lock()
        self._max = max_requests
        self._w = window

    def check(self, key):
        with self._l:
            now = time.time()
            self._r[key] = [t for t in self._r[key] if now - t < self._w]
            if len(self._r[key]) >= self._max:
                return False
            self._r[key].append(now)
            return True

limiter = RateLimiter(max_requests=200, window=60)


def rate_limit(fn):
    @wraps(fn)
    def w(*a, **kw):
        ip = request.remote_addr or "unknown"
        if not limiter.check(ip):
            return jsonify(error="Rate limit exceeded. Please retry in a minute."), 429
        return fn(*a, **kw)
    return w


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(self)"
    return resp

# ------------------------------------------------------------------
# AI SETUP
# ------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
gemini_model = None
if GEMINI_API_KEY and GENAI_OK:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        log.warning("Gemini setup failed: %s", e)

# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def _fmt_date(v):
    s = str(v or "").strip()
    if not s:
        return ""
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(s, f).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s


def _translate(text, lang):
    if not text or not lang or lang == "en" or not TRANSLATOR_OK:
        return text
    key = f"tr:{lang}:{hashlib.md5(text.encode()).hexdigest()}"
    cached = cache.get(key)
    if cached:
        return cached
    try:
        out = GoogleTranslator(source="auto", target=lang).translate(text)
        cache.set(key, out, ttl=86400)
        return out
    except Exception as e:
        log.warning("Translate failed: %s", e)
        return text


def _validate(payload):
    errs = []
    if not str(payload.get("name") or "").strip():
        errs.append("Name is required")
    if not any([payload.get("phone"), payload.get("email")]):
        errs.append("At least one contact method is required")
    return errs


LABELS_EN = {
    "contact": "Contact Details",
    "personal": "Personal Details",
    "family": "Family Details",
    "skills": "Skills",
    "additional": "Additional Details",
    "profile": "Profile / Objective",
    "education": "Education",
    "experience": "Work Experience",
    "declaration": "Declaration",
    "dob": "Date of Birth",
    "gender": "Gender",
    "height": "Height",
    "weight": "Weight",
    "blood": "Blood Group",
    "marital": "Marital Status",
    "religion": "Religion",
    "caste": "Caste / Community",
    "gotra": "Gotra",
    "rashi": "Rashi",
    "nakshatra": "Nakshatra",
    "manglik": "Manglik",
    "phone": "Mobile Number",
    "email": "Email",
    "address": "Address",
    "father": "Father",
    "mother": "Mother",
    "brothers": "Brothers",
    "sisters": "Sisters",
    "languages": "Languages",
    "hobbies": "Hobbies",
    "place": "Place",
    "date": "Date",
    "signature": "Signature",
}


def _labels_for(lang):
    if not lang or lang == "en":
        return LABELS_EN
    out = {}
    for k, v in LABELS_EN.items():
        out[k] = _translate(v, lang)
    return out


def _preprocess(payload):
    """Normalize & translate the incoming payload."""
    if not isinstance(payload, dict):
        payload = {}

    data = dict(payload)
    lang = str(data.get("language") or "en").lower()

    # Theme validation
    theme = data.get("theme") or {}
    if not isinstance(theme, dict) or not theme.get("primary"):
        theme = {
            "layout": "classic",
            "primary": "#6B0F1A",
            "accent": "#D4A853",
            "tint": "#FAF4E2",
            "ink": "#30242A",
            "displayFont": "Playfair Display",
            "bodyFont": "Lato",
            "name": "Default",
        }
    data["theme"] = theme

    # Skills
    skills = []
    for raw in str(data.get("skills") or "").splitlines():
        if "|" in raw:
            n, lvl = raw.split("|", 1)
            try:
                lv = max(0, min(100, int(float(lvl.strip()))))
            except Exception:
                lv = 80
            if n.strip():
                skills.append({"name": n.strip(), "level": lv})
    data["skills_list"] = skills

    # Translate text fields
    translate_keys = [
        "gender", "height", "blood", "marital", "religion", "caste",
        "gotra", "rashi", "nakshatra", "manglik", "profile", "address",
        "father_job", "mother_job", "brothers", "sisters",
        "education_simple", "experience", "languages", "hobbies",
        "declaration",
    ]
    for k in translate_keys:
        data[k] = _translate(str(data.get(k) or "").strip(), lang)

    # Non-translated string fields
    for k in ("name", "dob", "weight", "phone", "email", "father", "mother", "place", "date", "height"):
        data[k] = str(data.get(k) or "").strip()

    # Height combine
    hft = str(data.get("height_ft") or "").strip()
    hin = str(data.get("height_in") or "").strip()
    if hft and hin:
        data["height"] = f"{hft} ft {hin} in"
    elif hft:
        data["height"] = f"{hft} ft"
    elif hin:
        data["height"] = f"{hin} in"

    data["dob"] = _fmt_date(data.get("dob"))
    data["date"] = _fmt_date(data.get("date"))

    # Education
    edu_mode = str(data.get("education_mode") or "simple").lower()
    data["education_mode"] = edu_mode
    edu_list = []
    if edu_mode == "detailed" and isinstance(data.get("education_list"), list):
        for it in data["education_list"]:
            if not isinstance(it, dict):
                continue
            if not (it.get("level") or it.get("institute")):
                continue
            edu_list.append({
                "level": _translate(str(it.get("level") or "").strip(), lang),
                "board": _translate(str(it.get("board") or "").strip(), lang),
                "institute": _translate(str(it.get("institute") or "").strip(), lang),
                "year": str(it.get("year") or "").strip(),
                "score": str(it.get("score") or "").strip(),
            })
    data["education_list"] = edu_list

    # Labels
    data["labels"] = _labels_for(lang)

    # Photo
    photo = str(data.get("photo") or "")
    if photo and not photo.startswith("data:image/"):
        photo = ""
    data["photo"] = photo

    # Options
    data["watermark"] = bool(data.get("watermark"))
    data["watermark_text"] = str(data.get("watermark_text") or "Biodata")[:50]
    data["show_pagenum"] = bool(data.get("show_pagenum", True))
    data["page_size"] = str(data.get("page_size") or "A4").upper()

    return data


# ------------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Biodata Maker Pro",
        "short_name": "BiodataPro",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f1f5f9",
        "theme_color": "#0f172a",
        "icons": [
            {"src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='20' fill='%23d4a853'/%3E%3Ctext x='50' y='68' font-size='60' text-anchor='middle' font-family='serif' font-weight='bold' fill='%230f172a'%3EB%3C/text%3E%3C/svg%3E",
             "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
    })


@app.route("/api/health")
def health():
    return jsonify(
        status="ok",
        weasyprint=WEASYPRINT_OK,
        translator=TRANSLATOR_OK,
        ai=bool(gemini_model),
        ocr=OCR_OK,
    )


@app.route("/api/preview", methods=["POST"])
@rate_limit
def preview():
    try:
        payload = request.get_json(silent=True) or {}
        payload.pop("photo", None)  # skip photo in preview fetch
        data = _preprocess(payload)
        html = env.get_template("pdf_template.html").render(**data)
        return html
    except Exception as e:
        log.exception("Preview error")
        return f"<html><body><h1>Preview Error</h1><pre>{str(e)}</pre></body></html>", 500


@app.route("/api/pdf", methods=["POST"])
@rate_limit
def pdf():
    if not WEASYPRINT_OK:
        return jsonify(error="WeasyPrint not installed on server. Use 'Print > Save as PDF' from browser instead."), 503
    try:
        data = _preprocess(request.get_json(silent=True) or {})
        html_str = env.get_template("pdf_template.html").render(**data)
        pdf_bytes = HTML(string=html_str, base_url=request.url_root).write_pdf()
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", (data.get("name") or "Biodata").replace(" ", "_")) or "Biodata"
        return send_file(
            BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{safe}_Biodata.pdf",
        )
    except Exception as e:
        log.exception("PDF error")
        return jsonify(error=str(e)), 500


@app.route("/api/generate-profile", methods=["POST"])
@rate_limit
def generate_profile():
    if not gemini_model:
        return jsonify(error="AI not configured. Set GEMINI_API_KEY env var."), 503
    try:
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "the candidate").strip()
        education = str(data.get("education") or "Graduation").strip()
        skills = str(data.get("skills") or "Good communication").strip()
        tone = str(data.get("tone") or "traditional")
        prompt = (
            f"Write a 3-4 sentence humble biodata profile for an Indian marriage profile. "
            f"Name: {name}. Education: {education}. Skills: {skills}. Tone: {tone}. "
            "Focus on family values, career goals, and desire for a partner who shares these values. "
            "Return plain text only, no headings or markdown."
        )
        resp = gemini_model.generate_content(prompt)
        text = (resp.text or "").strip()
        return jsonify(profile=text)
    except Exception as e:
        log.exception("AI error")
        return jsonify(error=str(e)), 500


@app.route("/api/improve-text", methods=["POST"])
@rate_limit
def improve_text():
    if not gemini_model:
        return jsonify(error="AI not configured"), 503
    try:
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "").strip()
        kind = str(data.get("kind") or "general")
        if not text:
            return jsonify(error="No text to improve"), 400
        prompt = (
            f"Improve the following {kind} text for an Indian marriage biodata. "
            f"Keep meaning, make it professional and concise. Return only the improved text.\n\n{text}"
        )
        resp = gemini_model.generate_content(prompt)
        return jsonify(text=(resp.text or "").strip())
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/suggest-skills", methods=["POST"])
@rate_limit
def suggest_skills():
    if not gemini_model:
        return jsonify(error="AI not configured"), 503
    try:
        data = request.get_json(silent=True) or {}
        education = str(data.get("education") or "").strip()
        prompt = (
            f"Suggest 6 relevant skills (as 'Name | Level 0-100') for a candidate with education '{education}'. "
            "Return only one skill per line, no numbering, no markdown."
        )
        resp = gemini_model.generate_content(prompt)
        return jsonify(skills=(resp.text or "").strip())
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/translate", methods=["POST"])
@rate_limit
def translate_endpoint():
    try:
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "").strip()
        lang = str(data.get("lang") or "hi").lower()
        if not text:
            return jsonify(error="No text provided"), 400
        return jsonify(text=_translate(text, lang), lang=lang)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/ocr", methods=["POST"])
@rate_limit
def ocr_endpoint():
    if not OCR_OK:
        return jsonify(error="OCR not installed (need pytesseract + Pillow)"), 503
    try:
        if "photo" not in request.files:
            return jsonify(error="No image uploaded"), 400
        img = Image.open(request.files["photo"])
        text = pytesseract.image_to_string(img)
        return jsonify(text=text.strip())
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/templates")
def templates_meta():
    """Returns layout/colour/font list for client to rebuild template grid."""
    return jsonify(
        layouts=[
            "classic", "sidebar", "banner", "corporate", "cards",
            "split", "minimal", "timeline", "editorial", "traditional",
            "magazine", "executive", "vintage", "gradient", "geometric",
        ],
    )


# ------------------------------------------------------------------
# BOOT
# ------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    log.info("Starting Biodata Maker Pro on port %s", port)
    log.info("WeasyPrint=%s Translator=%s AI=%s OCR=%s",
             WEASYPRINT_OK, TRANSLATOR_OK, bool(gemini_model), OCR_OK)
    app.run(host="0.0.0.0", port=port, debug=False)
