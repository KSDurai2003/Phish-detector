import sys
sys.stdout.reconfigure(encoding='utf-8')
import urllib.parse, math, unicodedata, urllib.request, json
from collections import Counter

API = 'http://127.0.0.1:5000'

def post(urls):
    data = json.dumps({'urls': urls}).encode()
    req  = urllib.request.Request(
        f'{API}/predict', data=data,
        headers={'Content-Type': 'application/json'}, method='POST'
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

VOWELS    = set('aeiouAEIOU')
CONSONANTS = set('bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ')

def char_entropy(s):
    if not s: return 0.0
    c = Counter(s); t = len(s)
    return -sum((v/t)*math.log2(v/t) for v in c.values())

def get_us(ch):
    try:
        name = unicodedata.name(ch, '')
        return name.split()[0] if name else 'UNK'
    except:
        return 'UNK'

def extract_and_show(url):
    url = str(url)
    uf = url if url.startswith('http') else 'http://' + url
    parsed = urllib.parse.urlparse(uf)
    d = parsed.netloc or url
    path = parsed.path or ''
    full = d + path
    tot  = max(len(full), 1)
    parts = d.split('.')
    scripts = {get_us(ch) for ch in d if ord(ch) > 127}
    letters = [c for c in d if c.isalpha()]
    vn = sum(c in VOWELS for c in letters)
    cn = sum(c in CONSONANTS for c in letters)
    mc = cc = 0
    for c in d:
        if c in CONSONANTS:
            cc += 1; mc = max(mc, cc)
        else:
            cc = 0

    has_pn = int('xn--' in d.lower())
    uni_frac = sum(ord(c) > 127 for c in full) / tot

    print(f"  URL    : {url}")
    print(f"  domain : {d}")
    print(f"  has_punycode={has_pn}  subdomain_depth={max(len(parts)-2,0)}")
    print(f"  entropy={char_entropy(d):.2f}  unicode_fraction={uni_frac:.3f}")
    print(f"  unicode_scripts={scripts}")
    print()

print("=== Feature Diagnosis for False Negatives ===\n")
urls = [
    'http://xn--googIe-5f7c.com',
    'http://xn--80aaacpohgfo.xn--p1ai',
]
for u in urls:
    extract_and_show(u)

# Verify via API
res = post(urls)
for r in res['results']:
    print(f"  API result: {r['label']}  ({r['confidence']:.1f}%)  {r['url']}")
