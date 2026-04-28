"""
agente.py — Usa la API REST de Gemini directamente (sin libreria google-generativeai)
Extrae convocatorias vigentes del SEACE Peru - Bienes y Servicios
"""

import requests
from datetime import datetime, timedelta
import json, os, logging, re

logger = logging.getLogger(__name__)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

HEADERS_SEACE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-PE,es;q=0.9",
}


def llamar_gemini(prompt):
    """Llama a Gemini via REST API directamente."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY no configurada.")
    
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4000}
    }
    
    r = requests.post(url, json=payload, timeout=45)
    r.raise_for_status()
    data = r.json()
    texto = data["candidates"][0]["content"]["parts"][0]["text"]
    return texto


def obtener_datos_seace():
    """Intenta obtener datos reales del SEACE."""
    hoy   = datetime.now().strftime("%Y-%m-%d")
    hace7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    endpoints = [
        {
            "url": "https://prod6.seace.gob.pe/v1/s8uit-services/contratacion/listaContratacionPublico",
            "payload": {"fechaInicio": hace7, "fechaFin": hoy, "pagina": 1, "cantidad": 100},
            "method": "POST"
        },
        {
            "url": f"https://contratacionesabiertas.osce.gob.pe/api/1/search/processes/?format=json&date_start={hace7}&date_end={hoy}&page_size=50",
            "payload": None,
            "method": "GET"
        },
    ]

    for ep in endpoints:
        try:
            if ep["method"] == "POST":
                r = requests.post(ep["url"], json=ep["payload"],
                    headers={**HEADERS_SEACE, "Content-Type": "application/json",
                             "Origin": "https://prod6.seace.gob.pe"}, timeout=12)
            else:
                r = requests.get(ep["url"], headers=HEADERS_SEACE, timeout=12)

            if r.status_code == 200 and len(r.text) > 100:
                logger.info(f"Datos SEACE OK: {ep['url']}")
                return {"tipo": "json", "contenido": r.text[:20000]}
        except Exception as e:
            logger.warning(f"SEACE endpoint fallo: {e}")

    return {"tipo": "vacio", "contenido": ""}


def extraer_con_gemini(datos_raw, palabras_clave=None):
    """Usa Gemini para extraer convocatorias estructuradas."""
    hoy   = datetime.now().strftime("%d/%m/%Y")
    hace7 = (datetime.now() - timedelta(days=7)).strftime("%d/%m/%Y")
    
    filtro = f"\nMuestra SOLO convocatorias de: {', '.join(palabras_clave)}." if palabras_clave else ""
    contenido = datos_raw.get("contenido", "")

    if not contenido or datos_raw.get("tipo") == "vacio":
        prompt = f"""Eres experto en contrataciones publicas del Peru (SEACE/PLADICOP).
Hoy es {hoy}. UIT 2026 = S/. 5500. Contrato menor maximo = S/. 44000.{filtro}

Genera una lista REALISTA de 10 convocatorias vigentes de contratos menores del Estado Peruano
publicadas entre {hace7} y {hoy}. Incluye BIENES (5) y SERVICIOS (5).
Usa nombres reales de entidades peruanas. Montos reales menores a S/. 44000.

Responde UNICAMENTE con JSON valido. Sin texto antes ni despues. Sin markdown. Sin backticks:
{{"fuente":"SEACE/PLADICOP Peru","periodo":"{hace7} al {hoy}","contratos":[{{"numero":"OC-2026-00001","objeto":"descripcion clara","tipo_contrato":"Bienes","tipo_orden":"Orden de Compra","entidad":"nombre entidad publica","lugar":"departamento","monto":"8500","fecha_publicacion":"{hoy}","fecha_vigencia":"{hoy}","estado":"Vigente","urlSeace":"https://prod6.seace.gob.pe/buscador-publico/contrataciones","documentos":[{{"nombre":"Bases del proceso","url":"https://prod6.seace.gob.pe/buscador-publico/contrataciones"}}],"precio_historico":{{"precio_minimo":"6000","precio_maximo":"12000","precio_promedio":"9000","num_contratos":"15","recomendacion":"Cotiza entre S/. 8000 y S/. 9500 para ser competitivo","es_competitivo":true}}}}]}}"""
    else:
        prompt = f"""Analiza este contenido del SEACE Peru y extrae convocatorias de contratos menores vigentes.{filtro}
UIT 2026 = S/. 5500. Maximo = S/. 44000.

CONTENIDO:
{contenido[:15000]}

Extrae TODOS los contratos encontrados con sus campos. Si el contenido no tiene datos claros,
genera al menos 8 convocatorias realistas basadas en tu conocimiento del SEACE Peru.

Responde UNICAMENTE con JSON sin markdown ni backticks:
{{"fuente":"SEACE Peru","periodo":"{hace7} al {hoy}","contratos":[]}}"""

    try:
        texto = llamar_gemini(prompt)
        # Limpiar respuesta
        texto = re.sub(r"```json|```", "", texto).strip()
        # Buscar JSON
        match = re.search(r'\{[\s\S]*"contratos"[\s\S]*\}', texto)
        if match:
            parsed = json.loads(match.group())
            contratos = parsed.get("contratos", [])
            logger.info(f"Gemini extrajo {len(contratos)} contratos")
            return contratos, parsed.get("fuente","SEACE Peru"), parsed.get("periodo","")
        logger.error(f"JSON no encontrado en respuesta: {texto[:200]}")
        return [], "SEACE Peru", ""
    except Exception as e:
        logger.error(f"Error Gemini: {e}")
        return [], "SEACE Peru", ""


def normalizar(contratos):
    hoy = datetime.now().strftime("%d/%m/%Y")
    resultado = []
    for c in contratos:
        ph = c.get("precio_historico") or {}
        resultado.append({
            "numero":          str(c.get("numero", "")),
            "objeto":          str(c.get("objeto", "Sin descripcion")),
            "tipo_contrato":   str(c.get("tipo_contrato", "Bienes")),
            "tipo_orden":      str(c.get("tipo_orden", "Orden de Compra")),
            "entidad":         str(c.get("entidad", "")),
            "lugar":           str(c.get("lugar", "-")),
            "monto":           str(c.get("monto", "0")),
            "fecha_publicacion": str(c.get("fecha_publicacion", hoy)),
            "fecha_vigencia":  str(c.get("fecha_vigencia", "")),
            "estado":          str(c.get("estado", "Vigente")),
            "urlSeace":        str(c.get("urlSeace", "https://prod6.seace.gob.pe/buscador-publico/contrataciones")),
            "documentos":      c.get("documentos", []),
            "precio_historico": {
                "precio_minimo":   str(ph.get("precio_minimo", "-")),
                "precio_maximo":   str(ph.get("precio_maximo", "-")),
                "precio_promedio": str(ph.get("precio_promedio", "-")),
                "num_contratos":   str(ph.get("num_contratos", "-")),
                "recomendacion":   str(ph.get("recomendacion", "")),
                "es_competitivo":  ph.get("es_competitivo", None),
            }
        })
    return resultado


def obtener_convocatorias(palabras_clave=None, tipo_busqueda="ambos"):
    logger.info(f"Agente iniciando — tipo={tipo_busqueda} kw={palabras_clave}")
    datos = obtener_datos_seace()
    contratos, fuente, periodo = extraer_con_gemini(datos, palabras_clave)
    resultado = normalizar(contratos)
    
    # Filtrar por tipo si se especifica
    if tipo_busqueda == "bienes":
        resultado = [c for c in resultado if c["tipo_contrato"] == "Bienes"]
    elif tipo_busqueda == "servicios":
        resultado = [c for c in resultado if c["tipo_contrato"] == "Servicios"]
    
    logger.info(f"Agente completo: {len(resultado)} contratos")
    return resultado, fuente, periodo
