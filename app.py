[app.py](https://github.com/user-attachments/files/27089947/app.py)
"""
app.py — Monitor SEACE con Agente IA Gemini
Busca contratos menores del día, genera Excel y envía a Gmail cada 7 horas.
"""

from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
from agente import obtener_convocatorias
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── CONFIGURACIÓN ─────────────────────────────────────────────────────────────
GMAIL_USER       = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD   = os.environ.get("GMAIL_PASSWORD", "")
RECIPIENT_EMAIL  = os.environ.get("RECIPIENT_EMAIL", "Muros8478@gmail.com")
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
SEND_EVERY_HOURS = int(os.environ.get("SEND_EVERY_HOURS", "7"))


# ─── EXCEL ─────────────────────────────────────────────────────────────────────
def build_excel(contratos):
    wb = Workbook()
    ws = wb.active
    ws.title = "Contratos Menores SEACE"

    ROJO   = "B91C1C"
    BLANCO = "FFFFFF"
    GRIS   = "F9FAFB"
    BORDE  = "E5E7EB"

    thin   = Side(style="thin", color=BORDE)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Título
    ws.merge_cells("A1:H1")
    t = ws["A1"]
    t.value = f"🇵🇪 CONVOCATORIAS CONTRATOS MENORES ≤ 8 UIT  —  {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    t.font      = Font(name="Calibri", bold=True, size=13, color=BLANCO)
    t.fill      = PatternFill("solid", fgColor=ROJO)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    # Subtítulo
    ws.merge_cells("A2:H2")
    s = ws["A2"]
    s.value     = f"Fuente: SEACE · prod6.seace.gob.pe  |  Agente IA: Google Gemini  |  Total: {len(contratos)} convocatorias"
    s.font      = Font(name="Calibri", italic=True, size=10, color="6B7280")
    s.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 16

    # Encabezados
    cols = ["#", "N° ORDEN", "OBJETO / BIEN O SERVICIO", "TIPO", "ENTIDAD", "LUGAR", "MONTO (S/.)", "DOCUMENTOS Y BASES"]
    anchos = [4, 14, 50, 16, 38, 20, 14, 50]

    for i, (col, ancho) in enumerate(zip(cols, anchos), 1):
        c = ws.cell(row=3, column=i, value=col)
        c.font      = Font(name="Calibri", bold=True, size=10, color=BLANCO)
        c.fill      = PatternFill("solid", fgColor=ROJO)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border    = border
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.row_dimensions[3].height = 22

    # Datos
    for idx, c in enumerate(contratos, 1):
        fila = idx + 3
        bg   = PatternFill("solid", fgColor=BLANCO if idx % 2 else GRIS)

        try:
            monto_v = float(str(c.get("monto","0")).replace(",","").replace("S/.","").strip() or 0)
            monto_s = f"{monto_v:,.2f}"
        except Exception:
            monto_s = c.get("monto","—")

        docs_txt = "\n".join(
            f"• {d.get('nombre','Doc')}: {d.get('url','')}" if d.get("url") else f"• {d.get('nombre','Doc')}"
            for d in (c.get("documentos") or [])
        ) or "Sin documentos adjuntos"

        valores  = [idx, c.get("numero",""), c.get("objeto",""), c.get("tipo",""),
                    c.get("entidad",""), c.get("lugar","—"), monto_s, docs_txt]
        alineac  = ["center","center","left","center","left","left","right","left"]

        for col_i, (val, aln) in enumerate(zip(valores, alineac), 1):
            cell = ws.cell(row=fila, column=col_i, value=val)
            cell.font      = Font(name="Calibri", size=9)
            cell.fill      = bg
            cell.alignment = Alignment(horizontal=aln, vertical="top", wrap_text=True)
            cell.border    = border

        # Resaltar monto en verde
        m_cell = ws.cell(row=fila, column=7)
        try:
            if float(str(c.get("monto","0")).replace(",","").strip() or 0) > 0:
                m_cell.font = Font(name="Calibri", size=9, bold=True, color="065F46")
                m_cell.fill = PatternFill("solid", fgColor="D1FAE5")
        except Exception:
            pass

        n_docs = len(c.get("documentos") or [])
        ws.row_dimensions[fila].height = max(30, 14 * max(1, n_docs))

    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:H{3 + len(contratos)}"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─── HTML CORREO ───────────────────────────────────────────────────────────────
def build_html_email(contratos):
    hoy  = datetime.now().strftime("%d/%m/%Y")
    hora = datetime.now().strftime("%H:%M")

    filas = ""
    for i, c in enumerate(contratos):
        bg = "#ffffff" if i % 2 == 0 else "#f9fafb"
        try:
            mv = float(str(c.get("monto","0")).replace(",","").replace("S/.","").strip() or 0)
            ms = f"S/. {mv:,.2f}" if mv > 0 else "—"
        except Exception:
            ms = c.get("monto","—")

        docs_html = "".join(
            f'<a href="{d["url"]}" style="display:inline-block;margin:2px 3px 2px 0;padding:2px 8px;background:#fef3c7;color:#92400e;border-radius:4px;font-size:11px;font-weight:600;text-decoration:none">📄 {d["nombre"]}</a>'
            if d.get("url") else
            f'<span style="display:inline-block;margin:2px 3px 2px 0;padding:2px 8px;background:#f3f4f6;color:#374151;border-radius:4px;font-size:11px">📄 {d["nombre"]}</span>'
            for d in (c.get("documentos") or [])
        ) or '<span style="color:#9ca3af;font-size:11px;font-style:italic">Sin documentos</span>'

        url     = c.get("urlSeace","")
        objeto  = c.get("objeto","Sin descripción")
        obj_lnk = f'<a href="{url}" style="color:#b91c1c;font-weight:600;text-decoration:none">{objeto}</a>' if url else f"<strong>{objeto}</strong>"

        filas += f"""
        <tr style="background:{bg}">
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;text-align:center;color:#6b7280;vertical-align:top">{i+1}</td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;vertical-align:top">{c.get('numero','—')}</td>
          <td style="padding:9px 11px;font-size:13px;border-bottom:1px solid #e5e7eb;vertical-align:top">
            {obj_lnk}
            <div style="margin-top:5px">{docs_html}</div>
          </td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;vertical-align:top">{c.get('tipo','—')}</td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;vertical-align:top">{c.get('entidad','—')}</td>
          <td style="padding:9px 11px;font-size:12px;border-bottom:1px solid #e5e7eb;vertical-align:top">{c.get('lugar','—')}</td>
          <td style="padding:9px 11px;font-size:12px;font-weight:700;color:#065f46;border-bottom:1px solid #e5e7eb;white-space:nowrap;vertical-align:top;text-align:right">{ms}</td>
        </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Segoe UI',Arial,sans-serif">
<div style="max-width:980px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08)">
  <div style="background:#b91c1c;padding:22px 28px">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
      <span style="font-size:28px">🇵🇪</span>
      <div>
        <div style="font-size:10px;color:rgba(255,255,255,0.7);letter-spacing:.1em;text-transform:uppercase">OSCE · SEACE · Agente IA Gemini</div>
        <h1 style="margin:0;color:#fff;font-size:19px;font-weight:800">Convocatorias Contratos Menores ≤ 8 UIT</h1>
      </div>
    </div>
    <div style="color:rgba(255,255,255,0.85);font-size:13px">
      📅 {hoy} &nbsp;·&nbsp; 🕐 {hora} &nbsp;·&nbsp; 📋 <strong>{len(contratos)}</strong> convocatorias &nbsp;·&nbsp; 📎 Excel adjunto
    </div>
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse">
      <thead><tr style="background:#f9fafb">
        <th style="padding:9px 11px;text-align:center;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">#</th>
        <th style="padding:9px 11px;text-align:left;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">N° ORDEN</th>
        <th style="padding:9px 11px;text-align:left;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">OBJETO / DOCUMENTOS</th>
        <th style="padding:9px 11px;text-align:left;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">TIPO</th>
        <th style="padding:9px 11px;text-align:left;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">ENTIDAD</th>
        <th style="padding:9px 11px;text-align:left;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">LUGAR</th>
        <th style="padding:9px 11px;text-align:right;font-size:11px;color:#6b7280;border-bottom:2px solid #e5e7eb">MONTO S/.</th>
      </tr></thead>
      <tbody>{filas}</tbody>
    </table>
  </div>
  <div style="padding:14px 28px 20px;border-top:1px solid #f3f4f6;background:#fafafa">
    <p style="margin:0;font-size:11px;color:#9ca3af">
      📎 El Excel adjunto contiene todos los contratos con links a bases y documentos.<br>
      🤖 Extracción automática con <strong>Google Gemini AI</strong> · Fuente:
      <a href="https://prod6.seace.gob.pe/buscador-publico/contrataciones" style="color:#b91c1c">SEACE</a>
      · Envío automático cada {SEND_EVERY_HOURS} horas.
    </p>
  </div>
</div></body></html>"""


# ─── ENVÍO GMAIL ───────────────────────────────────────────────────────────────
def send_report(contratos):
    if not GMAIL_USER or not GMAIL_PASSWORD:
        raise ValueError("Configura GMAIL_USER y GMAIL_PASSWORD en las variables de entorno.")

    hoy  = datetime.now().strftime("%d/%m/%Y")
    hora = datetime.now().strftime("%H:%M")

    msg            = MIMEMultipart("mixed")
    msg["Subject"] = f"🇵🇪 Contratos Menores SEACE · {hoy} {hora} · {len(contratos)} convocatorias [Gemini AI]"
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(build_html_email(contratos), "html", "utf-8"))
    msg.attach(alt)

    excel_buf    = build_excel(contratos)
    nombre_excel = f"SEACE_ContratosMenores_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    part         = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    part.set_payload(excel_buf.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{nombre_excel}"')
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

    logger.info(f"✅ Correo enviado a {RECIPIENT_EMAIL} · {len(contratos)} contratos · Excel adjunto.")
    return len(contratos)


# ─── JOB AUTOMÁTICO ────────────────────────────────────────────────────────────
def job_automatico():
    logger.info(f"⏰ Job automático — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        contratos = obtener_convocatorias()
        if contratos:
            send_report(contratos)
        else:
            logger.info("Sin convocatorias en este ciclo.")
    except Exception as e:
        logger.error(f"Error en job: {e}")


# ─── SCHEDULER ─────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(job_automatico, "interval", hours=SEND_EVERY_HOURS, next_run_time=datetime.now())
scheduler.start()


# ─── RUTAS ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/convocatorias")
def api_convocatorias():
    try:
        contratos = obtener_convocatorias()
        return jsonify({"ok": True, "total": len(contratos), "contratos": contratos,
                        "fecha": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "agente": "Google Gemini 1.5 Flash"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/enviar", methods=["POST"])
def api_enviar():
    try:
        body      = request.get_json() or {}
        contratos = body.get("contratos") or obtener_convocatorias()
        total     = send_report(contratos)
        return jsonify({"ok": True, "message": f"Excel enviado a {RECIPIENT_EMAIL} con {total} convocatorias."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/config")
def api_config():
    return jsonify({
        "gmail_configurado":  bool(GMAIL_USER and GMAIL_PASSWORD),
        "gemini_configurado": bool(GEMINI_API_KEY),
        "destinatario":       RECIPIENT_EMAIL,
        "frecuencia":         f"Cada {SEND_EVERY_HOURS} horas automáticamente",
        "agente":             "Google Gemini 1.5 Flash",
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
