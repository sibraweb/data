"""UOCRA 76/75, tercer tramo: sep / oct / nov 2026 (Zona A).

Acuerdo del 21/09/2026 (sep +1,9 %, oct +1,8 %, nov +1,7 %, acumulativos),
HOMOLOGADO por disposición del 29/09/2026 (EX-2026-92531010-APN-CGDTEYS#MCH).
Valores transcriptos del Anexo I del acuerdo:
  https://www.uocra.org/pdf/f03639_acuerdo_76.75y577.10-21.09.2026.pdf
  https://www.uocra.org/pdf/8d5ddc_Homologacion_76.75y577.10-%2029.09.2026.pdf

⚠ NOVIEMBRE NO SE CARGA ANTES DEL 1/11. `presuapp_actualizar_mano_de_obra`
toma el `max(fecha)` de UOCRA: con noviembre adentro, el catálogo de
PresuApp cobraría la hora de noviembre en pleno octubre. Correr con `--nov`
a partir del 1/11/2026.
"""
import datetime as _dt
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
import db  # noqa: E402

MESES = {
    "2026-09-01": {"OFICIAL_ESPECIALIZADO": 7561, "OFICIAL": 6468,
                   "MEDIO_OFICIAL": 5977, "AYUDANTE": 5502, "SERENO": 999495},
    "2026-10-01": {"OFICIAL_ESPECIALIZADO": 7697, "OFICIAL": 6585,
                   "MEDIO_OFICIAL": 6085, "AYUDANTE": 5601, "SERENO": 1017485},
    "2026-11-01": {"OFICIAL_ESPECIALIZADO": 7828, "OFICIAL": 6697,
                   "MEDIO_OFICIAL": 6188, "AYUDANTE": 5696, "SERENO": 1034783},
}

if __name__ == "__main__":
    hoy = _dt.date.today().isoformat()
    for fecha, valores in MESES.items():
        if fecha > hoy and "--nov" not in sys.argv:
            print(f"UOCRA {fecha}: todavía no rige, no se carga (usar --nov desde el 1/11)")
            continue
        print(f"UOCRA {fecha}: {db.upsert_valores_ancha('UOCRA', fecha, valores)} nuevas")
