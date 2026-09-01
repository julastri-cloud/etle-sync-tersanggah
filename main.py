import os
import json
import time
import atexit
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
import requests


# ============================================================
# KONFIGURASI ETLE TERSANGGAH
# ============================================================

URL_LOGIN = "https://etilang-djpd.kemenhub.go.id:9000/main/"

URL_TERSANGGAH = (
    "https://etilang-djpd.kemenhub.go.id:9000/"
    "admin-etle/terkonfirmasi.php"
)

API_URL = (
    "https://etilang-djpd.kemenhub.go.id:9000"
    "/etle/admin-etle/list_terkonfirmasi.php"
)

EMAIL_ETLE = os.environ.get("EMAIL_ETLE", "")
PASSWORD_ETLE = os.environ.get("PASSWORD_ETLE", "")
GCP_SA_KEY = os.environ.get("GCP_SA_KEY", "")
WA_TARGET = os.environ.get("WA_TARGET", "")
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN", "")

# ============================================================
# GOOGLE SHEET & TANGGAL DINAMIS
# ============================================================

SPREADSHEET_ID = "1oOFiSkYQ6v05WhZgkgvhlJsX0ApUuQvDlqO5Yzb47AI"
SHEET_NAME = "Pelanggaran Tersanggah"

WIB = ZoneInfo("Asia/Jakarta")

# ============================================================
# RENTANG TANGGAL PENARIKAN DATA
# ============================================================

now_wib = datetime.now(WIB)

# Mulai selalu dari 1 Agustus 2026
DATE_FROM = "01-08-2026 00:00"

# Sampai tanggal hari ini
DATE_TO = now_wib.strftime("%d-%m-%Y 23:59")
CREDENTIALS_FILE = "temp_credentials.json"
MAX_RETRY = 3

HEADERS = [
    "KODE",
    "TANGGAL PELANGGARAN",
    "LOKASI PELANGGARAN",
    "TNKB",
    "WARNA KENDARAAN",
    "STATUS",
    "PELANGGARAN",
    "TANGGAL KONFIRMASI",
    "LAST SYNC"
]


# ============================================================
# HELPER & CLEANUP
# ============================================================

def log(message):
    print(
        f"[{datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')}] {message}",
        flush=True
    )

def clean(value):
    return str(value).strip() if value is not None else ""

def cleanup_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        try:
            os.remove(CREDENTIALS_FILE)
            log("File temporary credentials berhasil dihapus.")
        except Exception as e:
            log(f"Gagal menghapus temp credentials: {e}")

atexit.register(cleanup_credentials)


# ============================================================
# VALIDASI & SETUP CREDENTIALS
# ============================================================

def validate_environment():
    if not EMAIL_ETLE or not PASSWORD_ETLE or not GCP_SA_KEY:
        raise RuntimeError(
            "Secret EMAIL_ETLE, PASSWORD_ETLE, atau GCP_SA_KEY belum diset."
        )
    
    if not WA_TARGET or not FONNTE_TOKEN:
        log("PERINGATAN: WA_TARGET/FONNTE_TOKEN kosong - notifikasi WA dilewati.")
    
    log("Environment berhasil divalidasi.")

def create_credentials_file():
    try:
        sa_dict = json.loads(GCP_SA_KEY)
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as file:
            json.dump(sa_dict, file)
        log("File credentials sementara berhasil dibuat.")
    except json.JSONDecodeError:
        raise RuntimeError("Secret GCP_SA_KEY bukan format JSON yang valid.")
    except Exception as error:
        raise RuntimeError(f"Gagal membuat file credentials: {error}")


# ============================================================
# GOOGLE SHEET SERVICE
# ============================================================

def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    log("Otentikasi Google Sheets...")
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    
    log("Membuka spreadsheet...")
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
        log(f"Worksheet '{SHEET_NAME}' ditemukan.")
    except gspread.WorksheetNotFound:
        log(f"Worksheet '{SHEET_NAME}' belum ada. Membuat worksheet baru...")
        sheet = spreadsheet.add_worksheet(
            title=SHEET_NAME,
            rows=1000,
            cols=len(HEADERS)
        )
        log("Worksheet baru berhasil dibuat.")
        
    return sheet


# ============================================================
# ETLE AUTOMATION (PLAYWRIGHT)
# ============================================================

def login(page):
    log("Membuka halaman login ETLE...")
    page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
    
    email_input = page.locator('input[placeholder="Email"]')
    password_input = page.locator('input[placeholder="Password"]')
    
    email_input.wait_for(state="visible", timeout=30000)
    password_input.wait_for(state="visible", timeout=30000)
    
    email_input.fill(EMAIL_ETLE)
    password_input.fill(PASSWORD_ETLE)
    
    log("Menekan tombol Login...")
    page.locator('button:has-text("Login")').click()
    
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        log("Networkidle timeout, melanjutkan proses...")
    
    page.wait_for_timeout(2000)
    log(f"Login selesai. URL aktif: {page.url}")

def open_tersanggah_page(page):
    log("Membuka halaman Pelanggaran Tersanggah...")
    page.goto(URL_TERSANGGAH, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

def request_api(page):
    timestamp = int(time.time() * 1000)
    
    api_url = (
        f"{API_URL}"
        f"?dateFrom={requests.utils.quote(DATE_FROM)}"
        f"&dateTo={requests.utils.quote(DATE_TO)}"
        f"&status=Tersanggah"
        f"&_={timestamp}"
    )
    
    log(f"Fetching API: {api_url}")
    
    result = page.evaluate("""
        async (url) => {
            try {
                const response = await fetch(url, {
                    method: "GET",
                    credentials: "include",
                    cache: "no-store",
                    headers: {
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest"
                    }
                });
                const text = await response.text();
                return {
                    success: true,
                    status: response.status,
                    contentType: response.headers.get("content-type") || "",
                    body: text
                };
            } catch (error) {
                return { success: false, status: 0, error: String(error) };
            }
        }
    """, api_url)

    if not result["success"]:
        raise RuntimeError(f"Fetch API gagal: {result.get('error')}")

    if result["status"] != 200 or not result["body"].strip():
        raise RuntimeError(
            f"API HTTP {result['status']}. Body: {result['body'][:300]}"
        )

    parsed = json.loads(result["body"])
    
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ["data", "rows", "result", "aaData"]:
            if isinstance(parsed.get(key), list):
                return parsed[key]
                
    raise RuntimeError("Struktur JSON API tidak valid.")

def get_api_data():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        try:
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            
            login(page)
            open_tersanggah_page(page)
            
            for attempt in range(1, MAX_RETRY + 1):
                try:
                    log(f"Percobaan ambil API ({attempt}/{MAX_RETRY})...")
                    return request_api(page)
                except Exception as error:
                    log(f"Gagal mengambil data API: {error}")
                    if attempt < MAX_RETRY:
                        time.sleep(attempt * 3)
            raise RuntimeError("Exceeded maximum retries for API retrieval.")
        finally:
            browser.close()
            log("Browser ditutup.")


# ============================================================
# CONVERT DATA & SYNC
# ============================================================

def convert_item(item):
    return [
        clean(item.get("kode") or item.get("ref_number")),
        clean(item.get("tgl_pelanggaran") or item.get("inserted_date_vl")),
        clean(item.get("lokasi")),
        clean(item.get("plat_number") or item.get("tnkb")),
        clean(item.get("warna_kendaraan") or item.get("color")),
        clean(item.get("status")),
        clean(item.get("report_type") or item.get("pelanggaran")),
        clean(item.get("tgl_konfirmasi") or item.get("confirm_date")),
        datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")
    ]

def prepare_sheet(sheet):
    values = sheet.get_all_values()
    if not values or values[0] != HEADERS:
        sheet.update(range_name="A1", values=[HEADERS])
        return [HEADERS]
    return values

def kirim_notifikasi_wa(new_rows):
    if not WA_TARGET or not FONNTE_TOKEN:
        return

    jumlah = len(new_rows)
    contoh_kode = [row[0] for row in new_rows[:5] if row and row[0]]
    daftar_kode = "\n".join(f"- {kode}" for kode in contoh_kode)
    
    if jumlah > len(contoh_kode):
        daftar_kode += f"\n- ...dan {jumlah - len(contoh_kode)} data lainnya"

    pesan = (
        f"🚨 *NOTIFIKASI PELANGGARAN TERSANGGAH* 🚨\n\n"
        f"Halo Pak/Bu,\n"
        f"Ada *{jumlah} data pelanggaran tersanggah baru* tersinkronisasi ke Google Sheet.\n\n"
        f"{daftar_kode}\n\n"
        f"_Pesan otomatis dari Sistem Sync ETLE_"
    )

    try:
        response = requests.post(
            "https://api.fonnte.com/send",
            headers={"Authorization": FONNTE_TOKEN},
            data={"target": WA_TARGET, "message": pesan, "countryCode": "62"},
            timeout=15,
        )
        log(f"Respon Notifikasi WA: {response.json()}")
    except Exception as error:
        log(f"[ERROR WA FONNTE] {error}")

def sync_data(data):
    sheet = get_sheet()
    existing = prepare_sheet(sheet)
    existing_keys = {clean(row[0]) for row in existing[1:] if row and clean(row[0])}

    new_rows = []
    api_keys = set()

    for item in data:
        if not isinstance(item, dict):
            continue
            
        kode = clean(item.get("kode") or item.get("ref_number"))
        if not kode or kode in api_keys or kode in existing_keys:
            continue
        
        api_keys.add(kode)
        new_rows.append(convert_item(item))

    if not new_rows:
        log("Tidak ada data baru untuk ditulis.")
        return 0

    start_row = len(existing) + 1
    end_row = start_row + len(new_rows) - 1
    range_name = f"A{start_row}:I{end_row}"

    log(f"Menulis {len(new_rows)} baris baru ke range {range_name}...")
    sheet.update(range_name=range_name, values=new_rows)
    
    kirim_notifikasi_wa(new_rows)
    return len(new_rows)


# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    log("==================================================")
    log("STARTING ETLE SYNC PELANGGARAN TERSANGGAH")
    log("==================================================")
    log(f"Rentang Tanggal API : {DATE_FROM} s/d {DATE_TO}")
    
    validate_environment()
    create_credentials_file()
    
    data = get_api_data()
    log(f"Total baris didapatkan dari API: {len(data)}")
    
    new_count = sync_data(data)
    log(f"Proses Selesai. Total data baru tersimpan: {new_count}")

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_credentials()
