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

def _translate(text, lang):
    if not text or not lang or lang == "en":
        return text
    
    text = str(text).strip()
    if not text: return text
    
    cache_key = f"{lang}:{text}"
    if cache_key in TRANS_CACHE:
        return TRANS_CACHE[cache_key]
    
    # Direct Google API
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={lang}&dt=t&q={urllib.parse.quote(text)}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            out = "".join([item[0] for item in data[0]])
            TRANS_CACHE[cache_key] = out
            return out
    except Exception:
        pass
        
    return text

LABELS_MULTI = {
    "en": {"contact": "Contact Details", "personal": "Personal Details", "family": "Family Details", "skills": "Skills", "additional": "Additional Details", "profile": "Profile / Objective", "education": "Education", "experience": "Work Experience", "declaration": "Declaration", "dob": "Date of Birth", "gender": "Gender", "height": "Height", "weight": "Weight", "blood": "Blood Group", "marital": "Marital Status", "religion": "Religion", "caste": "Caste / Community", "gotra": "Gotra", "rashi": "Rashi", "nakshatra": "Nakshatra", "manglik": "Manglik", "phone": "Mobile Number", "email": "Email", "address": "Address", "father": "Father", "mother": "Mother", "brothers": "Brothers", "sisters": "Sisters", "languages": "Languages", "hobbies": "Hobbies", "place": "Place", "date": "Date", "signature": "Signature", "qualification": "Qualification", "institute": "Name of the University", "year": "Year of Passing", "score": "Total % Marks", "organization": "Organization", "designation": "Designation", "period": "Job Period", "responsibilities": "Responsibilities"},
    "hi": {"contact": "संपर्क विवरण", "personal": "व्यक्तिगत विवरण", "family": "पारिवारिक विवरण", "skills": "कौशल", "additional": "अतिरिक्त विवरण", "profile": "प्रोफ़ाइल / उद्देश्य", "education": "शिक्षा", "experience": "कार्य अनुभव", "declaration": "घोषणा", "dob": "जन्म तिथि", "gender": "लिंग", "height": "ऊंचाई", "weight": "वजन", "blood": "रक्त समूह", "marital": "वैवाहिक स्थिति", "religion": "धर्म", "caste": "जाति", "gotra": "गोत्र", "rashi": "राशि", "nakshatra": "नक्षत्र", "manglik": "मांगलिक", "phone": "मोबाइल नंबर", "email": "ईमेल", "address": "पता", "father": "पिता", "mother": "माता", "brothers": "भाई", "sisters": "बहनें", "languages": "भाषाएं", "hobbies": "शौक", "place": "स्थान", "date": "तिथि", "signature": "हस्ताक्षर", "qualification": "योग्यता", "institute": "विश्वविद्यालय का नाम", "year": "पास होने का वर्ष", "score": "कुल % अंक", "organization": "संगठन", "designation": "पद", "period": "कार्यकाल", "responsibilities": "जिम्मेदारियां"},
    "kn": {"contact": "ಸಂಪರ್ಕ ವಿವರಗಳು", "personal": "ವೈಯಕ್ತಿಕ ವಿವರಗಳು", "family": "ಕುಟುಂಬದ ವಿವರಗಳು", "skills": "ಕೌಶಲ್ಯಗಳು", "additional": "ಹೆಚ್ಚುವರಿ ವಿವರಗಳು", "profile": "ಪ್ರೊಫೈಲ್ / ಉದ್ದೇಶ", "education": "ಶಿಕ್ಷಣ", "experience": "ಕೆಲಸದ ಅನುಭವ", "declaration": "ಘೋಷಣೆ", "dob": "ಜನ್ಮ ದಿನಾಂಕ", "gender": "ಲಿಂಗ", "height": "ಎತ್ತರ", "weight": "ತೂಕ", "blood": "ರಕ್ತ ಗುಂಪು", "marital": "ವೈವಾಹಿಕ ಸ್ಥಿತಿ", "religion": "ಧರ್ಮ", "caste": "ಜಾತಿ", "gotra": "ಗೋತ್ರ", "rashi": "ರಾಶಿ", "nakshatra": "ನಕ್ಷತ್ರ", "manglik": "ಮಾಂಗಲಿಕ", "phone": "ಮೊಬೈಲ್ ಸಂಖ್ಯೆ", "email": "ಇಮೇಲ್", "address": "ವಿಳಾಸ", "father": "ತಂದೆ", "mother": "ತಾಯಿ", "brothers": "ಸಹೋದರರು", "sisters": "ಸಹೋದರಿಯರು", "languages": "ಭಾಷೆಗಳು", "hobbies": "ಹವ್ಯಾಸಗಳು", "place": "ಸ್ಥಳ", "date": "ದಿನಾಂಕ", "signature": "ಸಹಿ", "qualification": "ಅರ್ಹತೆ", "institute": "ವಿಶ್ವವಿದ್ಯಾಲಯದ ಹೆಸರು", "year": "ತೇರ್ಗಡೆಯಾದ ವರ್ಷ", "score": "ಒಟ್ಟು % ಅಂಕಗಳು", "organization": "ಸಂಸ್ಥೆ", "designation": "ಹುದ್ದೆ", "period": "ಕೆಲಸದ ಅವಧಿ", "responsibilities": "ಜವಾಬ್ದಾರಿಗಳು"},
    "ta": {"contact": "தொடர்பு விவரங்கள்", "personal": "தனிப்பட்ட விவரங்கள்", "family": "குடும்ப விவரங்கள்", "skills": "திறன்கள்", "additional": "கூடுதல் விவரங்கள்", "profile": "சுயவிவரம் / குறிக்கோள்", "education": "கல்வி", "experience": "பணி அனுபவம்", "declaration": "பிரகடனம்", "dob": "பிறந்த தேதி", "gender": "பாலினம்", "height": "உயரம்", "weight": "எடை", "blood": "இரத்தக் குழு", "marital": "திருமண நிலை", "religion": "மதம்", "caste": "சாதி", "gotra": "கோத்திரம்", "rashi": "ராசி", "nakshatra": "நட்சத்திரம்", "manglik": "மாங்கல்யம்", "phone": "கைபேசி எண்", "email": "மின்னஞ்சல்", "address": "முகவரி", "father": "தந்தை", "mother": "தாய்", "brothers": "சகோதரர்கள்", "sisters": "சகோதரிகள்", "languages": "மொழிகள்", "hobbies": "பொழுதுபோக்கு", "place": "இடம்", "date": "தேதி", "signature": "கையொப்பம்", "qualification": "தகுதி", "institute": "பல்கலைக்கழகத்தின் பெயர்", "year": "தேர்ச்சி பெற்ற ஆண்டு", "score": "மொத்த % மதிப்பெண்கள்", "organization": "நிறுவனம்", "designation": "பதவி", "period": "பணி காலம்", "responsibilities": "பொறுப்புகள்"},
    "te": {"contact": "సంప్రదింపు వివరాలు", "personal": "వ్యక్తిగత వివరాలు", "family": "కుటుంబ వివరాలు", "skills": "నైపుణ్యాలు", "additional": "అదనపు వివరాలు", "profile": "ప్రొఫైల్ / లక్ష్యం", "education": "విద్య", "experience": "పని అనుభవం", "declaration": "ప్రకటన", "dob": "పుట్టిన తేదీ", "gender": "లింగం", "height": "ఎత్తు", "weight": "బరువు", "blood": "రక్త వర్గం", "marital": "వైవాహిక స్థితి", "religion": "మతం", "caste": "కులం", "gotra": "గోత్రం", "rashi": "రాశి", "nakshatra": "నక్షత్రం", "manglik": "మాంగలిక్", "phone": "మొబైల్ నంబర్", "email": "ఇమెయిల్", "address": "చిరునామా", "father": "తండ్రి", "mother": "తల్లి", "brothers": "సహోదరులు", "sisters": "సహోదరులు (అక్కచెల్లెళ్ళు)", "languages": "భాషలు", "hobbies": "అభిరుచులు", "place": "స్థలం", "date": "తేదీ", "signature": "సంతకం", "qualification": "అర్హత", "institute": "విశ్వవిద్యాలయం పేరు", "year": "ఉత్తీర్ణత సంవత్సరం", "score": "మొత్తం % మార్కులు", "organization": "సంస్థ", "designation": "హోదా", "period": "పని కాలం", "responsibilities": "బాధ్యతలు"},
    "mr": {"contact": "संपर्क तपशील", "personal": "वैयक्तिक तपशील", "family": "कौटुंबिक तपशील", "skills": "कौशल्ये", "additional": "अतिरिक्त तपशील", "profile": "प्रोफाइल / उद्दिष्ट", "education": "शिक्षण", "experience": "कामाचा अनुभव", "declaration": "घोषणा", "dob": "जन्मतारीख", "gender": "लिंग", "height": "उंची", "weight": "वजन", "blood": "रक्तगट", "marital": "वैवाहिक स्थिती", "religion": "धर्म", "caste": "जात", "gotra": "गोत्र", "rashi": "राशी", "nakshatra": "नक्षत्र", "manglik": "मांगलिक", "phone": "मोबाइल क्रमांक", "email": "ईमेल", "address": "पत्ता", "father": "वडील", "mother": "आई", "brothers": "भाऊ", "sisters": "बहिणी", "languages": "भाषा", "hobbies": "छंद", "place": "ठिकाण", "date": "तारीख", "signature": "स्वाक्षरी", "qualification": "पात्रता", "institute": "विद्यापीठाचे नाव", "year": "उत्तीर्ण होण्याचे वर्ष", "score": "एकूण % गुण", "organization": "संस्था", "designation": "पद", "period": "कामाचा कालावधी", "responsibilities": "जबाबदाऱ्या"},
    "gu": {"contact": "સંપર્ક વિગતો", "personal": "અંગત વિગતો", "family": "કૌટુંબિક વિગતો", "skills": "કૌશલ્યો", "additional": "વધારાની વિગતો", "profile": "પ્રોફાઇલ / ઉદ્દેશ્ય", "education": "શિક્ષણ", "experience": "કાર્ય અનુભવ", "declaration": "ઘોષણા", "dob": "જન્મ તારીખ", "gender": "જાતિ", "height": "ઊંચાઈ", "weight": "વજન", "blood": "બ્લડ ગ્રુપ", "marital": "વૈવાહિક સ્થિતિ", "religion": "ધર્મ", "caste": "જ્ઞાતિ", "gotra": "ગોત્ર", "rashi": "રાશિ", "nakshatra": "નક્ષત્ર", "manglik": "માંગલિક", "phone": "મોબાઇલ નંબર", "email": "ઇમેઇલ", "address": "સરનામું", "father": "પિતા", "mother": "માતા", "brothers": "ભાઈઓ", "sisters": "બહેનો", "languages": "ભાષાઓ", "hobbies": "શોખ", "place": "સ્થળ", "date": "તારીખ", "signature": "સહી", "qualification": "લાયકાત", "institute": "યુનિવર્સિટીનું નામ", "year": "પાસ થયાનું વર્ષ", "score": "કુલ % માર્ક્સ", "organization": "સંસ્થા", "designation": "હોદ્દો", "period": "કાર્યકાળ", "responsibilities": "જવાબદારીઓ"},
    "bn": {"contact": "যোগাযোগের বিবরণ", "personal": "ব্যক্তিগত বিবরণ", "family": "পারিবারিক বিবরণ", "skills": "দক্ষতা", "additional": "অতিরিক্ত বিবরণ", "profile": "প্রোফাইল / উদ্দেশ্য", "education": "শিক্ষা", "experience": "কাজের অভিজ্ঞতা", "declaration": "ঘোষণা", "dob": "জন্ম তারিখ", "gender": "লিঙ্গ", "height": "উচ্চতা", "weight": "ওজন", "blood": "রক্তের গ্রুপ", "marital": "বৈবাহিক অবস্থা", "religion": "ধর্ম", "caste": "বর্ণ", "gotra": "গোত্র", "rashi": "রাশি", "nakshatra": "নক্ষত্র", "manglik": "মাঙ্গলিক", "phone": "মোবাইল নম্বর", "email": "ইমেল", "address": "ঠিকানা", "father": "পিতা", "mother": "মাতা", "brothers": "ভাই", "sisters": "বোন", "languages": "ভাষা", "hobbies": "শখ", "place": "স্থান", "date": "তারিখ", "signature": "স্বাক্ষর", "qualification": "যোগ্যতা", "institute": "বিশ্ববিদ্যালয়ের নাম", "year": "পাসের বছর", "score": "মোট % নম্বর", "organization": "সংস্থা", "designation": "পদবি", "period": "কাজের সময়কাল", "responsibilities": "দায়িত্ব"},
    "ml": {"contact": "ബന്ധപ്പെടാനുള്ള വിവരങ്ങൾ", "personal": "വ്യക്തിഗത വിവരങ്ങൾ", "family": "കുടുംബ വിവരങ്ങൾ", "skills": "കഴിവുകൾ", "additional": "അധിക വിവരങ്ങൾ", "profile": "പ്രൊഫൈൽ / ലക്ഷ്യം", "education": "വിദ്യാഭ്യാസം", "experience": "ജോലി പരിചയം", "declaration": "സത്യവാങ്മൂലം", "dob": "ജനനത്തീയതി", "gender": "ലിംഗഭേദം", "height": "ഉയരം", "weight": "ഭാരം", "blood": "രക്തഗ്രൂപ്പ്", "marital": "വൈവാഹിക നില", "religion": "മതം", "caste": "ജാതി", "gotra": "ഗോത്രം", "rashi": "രാശി", "nakshatra": "നക്ഷത്രം", "manglik": "മാംഗല്യം", "phone": "മൊബൈൽ നമ്പർ", "email": "ഇമെയിൽ", "address": "വിലാസം", "father": "പിതാവ്", "mother": "മാതാവ്", "brothers": "സഹോദരങ്ങൾ", "sisters": "സഹോദരിമാർ", "languages": "ഭാഷകൾ", "hobbies": "വിനോദങ്ങൾ", "place": "സ്ഥലം", "date": "തീയതി", "signature": "ഒപ്പ്", "qualification": "യോഗ്യത", "institute": "സർവ്വകലാശാലയുടെ പേര്", "year": "വിജയിച്ച വർഷം", "score": "ആകെ % മാർക്ക്", "organization": "സ്ഥാപനം", "designation": "പദവി", "period": "ജോലി കാലയളവ്", "responsibilities": "ഉത്തരവാദിത്തങ്ങൾ"},
    "pa": {"contact": "ਸੰਪਰਕ ਵੇਰਵੇ", "personal": "ਨਿੱਜੀ ਵੇਰਵੇ", "family": "ਪਰਿਵਾਰਕ ਵੇਰਵੇ", "skills": "ਹੁਨਰ", "additional": "ਵਾਧੂ ਵੇਰਵੇ", "profile": "ਪ੍ਰੋਫਾਈਲ / ਉਦੇਸ਼", "education": "ਸਿੱਖਿਆ", "experience": "ਕੰਮ ਦਾ ਤਜਰਬਾ", "declaration": "ਐਲਾਨ", "dob": "ਜਨਮ ਤਾਰੀਖ", "gender": "ਲਿੰਗ", "height": "ਕੱਦ", "weight": "ਭਾਰ", "blood": "ਬਲੱਡ ਗਰੁੱਪ", "marital": "ਵਿਆਹੁਤਾ ਸਥਿਤੀ", "religion": "ਧਰਮ", "caste": "ਜਾਤੀ", "gotra": "ਗੋਤਰ", "rashi": "ਰਾਸ਼ੀ", "nakshatra": "ਨਛੱਤਰ", "manglik": "ਮਾਂਗਲਿਕ", "phone": "ਮੋਬਾਈਲ ਨੰਬਰ", "email": "ਈਮੇਲ", "address": "ਪਤਾ", "father": "ਪਿਤਾ", "mother": "ਮਾਤਾ", "brothers": "ਭਰਾ", "sisters": "ਭੈਣਾਂ", "languages": "ਭਾਸ਼ਾਵਾਂ", "hobbies": "ਸ਼ੌਕ", "place": "ਜਗ੍ਹਾ", "date": "ਤਾਰੀਖ", "signature": "ਦਸਤਖਤ", "qualification": "ਯੋਗਤਾ", "institute": "ਯੂਨੀਵਰਸਿਟੀ ਦਾ ਨਾਮ", "year": "ਪਾਸ ਹੋਣ ਦਾ ਸਾਲ", "score": "ਕੁੱਲ % ਅੰਕ", "organization": "ਸੰਗਠਨ", "designation": "ਅਹੁਦਾ", "period": "ਕੰਮ ਦੀ ਮਿਆਦ", "responsibilities": "ਜ਼ਿੰਮੇਵਾਰੀਆਂ"},
    "or": {"contact": "ଯୋଗାଯୋଗ ବିବରଣୀ", "personal": "ବ୍ୟକ୍ତିଗତ ବିବରଣୀ", "family": "ପାରିବାରିକ ବିବରଣୀ", "skills": "ଦକ୍ଷତା", "additional": "ଅତିରିକ୍ତ ବିବରଣୀ", "profile": "ପ୍ରୋଫାଇଲ୍ / ଉଦ୍ଦେଶ୍ୟ", "education": "ଶିକ୍ଷା", "experience": "କାର୍ଯ୍ୟ ଅଭିଜ୍ଞତା", "declaration": "ଘୋଷଣା", "dob": "ଜନ୍ମ ତାରିଖ", "gender": "ଲିଙ୍ଗ", "height": "ଉଚ୍ଚତା", "weight": "ଓଜନ", "blood": "ରକ୍ତ ଗ୍ରୁପ୍", "marital": "ବୈବାହିକ ସ୍ଥିତି", "religion": "ଧର୍ମ", "caste": "ଜାତି", "gotra": "ଗୋତ୍ର", "rashi": "ରାଶି", "nakshatra": "ନକ୍ଷତ୍ର", "manglik": "ମାଙ୍ଗଳିକ", "phone": "ମୋବାଇଲ୍ ନମ୍ବର", "email": "ଇମେଲ୍", "address": "ଠିକଣା", "father": "ପିତା", "mother": "ମାତା", "brothers": "ଭାଇ", "sisters": "ଭଉଣୀ", "languages": "ଭାଷା", "hobbies": "ଶଉକ", "place": "ସ୍ଥାନ", "date": "ତାରିଖ", "signature": "ଦସ୍ତଖତ", "qualification": "ଯୋଗ୍ୟତା", "institute": "ବିଶ୍ୱବିଦ୍ୟାଳୟର ନାମ", "year": "ପାସ ହେବାର ବର୍ଷ", "score": "ମୋଟ % ମାର୍କ", "organization": "ସଂସ୍ଥା", "designation": "ପଦବୀ", "period": "କାର୍ଯ୍ୟକାଳ", "responsibilities": "ଦାୟିତ୍ୱ"}
}

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
            if n.strip(): 
                skills.append({"name": _translate(n.strip(), lang), "level": lv})
    data["skills_list"] = skills

    v_map = {
        "hi": {"Male": "पुरुष", "Female": "महिला", "Other": "अन्य", "Unmarried": "अविवाहित", "Never Married": "कभी शादी नहीं की", "Divorced": "तलाकशुदा", "Widowed": "विधवा/विधुर", "Awaiting Divorce": "तालाक का इंतजार", "Yes": "हाँ", "No": "नहीं", "Partial": "आंशिक", "Hindu": "हिंदू", "Muslim": "मुस्लिम", "Christian": "ईसाई", "Sikh": "सिख", "Buddhist": "बौद्ध", "Jain": "जैन", "Parsi": "पारसी"},
        "kn": {"Male": "ಪುರುಷ", "Female": "ಮಹಿಳೆ", "Other": "ಇತರೆ", "Unmarried": "ಅವಿವಾಹಿತ", "Never Married": "ಮದುವೆಯಾಗಿಲ್ಲ", "Divorced": "ವಿಚ್ಛೇದಿತ", "Widowed": "ವಿಧವೆ/ವಿಧುರ", "Awaiting Divorce": "ವಿಚ್ಛೇದನದ ನಿರೀಕ್ಷೆಯಲ್ಲಿದೆ", "Yes": "ಹೌದು", "No": "ಇಲ್ಲ", "Partial": "ಭಾಗಶಃ", "Hindu": "ಹಿಂದೂ", "Muslim": "ಮುಸ್ಲಿಂ", "Christian": "ಕ್ರಿಶ್ಚಿಯನ್", "Sikh": "ಸಿಖ್", "Buddhist": "ಬೌದ್ಧ", "Jain": "ಜೈನ", "Parsi": "ಪಾರ್ಸಿ"},
        "ta": {"Male": "ஆண்", "Female": "பெண்", "Other": "மற்றவை", "Unmarried": "திருமணமாகாத", "Never Married": "திருமணம் செய்யவில்லை", "Divorced": "விவாகரத்து", "Widowed": "விதவை/விதுரர்", "Awaiting Divorce": "விவாகரத்துக்காக காத்திருக்கிறது", "Yes": "ஆம்", "No": "இல்லை", "Partial": "பகுதி", "Hindu": "இந்து", "Muslim": "முஸ்லீம்", "Christian": "கிறிஸ்தவர்", "Sikh": "சீக்கியர்", "Buddhist": "பௌத்தர்", "Jain": "சமணர்", "Parsi": "பார்சி"},
        "te": {"Male": "పురుషుడు", "Female": "స్త్రీ", "Other": "ఇతర", "Unmarried": "అవివాహిత", "Never Married": "పెళ్లి కాదు", "Divorced": "విడాకులు", "Widowed": "వితంతువు", "Awaiting Divorce": "విడాకుల కోసం వేచి ఉంది", "Yes": "అవును", "No": "కాదు", "Partial": "పాక్షికం", "Hindu": "హిందూ", "Muslim": "ముస్లిం", "Christian": "క్రిస్టియన్", "Sikh": "సిక్కు", "Buddhist": "బౌద్ధ", "Jain": "జైన", "Parsi": "పార్సీ"},
        "mr": {"Male": "पुरुष", "Female": "स्त्री", "Other": "इतर", "Unmarried": "अविवाहित", "Never Married": "लग्न झाले नाही", "Divorced": "घटस्पोटित", "Widowed": "विधवा/विधुर", "Awaiting Divorce": "घटस्फोटाच्या प्रतीक्षेत", "Yes": "होय", "No": "नाही", "Partial": "अर्धवट", "Hindu": "हिंदू", "Muslim": "मुस्लिम", "Christian": "ख्रिश्चन", "Sikh": "शीख", "Buddhist": "बौद्ध", "Jain": "जैन", "Parsi": "पारशी"},
        "gu": {"Male": "પુરુષ", "Female": "સ્ત્રી", "Other": "અન્ય", "Unmarried": "અવિવાહિત", "Never Married": "કદી લગ્ન કર્યા નથી", "Divorced": "છૂટાછેડા", "Widowed": "વિધવા/વિધુર", "Awaiting Divorce": "છૂટાછેડાની રાહ જોઈ રહ્યા છે", "Yes": "હા", "No": "ના", "Partial": "આંશિક", "Hindu": "હિન્દુ", "Muslim": "મુસ્લિમ", "Christian": "ખ્રિસ્તી", "Sikh": "શીખ", "Buddhist": "બૌદ્ધ", "Jain": "જૈન", "Parsi": "પારસી"},
        "bn": {"Male": "পুরুষ", "Female": "মহিলা", "Other": "অন্যান্য", "Unmarried": "অবিবাহিত", "Never Married": "কখনো বিয়ে করেননি", "Divorced": "বিচ্ছেদ", "Widowed": "বিধবা/বিপত্নীক", "Awaiting Divorce": "বিচ্ছেদের অপেক্ষায়", "Yes": "হ্যাঁ", "No": "না", "Partial": "আংশিক", "Hindu": "হিন্দু", "Muslim": "মুসলিম", "Christian": "খ্রিস্টান", "Sikh": "শিখ", "Buddhist": "বৌদ্ধ", "Jain": "জৈন", "Parsi": "পারসি"},
        "ml": {"Male": "പുരുഷൻ", "Female": "സ്ത്രീ", "Other": "മറ്റുള്ളവർ", "Unmarried": "അവിവാഹിതൻ", "Never Married": "വിവാഹം കഴിച്ചിട്ടില്ല", "Divorced": "വിവാഹമോചിതൻ", "Widowed": "വിധവ/വിധുരൻ", "Awaiting Divorce": "വിവാഹമോചനത്തിനായി കാത്തിരിക്കുന്നു", "Yes": "അതെ", "No": "ഇല്ല", "Partial": "ഭാഗികം", "Hindu": "ഹിന്ദു", "Muslim": "മുസ്ലിം", "Christian": "ക്രിസ്ത്യൻ", "Sikh": "സിഖ്", "Buddhist": "ബുദ്ധമതക്കാർ", "Jain": "ജൈന", "Parsi": "പാർസി"},
        "pa": {"Male": "ਪੁਰਸ਼", "Female": "ਔਰਤ", "Other": "ਹੋਰ", "Unmarried": "ਅਣਵਿਆਹਿਆ", "Never Married": "ਕਦੇ ਵਿਆਹ ਨਹੀਂ ਕਰਵਾਇਆ", "Divorced": "ਤਲਾਕਸ਼ੁਦਾ", "Widowed": "ਵਿਧਵਾ/ਵਿਧੁਰ", "Awaiting Divorce": "ਤਲਾਕ ਦੀ ਉਡੀਕ", "Yes": "ਹਾਂ", "No": "ਨਹੀਂ", "Partial": "ਅੰਸ਼ਕ", "Hindu": "ਹਿੰਦੂ", "Muslim": "ਮੁਸਲਿਮ", "Christian": "ਈਸਾਈ", "Sikh": "ਸਿੱਖ", "Buddhist": "ਬੁੱਧ", "Jain": "ਜੈਨ", "Parsi": "ਪਾਰਸੀ"},
        "or": {"Male": "ପୁରୁଷ", "Female": "ମହିଳା", "Other": "ଅନ୍ୟାନ୍ୟ", "Unmarried": "ଅବିବାହିତ", "Never Married": "କେବେ ବିବାହ କରିନାହାଁନ୍ତି", "Divorced": "ଛାଡପତ୍ର", "Widowed": "ବିଧବା/ବିଧୁର", "Awaiting Divorce": "ଛାଡପତ୍ର ଅପେକ୍ଷାରେ", "Yes": "ହଁ", "No": "ନା", "Partial": "ଆଂଶିକ", "Hindu": "ହିନ୍ଦୁ", "Muslim": "ମୁସଲିମ", "Christian": "ଖ୍ରୀଷ୍ଟିଆନ", "Sikh": "ଶିଖ", "Buddhist": "ବୌଦ୍ଧ", "Jain": "ଜୈନ", "Parsi": "ପାର୍ସି"}
    }.get(lang, {})

    for k in ["gender", "marital", "manglik", "religion", "caste"]:
        val = str(data.get(k) or "").strip()
        if val in v_map:
            data[k] = v_map[val]
        else:
            data[k] = val

    translate_keys = [
        "name", "address", "profile", "father", "mother", "father_job", "mother_job", 
        "brothers", "sisters", "education_simple", "languages", "hobbies", 
        "declaration", "place"
    ]
    for k in translate_keys:
        data[k] = _translate(str(data.get(k) or "").strip(), lang)

    for k in ("dob", "weight", "phone", "email", "date"):
        data[k] = str(data.get(k) or "").strip()

    edu_mode = str(data.get("education_mode") or "simple").lower()
    data["education_mode"] = edu_mode
    raw_edu_list = data.get("education_list", [])
    processed_edu = []
    if edu_mode == "detailed" and isinstance(raw_edu_list, list):
        for item in raw_edu_list:
            if item.get("level") or item.get("institute"):
                processed_edu.append({
                    "level": _translate(str(item.get("level", "")).strip(), lang),
                    "board": _translate(str(item.get("board", "")).strip(), lang),
                    "institute": _translate(str(item.get("institute", "")).strip(), lang),
                    "year": str(item.get("year", "")).strip(),
                    "score": str(item.get("score", "")).strip()
                })
    data["education_list"] = processed_edu

    # 🔥 Work Experience Parse
    raw_jobs = data.get("work_experience_list", [])
    processed_jobs = []
    if isinstance(raw_jobs, list):
        for item in raw_jobs:
            if item.get("organization") or item.get("designation"):
                processed_jobs.append({
                    "organization": _translate(str(item.get("organization", "")).strip(), lang),
                    "designation": _translate(str(item.get("designation", "")).strip(), lang),
                    "period": str(item.get("period", "")).strip(),
                    "responsibilities": _translate(str(item.get("responsibilities", "")).strip(), lang)
                })
    data["work_experience_list"] = processed_jobs

    data["labels"] = LABELS_MULTI.get(lang, LABELS_MULTI["en"])
    
    data["photo"] = str(data.get("photo") or "")
    data["watermark"] = bool(data.get("watermark"))
    data["watermark_text"] = str(data.get("watermark_text") or "Biodata")[:50]
    data["show_pagenum"] = bool(data.get("show_pagenum", True))
    data["page_size"] = str(data.get("page_size") or "A4").upper()

    return data

@app.route("/")
def index(): return send_from_directory(BASE_DIR, "index.html")

@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Biodata Maker Pro", "short_name": "BiodataPro", "start_url": "/", "display": "standalone", "background_color": "#f1f5f9", "theme_color": "#0f172a"})

@app.route("/api/health")
def health():
    return jsonify(status="ok", ai=bool(gemini_model))

@app.route("/api/generate-profile", methods=["POST"])
def generate_profile():
    if not gemini_model: return jsonify(error="AI not configured"), 503
    try:
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "the candidate").strip()
        education = str(data.get("education") or "Graduation").strip()
        skills = str(data.get("skills") or "Good communication").strip()
        lang = str(data.get("language") or "en")
        lang_name = {"hi": "Hindi", "kn": "Kannada", "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "gu": "Gujarati", "bn": "Bengali", "ml": "Malayalam", "pa": "Punjabi", "or": "Odia"}.get(lang, "English")
        
        prompt = f"Write a 3-4 sentence humble biodata profile in {lang_name} language for an Indian marriage profile. Name: {name}. Education: {education}. Skills: {skills}. Focus on family values, career goals. Return plain text only."
        resp = gemini_model.generate_content(prompt)
        return jsonify(profile=(resp.text or "").strip())
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route("/api/suggest-skills", methods=["POST"])
def suggest_skills():
    if not gemini_model: return jsonify(error="AI not configured"), 503
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
