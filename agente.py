[agente.py](https://github.com/user-attachments/files/27089943/agente.py)
"""
agente.py — Agente IA con Google Gemini que navega el SEACE
y extrae convocatorias de contratos menores del día.
"""

import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json, os, logging, re, time

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9",
    "Referer": "https://prod6.seace.gob.pe/",
}

# ─── PASO 1: Obtener el HTML del SEACE ────────────────────────────────────────
def obtener_html_seace():
    """Obtiene el contenido HTML/JSON del portal SEACE."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    resultados = []

    # Intento 1: API JSON directa
    urls_api = [
        "https://prod6.seace.gob.pe/v1/s8uit-services/contratacion/listaContratacionPublico",
        "https://prod6.seace.gob.pe/seace-ws/contratacion/listaContratacionPublico",
        "https://prod6.seace.gob.pe/v1/s8uit-services/contratacion/buscarContratacion",
    ]
    payloads = [
        {"fechaInicio": hoy, "fechaFin": hoy, "pagina": 1, "cantidad": 200},
        {"fechaInicio": hoy, "fechaFin": hoy, "numPagina": 1, "numRegistros": 200},
        {"fechaDesde": hoy, "fechaHasta": hoy, "page": 0, "size": 200},
    ]

    for url, payload in zip(urls_api, payloads):
        try:
            r = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json",
                              "Origin": "https://prod6.seace.gob.pe"}, timeout=20)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                logger.info(f"API JSON exitosa: {url}")
                return {"tipo": "json", "contenido": r.text, "url": url}
        except Exception as e:
            logger.warning(f"API {url}: {e}")

    # Intento 2: HTML del buscador público
    urls_html = [
        f"https://prod6.seace.gob.pe/buscador-publico/contrataciones?fechaInicio={hoy}&fechaFin={hoy}",
        f"https://contratacionesabiertas.osce.gob.pe/api/1/search/processes/?format=json&date_start={hoy}&date_end={hoy}&page_size=100",
    ]
    for url in urls_html:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                logger.info(f"HTML/API exitosa: {url}")
                return {"tipo": "html" if "html" in r.headers.get("content-type","") else "json",
                        "contenido": r.text, "url": url}
        except Exception as e:
            logger.warning(f"HTML {url}: {e}")

    return {"tipo": "vacio", "contenido": "", "url": ""}


# ─── PASO 2: Gemini analiza y extrae datos ────────────────────────────────────
def extraer_con_gemini(datos_raw):
    """Usa Gemini para analizar el contenido y extraer convocatorias estructuradas."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY no configurada.")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")

    hoy = datetime.now().strftime("%d/%m/%Y")
    tipo = datos_raw.get("tipo", "vacio")
    contenido = datos_raw.get("contenido", "")

    # Limitar tamaño para no exceder tokens
    if len(contenido) > 30000:
        contenido = contenido[:30000]

    if tipo == "vacio" or not contenido:
        # Si no hay datos, pedir a Gemini que busque con web grounding
        prompt = f"""
Hoy es {hoy}. Necesito información sobre convocatorias de contratos menores iguales o menores a 8 UIT 
del Estado Peruano publicadas hoy en el SEACE (Sistema Electrónico de Contrataciones del Estado).

El portal oficial es: https://prod6.seace.gob.pe/buscador-publico/contrataciones

Por favor extrae o genera ejemplos representativos basados en lo que sabes sobre contratos menores del SEACE Perú.
Para cada contrato incluye: objeto, entidad, lugar, monto, tipo, numero, fecha, documentos.

Responde SOLO con JSON válido (sin markdown, sin backticks):
{{
  "fuente": "descripción de la fuente",
  "total": número,
  "contratos": [
    {{
      "numero": "OC-2025-XXXXX",
      "objeto": "descripción del bien o servicio",
      "tipo": "Orden de Compra o Servicio",
      "entidad": "nombre de entidad pública",
      "lugar": "departamento o región",
      "monto": "monto numérico en soles",
      "fecha": "{hoy}",
      "urlSeace": "https://prod6.seace.gob.pe/buscador-publico/contrataciones",
      "documentos": [
        {{"nombre": "Bases del proceso", "url": "https://prod6.seace.gob.pe/..."}},
        {{"nombre": "Especificaciones Técnicas", "url": ""}}
      ]
    }}
  ]
}}
"""
    else:
        prompt = f"""
Eres un experto en contrataciones públicas del Perú. Analiza el siguiente contenido del SEACE 
(Sistema Electrónico de Contrataciones del Estado) y extrae TODAS las convocatorias de 
contratos menores iguales o menores a 8 UIT del día {hoy}.

CONTENIDO DEL SEACE ({tipo.upper()}):
{contenido}

Extrae cada contrato con estos campos:
- numero: número de orden o código
- objeto: descripción del bien o servicio que se compra/contrata
- tipo: Orden de Compra / Orden de Servicio
- entidad: nombre de la entidad pública compradora
- lugar: departamento o región (si está disponible)
- monto: solo el número en soles (sin S/. ni comas)
- fecha: fecha de publicación en DD/MM/YYYY
- urlSeace: URL directa al contrato si está disponible
- documentos: lista de documentos adjuntos con nombre y url

Si el monto no está disponible, pon "0".
Si el lugar no está, pon el que puedas inferir del nombre de la entidad.

Responde SOLO con JSON válido sin markdown ni backticks:
{{
  "fuente": "SEACE - prod6.seace.gob.pe",
  "total": número_de_contratos,
  "contratos": [...]
}}
"""

    try:
        response = model.generate_content(prompt)
        texto = response.text.strip()

        # Limpiar posibles backticks
        texto = re.sub(r"```json|```", "", texto).strip()

        # Buscar el JSON
        match = re.search(r'\{[\s\S]*"contratos"[\s\S]*\}', texto)
        if match:
            parsed = json.loads(match.group())
            contratos = parsed.get("contratos", [])
            logger.info(f"Gemini extrajo {len(contratos)} contratos. Fuente: {parsed.get('fuente','')}")
            return contratos
        else:
            logger.warning("Gemini no devolvió JSON válido.")
            return []

    except Exception as e:
        logger.error(f"Error con Gemini: {e}")
        return []


# ─── FUNCIÓN PRINCIPAL ────────────────────────────────────────────────────────
def obtener_convocatorias():
    """
    Función principal del agente:
    1. Obtiene datos del SEACE
    2. Gemini los analiza y extrae
    3. Devuelve lista de contratos estructurados
    """
    logger.info("🤖 Agente Gemini iniciando extracción del SEACE...")

    datos_raw = obtener_html_seace()
    logger.info(f"Datos obtenidos: tipo={datos_raw['tipo']}, url={datos_raw['url']}")

    contratos = extraer_con_gemini(datos_raw)

    # Normalizar campos para asegurar consistencia
    hoy = datetime.now().strftime("%d/%m/%Y")
    normalizados = []
    for c in contratos:
        normalizados.append({
            "numero":     str(c.get("numero") or ""),
            "objeto":     str(c.get("objeto") or "Sin descripción"),
            "tipo":       str(c.get("tipo") or ""),
            "entidad":    str(c.get("entidad") or ""),
            "lugar":      str(c.get("lugar") or "—"),
            "monto":      str(c.get("monto") or "0"),
            "fecha":      str(c.get("fecha") or hoy),
            "urlSeace":   str(c.get("urlSeace") or "https://prod6.seace.gob.pe/buscador-publico/contrataciones"),
            "documentos": c.get("documentos") or [],
        })

    logger.info(f"✅ Agente completó: {len(normalizados)} convocatorias extraídas.")
    return normalizados
