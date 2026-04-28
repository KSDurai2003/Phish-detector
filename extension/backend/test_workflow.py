import sys
sys.stdout.reconfigure(encoding='utf-8')
import urllib.request, json, time

API = 'http://127.0.0.1:5000'

def post(urls):
    data = json.dumps({'urls': urls}).encode()
    req  = urllib.request.Request(
        f'{API}/predict', data=data,
        headers={'Content-Type': 'application/json'}, method='POST'
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

PASS = 'PASS'
FAIL = 'FAIL'

print('=' * 62)
print('  Silent Guard Extension — Full Workflow Test Suite')
print('=' * 62)

# ── 1. Ping ──────────────────────────────────────────────────────────────────
with urllib.request.urlopen(f'{API}/ping', timeout=5) as r:
    ping = json.loads(r.read())

status = ping.get('status')
loaded = ping.get('model_loaded')
print(f'\n[1] Ping → status={status}  model_loaded={loaded}')
assert status == 'ok', 'PING FAILED'
print('    PASS - Backend is alive and model is ready')

# ── 2. Legitimate URLs ────────────────────────────────────────────────────────
legit_urls = [
    'https://google.com',
    'https://microsoft.com',
    'https://github.com',
    'https://stackoverflow.com',
    'https://youtube.com',
]
print(f'\n[2] Legitimate URLs  ({len(legit_urls)} URLs)')
res = post(legit_urls)
legit_pass = 0
for r in res['results']:
    mark = PASS if r['label'] == 'legitimate' else FAIL
    if r['label'] == 'legitimate':
        legit_pass += 1
    print(f"    [{mark}]  {r['label']:11}  {r['confidence']:5.1f}%  {r['url']}")

# ── 3. Punycode / Homograph phishing URLs ────────────────────────────────────
phish_urls = [
    'http://xn--e1afmkfd.xn--p1ai',
    'http://xn--googIe-5f7c.com',
    'http://xn--pple-43d.com',
    'https://xn--pypal-4ve.com',
    'http://xn--80aaacpohgfo.xn--p1ai',
]
print(f'\n[3] Punycode / Homograph URLs  ({len(phish_urls)} URLs)')
res = post(phish_urls)
phish_pass = 0
for r in res['results']:
    mark = PASS if r['label'] == 'phishing' else FAIL
    if r['label'] == 'phishing':
        phish_pass += 1
    print(f"    [{mark}]  {r['label']:11}  {r['confidence']:5.1f}%  {r['url']}")

# ── 4. Mixed / edge cases ─────────────────────────────────────────────────────
mixed_urls = [
    'http://secure-login.paypa1.com',
    'https://www.amazon.com/dp/product/1234',
    'http://192.168.1.1/admin',
    'https://normal-company.co.uk',
    'http://totally-legit-bank-login.net',
]
print(f'\n[4] Mixed / Edge Cases  ({len(mixed_urls)} URLs)')
res = post(mixed_urls)
for r in res['results']:
    icon = 'OK  ' if r['label'] == 'legitimate' else 'WARN'
    print(f"    [{icon}]  {r['label']:11}  {r['confidence']:5.1f}%  {r['url']}")

# ── 5. Batch performance (simulate full page link scan) ───────────────────────
all_urls = legit_urls + phish_urls + mixed_urls
t0 = time.time()
res = post(all_urls)
elapsed_ms = (time.time() - t0) * 1000
phishing_found  = [r for r in res['results'] if r['label'] == 'phishing']
legitimate_found = [r for r in res['results'] if r['label'] == 'legitimate']

print(f'\n[5] Batch Scan ({len(all_urls)} URLs)  —  {elapsed_ms:.0f} ms total')
print(f'    Phishing  detected : {len(phishing_found)}/{len(all_urls)}')
print(f'    Legitimate detected: {len(legitimate_found)}/{len(all_urls)}')
print(f'    Avg per URL        : {elapsed_ms / len(all_urls):.1f} ms')

# ── 6. Address-bar simulation ─────────────────────────────────────────────────
print('\n[6] Address-bar URL Simulation (what the extension does on navigation)')
address_bar_urls = [
    'https://google.com',
    'http://xn--e1afmkfd.xn--p1ai',
]
res = post(address_bar_urls)
for r in res['results']:
    if r['label'] == 'phishing':
        print(f"    >> ALERT TRIGGERED  ({r['confidence']:.1f}% confidence)")
        print(f"       URL  : {r['url']}")
        print(f"       Action: Full-page modal overlay shown to user")
    else:
        print(f"    >> OK  ({r['confidence']:.1f}%)  {r['url']}  — no alert")

# ── Summary ───────────────────────────────────────────────────────────────────
print('\n' + '=' * 62)
print(f'  RESULTS SUMMARY')
print(f'  Legitimate correctly identified : {legit_pass}/{len(legit_urls)}')
print(f'  Phishing   correctly detected   : {phish_pass}/{len(phish_urls)}')
print(f'  Batch scan latency             : {elapsed_ms:.0f} ms for {len(all_urls)} URLs')
print('=' * 62)
