import csv
import time
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

MODULE_URL = "https://www.babypips.com/crypto/learn/on-chain-analysis-for-beginners"
OUTPUT_CSV = "lessons.csv"

def create_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

driver = create_driver()
print(f"[+] Cargando: {MODULE_URL}")
driver.get(MODULE_URL)
time.sleep(3)

links = driver.execute_script("""
    const base = 'https://www.babypips.com';
    const seen = new Set();
    const results = [];

    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href');
        if (!href) continue;
        const full = href.startsWith('http') ? href : base + href;

        // Solo links de lecciones del mismo módulo o sección /crypto/learn/
        if (!full.includes('/crypto/learn/')) continue;
        if (full === window.location.href) continue;
        if (seen.has(full)) continue;

        const text = a.textContent.trim();
        seen.add(full);
        results.push({ url: full, title: text });
    }
    return results;
""")

driver.quit()

if not links:
    print("[!] No se encontraron links de lecciones.")
else:
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "url"])
        writer.writeheader()
        writer.writerows(links)
    print(f"[✓] {len(links)} lecciones guardadas en {OUTPUT_CSV}")
    for i, l in enumerate(links, 1):
        print(f"  {i:02d}. {l['title'][:60]:<60} {l['url']}")
