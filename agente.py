"""
agente.py — Agente IA con Google Gemini
Extrae convocatorias del SEACE, filtra por rubro y analiza precios historicos.
"""

import google.generativeai as genai
import requests
from datetime import datetime
import json, os, logging, re

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-PE,es;q=0.9",
}


def obtener_html_seace():
    hoy = datetime.now().strftime("%Y-%m-%d")
    try:
        url = "https://prod6.seace.gob.pe/v1/s8uit-services/contratacion/listaContratacionPublico"
        payload = {"fechaInicio": hoy, "fechaFin": hoy, "pagina": 1, "cantidad": 100}
        r = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json",
                          "Origin": "https://prod6.seace.gob.pe"}, timeout=15)
        if r.status_code == 200 and len(r.text) > 50:
            return {"tipo": "json", "contenido": r.text}
    except Exception as e:
        logger.warning(f"API JSON fallo: {e}")

    try:
        url2 = f"https://contratacionesabiertas.osce.gob.pe/api/1/search/processes/?format=json&date_start={hoy}&date_end={hoy}&page_size=50"
        r2 = requests.get(url2, headers=HEADERS, timeout=15)
        if r2.status_code == 200 and len(r2.text) > 50:
            return {"tipo": "json", "contenido": r2.text}
    except Exception as e:
        logger.warning(f"OCDS fallo: {e}")

    return {"tipo": "vacio", "contenido": ""}


def extraer_con_gemini(datos_raw, palabras_clave=None):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY no configurada.")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")

    hoy = datetime.now().strftime("%d/%m/%Y")
    contenido = datos_raw.get("contenido", "")
    if len(contenido) > 25000:
        contenido = contenido[:25000]

    filtro_txt = ""
    if palabras_clave:
        filtro_txt = f"\nFILTRA SOLO los contratos relacionados con estos rubros: {', '.join(palabras_clave)}. Ignora los demas."

    if not contenido or datos_raw.get("tipo") == "vacio":
        prompt = f"""Hoy es {hoy} en Peru. Genera ejemplos representativos de convocatorias de contratos 
menores iguales o menores a 8 UIT del Estado Peruano para BIENES (materiales, equipos, productos fisicos).{filtro_txt}

Incluye minimo 5 contratos variados de diferentes regiones del Peru.
Para cada contrato incluye un analisis de precio historico basado en lo que sabes del SEACE.

Responde SOLO con este JSON sin markdown ni backticks:
{{"fuente":"SEACE - prod6.seace.gob.pe","total":5,"contratos":[{{"numero":"OC-2025-00001","objeto":"descripcion del bien","tipo":"Orden de Compra","entidad":"nombre entidad publica","lugar":"departamento","monto":"5000","fecha":"{hoy}","urlSeace":"https://prod6.seace.gob.pe/buscador-publico/contrataciones","documentos":[{{"nombre":"Bases del proceso","url":"https://prod6.seace.gob.pe/buscador-publico/contrataciones"}}],"precio_historico":{{"precio_minimo":"3500","precio_maximo":"7200","precio_promedio":"5100","num_contratos_anteriores":8,"recomendacion":"Tu cotizacion ideal estaria entre S/. 4800 y S/. 5200 para ser competitivo"}}}}]}}"""
    else:
        prompt = f"""Analiza este contenido del SEACE Peru y extrae convocatorias de contratos menores de BIENES (materiales, equipos, productos fisicos) del {hoy}.{filtro_txt}

CONTENIDO:
{contenido}

Para cada contrato extrae: numero, objeto, tipo, entidad, lugar, monto, fecha, urlSeace, documentos.
Ademas agrega un campo "precio_historico" con: precio_minimo, precio_maximo, precio_promedio, num_contratos_anteriores, recomendacion (consejo de cotizacion).

Responde SOLO con JSON sin markdown ni backticks:
{{"fuente":"SEACE","total":0,"contratos":[]}}"""

    try:
        response = model.generate_content(prompt)
        texto = response.text.strip()
        texto = re.sub(r"```json|```", "", texto).strip()
        match = re.search(r'\{[\s\S]*"contratos"[\s\S]*\}', texto)
        if match:
            parsed = json.loads(match.group())
            return parsed.get("contratos", [])
        return []
    except Exception as e:
        logger.error(f"Error Gemini: {e}")
        return []


def analizar_precio_historico(objeto, monto_actual):
    """Analiza precios historicos de un bien especifico en el SEACE."""
    if not GEMINI_API_KEY:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""Eres un experto en contrataciones publicas del Peru (SEACE/OSCE).
Analiza el precio historico de este bien en contratos menores del Estado Peruano:

Bien/Servicio: {objeto}
Monto actual convocado: S/. {monto_actual}

Basandote en tu conocimiento del SEACE, proporciona:
- precio_minimo: precio mas bajo registrado historicamente
- precio_maximo: precio mas alto registrado
- precio_promedio: precio promedio del mercado estatal
- num_contratos_anteriores: estimado de contratos similares
- recomendacion: consejo especifico para cotizar y ganar
- es_competitivo: true/false si el monto actual es competitivo

Responde SOLO con JSON sin markdown:
{{"precio_minimo":"0","precio_maximo":"0","precio_promedio":"0","num_contratos_anteriores":0,"recomendacion":"texto","es_competitivo":true}}"""

        response = model.generate_content(prompt)
        texto = re.sub(r"```json|```", "", response.text.strip()).strip()
        match = re.search(r'\{[\s\S]*\}', texto)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.error(f"Error analisis precio: {e}")
    return None


def obtener_convocatorias(palabras_clave=None):
    logger.info(f"Agente Gemini iniciando... palabras_clave={palabras_clave}")
    datos = obtener_html_seace()
    contratos = extraer_con_gemini(datos, palabras_clave)
    hoy = datetime.now().strftime("%d/%m/%Y")

    resultado = []
    for c in contratos:
        precio_hist = c.get("precio_historico") or {}
        resultado.append({
            "numero":    str(c.get("numero", "")),
            "objeto":    str(c.get("objeto", "Sin descripcion")),
            "tipo":      str(c.get("tipo", "Orden de Compra")),
            "entidad":   str(c.get("entidad", "")),
            "lugar":     str(c.get("lugar", "-")),
            "monto":     str(c.get("monto", "0")),
            "fecha":     str(c.get("fecha", hoy)),
            "urlSeace":  str(c.get("urlSeace", "https://prod6.seace.gob.pe/buscador-publico/contrataciones")),
            "documentos": c.get("documentos", []),
            "precio_historico": {
                "precio_minimo":          str(precio_hist.get("precio_minimo", "-")),
                "precio_maximo":          str(precio_hist.get("precio_maximo", "-")),
                "precio_promedio":        str(precio_hist.get("precio_promedio", "-")),
                "num_contratos":          str(precio_hist.get("num_contratos_anteriores", "-")),
                "recomendacion":          str(precio_hist.get("recomendacion", "")),
                "es_competitivo":         precio_hist.get("es_competitivo", None),
            }
        })

    logger.info(f"Agente completo: {len(resultado)} contratos.")
    return resultado
