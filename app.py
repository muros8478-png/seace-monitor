from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime
import os, io, json, logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

GMAIL_USER       = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD   = os.environ.get("GMAIL_PASSWORD", "")
RECIPIENT_EMAIL  = os.environ.get("RECIPIENT_EMAIL", "Muros8478@gmail.com")
SEND_EVERY_HOURS = int(os.environ.get("SEND_EVERY_HOURS", "7"))

# Palabras clave guardadas en archivo local
KEYWORDS_FILE = "keywords.json"

def load_keywords():
    try:
        if os.path.exists(KEYWORDS_FILE):
            with open(KEYWORDS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []

def save_keywords(kws):
    try:
        with open(KEYWORDS_FILE, "w") as f:
            json.dump(kws, f)
    except Exception as e:
        logger.error(f"Error guardando keywords: {e}")

try:
    from agente import obtener_convocatorias
    logger.info("Agente Gemini importado OK.")
except Exception as e:
    logger.error(f"Error importando agente: {e}")
    def obtener_convocatorias(palabras_clave=None):
        return []


def build_excel(contratos):
    wb = Workbook()
    ws = wb.active
    ws.title = "Contratos Menores SEACE"
    ROJO, BLANCO, GRIS, VERDE = "B91C1C", "FFFFFF", "F9FAFB", "D1FAE5"
    thin = Side(style="thin", color="E5E7EB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.merge_cells("A1:I1")
    t = ws["A1"]
    t.value = f"CONVOCATORIAS CONTRATOS MENORES BIENES - SEACE PERU  -  {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    t.font = Font(name="Calibri", bold=True, size=13, color=BLANCO)
    t.fill = PatternFill("solid", fgColor=ROJO)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:I2")
    s = ws["A2"]
    s.value = f"Fuente: SEACE Peru  |  Agente: Google Gemini  |  Total: {len(contratos)} convocatorias de bienes"
    s.font = Font(name="Calibri", italic=True, size=10, color="6B7280")
    s.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 15

    headers = ["#", "N ORDEN", "OBJETO / BIEN", "ENTIDAD", "LUGAR", "MONTO S/.", "PRECIO PROM. HIST.", "RECOMENDACION DE COTIZACION", "DOCUMENTOS"]
    widths  = [4,   13,        42,               35,        18,       12,           18,                    45,                            40]

    for i, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(name="Calibri", bold=True, size=10, color=BLANCO)
        c.fill = PatternFill("solid", fgColor=ROJO)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[3].height = 22

    for idx, c in enumerate(contratos, 1):
        fila = idx + 3
        bg = PatternFill("solid", fgColor=BLANCO if idx % 2 else GRIS)

        try:
            mv = float(str(c.get("monto","0")).replace(",","").replace("S/.","").strip() or 0)
            ms = f"{mv:,.2f}"
        except Exception:
            ms = str(c.get("monto","0"))

        ph = c.get("precio_historico") or {}
        precio_prom = ph.get("precio_promedio", "-")
        try:
            precio_prom = f"S/. {float(str(precio_prom).replace(',','').strip()):,.2f}"
        except Exception:
            precio_prom = str(precio_prom)

        recomendacion = ph.get("recomendacion", "Sin datos")
        es_competitivo = ph.get("es_competitivo", None)

        docs = "\n".join(
            f"- {d.get('nombre','')}: {d.get('url','')}" if d.get("url") else f"- {d.get('nombre','')}"
            for d in (c.get("documentos") or [])
        ) or "Sin documentos"

        vals = [idx, c.get("numero",""), c.get("objeto",""), c.get("entidad",""),
                c.get("lugar","-"), ms, precio_prom, recomendacion, docs]
        alns = ["center","center","left","left","left","right","right","left","left"]

        for col_i, (val, aln) in enumerate(zip(vals, alns), 1):
            cell = ws.cell(row=fila, column=col_i, value=val)
            cell.font = Font(name="Calibri", size=9)
            cell.fill = bg
            cell.alignment = Alignment(horizontal=aln, vertical="top", wrap_text=True)
            cell.border = border

        # Resaltar monto
        try:
            if mv > 0:
                ws.cell(row=fila, column=6).font = Font(name="Calibri", size=9, bold=True, color="065F46")
                ws.cell(row=fila, column=6).fill = PatternFill("solid", fgColor="D1FAE5")
        except Exception:
            pass

        # Resaltar recomendacion
        rec_cell = ws.cell(row=fila, column=8)
        if es_competitivo is True:
            rec_cell.fill = PatternFill("solid", fgColor="D1FAE5")
        elif es_competitivo is False:
            rec_cell.fill = PatternFill("solid", fgColor="FEF3C7")

        ws.row_dimensions[fila].height = max(30, 13 * max(1, len(c.get("documentos") or [])))

    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:I{3 + len(contratos)}"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_html_email(contratos, keywords):
    hoy  = datetime.now().strftime("%d/%m/%Y")
    hora = datetime.now().strftime("%H:%M")
    kw_txt = ", ".join(keywords) if keywords else "Todos los bienes"
    filas = ""

    for i, c in enumerate(contratos):
        bg = "#ffffff" if i % 2 == 0 else "#f9fafb"
        try:
            mv = float(str(c.get("monto","0")).replace(",","").replace("S/.","").strip() or 0)
            ms = f"S/. {mv:,.2f}" if mv > 0 else "-"
        except Exception:
            ms = "-"

        ph = c.get("precio_historico") or {}
        try:
            pp = f"S/. {float(str(ph.get('precio_promedio',0)).replace(',','').strip()):,.2f}"
        except Exception:
            pp = "-"

        rec = ph.get("recomendacion","")
        es_comp = ph.get("es_competitivo", None)
        rec_color = "#d1fae5" if es_comp is True else "#fef3c7" if es_comp is False else "#f9fafb"
        rec_badge = "✅ Competitivo" if es_comp is True else "⚠️ Revisar precio" if es_comp is False else ""

        docs_html = "".join(
            f'<a href="{d.get("url","")}" style="display:inline-block;margin:2px;padding:2px 7px;background:#fef3c7;color:#92400e;border-radius:4px;font-size:11px;font-weight:600;text-decoration:none">📄 {d.get("nombre","")}</a>'
            if d.get("url") else
            f'<span style="display:inline-block;margin:2px;padding:2px 7px;background:#f3f4f6;color:#374151;border-radius:4px;font-size:11px">📄 {d.get("nombre","")}</span>'
            for d in (c.get("documentos") or [])
        ) or '<span style="color:#9ca3af;font-size:11px">Sin documentos</span>'

        url = c.get("urlSeace","")
        obj = c.get("objeto","Sin descripcion")
        obj_html = f'<a href="{url}" style="color:#b91c1c;font-weight:600;text-decoration:none">{obj}</a>' if url else f"<strong>{obj}</strong>"

        filas += f"""<tr style="background:{bg}">
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;text-align:center;vertical-align:top">{i+1}</td>
          <td style="padding:9px 11px;font-size:13px;border-bottom:1px solid #e5e7eb;vertical-align:top">
            {obj_html}<br><small style="color:#6b7280">{c.get('entidad','')} · {c.get('lugar','')}</small>
            <div style="margin-top:4px">{docs_html}</div>
          </td>
          <td style="padding:9px 11px;font-size:12px;font-weight:700;color:#065f46;border-bottom:1px solid #e5e7eb;text-align:right;vertical-align:top;white-space:nowrap">{ms}</td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;text-align:right;vertical-align:top;white-space:nowrap;color:#374151">{pp}</td>
          <td style="padding:9px 11px;font-size:11px;border-bottom:1px solid #e5e7eb;vertical-align:top;background:{rec_color}">
            {f'<span style="font-size:10px;font-weight:700">{rec_badge}</span><br>' if rec_badge else ""}{rec}
          </td>
        </tr>"""

    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif">
<div style="max-width:960px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden">
  <div style="background:#b91c1c;padding:22px 28px">
    <h1 style="margin:0;color:#fff;font-size:19px;font-weight:800">Contratos Menores SEACE - Bienes</h1>
    <div style="color:rgba(255,255,255,0.85);font-size:13px;margin-top:6px">
      {hoy} - {hora} · {len(contratos)} convocatorias · Rubro: {kw_txt}
    </div>
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse">
      <thead><tr style="background:#f9fafb">
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">#</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:left">OBJETO / ENTIDAD / DOCUMENTOS</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:right">MONTO</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:right">PRECIO PROM. HIST.</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:left">RECOMENDACION DE COTIZACION</th>
      </tr></thead>
      <tbody>{filas}</tbody>
    </table>
  </div>
  <div style="padding:14px 28px 20px;border-top:1px solid #f3f4f6;background:#fafafa">
    <p style="margin:0;font-size:11px;color:#9ca3af">
      Excel adjunto con analisis completo · Google Gemini AI · SEACE Peru · Cada {SEND_EVERY_HOURS}h automatico
    </p>
  </div>
</div></body></html>"""


def send_report(contratos, keywords=None):
    if not GMAIL_USER or not GMAIL_PASSWORD:
        raise ValueError("GMAIL_USER y GMAIL_PASSWORD no configurados.")
    hoy  = datetime.now().strftime("%d/%m/%Y")
    hora = datetime.now().strftime("%H:%M")
    kw_txt = f" [{', '.join(keywords)}]" if keywords else ""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"SEACE Bienes{kw_txt} - {hoy} {hora} - {len(contratos)} convocatorias"
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(build_html_email(contratos, keywords or []), "html", "utf-8"))
    msg.attach(alt)
    excel_buf = build_excel(contratos)
    nombre = f"SEACE_Bienes_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    part = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    part.set_payload(excel_buf.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{nombre}"')
    msg.attach(part)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    logger.info(f"Correo enviado a {RECIPIENT_EMAIL}")
    return len(contratos)


def job_automatico():
    logger.info(f"Job automatico {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        keywords = load_keywords()
        contratos = obtener_convocatorias(palabras_clave=keywords if keywords else None)
        if contratos:
            send_report(contratos, keywords)
    except Exception as e:
        logger.error(f"Error job: {e}")


try:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(job_automatico, "interval", hours=SEND_EVERY_HOURS)
    scheduler.start()
    logger.info(f"Scheduler OK: cada {SEND_EVERY_HOURS} horas.")
except Exception as e:
    logger.error(f"Error scheduler: {e}")


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/convocatorias")
def api_convocatorias():
    try:
        keywords = load_keywords()
        contratos = obtener_convocatorias(palabras_clave=keywords if keywords else None)
        return jsonify({"ok": True, "total": len(contratos), "contratos": contratos,
                        "fecha": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "keywords": keywords})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/enviar", methods=["POST"])
def api_enviar():
    try:
        body = request.get_json() or {}
        keywords = load_keywords()
        contratos = body.get("contratos") or obtener_convocatorias(palabras_clave=keywords if keywords else None)
        total = send_report(contratos, keywords)
        return jsonify({"ok": True, "message": f"Excel enviado a {RECIPIENT_EMAIL} con {total} contratos."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/keywords", methods=["GET"])
def api_get_keywords():
    return jsonify({"keywords": load_keywords()})

@app.route("/api/keywords", methods=["POST"])
def api_save_keywords():
    try:
        body = request.get_json() or {}
        kws = [k.strip() for k in body.get("keywords", []) if k.strip()]
        save_keywords(kws)
        return jsonify({"ok": True, "keywords": kws})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/config")
def api_config():
    return jsonify({
        "gmail_configurado":  bool(GMAIL_USER and GMAIL_PASSWORD),
        "gemini_configurado": bool(os.environ.get("GEMINI_API_KEY","")),
        "destinatario":       RECIPIENT_EMAIL,
        "frecuencia":         f"Cada {SEND_EVERY_HOURS} horas",
        "keywords":           load_keywords(),
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
