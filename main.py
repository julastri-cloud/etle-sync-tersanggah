```python
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
# ETLE SYNC PELANGGARAN TERSANGGAH - V2
# ============================================================


# ============================================================
# KONFIGURASI URL ETLE
# ============================================================

URL_LOGIN = (
    "https://etilang-djpd.kemenhub.go.id:9000/main/"
)

URL_TERSANGGAH = (
    "https://etilang-djpd.kemenhub.go.id:9000/"
    "admin-etle/terkonfirmasi.php"
)

API_URL = (
    "https://etilang-djpd.kemenhub.go.id:9000"
    "/etle/admin-etle/list_terkonfirmasi.php"
)


# ============================================================
# GITHUB SECRETS
# ============================================================

EMAIL_ETLE = os.environ.get(
    "EMAIL_ETLE",
    ""
)

PASSWORD_ETLE = os.environ.get(
    "PASSWORD_ETLE",
    ""
)

GCP_SA_KEY = os.environ.get(
    "GCP_SA_KEY",
    ""
)

WA_TARGET = os.environ.get(
    "WA_TARGET",
    ""
)

FONNTE_TOKEN = os.environ.get(
    "FONNTE_TOKEN",
    ""
)


# ============================================================
# GOOGLE SHEETS
# ============================================================

SPREADSHEET_ID = (
    "1oOFiSkYQ6v05WhZgkgvhlJsX0ApUuQvDlqO5Yzb47AI"
)

SHEET_NAME = "Pelanggaran Tersanggah"


# ============================================================
# TIMEZONE
# ============================================================

WIB = ZoneInfo(
    "Asia/Jakarta"
)


# ============================================================
# RENTANG TANGGAL
# ============================================================

now_wib = datetime.now(WIB)

# ============================================================
# MULAI SELALU 1 AGUSTUS 2026
# ============================================================

DATE_FROM = "01-08-2026 00:00"

# ============================================================
# SAMPAI HARI INI 23:59
# ============================================================

DATE_TO = now_wib.strftime(
    "%d-%m-%Y 23:59"
)


# ============================================================
# FILE CREDENTIALS SEMENTARA
# ============================================================

CREDENTIALS_FILE = (
    "temp_credentials.json"
)


# ============================================================
# MAX RETRY API
# ============================================================

MAX_RETRY = 3


# ============================================================
# HEADER GOOGLE SHEETS
# ============================================================

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
# LOGGING
# ============================================================

def log(message):

    timestamp = datetime.now(
        WIB
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(
        f"[{timestamp}] {message}",
        flush=True
    )


# ============================================================
# CLEAN VALUE
# ============================================================

def clean(value):

    if value is None:
        return ""

    return str(value).strip()


# ============================================================
# CLEANUP CREDENTIALS
# ============================================================

def cleanup_credentials():

    if not os.path.exists(
        CREDENTIALS_FILE
    ):
        return

    try:

        os.remove(
            CREDENTIALS_FILE
        )

        log(
            "File temporary credentials "
            "berhasil dihapus."
        )

    except Exception as error:

        log(
            "Gagal menghapus temporary "
            f"credentials: {error}"
        )


atexit.register(
    cleanup_credentials
)


# ============================================================
# VALIDASI ENVIRONMENT
# ============================================================

def validate_environment():

    log(
        "Memvalidasi environment..."
    )

    if not EMAIL_ETLE:

        raise RuntimeError(
            "Secret EMAIL_ETLE belum diset."
        )

    if not PASSWORD_ETLE:

        raise RuntimeError(
            "Secret PASSWORD_ETLE belum diset."
        )

    if not GCP_SA_KEY:

        raise RuntimeError(
            "Secret GCP_SA_KEY belum diset."
        )

    if not WA_TARGET:

        log(
            "PERINGATAN: WA_TARGET kosong."
        )

    if not FONNTE_TOKEN:

        log(
            "PERINGATAN: FONNTE_TOKEN kosong."
        )

    if (
        not WA_TARGET
        or not FONNTE_TOKEN
    ):

        log(
            "Notifikasi WhatsApp "
            "akan dilewati."
        )

    log(
        "Environment berhasil divalidasi."
    )


# ============================================================
# CREATE GOOGLE SERVICE ACCOUNT FILE
# ============================================================

def create_credentials_file():

    log(
        "Membuat temporary credentials..."
    )

    try:

        service_account_data = json.loads(
            GCP_SA_KEY
        )

        with open(
            CREDENTIALS_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                service_account_data,
                file
            )

        log(
            "File credentials sementara "
            "berhasil dibuat."
        )

    except json.JSONDecodeError:

        raise RuntimeError(
            "GCP_SA_KEY bukan JSON yang valid."
        )

    except Exception as error:

        raise RuntimeError(
            "Gagal membuat temporary "
            f"credentials: {error}"
        )


# ============================================================
# GOOGLE SHEETS
# ============================================================

def get_sheet():

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    log(
        "Otentikasi Google Sheets..."
    )

    credentials = (
        Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=scopes
        )
    )

    client = gspread.authorize(
        credentials
    )

    log(
        "Membuka spreadsheet..."
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    try:

        sheet = spreadsheet.worksheet(
            SHEET_NAME
        )

        log(
            f"Worksheet '{SHEET_NAME}' "
            "ditemukan."
        )

    except gspread.WorksheetNotFound:

        log(
            f"Worksheet '{SHEET_NAME}' "
            "belum ada."
        )

        log(
            "Membuat worksheet baru..."
        )

        sheet = spreadsheet.add_worksheet(
            title=SHEET_NAME,
            rows=1000,
            cols=len(HEADERS)
        )

        sheet.update(
            range_name="A1",
            values=[HEADERS]
        )

        log(
            "Worksheet baru berhasil "
            "dibuat."
        )

    return sheet


# ============================================================
# LOGIN ETLE
# ============================================================

def login(page):

    log(
        "Membuka halaman login ETLE..."
    )

    page.goto(
        URL_LOGIN,
        wait_until="domcontentloaded",
        timeout=60000
    )

    email_input = page.locator(
        'input[placeholder="Email"]'
    )

    password_input = page.locator(
        'input[placeholder="Password"]'
    )

    email_input.wait_for(
        state="visible",
        timeout=30000
    )

    password_input.wait_for(
        state="visible",
        timeout=30000
    )

    email_input.fill(
        EMAIL_ETLE
    )

    password_input.fill(
        PASSWORD_ETLE
    )

    log(
        "Menekan tombol Login..."
    )

    page.locator(
        'button:has-text("Login")'
    ).click()

    try:

        page.wait_for_load_state(
            "networkidle",
            timeout=30000
        )

    except Exception:

        log(
            "Networkidle timeout. "
            "Melanjutkan proses..."
        )

    page.wait_for_timeout(
        2000
    )

    log(
        "Login selesai."
    )

    log(
        f"URL aktif: {page.url}"
    )


# ============================================================
# OPEN TERSANGGAH PAGE
# ============================================================

def open_tersanggah_page(page):

    log(
        "Membuka halaman "
        "Pelanggaran Tersanggah..."
    )

    page.goto(
        URL_TERSANGGAH,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        2000
    )

    log(
        "Halaman tersanggah aktif."
    )

    log(
        f"URL aktif: {page.url}"
    )


# ============================================================
# REQUEST API
# ============================================================

def request_api(page):

    timestamp = int(
        time.time() * 1000
    )

    date_from_encoded = (
        requests.utils.quote(
            DATE_FROM
        )
    )

    date_to_encoded = (
        requests.utils.quote(
            DATE_TO
        )
    )

    api_url = (
        f"{API_URL}"
        f"?dateFrom={date_from_encoded}"
        f"&dateTo={date_to_encoded}"
        f"&status=Tersanggah"
        f"&_={timestamp}"
    )

    log(
        "=================================================="
    )

    log(
        "REQUEST API"
    )

    log(
        f"DATE FROM : {DATE_FROM}"
    )

    log(
        f"DATE TO   : {DATE_TO}"
    )

    log(
        f"API URL   : {api_url}"
    )

    log(
        "=================================================="
    )

    # ========================================================
    # PERBAIKAN V2:
    # JavaScript page.evaluate dibuat sederhana
    # agar tidak terjadi SyntaxError.
    # ========================================================

    result = page.evaluate(
        """
        async (url) => {
            const response = await fetch(url, {
                method: "GET",
                credentials: "include",
                cache: "no-store",
                headers: {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest"
                }
            });

            const body = await response.text();

            return {
                status: response.status,
                contentType: response.headers.get("content-type") || "",
                body: body
            };
        }
        """,
        api_url
    )

    status = result.get(
        "status",
        0
    )

    body = result.get(
        "body",
        ""
    )

    content_type = result.get(
        "contentType",
        ""
    )

    # ========================================================
    # VALIDASI HTTP
    # ========================================================

    log(
        f"HTTP Status API: {status}"
    )

    log(
        f"Content-Type API: {content_type}"
    )

    if status != 200:

        raise RuntimeError(
            f"API HTTP {status}. "
            f"Body: {body[:500]}"
        )

    if not body.strip():

        raise RuntimeError(
            "API mengembalikan body kosong."
        )

    # ========================================================
    # PARSE JSON
    # ========================================================

    try:

        parsed = json.loads(
            body
        )

    except json.JSONDecodeError as error:

        log(
            "Response API bukan JSON valid."
        )

        log(
            f"Response awal API: "
            f"{body[:1000]}"
        )

        raise RuntimeError(
            f"JSON decode error: {error}"
        )

    # ========================================================
    # RESPONSE LANGSUNG LIST
    # ========================================================

    if isinstance(
        parsed,
        list
    ):

        log(
            f"API mengembalikan "
            f"{len(parsed)} data."
        )

        return parsed

    # ========================================================
    # RESPONSE OBJECT
    # ========================================================

    if isinstance(
        parsed,
        dict
    ):

        for key in [
            "data",
            "rows",
            "result",
            "aaData"
        ]:

            value = parsed.get(
                key
            )

            if isinstance(
                value,
                list
            ):

                log(
                    f"API mengembalikan "
                    f"{len(value)} data "
                    f"melalui key '{key}'."
                )

                return value

    # ========================================================
    # STRUKTUR JSON TIDAK DIKENALI
    # ========================================================

    raise RuntimeError(
        "Struktur JSON API tidak dikenali. "
        f"Response: {body[:1000]}"
    )


# ============================================================
# GET API DATA
# ============================================================

def get_api_data():

    with sync_playwright() as playwright:

        log(
            "Menjalankan Chromium..."
        )

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

                viewport={
                    "width": 1920,
                    "height": 1080
                }
            )

            page = context.new_page()

            # ------------------------------------------------
            # LOGIN
            # ------------------------------------------------

            login(
                page
            )

            # ------------------------------------------------
            # BUKA HALAMAN
            # ------------------------------------------------

            open_tersanggah_page(
                page
            )

            # ------------------------------------------------
            # RETRY API
            # ------------------------------------------------

            for attempt in range(
                1,
                MAX_RETRY + 1
            ):

                try:

                    log(
                        f"Percobaan mengambil API "
                        f"({attempt}/{MAX_RETRY})..."
                    )

                    data = request_api(
                        page
                    )

                    return data

                except Exception as error:

                    log(
                        f"Gagal mengambil API: "
                        f"{error}"
                    )

                    if attempt < MAX_RETRY:

                        wait_seconds = (
                            attempt * 3
                        )

                        log(
                            f"Menunggu "
                            f"{wait_seconds} detik "
                            "sebelum retry..."
                        )

                        time.sleep(
                            wait_seconds
                        )

            raise RuntimeError(
                "Exceeded maximum retries "
                "for API retrieval."
            )

        finally:

            browser.close()

            log(
                "Browser ditutup."
            )


# ============================================================
# CONVERT API ITEM
# ============================================================

def convert_item(item):

    return [

        # ----------------------------------------------------
        # KODE
        # ----------------------------------------------------

        clean(
            item.get("kode")
            or item.get("ref_number")
        ),

        # ----------------------------------------------------
        # TANGGAL PELANGGARAN
        # ----------------------------------------------------

        clean(
            item.get("tgl_pelanggaran")
            or item.get("inserted_date_vl")
        ),

        # ----------------------------------------------------
        # LOKASI
        # ----------------------------------------------------

        clean(
            item.get("lokasi")
        ),

        # ----------------------------------------------------
        # TNKB
        # ----------------------------------------------------

        clean(
            item.get("plat_number")
            or item.get("tnkb")
        ),

        # ----------------------------------------------------
        # WARNA KENDARAAN
        # ----------------------------------------------------

        clean(
            item.get("warna_kendaraan")
            or item.get("color")
        ),

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        clean(
            item.get("status")
        ),

        # ----------------------------------------------------
        # PELANGGARAN
        # ----------------------------------------------------

        clean(
            item.get("report_type")
            or item.get("pelanggaran")
        ),

        # ----------------------------------------------------
        # TANGGAL KONFIRMASI
        # ----------------------------------------------------

        clean(
            item.get("tgl_konfirmasi")
            or item.get("confirm_date")
        ),

        # ----------------------------------------------------
        # LAST SYNC
        # ----------------------------------------------------

        datetime.now(
            WIB
        ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    ]


# ============================================================
# PREPARE SHEET
# ============================================================

def prepare_sheet(sheet):

    log(
        "Membaca data Google Sheets..."
    )

    values = sheet.get_all_values()

    # ========================================================
    # SHEET KOSONG
    # ========================================================

    if not values:

        log(
            "Sheet kosong."
        )

        log(
            "Membuat header..."
        )

        sheet.update(
            range_name="A1",
            values=[HEADERS]
        )

        return [
            HEADERS
        ]

    # ========================================================
    # HEADER TIDAK SESUAI
    # ========================================================

    if values[0] != HEADERS:

        log(
            "Header Google Sheets "
            "tidak sesuai."
        )

        sheet.update(
            range_name="A1",
            values=[HEADERS]
        )

        values[0] = HEADERS

    return values


# ============================================================
# KIRIM NOTIFIKASI WHATSAPP
# ============================================================

def kirim_notifikasi_wa(
    new_rows
):

    if not WA_TARGET:

        log(
            "WA_TARGET kosong."
        )

        log(
            "Notifikasi WA dilewati."
        )

        return

    if not FONNTE_TOKEN:

        log(
            "FONNTE_TOKEN kosong."
        )

        log(
            "Notifikasi WA dilewati."
        )

        return

    jumlah = len(
        new_rows
    )

    # ========================================================
    # AMBIL KODE MAKSIMAL 5
    # ========================================================

    contoh_kode = [

        row[0]

        for row in new_rows[:5]

        if row
        and row[0]
    ]

    daftar_kode = "\n".join(

        f"- {kode}"

        for kode in contoh_kode
    )

    if jumlah > len(
        contoh_kode
    ):

        daftar_kode += (

            "\n- ...dan "
            f"{jumlah - len(contoh_kode)} "
            "data lainnya"
        )

    # ========================================================
    # PESAN
    # ========================================================

    pesan = (

        "🚨 *NOTIFIKASI "
        "PELANGGARAN TERSANGGAH* 🚨\n\n"

        "Halo Pak/Bu,\n\n"

        f"Ada *{jumlah} data "
        "pelanggaran tersanggah baru* "
        "yang berhasil disinkronisasi "
        "ke Google Sheet.\n\n"

        f"{daftar_kode}\n\n"

        "_Pesan otomatis dari "
        "Sistem Sync ETLE_"
    )

    # ========================================================
    # KIRIM
    # ========================================================

    try:

        log(
            "Mengirim notifikasi "
            "WhatsApp melalui Fonnte..."
        )

        response = requests.post(

            "https://api.fonnte.com/send",

            headers={
                "Authorization":
                    FONNTE_TOKEN
            },

            data={
                "target":
                    WA_TARGET,

                "message":
                    pesan,

                "countryCode":
                    "62"
            },

            timeout=15
        )

        log(
            f"HTTP Fonnte: "
            f"{response.status_code}"
        )

        try:

            response_json = (
                response.json()
            )

            log(
                f"Respon Fonnte: "
                f"{response_json}"
            )

        except Exception:

            log(
                f"Response Fonnte: "
                f"{response.text[:500]}"
            )

    except Exception as error:

        log(
            f"[ERROR WA FONNTE] "
            f"{error}"
        )


# ============================================================
# SYNC DATA
# ============================================================

def sync_data(data):

    log(
        "=================================================="
    )

    log(
        "MEMULAI SINKRONISASI GOOGLE SHEETS"
    )

    log(
        "=================================================="
    )

    sheet = get_sheet()

    existing = prepare_sheet(
        sheet
    )

    # ========================================================
    # KODE YANG SUDAH ADA
    # ========================================================

    existing_keys = {

        clean(row[0])

        for row in existing[1:]

        if row
        and clean(row[0])
    }

    log(
        f"Total KODE yang sudah ada "
        f"di Google Sheet: "
        f"{len(existing_keys)}"
    )

    # ========================================================
    # VARIABEL
    # ========================================================

    new_rows = []

    api_keys = set()

    duplicate_api = 0

    already_exists = 0

    invalid_data = 0

    # ========================================================
    # PROSES DATA API
    # ========================================================

    for item in data:

        if not isinstance(
            item,
            dict
        ):

            invalid_data += 1

            continue

        kode = clean(

            item.get("kode")
            or item.get("ref_number")
        )

        # ----------------------------------------------------
        # KODE KOSONG
        # ----------------------------------------------------

        if not kode:

            invalid_data += 1

            continue

        # ----------------------------------------------------
        # DUPLIKAT DALAM API
        # ----------------------------------------------------

        if kode in api_keys:

            duplicate_api += 1

            continue

        api_keys.add(
            kode
        )

        # ----------------------------------------------------
        # SUDAH ADA DI SHEET
        # ----------------------------------------------------

        if kode in existing_keys:

            already_exists += 1

            continue

        # ----------------------------------------------------
        # DATA BARU
        # ----------------------------------------------------

        new_rows.append(
            convert_item(item)
        )

    # ========================================================
    # LAPORAN
    # ========================================================

    log(
        "=================================================="
    )

    log(
        "HASIL PEMERIKSAAN DATA"
    )

    log(
        f"Total data API       : {len(data)}"
    )

    log(
        f"Data invalid         : {invalid_data}"
    )

    log(
        f"Duplikat dalam API   : {duplicate_api}"
    )

    log(
        f"Sudah ada di Sheet   : {already_exists}"
    )

    log(
        f"DATA BARU            : {len(new_rows)}"
    )

    log(
        "=================================================="
    )

    # ========================================================
    # TIDAK ADA DATA BARU
    # ========================================================

    if not new_rows:

        log(
            "Tidak ada data baru "
            "untuk ditulis."
        )

        return 0

    # ========================================================
    # DAFTAR DATA BARU
    # ========================================================

    log(
        "KODE DATA BARU:"
    )

    for row in new_rows:

        log(
            f"  + {row[0]}"
        )

    # ========================================================
    # RANGE GOOGLE SHEETS
    # ========================================================

    start_row = (
        len(existing) + 1
    )

    end_row = (
        start_row
        + len(new_rows)
        - 1
    )

    range_name = (
        f"A{start_row}:I{end_row}"
    )

    log(
        f"Menulis {len(new_rows)} "
        f"baris ke {range_name}..."
    )

    # ========================================================
    # TULIS DATA
    # ========================================================

    sheet.update(

        range_name=range_name,

        values=new_rows
    )

    log(
        "Google Sheets berhasil "
        "diperbarui."
    )

    # ========================================================
    # NOTIFIKASI WA
    # ========================================================

    kirim_notifikasi_wa(
        new_rows
    )

    return len(
        new_rows
    )


# ============================================================
# MAIN
# ============================================================

def main():

    log(
        "=================================================="
    )

    log(
        "STARTING ETLE SYNC "
        "PELANGGARAN TERSANGGAH V2"
    )

    log(
        "=================================================="
    )

    # ========================================================
    # INFORMASI TANGGAL
    # ========================================================

    log(
        f"Rentang Tanggal API : "
        f"{DATE_FROM} s/d {DATE_TO}"
    )

    log(
        "Tanggal mulai penarikan "
        "ditetapkan: 01-08-2026"
    )

    log(
        "Tanggal akhir otomatis "
        "mengikuti hari eksekusi."
    )

    # ========================================================
    # VALIDASI
    # ========================================================

    validate_environment()

    # ========================================================
    # CREDENTIALS
    # ========================================================

    create_credentials_file()

    # ========================================================
    # AMBIL DATA API
    # ========================================================

    data = get_api_data()

    log(
        f"Total baris didapatkan "
        f"dari API: {len(data)}"
    )

    # ========================================================
    # SYNC
    # ========================================================

    new_count = sync_data(
        data
    )

    # ========================================================
    # SELESAI
    # ========================================================

    log(
        "=================================================="
    )

    log(
        "PROSES SELESAI"
    )

    log(
        f"Total data baru tersimpan: "
        f"{new_count}"
    )

    log(
        "=================================================="
    )


# ============================================================
# EXECUTION
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        log(
            "=================================================="
        )

        log(
            "PROSES GAGAL"
        )

        log(
            f"ERROR: {error}"
        )

        log(
            "=================================================="
        )

        raise

    finally:

        cleanup_credentials()
```
