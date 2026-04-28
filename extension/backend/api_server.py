"""
Homograph Phishing Detection - REST API Backend
Serves predictions from the ONNX model to the browser extension.
"""
import os
import sys
import math
import unicodedata
import warnings
from collections import Counter
from urllib.parse import urlparse
import encodings.idna   # for punycode → unicode decoding
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np

warnings.filterwarnings('ignore')

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR   = os.path.join(BASE_DIR, '..', '..', 'ensembled_models')
ONNX_PATH   = os.path.join(MODEL_DIR, 'model.onnx')
MEAN_PATH   = os.path.join(MODEL_DIR, 'scaler_mean.npy')
SCALE_PATH  = os.path.join(MODEL_DIR, 'scaler_scale.npy')

FEATURES = [
    'url_length', 'domain_length', 'char_entropy', 'digit_fraction',
    'special_char_fraction', 'unicode_fraction', 'subdomain_depth',
    'has_punycode', 'unicode_script_count', 'mixed_script',
    'vowel_consonant_ratio', 'max_consec_consonants'
]

VOWELS    = set('aeiouAEIOU')
CONSONANTS = set('bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ')

# ─── Feature Extraction ───────────────────────────────────────────────────────

def get_domain(url: str) -> str:
    url = str(url)
    if not url.startswith('http'):
        url = 'http://' + url
    try:
        return urlparse(url).netloc
    except Exception:
        return url

def char_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    total  = len(s)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())

def get_unicode_script(ch: str) -> str:
    try:
        name = unicodedata.name(ch, '')
        if name:
            return name.split()[0]
    except Exception:
        pass
    return 'UNKNOWN'

def decode_punycode_domain(domain: str) -> str:
    """
    Decode each punycode label (xn--...) to its Unicode equivalent.
    This lets the model see the actual homograph characters.
    e.g. 'xn--e1afmkfd.xn--p1ai'  ->  'пример.испытание'
         'xn--pple-43d.com'        ->  'аpple.com'
    """
    labels = domain.split('.')
    decoded = []
    for label in labels:
        if label.lower().startswith('xn--'):
            try:
                decoded.append(label.encode('ascii').decode('idna'))
            except Exception:
                decoded.append(label)   # keep original if decode fails
        else:
            decoded.append(label)
    return '.'.join(decoded)

def extract_features(url: str) -> list:
    url = str(url)
    url_full = url if url.startswith('http') else 'http://' + url
    try:
        parsed = urlparse(url_full)
        domain = parsed.netloc or url
        path   = parsed.path or ''
    except Exception:
        domain = url
        path   = ''

    # ── Punycode decode: reveal the actual Unicode characters ──────────────────
    # has_punycode is captured BEFORE decoding (from raw domain)
    # then domain is decoded so unicode_fraction / mixed_script features fire
    has_punycode_flag = int('xn--' in domain.lower())
    domain_decoded    = decode_punycode_domain(domain)


    # Use decoded domain for all Unicode-sensitive features
    full_decoded  = domain_decoded + path
    total_decoded = max(len(full_decoded), 1)

    url_length    = len(url)
    domain_length = len(domain_decoded)
    entropy       = char_entropy(domain_decoded)
    digit_frac    = sum(c.isdigit()     for c in full_decoded) / total_decoded
    special_frac  = sum(not c.isalnum() for c in full_decoded) / total_decoded
    unicode_frac  = sum(ord(c) > 127    for c in full_decoded) / total_decoded

    parts           = domain_decoded.split('.')
    subdomain_depth = max(len(parts) - 2, 0)

    scripts = {get_unicode_script(ch) for ch in domain_decoded if ord(ch) > 127}
    unicode_script_count = len(scripts)
    mixed_script         = int(unicode_script_count > 1)

    letters    = [c for c in domain_decoded if c.isalpha()]
    vowels_n   = sum(c in VOWELS     for c in letters)
    consonants = sum(c in CONSONANTS for c in letters)
    vcr        = vowels_n / max(consonants, 1)

    max_cc = cur_cc = 0
    for c in domain_decoded:
        if c in CONSONANTS:
            cur_cc += 1
            max_cc = max(max_cc, cur_cc)
        else:
            cur_cc = 0

    return [
        url_length, domain_length, entropy, digit_frac, special_frac,
        unicode_frac, subdomain_depth, has_punycode_flag, unicode_script_count,
        mixed_script, vcr, max_cc
    ]

# ─── Load artefacts ───────────────────────────────────────────────────────────
try:
    import onnxruntime as rt
    _sess  = rt.InferenceSession(ONNX_PATH)
    _mean  = np.load(MEAN_PATH)
    _scale = np.load(SCALE_PATH)
    _input_name = _sess.get_inputs()[0].name
    print(f"[API] ONNX model loaded from {ONNX_PATH}")
except Exception as e:
    print(f"[API] ERROR loading ONNX model: {e}")
    _sess = None

# ─── General Phishing Heuristics ──────────────────────────────────────────────

SUSPICIOUS_WORDS = [
    'login', 'verify', 'update', 'secure', 'account', 'banking', 
    'signin', 'recover', 'wallet', 'password', 'credential', 'auth', 'billing'
]
SHORTENERS = {
    'bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'is.gd', 'ow.ly', 
    'rb.gy', 'cutt.ly', 'rebrand.ly', 'bit.do'
}

def check_general_phishing(url: str) -> bool:
    """
    Fallback heuristic engine to catch standard phishing URLs
    that are not homograph attacks.
    """
    url_full = url if url.startswith('http') else 'http://' + url
    try:
        parsed = urlparse(url_full)
        domain = parsed.netloc.lower()
    except Exception:
        return False
        
    domain_no_port = domain.split(':')[0]
    
    # 1. IP address in domain
    if re.match(r'^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)\.){3}(25[0-5]|(2[0-4]|1\d|[1-9]|)\d)$', domain_no_port):
        return True
        
    # 2. URL shorteners
    if domain_no_port in SHORTENERS:
        return True
        
    # 3. Suspicious keyword patterns in domain
    if any(f'-{w}' in domain_no_port or f'{w}-' in domain_no_port for w in SUSPICIOUS_WORDS):
        return True
        
    # 4. Multiple suspicious keywords in URL overall
    full_url_lower = url_full.lower()
    keyword_count = sum(1 for kw in SUSPICIOUS_WORDS if kw in full_url_lower)
    if keyword_count >= 2:
        return True
        
    # 5. Deep subdomain nesting (e.g. login.paypal.com.scam.net)
    if domain_no_port.count('.') >= 4:
        return True
        
    # 6. At symbol (@) used to hide domain
    if '@' in parsed.netloc:
        return True
        
    return False

# ─── Flask App ────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app, origins="*")   # allow extension origins

@app.route('/test')
def test_page():
    here = os.path.dirname(os.path.abspath(__file__))
    return open(os.path.join(here, 'test_page.html'), encoding='utf-8').read(), 200, {'Content-Type': 'text/html'}

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "ok", "model_loaded": _sess is not None})

@app.route('/predict', methods=['POST'])
def predict():
    if _sess is None:
        return jsonify({"error": "Model not loaded"}), 503

    data = request.get_json(force=True)
    urls = data.get('urls', [])
    if not urls:
        return jsonify({"error": "No URLs provided"}), 400

    results = []
    for url in urls:
        try:
            # First, check general phishing heuristics
            if check_general_phishing(url):
                results.append({
                    "url":        url,
                    "label":      "phishing",
                    "confidence": 95.0
                })
                continue
                
            # If heuristics pass, use the ONNX MLP model for homograph detection
            feats = np.array(extract_features(url), dtype=np.float32).reshape(1, -1)
            # manual StandardScaler transform
            feats_scaled = ((feats - _mean) / _scale).astype(np.float32)
            preds = _sess.run(None, {_input_name: feats_scaled})

            # preds[0] is label array, preds[1] is probability dict list
            label_pred = int(preds[0][0])

            try:
                prob_dict = preds[1][0]          # {0: p0, 1: p1}
                confidence = float(prob_dict.get(label_pred, 0.5)) * 100
            except (IndexError, TypeError, AttributeError):
                confidence = 85.0 if label_pred == 1 else 95.0

            results.append({
                "url":        url,
                "label":      "phishing" if label_pred == 1 else "legitimate",
                "confidence": round(confidence, 2)
            })
        except Exception as e:
            results.append({"url": url, "label": "error", "confidence": 0, "error": str(e)})

    return jsonify({"results": results})

if __name__ == '__main__':
    print("=" * 60)
    print("  Homograph Phishing Detection API  —  http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host='127.0.0.1', port=5000, debug=False)
