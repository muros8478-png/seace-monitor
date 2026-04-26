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
import os, io, logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

GMAIL_USER       = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD   = os.environ.get("GMAIL_PASSWORD", "")
RECIPIENT_EMAIL  = os.environ.get("RECIPIENT_EMAIL", "Muros8478@gmail.com")
SEND_EVERY_HOURS = int(os.environ.get("SEND_EVERY_HOURS", "7"))

# Importar agente con manejo de error
try:
    from agente import obtener_convocatorias
    logger.info("Agente Gemini importado correctamente.")
except Exception as e:
    logger.error(f"Error importando agente: {e}")
    def obtener_convocatorias():
        return []


def build_excel(contratos):
    wb = Workbook()
    ws = wb.active
    ws.title = "Contratos Menores SEACE"
    ROJO, BLANCO, GRIS = "B91C1C", "FFFFFF", "F9FAFB"
    thin = Side(style="thin", color="E5E7EB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.merge_cells("A1:H1")
    t = ws["A1"]
    t.value = f"CONVOCATORIAS CONTRATOS MENORES <= 8 UIT  -  {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    t.font = Font(name="Calibri", bold=True, size=13, color=BLANCO)
    t.fill = PatternFill("solid", fgColor=ROJO)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:H2")
    s = ws["A2"]
    s.value = f"Fuente: SEACE Peru  |  Agente IA: Google Gemini  |  Total: {len(contratos)} convocatorias"
    s.font = Font(name="Calibri", italic=True, size=10, color="6B7280")
    s.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 15

    headers = ["#", "N ORDEN", "OBJETO / BIEN O SERVICIO", "TIPO", "ENTIDAD", "LUGAR", "MONTO (S/.)", "DOCUMENTOS Y BASES"]
    widths  = [4,   14,        50,                          16,     38,        20,       14,             50]

    for i, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(name="Calibri", bold=True, size=10, color=BLANCO)
        c.fill = PatternFill("solid", fgColor=ROJO)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[3].height = 20

    for idx, c in enumerate(contratos, 1):
        fila = idx + 3
        bg = PatternFill("solid", fgColor=BLANCO if idx % 2 else GRIS)
        try:
            mv = float(str(c.get("monto","0")).replace(",","").replace("S/.","").strip() or 0)
            ms = f"{mv:,.2f}"
        except Exception:
            ms = str(c.get("monto","0"))

        docs = "\n".join(
            f"- {d.get('nombre','Doc')}: {d.get('url','')}" if d.get("url") else f"- {d.get('nombre','Doc')}"
            for d in (c.get("documentos") or [])
        ) or "Sin documentos"

        vals = [idx, c.get("numero",""), c.get("objeto",""), c.get("tipo",""),
                c.get("entidad",""), c.get("lugar",""), ms, docs]
        alns = ["center","center","left","center","left","left","right","left"]

        for col_i, (val, aln) in enumerate(zip(vals, alns), 1):
            cell = ws.cell(row=fila, column=col_i, value=val)
            cell.font = Font(name="Calibri", size=9)
            cell.fill = bg
            cell.alignment = Alignment(horizontal=aln, vertical="top", wrap_text=True)
            cell.border = border

        try:
            if float(str(c.get("monto","0")).replace(",","").strip() or 0) > 0:
                ws.cell(row=fila, column=7).font = Font(name="Calibri", size=9, bold=True, color="065F46")
                ws.cell(row=fila, column=7).fill = PatternFill("solid", fgColor="D1FAE5")
        except Exception:
            pass

        ws.row_dimensions[fila].height = max(28, 13 * max(1, len(c.get("documentos") or [])))

    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:H{3 + len(contratos)}"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_html_email(contratos):
    hoy  = datetime.now().strftime("%d/%m/%Y")
    hora = datetime.now().strftime("%H:%M")
    filas = ""
    for i, c in enumerate(contratos):
        bg = "#ffffff" if i % 2 == 0 else "#f9fafb"
        try:
            mv = float(str(c.get("monto","0")).replace(",","").replace("S/.","").strip() or 0)
            ms = f"S/. {mv:,.2f}" if mv > 0 else "-"
        except Exception:
            ms = "-"

        docs_html = "".join(
            f'<a href="{d.get("url","")}" style="display:inline-block;margin:2px;padding:2px 7px;background:#fef3c7;color:#92400e;border-radius:4px;font-size:11px;font-weight:600;text-decoration:none">Doc: {d.get("nombre","")}</a>'
            if d.get("url") else
            f'<span style="display:inline-block;margin:2px;padding:2px 7px;background:#f3f4f6;color:#374151;border-radius:4px;font-size:11px">{d.get("nombre","")}</span>'
            for d in (c.get("documentos") or [])
        ) or '<span style="color:#9ca3af;font-size:11px">Sin documentos</span>'

        url = c.get("urlSeace","")
        obj = c.get("objeto","Sin descripcion")
        obj_html = f'<a href="{url}" style="color:#b91c1c;font-weight:600;text-decoration:none">{obj}</a>' if url else f"<strong>{obj}</strong>"

        filas += f"""<tr style="background:{bg}">
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;text-align:center;vertical-align:top">{i+1}</td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;vertical-align:top">{c.get('numero','-')}</td>
          <td style="padding:9px 11px;font-size:13px;border-bottom:1px solid #e5e7eb;vertical-align:top">{obj_html}<div style="margin-top:4px">{docs_html}</div></td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;vertical-align:top">{c.get('tipo','-')}</td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;vertical-align:top">{c.get('entidad','-')}</td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;vertical-align:top">{c.get('lugar','-')}</td>
          <td style="padding:9px 11px;font-size:12px;font-weight:700;color:#065f46;border-bottom:1px solid #e5e7eb;text-align:right;vertical-align:top">{ms}</td>
        </tr>"""

    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif">
<div style="max-width:960px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden">
  <div style="background:#b91c1c;padding:22px 28px">
    <h1 style="margin:0;color:#fff;font-size:19px;font-weight:800">Contratos Menores SEACE Peru - menor o igual 8 UIT</h1>
    <div style="color:rgba(255,255,255,0.85);font-size:13px;margin-top:6px">{hoy} - {hora} - {len(contratos)} convocatorias - Excel adjunto</div>
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse">
      <thead><tr style="background:#f9fafb">
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">#</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:left">N ORDEN</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:left">OBJETO / DOCUMENTOS</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:left">TIPO</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:left">ENTIDAD</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:left">LUGAR</th>
        <th style="padding:9px 11px;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:right">MONTO S/.</th>
      </tr></thead>
      <tbody>{filas}</tbody>
    </table>
  </div>
  <div style="padding:14px 28px 20px;border-top:1px solid #f3f4f6;background:#fafafa">
    <p style="margin:0;font-size:11px;color:#9ca3af">Excel adjunto con detalle completo - Agente Google Gemini AI - Fuente: SEACE Peru - Envio automatico cada {SEND_EVERY_HOURS}h</p>
  </div>
</div></body></html>"""


def send_report(contratos):
    if not GMAIL_USER or not GMAIL_PASSWORD:
        raise ValueError("GMAIL_USER y GMAIL_PASSWORD no configurados.")
    hoy  = datetime.now().strftime("%d/%m/%Y")
    hora = datetime.now().strftime("%H:%M")
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Contratos Menores SEACE {hoy} {hora} - {len(contratos)} convocatorias"
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(build_html_email(contratos), "html", "utf-8"))
    msg.attach(alt)
    excel_buf = build_excel(contratos)
    nombre = f"SEACE_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
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
        contratos = obtener_convocatorias()
        if contratos:
            send_report(contratos)
    except Exception as e:
        logger.error(f"Error job: {e}")


# Iniciar scheduler con manejo de error
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
        contratos = obtener_convocatorias()
        return jsonify({"ok": True, "total": len(contratos), "contratos": contratos,
                        "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/enviar", methods=["POST"])
def api_enviar():
    try:
        body = request.get_json() or {}
        contratos = body.get("contratos") or obtener_convocatorias()
        total = send_report(contratos)
        return jsonify({"ok": True, "message": f"Excel enviado a {RECIPIENT_EMAIL} con {total} contratos."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/config")
def api_config():
    return jsonify({
        "gmail_configurado":  bool(GMAIL_USER and GMAIL_PASSWORD),
        "gemini_configurado": bool(os.environ.get("GEMINI_API_KEY","")),
        "destinatario":       RECIPIENT_EMAIL,
        "frecuencia":         f"Cada {SEND_EVERY_HOURS} horas",
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
