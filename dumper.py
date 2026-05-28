import os
import re
import json
import time
import base64
import requests as _requests
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ─── URLS OBJETIVO (máximo 10) ────────────────────────────────────────────────
TARGET_URLS = [
    "https://www.babypips.com/crypto/learn/what-is-on-chain-analysis",
    "https://www.babypips.com/crypto/learn/what-is-net-unrealized-profit-loss-nupl",
    "https://www.babypips.com/crypto/learn/long-short-term-on-chain-cost-basis",
    "https://www.babypips.com/crypto/learn/what-is-soor",
    "https://www.babypips.com/crypto/learn/what-is-mvrv",
    "https://www.babypips.com/crypto/learn/what-is-long-term-mvrv",
    "https://www.babypips.com/crypto/learn/what-is-sth-mvrv",
    "https://www.babypips.com/crypto/learn/what-is-mvrv-z-score",
    "https://www.babypips.com/crypto/learn/what-is-spot-volume",
    "https://www.babypips.com/crypto/learn/what-is-spot-volume-delta",
    "https://www.babypips.com/crypto/learn/what-is-percent-balance-on-exchanges",
    "https://www.babypips.com/crypto/learn/what-is-net-transfer-volume",
]

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Proxy list — one per line, format: http://ip:port  or  socks5://ip:port
# or with credentials: http://user:pass@ip:port
# Leave empty to use your real IP for all URLs.
PROXIES = [
    # "http://1.2.3.4:8080",
    # "socks5://5.6.7.8:1080",
    # "http://user:pass@9.10.11.12:3128",
]

# ─── FILTROS DE IMÁGENES NO DESEADAS ─────────────────────────────────────────
BLOCKED_DOMAINS = {
    "a.pub.network",
    "pagead2.googlesyndication.com",
    "securepubads.g.doubleclick.net",
    "googleads.g.doubleclick.net",
    "ad.doubleclick.net",
    "static.doubleclick.net",
    "tpc.googlesyndication.com",
    "dpm.demdex.net",
    "navvy.media.net",
    "s2s.t13.io",
    "pixel.facebook.com",
    "connect.facebook.net",
    "www.facebook.com",
    "www.google.com",
    "www.google.com.co",
}

BLOCKED_PATH_PATTERNS = [
    "/packs/",
    "/native_ads",
    "/ads/",
    "/pagead/",
    "/privacy_sandbox",
    "/pcs/view",
    "/simgad/",
    "/ga-audiences",
]

# ─── VALIDADOR DE URLs ────────────────────────────────────────────────────────
def is_valid_image_url(url: str) -> bool:
    if not url:
        return False
    if url.startswith("data:"):
        return False
    if url.startswith("blob:"):
        return False
    if len(url) > 2000:
        return False
    if not url.startswith("http"):
        return False

    parsed = urlparse(url)

    if parsed.netloc in BLOCKED_DOMAINS:
        return False

    for pat in BLOCKED_PATH_PATTERNS:
        if pat in parsed.path:
            return False

    return True

# ─── GENERAR CARPETA BASE DESDE LA URL ───────────────────────────────────────
def url_to_output_path(url: str) -> str:
    parsed = urlparse(url)
    path   = parsed.path.strip("/")
    if path:
        folder = os.path.join("scrape_output", parsed.netloc, *path.split("/"))
    else:
        folder = os.path.join("scrape_output", parsed.netloc)
    return folder

# ─── EXTENSIONES POR MIME ─────────────────────────────────────────────────────
EXT_MAP = {
    "image/jpeg"   : ".jpg",
    "image/png"    : ".png",
    "image/gif"    : ".gif",
    "image/webp"   : ".webp",
    "image/svg+xml": ".svg",
    "image/avif"   : ".avif",
}

# ─── PROCESO DE UNA URL ───────────────────────────────────────────────────────
def scrape_url(driver, target_url: str, url_index: int, total_urls: int):
    print(f"\n{'='*70}")
    print(f"[{url_index}/{total_urls}] URL objetivo: {target_url}")
    print(f"{'='*70}")

    output_dir  = url_to_output_path(target_url)
    images_dir  = os.path.join(output_dir, "images")
    html_path   = os.path.join(output_dir, "page.html")
    report_path = os.path.join(output_dir, "images_report.json")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    print(f"[+] Carpeta salida: {output_dir}")

    # ── Navegar ───────────────────────────────────────────────────────────────
    print(f"[+] Navegando...")
    driver.get(target_url)
    time.sleep(3)

    # ── Scroll para disparar lazy-loading ────────────────────────────────────
    total_height = driver.execute_script("return document.body.scrollHeight")
    step         = 400
    pos          = 0
    while pos < total_height:
        pos += step
        driver.execute_script(f"window.scrollTo(0, {pos});")
        time.sleep(0.4)
        total_height = driver.execute_script("return document.body.scrollHeight")
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(2)

    # ── Guardar HTML ──────────────────────────────────────────────────────────
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"[+] HTML guardado → {html_path}")

    # ── Cookies ───────────────────────────────────────────────────────────────
    selenium_cookies = driver.get_cookies()

    # ── Logs de red (captura URL + requestId para CDP) ────────────────────────
    network_image_urls = set()
    request_id_map = {}   # url -> requestId
    try:
        for entry in driver.get_log("performance"):
            msg = json.loads(entry["message"])["message"]
            if msg["method"] == "Network.responseReceived":
                params = msg.get("params", {})
                r = params.get("response", {})
                url_found = r.get("url", "")
                if r.get("mimeType", "").startswith("image/") and is_valid_image_url(url_found):
                    network_image_urls.add(url_found)
                    request_id_map[url_found] = params.get("requestId", "")
    except Exception as e:
        print(f"[!] Logs de red: {e}")

    # ── DOM: todas las imágenes de la página ──────────────────────────────────
    raw_dom_urls = driver.execute_script("""
        const IMG_ATTRS = [
            'src', 'data-src', 'data-lazy-src', 'data-original',
            'data-original-src', 'data-img-src', 'data-lazy',
            'data-url', 'data-image', 'data-bg', 'data-background'
        ];
        const SRCSET_ATTRS = [
            'srcset', 'data-srcset', 'data-lazy-srcset'
        ];

        const EXCLUDE_SELECTORS = [
            'aside', 'nav', 'footer',
            '.advertisement', '[class*="ad-"]', '[id*="ad-"]',
            '[class*="-ad"]', '[class*="sponsor"]', '[class*="promo"]'
        ];

        const excludedNodes = new Set([...document.querySelectorAll(EXCLUDE_SELECTORS.join(','))]);

        function isExcluded(el) {
            let node = el;
            while (node) {
                if (excludedNodes.has(node)) return true;
                node = node.parentElement;
            }
            return false;
        }

        function parseSrcset(srcset) {
            const urls = [];
            for (const part of srcset.split(',')) {
                const u = part.trim().split(/\\s+/)[0];
                if (u) urls.push(u);
            }
            return urls;
        }

        const urls = new Set();

        // <img> con todos los atributos lazy conocidos
        for (const img of document.querySelectorAll('img')) {
            if (isExcluded(img)) continue;
            for (const attr of IMG_ATTRS) {
                const val = img.getAttribute(attr);
                if (val && !val.startsWith('data:')) urls.add(val);
            }
            for (const attr of SRCSET_ATTRS) {
                const val = img.getAttribute(attr);
                if (val) parseSrcset(val).forEach(u => urls.add(u));
            }
            // currentSrc captura la imagen real ya seleccionada por el browser
            if (img.currentSrc && !img.currentSrc.startsWith('data:')) urls.add(img.currentSrc);
        }

        // <picture><source srcset="...">
        for (const source of document.querySelectorAll('picture source')) {
            if (isExcluded(source)) continue;
            for (const attr of SRCSET_ATTRS) {
                const val = source.getAttribute(attr);
                if (val) parseSrcset(val).forEach(u => urls.add(u));
            }
        }

        // CSS background-image en todos los elementos
        for (const el of document.querySelectorAll('*')) {
            if (isExcluded(el)) continue;
            const bg = window.getComputedStyle(el).backgroundImage;
            if (bg && bg !== 'none' && bg.includes('url(')) {
                const matches = bg.matchAll(/url\\(["']?([^"')]+)["']?\\)/g);
                for (const m of matches) urls.add(m[1]);
            }
        }

        return [...urls];
    """) or []

    dom_image_urls = set()
    for u in raw_dom_urls:
        full = urljoin(target_url, u)
        if is_valid_image_url(full):
            dom_image_urls.add(full)

    all_image_urls = network_image_urls | dom_image_urls
    print(f"[+] Imágenes detectadas: {len(all_image_urls)}")

    def download_via_cdp(request_id: str) -> bytes:
        """Retrieve an already-loaded image body from Chrome's network cache via CDP."""
        result = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        body = result.get("body", "")
        if result.get("base64Encoded"):
            return base64.b64decode(body)
        return body.encode("latin-1")

    def download_via_requests(img_url: str) -> bytes:
        """Python-level HTTP GET — not subject to CORS. Uses browser cookies + Referer."""
        cookie_dict = {c["name"]: c["value"] for c in selenium_cookies}
        headers = {
            "User-Agent": USER_AGENT,
            "Referer"   : target_url,
            "Accept"    : "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        resp = _requests.get(img_url, headers=headers, cookies=cookie_dict, timeout=15)
        resp.raise_for_status()
        if len(resp.content) == 0:
            raise Exception("empty response")
        return resp.content

    def download_via_fetch(img_url: str) -> bytes:
        """Fetch an image through the browser JS context (same-origin or CORS-enabled CDNs)."""
        result = driver.execute_async_script("""
            const [url, callback] = arguments;
            fetch(url, {credentials: 'include'})
                .then(r => {
                    if (!r.ok) { callback({ok: false, error: 'HTTP ' + r.status}); return; }
                    return r.arrayBuffer();
                })
                .then(buf => {
                    if (!buf) return;
                    const bytes = new Uint8Array(buf);
                    let binary = '';
                    const chunk = 8192;
                    for (let i = 0; i < bytes.length; i += chunk)
                        binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
                    callback({ok: true, data: btoa(binary)});
                })
                .catch(e => callback({ok: false, error: e.message}));
        """, img_url)
        if not result or not result.get("ok"):
            err_msg = (result.get("error", "fetch failed") if result else "null result")
            raise Exception(f"JS fetch error: {err_msg}")
        return base64.b64decode(result["data"])

    # ── Descargar imágenes ────────────────────────────────────────────────────
    image_log     = []
    target_netloc = urlparse(target_url).netloc

    for idx, img_url in enumerate(sorted(all_image_urls), start=1):
        parsed_img = urlparse(img_url)
        img_server = parsed_img.netloc
        img_path   = parsed_img.path.strip("/")

        if img_server != target_netloc:
            parts      = img_path.split("/")
            img_folder = os.path.join(images_dir, img_server, *parts[:-1]) if len(parts) > 1 else os.path.join(images_dir, img_server)
        else:
            parts      = img_path.split("/")
            img_folder = os.path.join(images_dir, *parts[:-1]) if len(parts) > 1 else images_dir

        record = {
            "index"       : idx,
            "source_url"  : img_url,
            "server"      : img_server,
            "remote_path" : parsed_img.path,
            "local_file"  : None,
            "status"      : None,
            "content_type": None,
            "size_bytes"  : None,
        }

        try:
            os.makedirs(img_folder, exist_ok=True)
        except OSError as e:
            record["status"] = "ERROR"
            record["error"]  = f"Ruta inválida: {e}"
            print(f"  [{idx:03d}] ✗ Ruta inválida, saltando: {img_url}")
            image_log.append(record)
            continue

        try:
            # Primary: CDP getResponseBody (image already in Chrome's cache)
            request_id = request_id_map.get(img_url, "")
            if request_id:
                try:
                    raw = download_via_cdp(request_id)
                except Exception as cdp_err:
                    print(f"  [{idx:03d}] CDP fallback→fetch ({cdp_err})")
                    try:
                        raw = download_via_fetch(img_url)
                    except Exception as fetch_err:
                        print(f"  [{idx:03d}] fetch fallback→requests ({fetch_err})")
                        raw = download_via_requests(img_url)
            else:
                # Image found only in DOM — try JS fetch first, then Python requests
                try:
                    raw = download_via_fetch(img_url)
                except Exception as fetch_err:
                    print(f"  [{idx:03d}] fetch fallback→requests ({fetch_err})")
                    raw = download_via_requests(img_url)

            if len(raw) == 0:
                raise Exception("empty response (possible Cloudflare block)")

            ext           = os.path.splitext(parsed_img.path)[1] or ".img"
            original_name = os.path.basename(parsed_img.path)
            filename      = original_name if (original_name and "." in original_name) else f"img_{idx:04d}{ext}"
            filepath      = os.path.join(img_folder, filename)

            if os.path.exists(filepath):
                name, dot_ext = os.path.splitext(filename)
                filepath = os.path.join(img_folder, f"{name}_{idx:04d}{dot_ext}")

            with open(filepath, "wb") as f:
                f.write(raw)

            record.update({
                "local_file" : filepath,
                "status"     : 200,
                "size_bytes" : len(raw),
            })
            print(f"  [{idx:03d}] ✓ {filename} ({len(raw)//1024} KB) — {img_server}")

        except Exception as e:
            record["status"] = "ERROR"
            record["error"]  = str(e)
            print(f"  [{idx:03d}] ✗ ERROR — {e}")

        image_log.append(record)
        time.sleep(0.3)

    # ── Reporte final de esta URL ─────────────────────────────────────────────
    ok  = [r for r in image_log if r.get("status") == 200]
    err = [r for r in image_log if r not in ok]

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_url": target_url,
            "output_dir" : output_dir,
            "total"      : len(image_log),
            "downloaded" : len(ok),
            "failed"     : len(err),
            "images"     : image_log,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n[✓] URL completada — {len(ok)} descargadas / {len(err)} fallidas")
    print(f"    Reporte → {report_path}")

    return {"url": target_url, "downloaded": len(ok), "failed": len(err)}


# ─── DRIVER FACTORY ───────────────────────────────────────────────────────────
def create_driver(proxy: str | None = None) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    urls = [u.strip() for u in TARGET_URLS if u.strip()]

    if not urls:
        print("[!] No hay URLs en TARGET_URLS. Agrega al menos una.")
        exit(1)

    proxies   = [p.strip() for p in PROXIES if p.strip()]
    use_proxy = bool(proxies)

    print(f"[+] Total de URLs a procesar: {len(urls)}")
    if use_proxy:
        print(f"[+] Proxy rotation activada — {len(proxies)} proxies disponibles")
    else:
        print("[+] Sin proxies configurados — usando IP directa")

    summary = []

    for i, url in enumerate(urls, start=1):
        proxy = proxies[(i - 1) % len(proxies)] if use_proxy else None
        if proxy:
            print(f"\n[~] Proxy para esta URL: {proxy}")

        driver = create_driver(proxy)
        try:
            result = scrape_url(driver, url, i, len(urls))
            summary.append(result)
        finally:
            driver.quit()

    # ── Resumen global ────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"[✓] RESUMEN GLOBAL — {len(urls)} URL(s) procesadas")
    print(f"{'='*70}")
    total_ok  = sum(r["downloaded"] for r in summary)
    total_err = sum(r["failed"]     for r in summary)
    for r in summary:
        status = "✓" if r["failed"] == 0 else "~"
        print(f"  [{status}] {r['downloaded']} desc / {r['failed']} fallidas — {r['url']}")
    print(f"\n  Total descargadas : {total_ok}")
    print(f"  Total fallidas    : {total_err}")
