# SETUP - Indices API

## 1. Instalar dependencias

```bash
cd api
pip install -r ../requirements.txt
```

## 2. credentials.json

Reutilizá el mismo OAuth client que usa Obra (mismo proyecto de Google Cloud,
mismo usuario dueño de todas las Sheets):

```bash
cp ../../sibra-obra-repo/api/credentials.json credentials.json
```

Si preferís uno nuevo: Google Cloud Console → Credenciales → OAuth 2.0 Client ID
→ Aplicación de escritorio → descargar como `api/credentials.json`. Necesita
la Google Sheets API y la Google Drive API activadas.

## 3. Primera corrida — migrar el histórico

```bash
cd api
python migrar_historico.py
```

Esto abre el navegador para autorizar (una sola vez — el token queda en
`api/token.pickle`), crea la Sheet **SIBRATECH_INDICES** y carga el
histórico que ya está en `../../SIBRA-DATA-CORREGIDO/`.

Al final imprime el ID de la Sheet — copialo a `.env` como `INDICES_SHEET_ID`
para no tener que volver a buscarla en cada arranque (`cp ../.env.example ../.env`).

## 4. Levantar el servidor

```bash
python server.py
```

Corre en `http://localhost:8100`. Al arrancar refresca CER/UVA, dólar y RIPTE
una vez, y después sigue el cronograma del scheduler (12hs / 4hs / 7 días).

## 5. Abrir el frontend

Abrir `index.html` en el navegador (el `const API` ya apunta a
`http://localhost:8100`).

## Pendiente

- **UOCRA**: la migración carga el histórico ya guardado a mano, pero todavía
  no hay scraper — falta relevar la fuente de las paritarias.
- **Che Camba / Electropunto**: falta armarles parser en
  `sibra-obra-repo/api/parsers/` (mismo mecanismo que Cerámica Norte/SERINAR/
  Construcciones en Seco) para que aparezcan en la ventana de Materiales.
