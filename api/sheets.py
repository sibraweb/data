"""
Acceso a Google Sheets para el módulo indices.

Mismo patrón que sibra-obra-repo/api/server.py: OAuth desktop
(credentials.json + token.pickle) + caché en memoria TTL 90s.
"""

import os
import pickle
import time
from pathlib import Path

import gspread
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

SHEET_NAME = "SIBRATECH_INDICES"

# Sheet SEPARADA de la interna (SIBRATECH_INDICES) — esta se comparte
# "Cualquiera con el link: Lector" y solo recibe valores planos ya
# calculados (nunca fórmulas ni datos crudos), para que la página pública
# (sibratech.com.ar) la lea directo sin exponer el backend interno ni las
# hojas de trabajo. Mismo patrón de seguridad ya usado en Obra (ver memoria
# project_cotizaciones_publicas_pagina).
PUBLIC_SHEET_NAME = "SIBRATECH_PUBLICO"

BASE_DIR = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.pickle"
CREDS_FILE = BASE_DIR / "credentials.json"

INDICES_SHEET_ID = os.environ.get("INDICES_SHEET_ID", "")
PUBLIC_SHEET_ID = os.environ.get("PUBLIC_SHEET_ID", "")
OBRA_PRECIOS_SHEET_ID = os.environ.get(
    "OBRA_PRECIOS_SHEET_ID", "1qm3pZ546OGUWT-xiBzZHv_dM5aVvw-rjC3wmSWR7_84"
)

_CACHE: dict = {}
_CACHE_TTL = 90  # segundos


def _cache_get(key: str):
    e = _CACHE.get(key)
    if e and (time.time() - e[1]) < _CACHE_TTL:
        return e[0]
    return None


def _cache_set(key: str, data):
    _CACHE[key] = (data, time.time())


def cache_bust(*prefixes: str):
    for k in list(_CACHE.keys()):
        if any(k.startswith(p) for p in prefixes):
            del _CACHE[k]


def get_credentials():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                raise RuntimeError(
                    "Falta api/credentials.json — descargar el OAuth client "
                    "desktop de Google Cloud Console (mismo proyecto que Obra)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return creds


def get_client() -> gspread.Client:
    return gspread.authorize(get_credentials())


def ensure_indices_sheet() -> str:
    """Busca la Sheet 'SIBRATECH_INDICES' (creada por esta app); la crea si no existe.
    Devuelve el ID — guardalo en .env como INDICES_SHEET_ID para no tener que
    buscarla de nuevo en cada arranque."""
    global INDICES_SHEET_ID
    if INDICES_SHEET_ID:
        return INDICES_SHEET_ID

    creds = get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    resp = drive_svc.files().list(
        q=f"name='{SHEET_NAME}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
        fields="files(id,name)",
        pageSize=5,
    ).execute()
    files = resp.get("files", [])
    if files:
        INDICES_SHEET_ID = files[0]["id"]
        return INDICES_SHEET_ID

    meta = {"name": SHEET_NAME, "mimeType": "application/vnd.google-apps.spreadsheet"}
    file = drive_svc.files().create(body=meta, fields="id").execute()
    INDICES_SHEET_ID = file["id"]
    print(f"[sheets] Creada {SHEET_NAME}: https://docs.google.com/spreadsheets/d/{INDICES_SHEET_ID}")
    print(f"[sheets] Guardá INDICES_SHEET_ID={INDICES_SHEET_ID} en .env")
    return INDICES_SHEET_ID


# Estructura de carpetas en My Drive de la cuenta que corre este server,
# para que todo lo público quede ordenado en un solo lugar (no sueltos en
# la raíz de Drive): "REPO de sibratech" / "publicaciones de indices" (acá
# vive SIBRATECH_PUBLICO) y "precio de la OBRA 1 (casa)" (vacía por ahora,
# para cuando exista la base de cotización de la casa tipo).
CARPETA_REPO = "REPO de sibratech"
CARPETA_PUBLICACIONES_INDICES = "publicaciones de indices"
CARPETA_OBRA_1_CASA = "precio de la OBRA 1 (casa)"


def _buscar_o_crear_carpeta(drive_svc, nombre: str, parent_id: str | None = None) -> str:
    q = f"name='{nombre}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    resp = drive_svc.files().list(q=q, fields="files(id,name)", pageSize=5).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]

    meta = {"name": nombre, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    carpeta = drive_svc.files().create(body=meta, fields="id").execute()
    print(f"[sheets] Creada carpeta '{nombre}'" + (f" dentro de la carpeta padre" if parent_id else " en My Drive"))
    return carpeta["id"]


def ensure_carpeta_publicaciones_indices(drive_svc) -> str:
    """Asegura la estructura REPO de sibratech / publicaciones de indices +
    / precio de la OBRA 1 (casa) (esta última se crea vacía, para más
    adelante). Devuelve el ID de la carpeta "publicaciones de indices"."""
    repo_id = _buscar_o_crear_carpeta(drive_svc, CARPETA_REPO)
    carpeta_indices_id = _buscar_o_crear_carpeta(drive_svc, CARPETA_PUBLICACIONES_INDICES, repo_id)
    _buscar_o_crear_carpeta(drive_svc, CARPETA_OBRA_1_CASA, repo_id)
    return carpeta_indices_id


def _mover_a_carpeta(drive_svc, file_id: str, carpeta_id: str, nombre_archivo: str):
    file = drive_svc.files().get(fileId=file_id, fields="parents").execute()
    parents_actuales = file.get("parents", [])
    if carpeta_id in parents_actuales:
        return
    drive_svc.files().update(
        fileId=file_id,
        addParents=carpeta_id,
        removeParents=",".join(parents_actuales) if parents_actuales else None,
        fields="id, parents",
    ).execute()
    print(f"[sheets] {nombre_archivo} movida a la carpeta '{CARPETA_PUBLICACIONES_INDICES}'")


def ensure_public_sheet() -> str:
    """Busca la Sheet pública 'SIBRATECH_PUBLICO'; la crea si no existe,
    la ubica dentro de 'REPO de sibratech/publicaciones de indices' en My
    Drive, y le confirma el permiso "cualquiera con el link: lector"
    (idempotente en los tres casos). Devuelve el ID — guardalo en .env como
    PUBLIC_SHEET_ID para no tener que buscarla en cada arranque."""
    global PUBLIC_SHEET_ID
    creds = get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    carpeta_id = ensure_carpeta_publicaciones_indices(drive_svc)

    if not PUBLIC_SHEET_ID:
        resp = drive_svc.files().list(
            q=f"name='{PUBLIC_SHEET_NAME}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            fields="files(id,name)",
            pageSize=5,
        ).execute()
        files = resp.get("files", [])
        if files:
            PUBLIC_SHEET_ID = files[0]["id"]
        else:
            meta = {"name": PUBLIC_SHEET_NAME, "mimeType": "application/vnd.google-apps.spreadsheet", "parents": [carpeta_id]}
            file = drive_svc.files().create(body=meta, fields="id").execute()
            PUBLIC_SHEET_ID = file["id"]
            print(f"[sheets] Creada {PUBLIC_SHEET_NAME}: https://docs.google.com/spreadsheets/d/{PUBLIC_SHEET_ID}")
            print(f"[sheets] Guardá PUBLIC_SHEET_ID={PUBLIC_SHEET_ID} en .env")

    try:
        _mover_a_carpeta(drive_svc, PUBLIC_SHEET_ID, carpeta_id, PUBLIC_SHEET_NAME)
    except Exception as exc:
        print(f"[sheets] No se pudo confirmar la carpeta de {PUBLIC_SHEET_NAME}: {exc}")

    try:
        permisos = drive_svc.permissions().list(fileId=PUBLIC_SHEET_ID, fields="permissions(type,role)").execute()
        ya_publico = any(p.get("type") == "anyone" for p in permisos.get("permissions", []))
        if not ya_publico:
            drive_svc.permissions().create(
                fileId=PUBLIC_SHEET_ID, body={"type": "anyone", "role": "reader"}, fields="id"
            ).execute()
            print(f"[sheets] {PUBLIC_SHEET_NAME} compartida como pública (lector)")
    except Exception as exc:
        print(f"[sheets] No se pudo confirmar el permiso público de {PUBLIC_SHEET_NAME}: {exc}")

    return PUBLIC_SHEET_ID


def get_or_create_ws(gc: gspread.Client, sheet_id: str, title: str, headers: list[str]):
    wb = gc.open_by_key(sheet_id)
    try:
        ws = wb.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = wb.add_worksheet(title=title, rows=2000, cols=max(len(headers), 2))
        ws.append_row(headers, value_input_option="RAW")
    return ws


def read_records(sheet_id: str, title: str, cache_key: str | None = None) -> list[dict]:
    key = cache_key or f"{sheet_id}:{title}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    gc = get_client()
    wb = gc.open_by_key(sheet_id)
    ws = wb.worksheet(title)
    records = ws.get_all_records()
    _cache_set(key, records)
    return records


def upsert_series(sheet_id: str, title: str, headers: list[str], key_col: str, rows: list[dict]):
    """Inserta filas nuevas por valor único de `key_col` (ej. FECHA); no duplica ni pisa filas existentes."""
    gc = get_client()
    ws = get_or_create_ws(gc, sheet_id, title, headers)
    existing = ws.get_all_records()
    existing_keys = {str(r.get(key_col)) for r in existing}

    nuevas = [r for r in rows if str(r.get(key_col)) not in existing_keys]
    if not nuevas:
        return 0

    filas = [[r.get(h, "") for h in headers] for r in nuevas]
    ws.append_rows(filas, value_input_option="RAW")
    cache_bust(f"{sheet_id}:{title}")
    return len(nuevas)
