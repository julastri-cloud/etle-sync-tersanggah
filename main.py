import os
import json
import time
import atexit
from datetime import datetime, timedelta
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

URL_DETAIL_BASE = (
    "https://etilang-djpd.kemenhub.go.id:9000/"
    "admin-etle/terkonfirmasi_detail.php"
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

# Rentang Tanggal API: Tanggal 1 bulan berjalan s/d Besok Jam 00:00 (Mencakup full 24 jam hari ini)
now_wib = datetime.now(WIB)
DATE_FROM = now_wib.replace(day=1).strftime("%d-%m-%Y 00:00")
DATE_TO = (now_wib + timedelta(days=1)).strftime("%d-%m-%Y 00:00")

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
    "ALASAN DISANGGAH",
    "KETERANGAN SANGGAHAN",
    "PASAL",
    "NAMA PEMILIK",
    "ALAMAT PEMILIK",
    "MERK & MODEL",
    "TGL MASA BERLAKU KIR",
    "NAMA PELANGGAR",
    "NO TELEPON PELANGGAR",
    "NO SIM PELANGGAR",
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

def prepare_sheet(sheet):
    values = sheet.get_all_values()
    if not values or values[0] != HEADERS:
        sheet.update(values=[HEADERS], range_name="A1")
        return [HEADERS]
    return values


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
        page.wait_for_url("**/admin-etle/**", timeout=30000)
    except Exception:
        log("Redirect URL timeout, melanjutkan...")
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

def extract_field(page, label):
    """
    Helper untuk mencari pasangan Key-Value dari teks UI
    """
    try:
        loc = page.locator(f'*:text("{label}") + *')
        if loc.count() > 0:
            return clean(loc.first.inner_text().strip(" :"))
    except Exception:
        pass
    return ""

def get_detail_info(page, item_id):
    """
    Scrape data lengkap dari terkonfirmasi_detail.php?id={item_id}
    """
    if not item_id:
        return {}
        
    url_detail = f"{URL_DETAIL_BASE}?id={item_id}&status_konfirmasi=Tersanggah"
    
    try:
        page.goto(url_detail, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1000)
        
        # Ekstrak seluruh field detail yang tersedia
        alasan = extract_field(page, "Alasan Disanggah")
        keterangan = extract_field(page, "Keterangan Sanggahan")
        pasal = extract_field(page, "Pasal")
        nama_pemilik = extract_field(page, "Nama Pemilik")
        alamat_pemilik = extract_field(page, "Alamat")
        merk = extract_field(page, "Merk")
        model = extract_field(page, "Model")
        tgl_kir = extract_field(page, "Tanggal Masa Berlaku")
        nama_pelanggar = extract_field(page, "Nama")
        no_telp = extract_field(page, "No. Telepon")
        no_sim = extract_field(page, "No. SIM")

        merk_model = f"{merk} {model}".strip()

        return {
            "alasan": alasan,
            "keterangan": keterangan,
            "pasal": pasal,
            "nama_pemilik": nama_pemilik,
            "alamat_pemilik": alamat_pemilik,
            "merk_model": merk_model,
            "tgl_kir": tgl_kir,
            "nama_pelanggar": nama_pelanggar,
            "no_telp": no_telp,
            "no_sim": no_sim
        }
    except Exception as e:
        log(f"[WARNING] Gagal mengambil detail ID {item_id}: {e}")
        return {}


# ============================================================
# CONVERT DATA & SYNC
# ============================================================

def convert_item(item, detail_info=None):
    if detail_info is None:
        detail_info = {}
        
    return [
        clean(item.get("kode") or item.get("ref_number")),
        clean(item.get("tgl_pelanggaran") or item.get("inserted_date_vl")),
        clean(item.get("lokasi")),
        clean(item.get("plat_number") or item.get("tnkb")),
        clean(item.get("warna_kendaraan") or item.get("color")) or "-",
        clean(item.get("status")),
        clean(item.get("report_type") or item.get("pelanggaran")),
        clean(item.get("tgl_konfirmasi") or item.get("confirm_date")),
        clean(detail_info.get("alasan")),
        clean(detail_info.get("keterangan")),
        clean(detail_info.get("pasal")),
        clean(detail_info.get("nama_pemilik")),
        clean(detail_info.get("alamat_pemilik")),
        clean(detail_info.get("merk_model")),
        clean(detail_info.get("tgl_kir")),
        clean(detail_info.get("nama_pelanggar")),
        clean(detail_info.get("no_telp")),
        clean(detail_info.get("no_sim")),
        datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")
    ]

def kirim_notifikasi_wa(new_rows):
    if not WA_TARGET or not FONNTE_TOKEN:
        return

    jumlah = len(new_rows)
    rincian = []
    
    for row in new_rows[:5]:
        kode = row[0]
        tnkb = row[3]
        alasan = row[8] or "Tidak ada alasan"
        rincian.append(f"- *{kode}* ({tnkb})\n  _Alasan:_ {alasan}")
        
    daftar_rincian = "\n".join(rincian)
    
    if jumlah > 5:
        daftar_rincian += f"\n\n...dan {jumlah - 5} data pelanggaran lainnya."

    pesan = (
        f"🚨 *NOTIFIKASI PELANGGARAN TERSANGGAH* 🚨\n\n"
        f"Halo Pak/Bu,\n"
        f"Ada *{jumlah} data pelanggaran tersanggah baru* yang tersinkronisasi ke Google Sheet:\n\n"
        f"{daftar_rincian}\n\n"
        f"_Pesan otomatis dari Sistem Sync ETLE HUB_"
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


# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    log("==================================================")
    log("STARTING ETLE SYNC PELANGGARAN TERSANGGAH (FULL DETAIL)")
    log("==================================================")
    log(f"Rentang Tanggal API : {DATE_FROM} s/d {DATE_TO}")
    
    validate_environment()
    create_credentials_file()
    
    # Ambil sheet & daftar KODE yang sudah ada
    sheet = get_sheet()
    existing = prepare_sheet(sheet)
    existing_keys = {clean(row[0]) for row in existing[1:] if row and clean(row[0])}

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
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # 1. Login & Request Data List dari API
            login(page)
            open_tersanggah_page(page)
            
            api_data = []
            for attempt in range(1, MAX_RETRY + 1):
                try:
                    log(f"Percobaan ambil API list ({attempt}/{MAX_RETRY})...")
                    api_data = request_api(page)
                    break
                except Exception as error:
                    log(f"Gagal mengambil data API list: {error}")
                    if attempt < MAX_RETRY:
                        time.sleep(attempt * 3)
            
            log(f"Total baris didapatkan dari API: {len(api_data)}")

            # 2. Filter Data Baru & Pull Halaman Detail
            new_rows = []
            api_keys = set()

            for item in api_data:
                if not isinstance(item, dict):
                    continue
                    
                kode = clean(item.get("kode") or item.get("ref_number"))
                item_id = clean(item.get("id") or item.get("id_pelanggaran"))
                
                # Biarkan jika KODE kosong atau sudah pernah disimpan
                if not kode or kode in api_keys or kode in existing_keys:
                    continue
                
                api_keys.add(kode)
                
                # Fetch halaman detail
                log(f"Mengambil detail lengkap KODE: {kode} (ID: {item_id})...")
                detail_info = get_detail_info(page, item_id)
                
                row = convert_item(item, detail_info)
                new_rows.append(row)

            # 3. Tulis Ke Google Sheet & Kirim WhatsApp
            if not new_rows:
                log("Tidak ada data baru untuk ditulis.")
            else:
                log(f"Menulis {len(new_rows)} baris baru ke Google Sheet...")
                sheet.append_rows(new_rows, value_input_option="USER_ENTERED")
                log("Berhasil memperbarui Google Sheet.")
                
                kirim_notifikasi_wa(new_rows)
                
            log(f"Proses Selesai. Total data baru tersimpan: {len(new_rows)}")

        finally:
            browser.close()
            log("Browser ditutup.")

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_credentials()
