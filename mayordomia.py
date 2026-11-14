import streamlit as st, requests, pandas as pd, io, os, zipfile, base64, json
from datetime import datetime, date
from operator import itemgetter
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table as RLTable, TableStyle, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

st.set_page_config(page_title="Hermandad de Ntra. Sra. de los Desamparados", page_icon="escudo.png", layout="wide")
if os.path.exists("escudo.png"):
    with open("escudo.png", "rb") as _f:
        _ico_b64 = base64.b64encode(_f.read()).decode()
    st.markdown(f'<link rel="apple-touch-icon" href="data:image/png;base64,{_ico_b64}"><link rel="icon" sizes="192x192" href="data:image/png;base64,{_ico_b64}">', unsafe_allow_html=True)
st.markdown("<style>.main { background-color: #FDFCFB; } h1, h2, h3 { color: #800020 !important; font-family: 'Georgia', serif; } .stButton>button { background-color: #800020; color: white; border-radius: 4px; border: none; font-weight: bold; } .stButton>button:hover { background-color: #5C0017; color: white; } div[data-testid='stMetricValue'] { font-size: 26px; font-weight: bold; color: #800020; } div[data-testid='stMetricLabel'] { font-size: 13px; font-weight: 600; color: #4B5563; } .stRadio>label { font-weight: bold; }</style>", unsafe_allow_html=True)

if "autenticado" not in st.session_state: st.session_state.autenticado = False
if not st.session_state.autenticado:
    c_l1, c_l2, c_l3 = st.columns((1, 1.5, 1))
    with c_l2:
        if os.path.exists("escudo.png"): st.image("escudo.png", width=110)
        st.markdown("### Acceso Restringido — Mayordomía")
        clave = st.text_input("Introduce la contraseña de la Junta de Gobierno:", type="password")
        if st.button("Entrar al Sistema", use_container_width=True):
            if clave == st.secrets["password_hermandad"]: st.session_state.autenticado = True; st.rerun()
            else: st.error("Contraseña incorrecta.")
    st.stop()

@st.cache_resource
def obtener_sesion_http():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {st.secrets['TURSO_AUTH_TOKEN']}", "Content-Type": "application/json"})
    return s

def ejecutar_turso_http(sql, params=()):
    url = st.secrets["TURSO_DATABASE_URL"].replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    args = list()
    for p in params:
        if p is None: args.append({"type": "null"})
        elif isinstance(p, int): args.append({"type": "integer", "value": str(p)})
        elif isinstance(p, float): args.append({"type": "float", "value": p})
        else: args.append({"type": "text", "value": str(p)})
    payload = {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": args}}, {"type": "close"}]}
    r = obtener_sesion_http().post(url, json=payload, timeout=15)
    r.raise_for_status()
    res = itemgetter(0)(r.json()["results"])["response"]["result"]
    cols = [c["name"] for c in res.get("cols", list())]
    rows = list()
    for row in res.get("rows", list()):
        fila = list()
        for cell in row:
            t = cell.get("type")
            if t == "null": fila.append(None)
            elif t == "integer": fila.append(int(cell.get("value")))
            elif t == "float": fila.append(float(cell.get("value")))
            else: fila.append(cell.get("value"))
        rows.append(tuple(fila))
    return cols, rows
class TursoCursor:
    def __init__(self):
        self.rows = list()
    def execute(self, sql, params=()):
        _, self.rows = ejecutar_turso_http(sql, params)
        return self
    def fetchall(self):
        return self.rows
    def fetchone(self):
        return itemgetter(0)(self.rows) if self.rows else None

class TursoConn:
    def cursor(self): return TursoCursor()
    def commit(self): pass
    def sync(self): pass

def leer_tabla_turso(sql):
    cols, rows = ejecutar_turso_http(sql)
    return pd.DataFrame(rows, columns=cols)

def registrar_presencia_usuario(nombre_usuario, accion="registrar"):
    ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ejecutar_turso_http("INSERT OR REPLACE INTO config_sistema (clave, valor) VALUES ('ultimo_usuario', ?)", (f"{nombre_usuario} ({ahora_str})",))
    ejecutar_turso_http("INSERT OR REPLACE INTO config_sistema (clave, valor) VALUES ('ultima_accion', ?)", (accion,))

def comprobar_bloqueo_concurrencia(nombre_actual):
    try:
        _, res_u = ejecutar_turso_http("SELECT valor FROM config_sistema WHERE clave = 'ultimo_usuario'")
        _, res_a = ejecutar_turso_http("SELECT valor FROM config_sistema WHERE clave = 'ultima_accion'")
        if res_u and res_a:
            user_info = itemgetter(0)(res_u)[0]
            accion_info = itemgetter(0)(res_a)[0]
            if nombre_actual not in user_info:
                fecha_partes = user_info.split("(")[1].replace(")", "").strip()
                fecha_dt = datetime.strptime(fecha_partes, "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - fecha_dt).total_seconds() < 300:
                    return f"⚠️ {user_info} está usando el módulo de {accion_info} ahora mismo. Espera a que termine para evitar duplicados."
    except:
        pass
    return None

def conectar_bd():
    conn = TursoConn()
    if "bd_inicializada" not in st.session_state:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS contabilidad (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, tipo TEXT NOT NULL, origen_destino TEXT NOT NULL, partida TEXT NOT NULL, proveedor TEXT DEFAULT '', num_factura TEXT DEFAULT '', concepto TEXT NOT NULL, forma_pago TEXT NOT NULL, importe REAL NOT NULL, comprobante TEXT, eliminado INTEGER DEFAULT 0, pendiente INTEGER DEFAULT 0)")
        try: cursor.execute("ALTER TABLE contabilidad ADD COLUMN eliminado INTEGER DEFAULT 0")
        except: pass
        try: cursor.execute("ALTER TABLE contabilidad ADD COLUMN pendiente INTEGER DEFAULT 0")
        except: pass
        try: cursor.execute("ALTER TABLE contabilidad ADD COLUMN proveedor TEXT DEFAULT ''")
        except: pass
        try: cursor.execute("ALTER TABLE contabilidad ADD COLUMN num_factura TEXT DEFAULT ''")
        except: pass
        cursor.execute("CREATE TABLE IF NOT EXISTS traspasos_internos (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, origen TEXT NOT NULL, destino TEXT NOT NULL, importe REAL NOT NULL, concepto TEXT NOT NULL)")
        cursor.execute("CREATE TABLE IF NOT EXISTS partidas_personalizadas (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, nombre TEXT NOT NULL UNIQUE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS saldos_iniciales (id INTEGER PRIMARY KEY, caja_inicio REAL DEFAULT 0.0, banco_inicio REAL DEFAULT 0.0)")
        cursor.execute("INSERT OR IGNORE INTO saldos_iniciales (id, caja_inicio, banco_inicio) VALUES (1, 0.0, 0.0)")
        cursor.execute("CREATE TABLE IF NOT EXISTS presupuestos (partida TEXT PRIMARY KEY, tipo TEXT NOT NULL, importe_presupuestado REAL DEFAULT 0.0)")
        cursor.execute("CREATE TABLE IF NOT EXISTS archivos_nube (nombre TEXT PRIMARY KEY, datos_b64 TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS config_sistema (clave TEXT PRIMARY KEY, valor TEXT)")
        cursor.execute("SELECT valor FROM config_sistema WHERE clave = 'init_partidas'")
        if not cursor.fetchone():
            iniciales = [("Ingreso", "Cuotas de Hermanos"), ("Ingreso", "Limosnas y Cepillos"), ("Ingreso", "Papeletas de Sitio"), ("Ingreso", "Venta de Recuerdos"), ("Ingreso", "Lotería"), ("Ingreso", "Donaciones"), ("Gasto", "Caridad y Bolsa Social"), ("Gasto", "Cultos, Cera y Flores"), ("Gasto", "Mantenimiento y Conservación"), ("Gasto", "Música y Acompañamiento"), ("Gasto", "Gastos de Administración")]
            for t_ini, n_ini in iniciales:
                cursor.execute("INSERT OR IGNORE INTO partidas_personalizadas (tipo, nombre) VALUES (?, ?)", (t_ini, n_ini))
            cursor.execute("INSERT INTO config_sistema (clave, valor) VALUES ('init_partidas', '1')")
        st.session_state.bd_inicializada = True
    return conn
def procesar_panel_remesas(archivo_excel):
    try:
        try:
            df_b = pd.read_excel(archivo_excel, engine="openpyxl").dropna(how="all")
        except:
            df_b = pd.read_excel(archivo_excel, engine="xlrd").dropna(how="all")
        
        cols_b = list(df_b.columns)
        if len(cols_b) >= 2:
            st.markdown("**1. Asigna las columnas de tu archivo Excel:**")
            m1, m2, m3, m4, m5 = st.columns(5)
            col_ref = m1.selectbox("Referencia Banco:", ["(Sin ref)"] + cols_b, index=1 if len(cols_b) > 0 else 0)
            col_nom = m2.selectbox("Nombre Hermano:", cols_b, index=min(1, len(cols_b)-1))
            col_imp = m3.selectbox("Cuota / Importe (€):", cols_b, index=min(3, len(cols_b)-1))
            col_fec = m4.selectbox("Fecha Vencimiento:", cols_b, index=min(4, len(cols_b)-1))
            col_est = m5.selectbox("Estado Recibo:", ["(Todos)"] + cols_b, index=min(len(cols_b), 5))
            df_val = df_b.copy()
            if col_est != "(Todos)":
                estados_disp = list(df_val[col_est].dropna().unique())
                estados_ok = st.multiselect("2. Selecciona los estados válidos a cobrar (ej. Pagado/Cobrado):", estados_disp, default=estados_disp)
                df_val = df_val.loc[df_val[col_est].isin(estados_ok)]
            def limpiar_num(val):
                if isinstance(val, (int, float)): return float(val)
                s = str(val).replace("€", "").replace(" ", "").strip()
                if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
                elif "," in s: s = s.replace(",", ".")
                try: return float(s)
                except: return 0.0
            df_val["_imp_limpio"] = df_val[col_imp].apply(limpiar_num)
            df_val = df_val.loc[df_val["_imp_limpio"] > 0]
            part_remesa = st.selectbox("3. Partida contable donde asentar los recibos:", obtener_partidas("Ingreso"), key="part_remesa")
            prefijo_con = st.text_input("Texto inicial del concepto:", value="Cuota domiciliada - ", key="pref_remesa")
            def armar_detalle(fila):
                n = str(fila.get(col_nom, "")).strip()
                c = float(fila.get("_imp_limpio", 0.0))
                r_txt = f" [Ref: {str(fila.get(col_ref, '')).strip()}]" if col_ref != "(Sin ref)" and pd.notna(fila.get(col_ref)) else ""
                return f"{prefijo_con}{n} | Cuota abonada: {c:,.2f} €{r_txt}"
            df_val["_concepto_final"] = df_val.apply(armar_detalle, axis=1)
            st.info(f"Se han detectado **{len(df_val)} hermanos con recibo válido** por un importe total de **{df_val['_imp_limpio'].sum():,.2f} €**.")
            df_preview = pd.DataFrame({"Hermano": df_val[col_nom], "Cuota (€)": df_val["_imp_limpio"], "Vencimiento": df_val[col_fec], "Concepto que se guardará": df_val["_concepto_final"]})
            st.dataframe(df_preview, use_container_width=True, hide_index=True)
            if st.button(f"📥 VOLCAR {len(df_val)} RECIBOS EN BANCO", use_container_width=True):
                if not df_val.empty:
                    conn = conectar_bd(); cur = conn.cursor()
                    for _, r_b in df_val.iterrows():
                        imp_val = float(r_b.get("_imp_limpio", 0.0))
                        con_str = str(r_b.get("_concepto_final", ""))
                        fec_raw = r_b.get(col_fec)
                        try: fec_str = pd.to_datetime(fec_raw).strftime("%Y-%m-%d 09:00")
                        except: fec_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        cur.execute("INSERT INTO contabilidad (fecha, tipo, origen_destino, partida, concepto, forma_pago, importe, comprobante) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (fec_str, "Ingreso", "Banco", part_remesa, con_str, "Domiciliación Bancaria", imp_val, ""))
                    conn.commit(); conn.sync()
                    st.success(f"¡{len(df_val)} recibos importados en la nube!"); st.rerun()
    except Exception as e:
        st.error(f"No se pudo leer el archivo Excel. Detalle: {e}")
@st.cache_data(show_spinner=False)
def obtener_escudo_b64():
    if os.path.exists("escudo.png"):
        with open("escudo.png", "rb") as _f:
            return base64.b64encode(_f.read()).decode()
    return ""

@st.cache_data(ttl=300, show_spinner=False)
def obtener_partidas(tipo):
    cols, rows = ejecutar_turso_http("SELECT nombre FROM partidas_personalizadas WHERE tipo = ? ORDER BY nombre ASC", (tipo,))
    lista = [itemgetter(0)(f) for f in rows]
    return lista if lista else ["General"]

def guardar_archivo_nube(nombre, bytes_data):
    conn = conectar_bd(); cur = conn.cursor()
    b64_str = base64.b64encode(bytes_data).decode('utf-8')
    cur.execute("INSERT OR REPLACE INTO archivos_nube (nombre, datos_b64) VALUES (?, ?)", (nombre, b64_str))

def leer_archivo_nube(nombre):
    conn = conectar_bd(); cur = conn.cursor()
    cur.execute("SELECT datos_b64 FROM archivos_nube WHERE nombre = ?", (nombre,))
    res = cur.fetchone()
    return base64.b64decode(itemgetter(0)(res)) if res else None

def borrar_registro(id_reg):
    conn = conectar_bd(); cursor = conn.cursor()
    cursor.execute("UPDATE contabilidad SET eliminado = 1 WHERE id = ?", (id_reg,))

def restaurar_registro(id_reg):
    conn = conectar_bd(); cursor = conn.cursor()
    cursor.execute("UPDATE contabilidad SET eliminado = 0 WHERE id = ?", (id_reg,))

def borrar_definitivo(id_reg):
    conn = conectar_bd(); cursor = conn.cursor(); cursor.execute("SELECT comprobante FROM contabilidad WHERE id = ?", (id_reg,)); arc = cursor.fetchone()
    if arc and itemgetter(0)(arc):
        cursor.execute("DELETE FROM archivos_nube WHERE nombre = ?", (itemgetter(0)(arc),))
    cursor.execute("DELETE FROM contabilidad WHERE id = ?", (id_reg,))

def generar_excel(df, agrupar=False):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df_export = df.drop(columns=['Comprobante'], errors='ignore').copy()
        if agrupar and not df_export.empty:
            df_export = df_export.sort_values(by=['Partida', 'Fecha'], ascending=[True, True])
        df_export.to_excel(writer, index=False, sheet_name='Movimientos')
        if agrupar and not df_export.empty:
            df_resumen = df_export.groupby(['Tipo', 'Partida'], as_index=False)['Importe (€)'].sum()
            df_resumen.to_excel(writer, index=False, sheet_name='Resumen_Por_Conceptos')
        try:
            df_t_ex = leer_tabla_turso("SELECT id as 'Nº Traspaso', fecha as 'Fecha', origen as 'Origen', destino as 'Destino', concepto as 'Motivo / Concepto', importe as 'Importe (€)' FROM traspasos_internos ORDER BY id ASC")
            if not df_t_ex.empty:
                df_t_ex.to_excel(writer, index=False, sheet_name='Traspasos_Internos')
        except:
            pass
    buf.seek(0); return buf
def generar_backup_zip():
    buf = io.BytesIO()
    tablas = ["contabilidad", "partidas_personalizadas", "saldos_iniciales", "presupuestos", "config_sistema"]
    respaldo = {}
    for t in tablas:
        cols, rows = ejecutar_turso_http(f"SELECT * FROM {t}")
        respaldo[t] = {"cols": cols, "rows": rows}
    _, archivos = ejecutar_turso_http("SELECT nombre, datos_b64 FROM archivos_nube")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("datos_hermandad.json", json.dumps(respaldo, ensure_ascii=False, indent=2))
        for nom, b64 in archivos:
            if nom and b64:
                zf.writestr(f"tickets/{nom}", base64.b64decode(b64))
    buf.seek(0)
    return buf

def restaurar_backup_zip(archivo_zip):
    with zipfile.ZipFile(archivo_zip, "r") as zf:
        respaldo = json.loads(zf.read("datos_hermandad.json").decode("utf-8"))
        for t in ["contabilidad", "partidas_personalizadas", "saldos_iniciales", "presupuestos", "config_sistema", "archivos_nube"]:
            ejecutar_turso_http(f"DELETE FROM {t}")
        for t, contenido in respaldo.items():
            cols = contenido["cols"]
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            for fila in contenido["rows"]:
                ejecutar_turso_http(f"INSERT INTO {t} ({col_names}) VALUES ({placeholders})", tuple(fila))
        for item in zf.namelist():
            if item.startswith("tickets/") and not item.endswith("/"):
                nom_real = item.replace("tickets/", "", 1)
                b64_str = base64.b64encode(zf.read(item)).decode("utf-8")
                ejecutar_turso_http("INSERT OR REPLACE INTO archivos_nube (nombre, datos_b64) VALUES (?, ?)", (nom_real, b64_str))
def mostrar_panel_respaldos(df_global):
    st.markdown("---")
    st.markdown("**🛡️ Copias de Seguridad y Restauración**")
    st.download_button(label="📦 DESCARGAR BACKUP INTEGRAL (.ZIP CON TICKETS)", data=generar_backup_zip(), file_name=f"Backup_Integral_Desamparados_{datetime.now().strftime('%Y%m%d_%H%M')}.zip", mime="application/zip", use_container_width=True)
    st.download_button(label="📊 Exportar Solo Movimientos (.XLSX)", data=generar_excel(df_global), file_name=f"Movimientos_Mayordomia_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with st.expander("⏪ Restaurar Base de Datos desde Backup (.ZIP)", expanded=False):
        st.warning("⚠️ Atención: Al restaurar un archivo .ZIP se reemplazarán todos los datos actuales por los de la copia.")
        zip_subido = st.file_uploader("Selecciona el archivo Backup_Integral (.zip):", type=["zip"], key="up_zip_restore")
        if zip_subido is not None:
            if st.button("🔄 CONFIRMAR Y RESTAURAR AHORA", use_container_width=True):
                try:
                    restaurar_backup_zip(zip_subido)
                    st.success("¡Base de datos y tickets restaurados correctamente!"); st.rerun()
                except Exception as e:
                    st.error(f"Error al restaurar el backup: {e}")
    st.markdown("---")
    df_pap = leer_tabla_turso("SELECT id, fecha, tipo, origen_destino, partida, concepto, importe FROM contabilidad WHERE eliminado = 1 ORDER BY id DESC")
    with st.expander(f"🗑️ Papelera de Reciclaje ({len(df_pap)} apuntes borrados)", expanded=False):
        if df_pap.empty:
            st.caption("La papelera está vacía.")
        else:
            for _, rp in df_pap.iterrows():
                pid_b = rp.get("id")
                with st.container(border=True):
                    st.markdown(f"**#{pid_b}** | {rp.get('partida')} — {rp.get('concepto')} (**{float(rp.get('importe')):,.2f} €**)<br/><small style='color:gray;'>{rp.get('fecha')} | {rp.get('origen_destino')}</small>", unsafe_allow_html=True)
                    b_res, b_del = st.columns(2)
                    if b_res.button("♻️ Restaurar", key=f"rest_{pid_b}", use_container_width=True):
                        restaurar_registro(pid_b); st.rerun()
                    if b_del.button("🔥 Borrar Definitivo", key=f"pdel_{pid_b}", use_container_width=True):
                        borrar_definitivo(pid_b); st.rerun()
def marca_agua_vertical(canvas, doc):
    if os.path.exists("escudo.png"):
        canvas.saveState(); canvas.setFillAlpha(0.08); canvas.setStrokeAlpha(0.08)
        canvas.drawImage("escudo.png", 156, 246, width=300, height=300, mask='auto'); canvas.restoreState()

def marca_agua_horizontal(canvas, doc):
    if os.path.exists("escudo.png"):
        canvas.saveState(); canvas.setFillAlpha(0.08); canvas.setStrokeAlpha(0.08)
        canvas.drawImage("escudo.png", 266, 176, width=260, height=260, mask='auto'); canvas.restoreState()

def generar_pdf_recibo(row):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=35, bottomMargin=35); story = list(); styles = getSampleStyleSheet(); burdeos = colors.HexColor("#800020")
    t_st = ParagraphStyle('T', parent=styles['Heading1'], fontSize=15, leading=18, alignment=1, textColor=burdeos); n_st = ParagraphStyle('N', parent=styles['Normal'], fontSize=10, leading=14)
    for i, ej in enumerate(["EJEMPLAR PARA EL INTERESADO", "EJEMPLAR PARA LA HERMANDAD"]):
        if os.path.exists("escudo.png"):
            try: img = RLImage("escudo.png", width=95, height=95); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 8))
            except: pass
        story.append(Paragraph("<b>HERMANDAD DE NUESTRA SEÑORA DE LOS DESAMPARADOS</b>", t_st))
        story.append(Paragraph(f"<b>{ej}</b>", ParagraphStyle('SubE', alignment=1, fontSize=10, textColor=burdeos)))
        
        if row.get('Tipo') == 'Ingreso':
            sub = "JUSTIFICANTE OFICIAL DE RECAUDACIÓN"
        else:
            sub = "ORDEN DE PAGO A PROVEEDOR / ACREEDOR"
            
        story.append(Paragraph(sub, ParagraphStyle('S', alignment=1, fontSize=11, textColor=colors.gray))); story.append(Spacer(1, 15))
        
        importe_positivo = abs(float(row.get('Importe (€)', 0.0)))
        prov_txt = str(row.get('Proveedor', '') or '').strip() or "No especificado"
        fac_txt = str(row.get('Nº Factura', '') or '').strip() or "S/N"
        
        t_data = [
            [Paragraph(f"<b>Nº Asiento:</b> #{row.get('id')}", n_st), Paragraph(f"<b>Fecha:</b> {row.get('Fecha')}", n_st)], 
            [Paragraph(f"<b>Tipo Operación:</b> {row.get('Tipo')}", n_st), Paragraph(f"<b>Cuenta Asignada:</b> {row.get('Cuenta')}", n_st)], 
            [Paragraph(f"<b>Partida Contable:</b> {row.get('Partida')}", n_st), Paragraph(f"<b>Forma Pago:</b> {row.get('Forma Pago')}", n_st)], 
            [Paragraph(f"<b>Proveedor / Interesado:</b> {prov_txt}", n_st), Paragraph(f"<b>Nº Factura / Ticket:</b> {fac_txt}", n_st)], 
            [Paragraph(f"<b>Concepto / Detalle:</b> {row.get('Concepto')}", n_st), Paragraph(f"<b>IMPORTE:</b> <font color='#800020'><b>{importe_positivo:,.2f} €</b></font>", n_st)]
        ]
        
        t = RLTable(t_data, colWidths=(250, 250)); t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('PADDING', (0,0), (-1,-1), 8), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')])); story.append(t); story.append(Spacer(1, 35))
        if row.get('Tipo') == 'Ingreso': story.append(Paragraph("<b>___________________________</b><br/>Firma y Sello del Mayordomo", ParagraphStyle('F', alignment=1, fontSize=10)))
        else:
            tf = RLTable([[Paragraph("<b>___________________________</b><br/>Páguese, El Mayordomo", ParagraphStyle('F1', alignment=1, fontSize=10)), Paragraph("<b>___________________________</b><br/>Recibí, El Beneficiario / Perceptor", ParagraphStyle('F2', alignment=1, fontSize=10))]], colWidths=(250, 250)); tf.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')])); story.append(tf)
        if i == 0: story.append(PageBreak())
    doc.build(story, onFirstPage=marca_agua_vertical, onLaterPages=marca_agua_vertical); buf.seek(0); return buf
def generar_pdf_resumen(df, titulo_reporte, agrupar=False):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30); story = list(); styles = getSampleStyleSheet(); burdeos = colors.HexColor("#800020")
    t_st = ParagraphStyle('T', parent=styles['Heading1'], fontSize=15, leading=18, alignment=1, textColor=burdeos); s_st = ParagraphStyle('S', parent=styles['Normal'], fontSize=9, leading=12, alignment=1, textColor=colors.gray); n_st = ParagraphStyle('N', parent=styles['Normal'], fontSize=8, leading=11)
    if os.path.exists("escudo.png"):
        try: img = RLImage("escudo.png", width=55, height=55); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 6))
        except: pass
    story.append(Paragraph("<b>HERMANDAD DE NUESTRA SEÑORA DE LOS DESAMPARADOS</b>", t_st)); story.append(Paragraph(f"Extracto de Cuentas Oficial - {titulo_reporte} | Emitido: {datetime.now().strftime('%d/%m/%Y %H:%M')}", s_st)); story.append(Spacer(1, 14))
    t_datos = [[Paragraph("<b><font color='white'>Fecha</font></b>", n_st), Paragraph("<b><font color='white'>Tipo</font></b>", n_st), Paragraph("<b><font color='white'>Cuenta</font></b>", n_st), Paragraph("<b><font color='white'>Partida</font></b>", n_st), Paragraph("<b><font color='white'>Concepto / Detalle</font></b>", n_st), Paragraph("<b><font color='white'>Forma Pago</font></b>", n_st), Paragraph("<b><font color='white'>Importe</font></b>", n_st)]]
    t_ing, t_gas = 0.0, 0.0
    
    if agrupar:
        df_proc = df.sort_values(by=['Partida', 'Fecha'], ascending=[True, True])
        for part_nom, grupo in df_proc.groupby('Partida', sort=False):
            sub_ing, sub_gas = 0.0, 0.0
            for _, f in grupo.iterrows():
                v = float(f.get('Importe (€)')); v_str = f"-{v:,.2f} €" if f.get('Tipo') == 'Gasto' else f"{v:,.2f} €"
                if f.get('Tipo') == 'Gasto': t_gas += v; sub_gas += v
                else: t_ing += v; sub_ing += v
                t_datos.append([Paragraph(str(f.get('Fecha'))[:16], n_st), Paragraph(str(f.get('Tipo')), n_st), Paragraph(str(f.get('Cuenta')), n_st), Paragraph(str(f.get('Partida'))[:28], n_st), Paragraph(str(f.get('Concepto'))[:55], n_st), Paragraph(str(f.get('Forma Pago')), n_st), Paragraph(v_str, n_st)])
            sub_neto = sub_ing - sub_gas
            sub_str = f"-{abs(sub_neto):,.2f} €" if sub_neto < 0 else f"{sub_neto:,.2f} €"
            t_datos.append([Paragraph(f"<b>SUBTOTAL {str(part_nom).upper()}</b>", n_st), "", "", "", "", "", Paragraph(f"<b>{sub_str}</b>", n_st)])
    else:
        for _, f in df.iterrows():
            v = float(f.get('Importe (€)')); v_str = f"-{v:,.2f} €" if f.get('Tipo') == 'Gasto' else f"{v:,.2f} €"
            if f.get('Tipo') == 'Gasto': t_gas += v
            else: t_ing += v
            t_datos.append([Paragraph(str(f.get('Fecha'))[:16], n_st), Paragraph(str(f.get('Tipo')), n_st), Paragraph(str(f.get('Cuenta')), n_st), Paragraph(str(f.get('Partida'))[:28], n_st), Paragraph(str(f.get('Concepto'))[:55], n_st), Paragraph(str(f.get('Forma Pago')), n_st), Paragraph(v_str, n_st)])
            
    t_datos.append([Paragraph("<b>TOTAL INGRESOS FILTRADOS</b>", n_st), "", "", "", "", "", Paragraph(f"<b>{t_ing:,.2f} €</b>", n_st)])
    t_datos.append([Paragraph("<b>TOTAL GASTOS FILTRADOS</b>", n_st), "", "", "", "", "", Paragraph(f"<b>-{t_gas:,.2f} €</b>", n_st)])
    t_datos.append([Paragraph("<b>RESULTADO NETO DEL EXTRACTO</b>", n_st), "", "", "", "", "", Paragraph(f"<b>{(t_ing - t_gas):,.2f} €</b>", n_st)])
    t = RLTable(t_datos, colWidths=(75, 45, 45, 120, 250, 115, 70)); t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('BOTTOMPADDING', (0,0), (-1,-1), 4), ('TOPPADDING', (0,0), (-1,-1), 4), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('LINEABOVE', (0,-3), (-1,-3), 1.2, burdeos)])); story.append(t)

    try:
        df_t_pdf = leer_tabla_turso("SELECT id, fecha, origen, destino, importe, concepto FROM traspasos_internos ORDER BY id ASC")
        if not df_t_pdf.empty:
            story.append(Spacer(1, 18))
            story.append(Paragraph("<b>MOVIMIENTOS INTERNOS DE TESORERÍA (TRASPASOS ENTRE CAJA Y BANCO)</b>", ParagraphStyle('SubT', parent=styles['Normal'], fontSize=9, textColor=burdeos)))
            story.append(Spacer(1, 6))
            t_trasp = [[Paragraph("<b><font color='white'>Nº</font></b>", n_st), Paragraph("<b><font color='white'>Fecha</font></b>", n_st), Paragraph("<b><font color='white'>Origen</font></b>", n_st), Paragraph("<b><font color='white'>Destino</font></b>", n_st), Paragraph("<b><font color='white'>Motivo / Concepto</font></b>", n_st), Paragraph("<b><font color='white'>Importe</font></b>", n_st)]]
            for _, ft in df_t_pdf.iterrows():
                t_trasp.append([Paragraph(f"#{ft.get('id')}", n_st), Paragraph(str(ft.get('fecha'))[:16], n_st), Paragraph(str(ft.get('origen')), n_st), Paragraph(str(ft.get('destino')), n_st), Paragraph(str(ft.get('concepto'))[:65], n_st), Paragraph(f"{float(ft.get('importe')):,.2f} €", n_st)])
            tt = RLTable(t_trasp, colWidths=(45, 85, 75, 75, 360, 80)); tt.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('BOTTOMPADDING', (0,0), (-1,-1), 4), ('TOPPADDING', (0,0), (-1,-1), 4), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')])); story.append(tt)
    except:
        pass

    doc.build(story, onFirstPage=marca_agua_horizontal, onLaterPages=marca_agua_horizontal); buf.seek(0); return buf
def generar_pdf_cierre(df, anio, c_ini, b_ini, c_fin, b_fin):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30); story = list(); styles = getSampleStyleSheet(); burdeos = colors.HexColor("#800020")
    t_st = ParagraphStyle('T', parent=styles['Heading1'], fontSize=16, leading=20, alignment=1, textColor=burdeos); s_st = ParagraphStyle('S', parent=styles['Normal'], fontSize=10, leading=13, alignment=1, textColor=colors.gray); n_st = ParagraphStyle('N', parent=styles['Normal'], fontSize=8, leading=11); b_st = ParagraphStyle('B', parent=styles['Normal'], fontSize=9, leading=12)
    if os.path.exists("escudo.png"):
        try: img = RLImage("escudo.png", width=65, height=65); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 6))
        except: pass
    story.append(Paragraph("<b>HERMANDAD DE NUESTRA SEÑORA DE LOS DESAMPARADOS</b>", t_st))
    story.append(Paragraph(f"<b>ACTA OFICIAL DE CIERRE DE EJERCICIO CONTABLE — AÑO {anio}</b>", ParagraphStyle('SubC', alignment=1, fontSize=11, textColor=burdeos)))
    story.append(Paragraph(f"Documento emitido el: {datetime.now().strftime('%d/%m/%Y %H:%M')}", s_st)); story.append(Spacer(1, 14))
    t_ing = df.loc[df['Tipo'] == 'Ingreso', 'Importe (€)'].sum(); t_gas = df.loc[df['Tipo'] == 'Gasto', 'Importe (€)'].sum()
    ing_c = df.loc[(df['Cuenta']=='Caja') & (df['Tipo']=='Ingreso'), 'Importe (€)'].sum(); ing_b = df.loc[(df['Cuenta']=='Banco') & (df['Tipo']=='Ingreso'), 'Importe (€)'].sum()
    gas_c = df.loc[(df['Cuenta']=='Caja') & (df['Tipo']=='Gasto'), 'Importe (€)'].sum(); gas_b = df.loc[(df['Cuenta']=='Banco') & (df['Tipo']=='Gasto'), 'Importe (€)'].sum()
    res_data = [[Paragraph("<b><font color='white'>CONCEPTO DE TESORERÍA</font></b>", b_st), Paragraph("<b><font color='white'>CAJA FÍSICA</font></b>", b_st), Paragraph("<b><font color='white'>CUENTA BANCARIA</font></b>", b_st), Paragraph("<b><font color='white'>TOTAL COFRADÍA</font></b>", b_st)], [Paragraph("Saldo Inicial de Apertura", b_st), Paragraph(f"{c_ini:,.2f} €", b_st), Paragraph(f"{b_ini:,.2f} €", b_st), Paragraph(f"{(c_ini + b_ini):,.2f} €", b_st)], [Paragraph("Total Ingresos del Ejercicio", b_st), Paragraph(f"+{ing_c:,.2f} €", b_st), Paragraph(f"+{ing_b:,.2f} €", b_st), Paragraph(f"+{t_ing:,.2f} €", b_st)], [Paragraph("Total Gastos del Ejercicio", b_st), Paragraph(f"-{gas_c:,.2f} €", b_st), Paragraph(f"-{gas_b:,.2f} €", b_st), Paragraph(f"-{t_gas:,.2f} €", b_st)], [Paragraph("<b>SALDO FINAL AL CIERRE (Traspasado a Nuevo Curso)</b>", b_st), Paragraph(f"<b>{c_fin:,.2f} €</b>", b_st), Paragraph(f"<b>{b_fin:,.2f} €</b>", b_st), Paragraph(f"<b>{(c_fin + b_fin):,.2f} €</b>", b_st)]]
    tr = RLTable(res_data, colWidths=(280, 145, 145, 150)); tr.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('GRID', (0,0), (-1,-1), 0.6, colors.grey), ('PADDING', (0,0), (-1,-1), 6), ('LINEABOVE', (0,-1), (-1,-1), 1.5, burdeos)])); story.append(tr); story.append(Spacer(1, 18))
    story.append(Paragraph("<b>DETALLE COMPLETO DE MOVIMIENTOS DEL EJERCICIO CERRADO</b>", b_st)); story.append(Spacer(1, 6))
    t_datos = [[Paragraph("<b><font color='white'>Fecha</font></b>", n_st), Paragraph("<b><font color='white'>Tipo</font></b>", n_st), Paragraph("<b><font color='white'>Cuenta</font></b>", n_st), Paragraph("<b><font color='white'>Partida</font></b>", n_st), Paragraph("<b><font color='white'>Concepto / Detalle</font></b>", n_st), Paragraph("<b><font color='white'>Forma Pago</font></b>", n_st), Paragraph("<b><font color='white'>Importe</font></b>", n_st)]]
    for _, f in df.sort_values(by="id", ascending=True).iterrows():
        v = f.get('Importe (€)'); v_str = f"-{v:,.2f} €" if f.get('Tipo') == 'Gasto' else f"{v:,.2f} €"
        t_datos.append([Paragraph(str(f.get('Fecha'))[:16], n_st), Paragraph(str(f.get('Tipo')), n_st), Paragraph(str(f.get('Cuenta')), n_st), Paragraph(str(f.get('Partida'))[:26], n_st), Paragraph(str(f.get('Concepto'))[:52], n_st), Paragraph(str(f.get('Forma Pago')), n_st), Paragraph(v_str, n_st)])
    tm = RLTable(t_datos, colWidths=(75, 45, 45, 120, 250, 115, 70)); tm.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('PADDING', (0,0), (-1,-1), 4), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')])); story.append(tm); story.append(Spacer(1, 35))
    tf = RLTable([[Paragraph("<b>___________________________</b><br/>Vº Bº El Hermano Mayor", ParagraphStyle('F1', alignment=1, fontSize=9)), Paragraph("<b>___________________________</b><br/>El Mayordomo", ParagraphStyle('F2', alignment=1, fontSize=9)), Paragraph("<b>___________________________</b><br/>El Secretario", ParagraphStyle('F3', alignment=1, fontSize=9))]], colWidths=(240, 240, 240)); tf.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')])); story.append(tf)
    doc.build(story, onFirstPage=marca_agua_horizontal, onLaterPages=marca_agua_horizontal); buf.seek(0); return buf
def generar_pdf_presupuesto(df, tipo_comp):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=35, bottomMargin=35); story = list(); styles = getSampleStyleSheet(); burdeos = colors.HexColor("#800020")
    t_st = ParagraphStyle('T', parent=styles['Heading1'], fontSize=15, leading=18, alignment=1, textColor=burdeos); s_st = ParagraphStyle('S', parent=styles['Normal'], fontSize=9, leading=12, alignment=1, textColor=colors.gray); n_st = ParagraphStyle('N', parent=styles['Normal'], fontSize=9, leading=12)
    if os.path.exists("escudo.png"):
        try: img = RLImage("escudo.png", width=65, height=65); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 6))
        except: pass
    story.append(Paragraph("<b>HERMANDAD DE NUESTRA SEÑORA DE LOS DESAMPARADOS</b>", t_st))
    story.append(Paragraph(f"Estado Comparativo Presupuestado vs Ejecutado ({tipo_comp}s)", ParagraphStyle('SubP', alignment=1, fontSize=11, textColor=burdeos)))
    story.append(Paragraph(f"Documento emitido el: {datetime.now().strftime('%d/%m/%Y %H:%M')}", s_st)); story.append(Spacer(1, 18))
    t_datos = [[Paragraph("<b><font color='white'>Partida / Concepto</font></b>", n_st), Paragraph("<b><font color='white'>Presupuestado</font></b>", n_st), Paragraph("<b><font color='white'>Ejecutado</font></b>", n_st), Paragraph("<b><font color='white'>Diferencia</font></b>", n_st)]]
    for idx, f in df.iterrows():
        es_tot = (idx == len(df) - 1)
        p_txt = f"<b>{f.get('Partida')}</b>" if es_tot else str(f.get('Partida'))
        pr_txt = f"<b>{f.get('Presupuestado (€)'):,.2f} €</b>" if es_tot else f"{f.get('Presupuestado (€)'):,.2f} €"
        ej_txt = f"<b>{f.get('Ejecutado (€)'):,.2f} €</b>" if es_tot else f"{f.get('Ejecutado (€)'):,.2f} €"
        df_txt = f"<b>{f.get('Diferencia (€)'):,.2f} €</b>" if es_tot else f"{f.get('Diferencia (€)'):,.2f} €"
        t_datos.append([Paragraph(p_txt, n_st), Paragraph(pr_txt, n_st), Paragraph(ej_txt, n_st), Paragraph(df_txt, n_st)])
    t = RLTable(t_datos, colWidths=(230, 100, 100, 100)); t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('PADDING', (0,0), (-1,-1), 6), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('LINEABOVE', (0,-1), (-1,-1), 1.5, burdeos)])); story.append(t); story.append(Spacer(1, 45))
    tf = RLTable([[Paragraph("<b>___________________________</b><br/>Vº Bº El Hermano Mayor", ParagraphStyle('F1', alignment=1, fontSize=9)), Paragraph("<b>___________________________</b><br/>El Mayordomo", ParagraphStyle('F2', alignment=1, fontSize=9))]], colWidths=(265, 265)); tf.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')])); story.append(tf)
    doc.build(story, onFirstPage=marca_agua_vertical, onLaterPages=marca_agua_vertical); buf.seek(0); return buf

def generar_pdf_presupuesto_global(df_ing, df_gas):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=30, bottomMargin=30); story = list(); styles = getSampleStyleSheet(); burdeos = colors.HexColor("#800020")
    t_st = ParagraphStyle('T', parent=styles['Heading1'], fontSize=14, leading=17, alignment=1, textColor=burdeos); s_st = ParagraphStyle('S', parent=styles['Normal'], fontSize=8, leading=11, alignment=1, textColor=colors.gray); n_st = ParagraphStyle('N', parent=styles['Normal'], fontSize=8, leading=10); b_st = ParagraphStyle('B', parent=styles['Normal'], fontSize=9, leading=11)
    if os.path.exists("escudo.png"):
        try: img = RLImage("escudo.png", width=55, height=55); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 4))
        except: pass
    story.append(Paragraph("<b>HERMANDAD DE NUESTRA SEÑORA DE LOS DESAMPARADOS</b>", t_st))
    story.append(Paragraph("<b>ESTADO COMPARATIVO PRESUPUESTARIO GLOBAL (CABILDO GENERAL)</b>", ParagraphStyle('SubPG', alignment=1, fontSize=10, textColor=burdeos)))
    story.append(Paragraph(f"Documento emitido el: {datetime.now().strftime('%d/%m/%Y %H:%M')}", s_st)); story.append(Spacer(1, 10))
    for titulo_sec, df_sec in [("1. ESTADO DE INGRESOS", df_ing), ("2. ESTADO DE GASTOS", df_gas)]:
        story.append(Paragraph(f"<b>{titulo_sec}</b>", b_st)); story.append(Spacer(1, 4))
        t_datos = [[Paragraph("<b><font color='white'>Partida / Concepto</font></b>", n_st), Paragraph("<b><font color='white'>Presupuestado</font></b>", n_st), Paragraph("<b><font color='white'>Ejecutado</font></b>", n_st), Paragraph("<b><font color='white'>Diferencia</font></b>", n_st)]]
        for idx, f in df_sec.iterrows():
            es_tot = (idx == len(df_sec) - 1)
            p_txt = f"<b>{f.get('Partida')}</b>" if es_tot else str(f.get('Partida'))
            pr_txt = f"<b>{f.get('Presupuestado (€)'):,.2f} €</b>" if es_tot else f"{f.get('Presupuestado (€)'):,.2f} €"
            ej_txt = f"<b>{f.get('Ejecutado (€)'):,.2f} €</b>" if es_tot else f"{f.get('Ejecutado (€)'):,.2f} €"
            df_txt = f"<b>{f.get('Diferencia (€)'):,.2f} €</b>" if es_tot else f"{f.get('Diferencia (€)'):,.2f} €"
            t_datos.append([Paragraph(p_txt, n_st), Paragraph(pr_txt, n_st), Paragraph(ej_txt, n_st), Paragraph(df_txt, n_st)])
        t = RLTable(t_datos, colWidths=(230, 100, 100, 100)); t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('PADDING', (0,0), (-1,-1), 4), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('LINEABOVE', (0,-1), (-1,-1), 1.2, burdeos)])); story.append(t); story.append(Spacer(1, 12))
    ing_p = float(df_ing.iloc[-1].get('Presupuestado (€)')); ing_e = float(df_ing.iloc[-1].get('Ejecutado (€)'))
    gas_p = float(df_gas.iloc[-1].get('Presupuestado (€)')); gas_e = float(df_gas.iloc[-1].get('Ejecutado (€)'))
    res_p = ing_p - gas_p; res_e = ing_e - gas_e; res_d = res_e - res_p
    story.append(Paragraph("<b>3. RESULTADO PRESUPUESTARIO GLOBAL (INGRESOS - GASTOS)</b>", b_st)); story.append(Spacer(1, 4))
    t_res = [[Paragraph("<b><font color='white'>CONCEPTO</font></b>", n_st), Paragraph("<b><font color='white'>PRESUPUESTADO</font></b>", n_st), Paragraph("<b><font color='white'>EJECUTADO</font></b>", n_st), Paragraph("<b><font color='white'>DESVIACIÓN</font></b>", n_st)], [Paragraph("<b>SUPERÁVIT / DÉFICIT DEL EJERCICIO</b>", n_st), Paragraph(f"<b>{res_p:,.2f} €</b>", n_st), Paragraph(f"<b>{res_e:,.2f} €</b>", n_st), Paragraph(f"<b>{res_d:,.2f} €</b>", n_st)]]
    tr = RLTable(t_res, colWidths=(230, 100, 100, 100)); tr.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('PADDING', (0,0), (-1,-1), 5), ('GRID', (0,0), (-1,-1), 0.6, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')])); story.append(tr); story.append(Spacer(1, 25))
    tf = RLTable([[Paragraph("<b>___________________________</b><br/>Vº Bº El Hermano Mayor", ParagraphStyle('F1', alignment=1, fontSize=8)), Paragraph("<b>___________________________</b><br/>El Mayordomo", ParagraphStyle('F2', alignment=1, fontSize=8)), Paragraph("<b>___________________________</b><br/>El Secretario", ParagraphStyle('F3', alignment=1, fontSize=8))]], colWidths=(176, 176, 176)); tf.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')])); story.append(tf)
    doc.build(story, onFirstPage=marca_agua_vertical, onLaterPages=marca_agua_vertical); buf.seek(0); return buf
def generar_informe_arzobispado(df_global, dict_pres):
    gastos_grupos = [
        ("LH", "COMPRAS (para vender)"), ("MH", "GASTOS DE PERSONAL"), ("NH", "SUBSIDIO SACERDOTE (Estipendio)"),
        ("OH", "GASTOS FINANCIEROS"), ("PH", "IMPUESTOS Y TASAS"), ("QH", "SUMINISTROS Y CONSERVACIÓN"),
        ("RH", "SALIDA DE LA COFRADÍA"), ("SH", "GASTOS DE FUNCIONAMIENTO"), ("TH", "ACTIVIDADES PASTORALES Y ASIST"),
        ("UH", "OTROS"), ("VH", "COMUNICACIÓN DE BIENES")
    ]
    ing_ord_grupos = [
        ("AH", "POR SERVICIOS"), ("BH", "RENTAS DEL PATRIMONIO INMOB."), ("CH", "RENTAS DEL PATRIMONIO MOB."),
        ("DH", "APORTACIÓN DE LOS FIELES"), ("EH", "DONATIVOS Y LIMOSNAS"), ("IH", "ACTIVIDADES ECONOMICAS")
    ]
    ing_no_ord_grupos = [
        ("FH", "SUBVENCIONES"), ("GH", "OBRAS ASISTENCIALES"), ("HH", "OTROS INGRESOS")
    ]
    
    todos_codigos_2 = {c: n for c, n in (gastos_grupos + ing_ord_grupos + ing_no_ord_grupos)}
    subgrupos_data = {c: {"p": 0.0, "r": 0.0, "hijos": list()} for c in todos_codigos_2}
    filas_detalle = list()
    
    for tipo_op in ["Gasto", "Ingreso"]:
        for p in obtener_partidas(tipo_op):
            p_str = str(p).strip()
            partes = p_str.split(" - ", 1)
            cod_part = partes[0].strip() if len(partes) > 1 else p_str[:3].strip()
            nom_sub = partes[1].strip() if len(partes) > 1 else p_str
            cod_2 = cod_part[:2].upper()
            
            pres_v = float(dict_pres.get(p, 0.0))
            real_v = float(df_global.loc[(df_global['Tipo'] == tipo_op) & (df_global['Partida'] == p), 'Importe (€)'].sum()) if not df_global.empty else 0.0
            filas_detalle.append({"Tipo": tipo_op.upper(), "Grupo": cod_2, "Cuenta": cod_part, "Nombre": nom_sub, "Presupuesto (€)": pres_v, "Real (€)": real_v})
            
            if cod_2 in subgrupos_data:
                subgrupos_data[cod_2]["p"] += pres_v
                subgrupos_data[cod_2]["r"] += real_v
                if len(cod_part) > 2:
                    subgrupos_data[cod_2]["hijos"].append((cod_part, nom_sub, real_v))

    filas_resumen = list()
    for sec_nom, lista_g in [("GASTOS", gastos_grupos), ("INGRESOS ORDINARIOS", ing_ord_grupos), ("INGRESOS NO ORDINARIOS", ing_no_ord_grupos)]:
        for c2, nom2 in lista_g:
            filas_resumen.append({"Bloque": sec_nom, "Código": c2, "Concepto Oficial": nom2, "Presupuesto (€)": subgrupos_data[c2]["p"], "Real (€)": subgrupos_data[c2]["r"]})
            
    df_res3 = pd.DataFrame(filas_resumen)
    df_det = pd.DataFrame(filas_detalle)
    
    buf_ex = io.BytesIO()
    with pd.ExcelWriter(buf_ex, engine='openpyxl') as writer:
        df_res3.to_excel(writer, index=False, sheet_name='Resumen_Palacio_2_Letras')
        df_det.to_excel(writer, index=False, sheet_name='Desglose_Subcuentas')
    buf_ex.seek(0)
    def construir_pdf_palacio(desarrollado=False):
        b_pdf = io.BytesIO()
        doc = SimpleDocTemplate(b_pdf, pagesize=letter, rightMargin=32, leftMargin=32, topMargin=28, bottomMargin=28)
        story = list(); styles = getSampleStyleSheet(); burdeos = colors.HexColor("#800020"); gris_suave = colors.HexColor("#E5E7EB")
        t_st = ParagraphStyle('T', parent=styles['Heading1'], fontSize=13, leading=16, alignment=1, textColor=burdeos)
        n_st = ParagraphStyle('N', parent=styles['Normal'], fontSize=8, leading=10.5)
        n_der = ParagraphStyle('ND', parent=styles['Normal'], fontSize=8, leading=10.5, alignment=2)
        
        if os.path.exists("escudo.png"):
            try: img = RLImage("escudo.png", width=48, height=48); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 4))
            except: pass
        story.append(Paragraph("<b>ARCHIDIÓCESIS DE SEVILLA — PROTECTORADO CANÓNICO DE HH. Y CC.</b>", t_st))
        story.append(Paragraph(f"<b>HERMANDAD DE NUESTRA SEÑORA DE LOS DESAMPARADOS — EJERCICIO {date.today().year}</b>", ParagraphStyle('SubA', alignment=1, fontSize=9.5, textColor=burdeos)))
        story.append(Spacer(1, 8))

        tot_gas = sum(subgrupos_data[c]["r"] for c, _ in gastos_grupos)
        tot_ing_ord = sum(subgrupos_data[c]["r"] for c, _ in ing_ord_grupos)
        tot_ing_no = sum(subgrupos_data[c]["r"] for c, _ in ing_no_ord_grupos)
        tot_ing_gen = tot_ing_ord + tot_ing_no

        if not desarrollado:
            story.append(Paragraph("<b>RESUMEN DE CUENTAS ANUALES (MODELO PALACIO ARZOBISPAL)</b>", ParagraphStyle('R1', alignment=1, fontSize=10)))
            story.append(Spacer(1, 8))
            t_res = [[Paragraph("<b><font color='white'>Cód.</font></b>", n_st), Paragraph("<b><font color='white'>GASTOS</font></b>", n_st), Paragraph("<b><font color='white'>Importe</font></b>", n_der), Paragraph("<b><font color='white'>Cód.</font></b>", n_st), Paragraph("<b><font color='white'>INGRESOS</font></b>", n_st), Paragraph("<b><font color='white'>Importe</font></b>", n_der)]]
            der_rows = [("---", "<b>INGRESOS ORDINARIOS</b>", "")] + [(c, n, f"{subgrupos_data[c]['r']:,.2f} €") for c, n in ing_ord_grupos] + [("", "<b>TOTAL INGRESOS ORDINARIOS</b>", f"<b>{tot_ing_ord:,.2f} €</b>"), ("---", "<b>INGRESOS NO ORDINARIOS</b>", "")] + [(c, n, f"{subgrupos_data[c]['r']:,.2f} €") for c, n in ing_no_ord_grupos] + [("", "<b>TOTAL INGRESOS NO ORDINARIOS</b>", f"<b>{tot_ing_no:,.2f} €</b>")]
            izq_rows = [(c, n, f"{subgrupos_data[c]['r']:,.2f} €") for c, n in gastos_grupos] + [("", "<b>TOTAL GASTOS</b>", f"<b>{tot_gas:,.2f} €</b>")]
            max_r = max(len(izq_rows), len(der_rows))
            for i in range(max_r):
                iz = izq_rows[i] if i < len(izq_rows) else ("", "", "")
                de = der_rows[i] if i < len(der_rows) else ("", "", "")
                t_res.append([Paragraph(f"<b>{iz[0]}</b>", n_st), Paragraph(iz[1], n_st), Paragraph(iz[2], n_der), Paragraph(f"<b>{de[0]}</b>", n_st), Paragraph(de[1], n_st), Paragraph(de[2], n_der)])
            tr_tbl = RLTable(t_res, colWidths=(32, 165, 68, 32, 165, 68))
            tr_tbl.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('PADDING', (0,0), (-1,-1), 4), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
            story.append(tr_tbl); story.append(Spacer(1, 12))
            
            t_cuadre = [
                [Paragraph("<b>Resultado del Ejercicio anterior (Saldos Iniciales Caja + Banco)</b>", n_st), Paragraph(f"<b>{(caja_ini + banco_ini):,.2f} €</b>", n_der)],
                [Paragraph("<b>Total de ingresos (ordinarios + no ordinarios)</b>", n_st), Paragraph(f"<b>{tot_ing_gen:,.2f} €</b>", n_der)],
                [Paragraph("<b>Total de gastos</b>", n_st), Paragraph(f"<b>{tot_gas:,.2f} €</b>", n_der)],
                [Paragraph("<b>Resultado (resultado ejercicio anterior + total ingresos - total gastos)</b>", n_st), Paragraph(f"<b>{(caja_ini + banco_ini + tot_ing_gen - tot_gas):,.2f} €</b>", n_der)]
            ]
            tc_tbl = RLTable(t_cuadre, colWidths=(420, 110))
            tc_tbl.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.6, burdeos), ('BACKGROUND', (0,3), (-1,3), colors.HexColor("#FDF2F2")), ('PADDING', (0,0), (-1,-1), 5)]))
            story.append(tc_tbl)
        else:
            for titulo_b, lista_b, tot_b in [("DESGLOSE DE GASTOS", gastos_grupos, tot_gas), ("DESGLOSE DE INGRESOS ORDINARIOS", ing_ord_grupos, tot_ing_ord), ("DESGLOSE DE INGRESOS NO ORDINARIOS", ing_no_ord_grupos, tot_ing_no)]:
                story.append(Paragraph(f"<b>{titulo_b}</b>", ParagraphStyle('B1', fontSize=9.5, textColor=burdeos)))
                story.append(Spacer(1, 4))
                t_des = [[Paragraph("<b><font color='white'>Cód.</font></b>", n_st), Paragraph("<b><font color='white'>Concepto / Subcuenta</font></b>", n_st), Paragraph("<b><font color='white'>Subcuenta</font></b>", n_der), Paragraph("<b><font color='white'>Total Grupo</font></b>", n_der)]]
                est_d = list(); r_i = 1
                for c2, nom2 in lista_b:
                    t_des.append([Paragraph(f"<b>{c2}</b>", n_st), Paragraph(f"<b>{c2} - {nom2}</b>", n_st), "", Paragraph(f"<b>{subgrupos_data[c2]['r']:,.2f} €</b>", n_der)])
                    est_d.append(('BACKGROUND', (0, r_i), (-1, r_i), gris_suave))
                    r_i += 1
                    for hc, hn, hv in subgrupos_data[c2]["hijos"]:
                        t_des.append([Paragraph(hc, n_st), Paragraph(hn, n_st), Paragraph(f"{hv:,.2f} €", n_der), ""])
                        r_i += 1
                t_des.append(["", Paragraph(f"<b>TOTAL {titulo_b.replace('DESGLOSE DE ', '')}</b>", n_st), "", Paragraph(f"<b>{tot_b:,.2f} €</b>", n_der)])
                est_d.append(('BACKGROUND', (0, r_i), (-1, r_i), colors.HexColor("#FDF2F2")))
                td_tbl = RLTable(t_des, colWidths=(45, 335, 75, 75))
                td_tbl.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('GRID', (0,0), (-1,-1), 0.4, colors.grey), ('PADDING', (0,0), (-1,-1), 3.5)] + est_d))
                story.append(td_tbl); story.append(Spacer(1, 10))

        story.append(PageBreak())
        story.append(Paragraph(f"<b>ESTADO FINANCIERO AL 31 DE DICIEMBRE DE {date.today().year}</b>", t_st))
        story.append(Spacer(1, 12))
        pend_cobrar = float(df_global.loc[(df_global['Tipo'] == 'Ingreso') & (df_global['Pendiente'] == 1), 'Importe (€)'].sum()) if not df_global.empty else 0.0
        pend_pagar = float(df_global.loc[(df_global['Tipo'] == 'Gasto') & (df_global['Pendiente'] == 1), 'Importe (€)'].sum()) if not df_global.empty else 0.0
        
        t_ef = [
            [Paragraph("<b><font color='white'>ACTIVO / TESORERÍA</font></b>", n_st), Paragraph("<b><font color='white'>Importe</font></b>", n_der), Paragraph("<b><font color='white'>PASIVO / DEUDAS</font></b>", n_st), Paragraph("<b><font color='white'>Importe</font></b>", n_der)],
            [Paragraph("Saldo en Caja", n_st), Paragraph(f"{s_caja:,.2f} €", n_der), Paragraph("Préstamos recibidos", n_st), Paragraph("0,00 €", n_der)],
            [Paragraph("Saldo en Banco", n_st), Paragraph(f"{s_banco:,.2f} €", n_der), Paragraph("Cuentas Pendientes de pagar", n_st), Paragraph(f"{pend_pagar:,.2f} €", n_der)],
            [Paragraph("Depósitos e IPF", n_st), Paragraph("0,00 €", n_der), Paragraph("Deuda con Seguridad Social", n_st), Paragraph("0,00 €", n_der)],
            [Paragraph("Inversiones en Fondos Públicos", n_st), Paragraph("0,00 €", n_der), Paragraph("Deuda con la Agencia Tributaria", n_st), Paragraph("0,00 €", n_der)],
            [Paragraph("Inversiones en Bolsa de Valores", n_st), Paragraph("0,00 €", n_der), Paragraph("Deuda con otras entidades públicas", n_st), Paragraph("0,00 €", n_der)],
            [Paragraph("Cuentas pendientes de cobrar", n_st), Paragraph(f"{pend_cobrar:,.2f} €", n_der), "", ""],
            [Paragraph("Préstamos concedidos", n_st), Paragraph("0,00 €", n_der), "", ""]
        ]
        tef_tbl = RLTable(t_ef, colWidths=(185, 80, 185, 80))
        tef_tbl.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), burdeos), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('PADDING', (0,0), (-1,-1), 6)]))
        story.append(tef_tbl); story.append(Spacer(1, 45))
        
        tf = RLTable([[Paragraph("<b>Mayordomo</b><br/><br/><br/>Fdo: _________________________", ParagraphStyle('F1', alignment=1, fontSize=9)), Paragraph("<b>Hermano Mayor</b><br/><br/><br/>Fdo: _________________________", ParagraphStyle('F2', alignment=1, fontSize=9))]], colWidths=(265, 265))
        tf.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        story.append(tf); story.append(Spacer(1, 30))
        story.append(Paragraph("Sello de la Hermandad<br/><br/>En Sevilla, a _____ de ___________________ de 20____.", ParagraphStyle('Sel', alignment=1, fontSize=9)))
        story.append(Spacer(1, 20))
        story.append(Paragraph("<b>Delegado Episcopal Asuntos Jurídicos HH y CC — Protectorado Canónico de la Archidiócesis de Sevilla</b>", ParagraphStyle('Pie', alignment=1, fontSize=8, textColor=colors.gray)))
        
        doc.build(story, onFirstPage=marca_agua_vertical, onLaterPages=marca_agua_vertical)
        b_pdf.seek(0)
        return b_pdf

    return df_res3, df_det, buf_ex, construir_pdf_palacio(desarrollado=False), construir_pdf_palacio(desarrollado=True)

def dibujar_tabla_movimientos(df_f):
    total_regs = len(df_f)
    por_pagina = 25
    total_paginas = max(1, (total_regs + por_pagina - 1) // por_pagina)
    
    if total_paginas > 1:
        col_pag1, col_pag2 = st.columns((1.5, 3))
        pagina_actual = col_pag1.number_input(f"Página (1 a {total_paginas}):", min_value=1, max_value=total_paginas, value=1, step=1, key="pag_diario")
        col_pag2.caption(f"Mostrando bloques de {por_pagina} apuntes para máxima fluidez (Total filtrados: {total_regs}).")
    else:
        pagina_actual = 1
        
    inicio = (pagina_actual - 1) * por_pagina
    fin = inicio + por_pagina
    df_pagina = df_f.iloc[inicio:fin]

    for idx, row in df_pagina.iterrows():
        r_id = row.get('id'); r_tipo = row.get('Tipo'); r_cue = row.get('Cuenta'); r_par = row.get('Partida'); r_prov = str(row.get('Proveedor', '') or '').strip(); r_fac = str(row.get('Nº Factura', '') or '').strip(); r_con = row.get('Concepto'); r_fec = row.get('Fecha'); r_pag = row.get('Forma Pago'); r_imp = float(row.get('Importe (€)')); r_com = row.get('Comprobante')
        es_pend = int(row.get('Pendiente', 0)) if pd.notna(row.get('Pendiente')) else 0

        with st.container(border=True):
            ca, cb, cc, cd = st.columns((0.6, 4.4, 1.5, 2.5))
            ca.markdown(f"**#{r_id}**")
            txt_p = " <span style='color:#d97706; font-weight:bold; font-size:11px; background:#fef3c7; padding:2px 6px; border-radius:3px;'>⏳ PENDIENTE</span>" if es_pend == 1 else ""
            txt_prov = f" <span style='color:#800020; font-weight:bold;'>[{r_prov}]</span>" if r_prov else ""
            txt_fac = f" <span style='color:#4b5563; font-size:11.5px; background:#f3f4f6; padding:1px 5px; border-radius:3px;'>Doc: {r_fac}</span>" if r_fac else ""
            cb.markdown(f"**{r_par}**{txt_prov}{txt_fac} - {r_con}{txt_p}<br/><small style='color:gray;'>{r_fec} | {r_pag} ({r_cue})</small>", unsafe_allow_html=True)
            c_val = "green" if r_tipo == 'Ingreso' else "red"
            cc.markdown(f"<h4 style='color:{c_val}; margin:0;'>{r_imp:,.2f} €</h4>", unsafe_allow_html=True)
            
            txt_b = "📥 Preparar Justificante" if r_tipo == 'Ingreso' else "📄 Preparar Recibí"
            if cd.button(txt_b, key=f"prep_pdf_{r_id}", use_container_width=True):
                st.session_state[f"pdf_listo_{r_id}"] = generar_pdf_recibo(row).getvalue()
            if f"pdf_listo_{r_id}" in st.session_state:
                cd.download_button(label="⬇️ Descargar PDF Listo", data=st.session_state[f"pdf_listo_{r_id}"], file_name=f"Justificante_{r_id}.pdf", mime="application/pdf", key=f"dl_pdf_{r_id}", use_container_width=True)
            
            if es_pend == 1:
                if cd.button("🟢 Marcar como Pagado/Cobrado", key=f"liq_{r_id}", use_container_width=True):
                    ejecutar_turso_http(f"UPDATE contabilidad SET pendiente = 0 WHERE id = {r_id}")
                    st.cache_data.clear()
                    st.rerun()
            elif r_com:
                if cd.button("📷 Cargar Ticket", key=f"prep_img_{r_id}", use_container_width=True):
                    st.session_state[f"img_lista_{r_id}"] = leer_archivo_nube(r_com)
                if st.session_state.get(f"img_lista_{r_id}"):
                    cd.download_button(label="⬇️ Descargar Ticket", data=st.session_state[f"img_lista_{r_id}"], file_name=r_com, key=f"dl_img_{r_id}", use_container_width=True)
            
            if cd.button("❌ Eliminar Asiento", key=f"del_{r_id}", use_container_width=True):
                borrar_registro(r_id)
                st.cache_data.clear()
                st.rerun()
def dibujar_tabla_traspasos(df_t):
    if df_t.empty:
        st.caption("No se han registrado traspasos internos de fondos en este ejercicio.")
        return
    df_t = df_t.sort_values(by="id", ascending=False)
    for idx, row in df_t.iterrows():
        t_id = row.get('id')
        t_fec = row.get('fecha')
        t_ori = row.get('origen')
        t_des = row.get('destino')
        t_imp = float(row.get('importe'))
        t_con = row.get('concepto')
        with st.container(border=True):
            cx, cy, cz = st.columns((1.2, 5.8, 3.0))
            cx.markdown(f"**🔄 #{t_id}**")
            cy.markdown(f"**Traspaso de Fondos:** {t_con}<br/><small style='color:gray;'>{t_fec} | Origen: <b>{t_ori}</b> &rarr; Destino: <b>{t_des}</b></small>", unsafe_allow_html=True)
            cz.markdown(f"<h4 style='color:#b45309; margin:0; text-align:right;'>{t_imp:,.2f} €</h4>", unsafe_allow_html=True)

    st.markdown("---")
    with st.expander("✏️ Editar o Eliminar un Traspaso Interno (por Nº #)", expanded=False):
        st.caption("Introduce el número del traspaso (ej: 1) para corregir su importe, dirección o eliminarlo.")
        id_t_ed = int(st.number_input("Número de Traspaso (#):", min_value=1, step=1, key="id_traspaso_ed"))
        df_t_sel = df_t.loc[df_t['id'] == id_t_ed]
        if not df_t_sel.empty:
            rt = df_t_sel.iloc[0]
            ct1, ct2 = st.columns(2)
            ed_t_fec = ct1.text_input("Fecha:", value=str(rt.get('fecha')), key=f"et_fec_{id_t_ed}")
            ed_t_ori = ct1.selectbox("Origen (Sale de):", ["Caja", "Banco"], index=0 if rt.get('origen') == "Caja" else 1, key=f"et_ori_{id_t_ed}")
            ed_t_des = "Banco" if ed_t_ori == "Caja" else "Caja"
            ct1.markdown(f"➡️ **Destino (Entra en):** `{ed_t_des}`")
            ed_t_imp = ct2.number_input("Importe (€):", value=float(rt.get('importe')), min_value=0.01, step=10.0, format="%.2f", key=f"et_imp_{id_t_ed}")
            ed_t_con = ct2.text_input("Motivo / Concepto:", value=str(rt.get('concepto')), key=f"et_con_{id_t_ed}")

            b_t1, b_t2 = st.columns(2)
            if b_t1.button("💾 Guardar Cambios del Traspaso", use_container_width=True, key=f"btn_sv_trasp_{id_t_ed}"):
                ejecutar_turso_http("UPDATE traspasos_internos SET fecha=?, origen=?, destino=?, importe=?, concepto=? WHERE id=?", (ed_t_fec, ed_t_ori, ed_t_des, ed_t_imp, ed_t_con.strip(), id_t_ed))
                st.success("Traspaso actualizado."); st.rerun()
            if b_t2.button("🗑️ Eliminar Traspaso", use_container_width=True, key=f"btn_dl_trasp_{id_t_ed}"):
                ejecutar_turso_http("DELETE FROM traspasos_internos WHERE id=?", (id_t_ed,))
                st.success("Traspaso eliminado."); st.rerun()
        else:
            st.caption("No existe ningún traspaso con ese número.")
conn = conectar_bd()
df_global = leer_tabla_turso("SELECT id, fecha as 'Fecha', tipo as 'Tipo', origen_destino as 'Cuenta', partida as 'Partida', COALESCE(proveedor, '') as 'Proveedor', concepto as 'Concepto', forma_pago as 'Forma Pago', importe as 'Importe (€)', comprobante as 'Comprobante', COALESCE(pendiente, 0) as 'Pendiente' FROM contabilidad WHERE COALESCE(eliminado, 0) = 0 ORDER BY id DESC")
cursor = conn.cursor(); cursor.execute("SELECT caja_inicio, banco_inicio FROM saldos_iniciales WHERE id = 1"); s_ini = cursor.fetchone()
if s_ini:
    caja_ini, banco_ini = s_ini
else:
    caja_ini, banco_ini = 0.0, 0.0

# --- REGENERACIÓN COMPLETA Y REPARADA DE SALDOS REALES ---
if "usr_activo" not in st.session_state: 
    st.session_state.usr_activo = "Mayordomo"

# Leemos los traspasos de fondos directamente desde la nube
df_traspasos_calc = leer_tabla_turso("SELECT origen, destino, importe FROM traspasos_internos")
if df_traspasos_calc.empty:
    df_traspasos_calc = pd.DataFrame(columns=['origen', 'destino', 'importe'])

# Leemos también los registros que están marcados expresamente como pendientes
cols_p, rows_p = ejecutar_turso_http("SELECT id FROM contabilidad WHERE COALESCE(pendiente, 0) = 1 AND COALESCE(eliminado, 0) = 0")
lista_pendientes = [f[0] for f in rows_p] if rows_p else []

# Calculamos Ingresos y Gastos usando estrictamente tu tabla df_global original
if df_global.empty:
    ing_caja, gas_caja = 0.0, 0.0
    ing_banco, gas_banco = 0.0, 0.0
else:
    # Filtramos la tabla excluyendo los asientos que estén pendientes de pago/cobro real
    df_liquidados = df_global.loc[~df_global['id'].isin(lista_pendientes)]
    
    ing_caja = df_liquidados.loc[(df_liquidados['Cuenta'] == 'Caja') & (df_liquidados['Tipo'] == 'Ingreso'), 'Importe (€)'].sum()
    gas_caja = df_liquidados.loc[(df_liquidados['Cuenta'] == 'Caja') & (df_liquidados['Tipo'] == 'Gasto'), 'Importe (€)'].sum()
    
    ing_banco = df_liquidados.loc[(df_liquidados['Cuenta'] == 'Banco') & (df_liquidados['Tipo'] == 'Ingreso'), 'Importe (€)'].sum()
    gas_banco = df_liquidados.loc[(df_liquidados['Cuenta'] == 'Banco') & (df_liquidados['Tipo'] == 'Gasto'), 'Importe (€)'].sum()

# Calculamos los traspasos internos realizados entre bolsillos
tr_in_c = df_traspasos_calc.loc[df_traspasos_calc['destino'] == 'Caja', 'importe'].sum()
tr_out_c = df_traspasos_calc.loc[df_traspasos_calc['origen'] == 'Caja', 'importe'].sum()

tr_in_b = df_traspasos_calc.loc[df_traspasos_calc['destino'] == 'Banco', 'importe'].sum()
tr_out_b = df_traspasos_calc.loc[df_traspasos_calc['origen'] == 'Banco', 'importe'].sum()

# Consolidación final de los tres marcadores de la cabecera
s_caja = caja_ini + ing_caja - gas_caja + tr_in_c - tr_out_c
s_banco = banco_ini + ing_banco - gas_banco + tr_in_b - tr_out_b
# --- FIN DEL REEMPLAZO DE LA CABECERA ---
# --- REPARACIÓN DE CABECERA, MODO MÓVIL AUTOMÁTICO Y SALDOS ---
if "usr_activo" not in st.session_state: 
    st.session_state.usr_activo = "Mayordomo"

# 1. Dibujamos el Escudo y el Título de la Hermandad
_esc_b64 = obtener_escudo_b64()
img_b64 = f'<img src="data:image/png;base64,{_esc_b64}" style="height: 85px; margin-right: 15px;">' if _esc_b64 else ""
st.markdown(f"<div style='display: flex; align-items: center; justify-content: center; padding: 5px 0;'>{img_b64}<div><h1 style='margin: 0; font-size: 24px; color: #800020;'>Hermandad de Nuestra Señora de los Desamparados</h1><p style='margin: 0; color: #6B7280; font-size: 12px; font-weight: bold; letter-spacing: 1.5px;'>MAYORDOMÍA INSTITUCIONAL (NUBE)</p></div></div>", unsafe_allow_html=True)
st.markdown("---")

# 2. DETECTOR DE MÓVIL (Fuerza la vista simplificada de forma automática)
_ua = st.context.headers.get("User-Agent", "").lower() if hasattr(st, "context") else ""
_es_movil = any(k in _ua for k in ("android", "iphone", "ipad", "mobile"))
modo_movil = st.toggle("📱 Activar Vista Móvil Simplificada (Registro Rápido)", value=_es_movil)

st.markdown("---")

# 3. Si es móvil, se muestra la vista móvil simplificada y se detiene aquí la carga
if modo_movil:
    cm1, cm2 = st.columns(2)
    cm1.metric("🏪 Caja Física", f"{s_caja:,.2f} €")
    cm2.metric("🏦 Banco", f"{s_banco:,.2f} €")
    st.markdown(f"**💰 Total Cofradía:** `{(s_caja + s_banco):,.2f} €`")
    st.markdown("---")
    st.markdown("#### ⚡ Apunte Rápido desde Móvil")
    m_tipo = st.radio("Operación:", ["Gasto", "Ingreso"], horizontal=True, key="m_tipo")
    m_cuenta = st.radio("Cuenta:", ["Caja", "Banco"], horizontal=True, key="m_cuenta")
    m_partida = st.selectbox("Concepto / Partida:", obtener_partidas(m_tipo), key="m_part")
    m_pago = st.selectbox("Forma de Pago:", ["Efectivo", "Tarjeta / TPV Físico"] if m_cuenta == "Caja" else ["Transferencia Bancaria", "Domiciliación Bancaria", "Cargo / Comisión Bancaria"], key="m_pago")
    m_proveedor = st.text_input("Proveedor / Hermano (Opcional):", placeholder="Ej: Cerería Bellido / Manuel García", key="m_prov")
    m_factura = st.text_input("Nº Ticket / Factura (Opcional):", placeholder="Ej: F-2026/104", key="m_fac")
    m_concepto = st.text_input("Detalle (¿Qué o quién?):", placeholder="Ej: Compra de cera / Limosna", key="m_con")
    m_importe = st.number_input("Importe (€):", min_value=0.01, step=1.0, format="%.2f", key="m_imp")
    m_foto = st.file_uploader("📸 Hacer Foto al Ticket / Recibo:", type=["png", "jpg", "jpeg", "pdf"], key="m_foto")

    bloqueo_movil = comprobar_bloqueo_concurrencia(st.session_state.get("usr_activo", "Usuario"))
    if bloqueo_movil:
        st.warning(bloqueo_movil)
        st.button("🔒 GUARDADO DESACTIVADO POR CONCURRENCIA", disabled=True, use_container_width=True)
    else:
        if st.button("✅ GUARDAR APUNTE AHORA", use_container_width=True, key="m_btn_save"):
            if not m_concepto.strip():
                st.error("Escribe un detalle antes de guardar.")
            else:
                registrar_presencia_usuario(st.session_state.get("usr_activo", "Usuario"), "Vista Móvil")
                n_arc = ""
                if m_foto is not None:
                    n_arc = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{m_foto.name}"
                    guardar_archivo_nube(n_arc, m_foto.getbuffer())
                conn = conectar_bd(); cur = conn.cursor()
                cur.execute("INSERT INTO contabilidad (fecha, tipo, origen_destino, partida, proveedor, num_factura, concepto, forma_pago, importe, comprobante, eliminado, pendiente) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)", (datetime.now().strftime("%Y-%m-%d %H:%M"), m_tipo, m_cuenta, m_partida, m_proveedor.strip(), m_factura.strip(), m_concepto.strip(), m_pago, m_importe, n_arc))
                conn.commit(); conn.sync()
                st.cache_data.clear()
                st.success("¡Apunte registrado en la nube!"); st.rerun()
    st.markdown("---")
    st.markdown("##### 🕒 Últimos 5 movimientos")
    if not df_global.empty:
        for _, r_m in df_global.head(5).iterrows():
            col_ic = "🟢" if r_m.get('Tipo') == 'Ingreso' else "🔴"
            st.markdown(f"{col_ic} **{r_m.get('Importe (€)'):,.2f} €** — {r_m.get('Partida')} ({r_m.get('Concepto')}) <br/><small style='color:gray;'>{r_m.get('Fecha')} | {r_m.get('Cuenta')}</small>", unsafe_allow_html=True)
    st.stop()
# 4. Si es ordenador de escritorio, muestra las tarjetas normales y el identificador
c1, c2, c3 = st.columns(3)
c1.metric("🏪 Saldo Real en Caja Física", f"{s_caja:,.2f} €")
c2.metric("🏦 Saldo Real en Banco", f"{s_banco:,.2f} €")
c3.metric("💰 Caja Total Cofradía", f"{(s_caja + s_banco):,.2f} €")
st.markdown("---")

quien_opera = st.selectbox("👤 Identificación de usuario activo:", ["Mayordomo", "Secretario", "Hermano Mayor", "Diputado de Gobierno"], key="usr_activo")
st.markdown("---")
# --- FIN DE LA CABECERA ---

# --- DECLARACIÓN OFICIAL DE LAS PESTAÑAS DEL PROGRAMA ---
p_reg, p_fil, p_pre, p_con = st.tabs(["📝 Registrar Movimiento", "🔍 Libro Diario y Filtros", "📊 Presupuestos y Cierre Anual", "⚙️ Configuración y Respaldos"])

with p_reg:
    c_r1, c_r2 = st.columns(2)
    with c_r1:
        tipo = st.radio("Tipo de Apunte:", ["Ingreso", "Gasto"], horizontal=True)
        cuenta = st.radio("Destino / Origen del dinero:", ["Caja", "Banco"], horizontal=True)
        partida = st.selectbox("Concepto General o Partida:", obtener_partidas(tipo))
        provs_existentes = sorted([p for p in df_global['Proveedor'].dropna().unique() if str(p).strip() != ""]) if not df_global.empty else []
        prov_sel = st.selectbox("Seleccionar Proveedor / Hermano frecuente (o escribir nuevo abajo):", ["(Escribir nuevo)"] + provs_existentes)
    with c_r2:
        forma_pago = st.selectbox("Forma o Canal de Pago:", ["Efectivo", "Tarjeta / TPV Físico"] if cuenta == "Caja" else ["Domiciliación Bancaria", "Transferencia Bancaria", "Cargo / Comisión Bancaria"])
        proveedor_nuevo = st.text_input("Nombre del Proveedor / Hermano:", value="" if prov_sel == "(Escribir nuevo)" else prov_sel, placeholder="Ej: Cerería Bellido / Banda de Música")
        num_factura = st.text_input("Nº de Ticket / Factura (Opcional):", placeholder="Ej: FAC-2026/089")
        concepto = st.text_input("Detalle específico:", placeholder="Ej: Compra de cirios para Altar de Cultos")
        importe = st.number_input("Importe del apunte (€):", min_value=0.01, step=5.0, format="%.2f")
        es_pendiente = st.checkbox("⏳ Marcar como OPERACIÓN PENDIENTE (No altera el saldo de caja/banco todavía)", value=False)

    up_file = st.file_uploader("📷 Adjuntar foto del Ticket o Recibo (Opcional):", type=["png", "jpg", "jpeg", "pdf"])

    bloqueo_msg = comprobar_bloqueo_concurrencia(quien_opera)
    if bloqueo_msg:
        st.warning(bloqueo_msg)
        st.button("🔒 GUARDADO DESACTIVADO TEMPORALMENTE", disabled=True, use_container_width=True)
    else:
        if st.button("Asentar Asiento Contable", use_container_width=True):
            if not concepto.strip():
                st.error("Por favor, añada una descripción o detalle antes de guardar.")
            else:
                registrar_presencia_usuario(quien_opera, "Registro Manual")
                n_arc = ""
                if up_file is not None:
                    n_arc = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{up_file.name}"
                    guardar_archivo_nube(n_arc, up_file.getbuffer())
                conn = conectar_bd(); cursor = conn.cursor()
                cursor.execute("INSERT INTO contabilidad (fecha, tipo, origen_destino, partida, proveedor, num_factura, concepto, forma_pago, importe, comprobante, eliminado, pendiente) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)", (datetime.now().strftime("%Y-%m-%d %H:%M"), tipo, cuenta, partida, proveedor_nuevo.strip(), num_factura.strip(), concepto, forma_pago, importe, n_arc, 1 if es_pendiente else 0))
                conn.commit(); conn.sync()
                st.cache_data.clear()
                st.success("Asiento grabado en la nube."); st.rerun()

    st.markdown("---")
    with st.expander("🏦 Importar Remesa de Cuotas desde Excel del Banco (.xlsx / .xls)", expanded=False):
        st.caption("Sube el archivo Excel exportado por tu banco para registrar automáticamente cada hermano junto con su cuota abonada en la cuenta Banco.")
        df_plantilla = pd.DataFrame([
            {"Referencia": "REM-2026-001", "Hermano": "Manuel García López", "IBAN": "ES9121000418450200051332", "Importe": 35.00, "Vencimiento": "2026-11-05", "Estado": "Pagado"}
        ])
        st.download_button(label="📥 Descargar Plantilla Excel de Ejemplo (.xlsx)", data=generar_excel(df_plantilla), file_name="Plantilla_Remesa_Ejemplo.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        archivo_excel = st.file_uploader("Seleccionar archivo Excel de remesa bancaria:", type=["xlsx", "xls"], key="up_remesa_banco")
        if archivo_excel is not None:
            procesar_panel_remesas(archivo_excel)

    st.markdown("---")
    with st.expander("🔄 Registrar Traspaso Interno de Fondos (Mover dinero de Caja a Banco o viceversa)", expanded=False):
        st.caption("Esta acción traspasa dinero real entre tus cuentas de tesorería, manteniendo los informes del Cabildo limpios de falsos ingresos o gastos.")
        t_origen = st.radio("Cuenta de ORIGEN (De dónde sale el dinero):", ["Caja", "Banco"], horizontal=True, key="t_ori")
        t_destino = "Banco" if t_origen == "Caja" else "Caja"
        st.markdown(f"➡️ **Cuenta de DESTINO (A dónde entra el dinero):** `{t_destino}`")
        t_importe = st.number_input("Cantidad a traspasar (€):", min_value=0.01, step=10.0, format="%.2f", key="t_imp")
        t_concepto = st.text_input("Motivo o nota del traspaso:", value="Traspaso interno de fondos para necesidades de caja", key="t_con")

        bloqueo_traspaso = comprobar_bloqueo_concurrencia(quien_opera)
        if bloqueo_traspaso:
            st.warning(bloqueo_traspaso)
            st.button("🔒 TRASPASO DESACTIVADO TEMPORALMENTE", disabled=True, use_container_width=True)
        else:
            if st.button("Confirmar y Registrar Traspaso Interno", use_container_width=True):
                registrar_presencia_usuario(quien_opera, "Traspaso de Fondos")
                conn = conectar_bd(); cur = conn.cursor()
                cur.execute("INSERT INTO traspasos_internos (fecha, origen, destino, importe, concepto) VALUES (?, ?, ?, ?, ?)", (datetime.now().strftime("%Y-%m-%d %H:%M"), t_origen, t_destino, t_importe, t_concepto.strip()))
                conn.commit(); conn.sync()
                st.cache_data.clear()
                st.success("¡Traspaso interno asentado en las cuentas!"); st.rerun()
with p_fil:
    with st.container(border=True):
        cf1, cf2, cf3, cf4 = st.columns(4)
        with cf1: f_cuenta = st.selectbox("Cuenta:", ["Todas", "Caja", "Banco"]); f_tipo = st.selectbox("Tipo:", ["Todos", "Ingreso", "Gasto"])
        with cf2: f_pago = st.selectbox("Forma Pago:", ["Todas", "Efectivo", "Tarjeta / TPV Físico", "Domiciliación Bancaria", "Transferencia Bancaria", "Cargo / Comisión Bancaria"])
        with cf3:
            try: r_fechas = st.date_input("Rango Fechas:", value=(date.today().replace(month=1, day=1), date.today()))
            except: r_fechas = date.today()
        with cf4: f_texto = st.text_input("Buscar Texto libre:", placeholder="Ej: Factura, Lotería...")

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            partidas_disponibles = sorted(list(df_global['Partida'].dropna().unique())) if not df_global.empty else []
            f_partidas = st.multiselect("Filtrar por Partidas / Conceptos específicos (vacío = todas):", partidas_disponibles, default=[])
        with col_f2:
            proveedores_disp = sorted([p for p in df_global['Proveedor'].dropna().unique() if str(p).strip() != ""]) if not df_global.empty else []
            f_proveedor = st.selectbox("Filtrar por Proveedor / Hermano:", ["Todos"] + proveedores_disp)

        agrupar_conceptos = st.checkbox("📊 Agrupar informe por Conceptos / Partidas (con subtotales en PDF y hoja resumen en Excel)", value=False)

    with st.expander("✏️ PANEL CENTRAL DE EDICIÓN (Modificar Asientos o Añadir Fotos)", expanded=False):
        st.caption("Introduce el número de asiento (ej: 14) para modificar cualquier dato o adjuntarle una imagen/ticket.")
        id_a_editar = int(st.number_input("Número de Asiento (#) a modificar:", min_value=1, step=1, key="id_central_ed"))
        if id_a_editar:
            df_buscado = df_global.loc[df_global['id'] == id_a_editar]
            if not df_buscado.empty:
                r_edit = df_buscado.iloc[0]
                c_ed1, c_ed2 = st.columns(2)
                ed_fec = c_ed1.text_input("Fecha:", value=str(r_edit.get('Fecha')), key=f"cef_fec_{id_a_editar}")
                ed_cue = c_ed1.selectbox("Cuenta:", ["Caja", "Banco"], index=0 if r_edit.get('Cuenta')=="Caja" else 1, key=f"cef_cue_{id_a_editar}")
                p_t_op = obtener_partidas("Ingreso") if r_edit.get('Tipo') == "Ingreso" else obtener_partidas("Gasto")
                idx_p_op = p_t_op.index(r_edit.get('Partida')) if r_edit.get('Partida') in p_t_op else 0
                ed_par = c_ed1.selectbox("Partida:", p_t_op, index=idx_p_op, key=f"cef_par_{id_a_editar}")
                ed_prov = c_ed1.text_input("Proveedor / Hermano:", value=str(r_edit.get('Proveedor', '')), key=f"cef_prov_{id_a_editar}")

                opciones_pago = ["Efectivo", "Tarjeta / TPV Físico", "Domiciliación Bancaria", "Transferencia Bancaria", "Cargo / Comisión Bancaria"]
                idx_pago = opciones_pago.index(r_edit.get('Forma Pago')) if r_edit.get('Forma Pago') in opciones_pago else 0
                ed_pag = c_ed2.selectbox("Forma de Pago:", opciones_pago, index=idx_pago, key=f"cef_pag_{id_a_editar}")
                ed_fac = c_ed2.text_input("Nº Ticket / Factura:", value=str(r_edit.get('Nº Factura', '')), key=f"cef_fac_{id_a_editar}")
                ed_con = c_ed2.text_input("Concepto:", value=str(r_edit.get('Concepto')), key=f"cef_con_{id_a_editar}")
                ed_imp = c_ed2.number_input("Importe (€):", value=float(r_edit.get('Importe (€)')), min_value=0.01, step=1.0, key=f"cef_imp_{id_a_editar}")
                ed_file = st.file_uploader("📷 Añadir o Cambiar Foto del Ticket/Recibo:", type=["png", "jpg", "jpeg", "pdf"], key=f"cef_file_{id_a_editar}")

                if st.button("💾 GUARDAR CAMBIOS EN EL ASIENTO", use_container_width=True, key=f"cef_btn_save_{id_a_editar}"):
                    n_arc = r_edit.get('Comprobante') if r_edit.get('Comprobante') else ""
                    if ed_file is not None:
                        n_arc = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ed_file.name}"
                        guardar_archivo_nube(n_arc, ed_file.getbuffer())
                    conn = conectar_bd(); cur = conn.cursor()
                    cur.execute("UPDATE contabilidad SET fecha=?, origen_destino=?, partida=?, proveedor=?, forma_pago=?, num_factura=?, concepto=?, importe=?, comprobante=? WHERE id=?", (ed_fec, ed_cue, ed_par, ed_prov.strip(), ed_pag, ed_fac.strip(), ed_con, ed_imp, n_arc, id_a_editar))
                    conn.commit(); conn.sync()
                    st.cache_data.clear()
                    st.session_state.pop(f"pdf_listo_{id_a_editar}", None)
                    st.success("¡Asiento actualizado correctamente!"); st.rerun()
            else:
                st.caption("Introduce un número de asiento válido para ver sus datos.")

    df_f = df_global.copy()
    if f_cuenta != "Todas": df_f = df_f.loc[df_f['Cuenta'] == f_cuenta]
    if f_tipo != "Todos": df_f = df_f.loc[df_f['Tipo'] == f_tipo]
    if f_pago != "Todas": df_f = df_f.loc[df_f['Forma Pago'] == f_pago]
    if f_partidas: df_f = df_f.loc[df_f['Partida'].isin(f_partidas)]
    if f_proveedor != "Todos": df_f = df_f.loc[df_f['Proveedor'] == f_proveedor]
    if f_texto: df_f = df_f.loc[df_f['Concepto'].str.contains(f_texto, case=False) | df_f['Partida'].str.contains(f_texto, case=False) | df_f['Proveedor'].str.contains(f_texto, case=False) | df_f['Nº Factura'].str.contains(f_texto, case=False)]
    if isinstance(r_fechas, tuple) and len(r_fechas) == 2:
        f_ini_d, f_fin_d = r_fechas
        df_f = df_f.loc[(df_f['Fecha'] >= f_ini_d.strftime("%Y-%m-%d")) & (df_f['Fecha'] <= (f_fin_d.strftime("%Y-%m-%d") + " 23:59"))]

    if not df_f.empty:
        v_ing = df_f.loc[df_f['Tipo'] == 'Ingreso', 'Importe (€)'].sum(); v_gas = df_f.loc[df_f['Tipo'] == 'Gasto', 'Importe (€)'].sum()
        with st.container(border=True):
            ct1, ct2, ct3 = st.columns(3)
            ct1.markdown(f"**Suma Ingresos:** <font color='green'><b>{v_ing:,.2f} €</b></font>", unsafe_allow_html=True)
            ct2.markdown(f"**Suma Gastos:** <font color='red'><b>-{v_gas:,.2f} €</b></font>", unsafe_allow_html=True)
            ct3.markdown(f"**Rendimiento Neto:** <b>{(v_ing - v_gas):,.2f} €</b>", unsafe_allow_html=True)
        cb1, cb2 = st.columns(2)
        subtitulo_pdf = f"Filtro ({f_cuenta} | {f_tipo})" + (" - Agrupado por Conceptos" if agrupar_conceptos else "")
        with cb1: st.download_button(label="👑 Imprimir Extracto Horizontal en PDF", data=generar_pdf_resumen(df_f, subtitulo_pdf, agrupar=agrupar_conceptos), file_name="Extracto_Horizontal_Desamparados.pdf", mime="application/pdf", use_container_width=True)
        with cb2: st.download_button(label="📊 Exportar Tabla a Excel (.xlsx)", data=generar_excel(df_f, agrupar=agrupar_conceptos), file_name="Contabilidad_Desamparados.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        with st.expander(f"📋 Desplegar / Ocultar Listado de Movimientos ({len(df_f)} apuntes encontrados)", expanded=False):
            dibujar_tabla_movimientos(df_f)
    else:
        st.info("No hay movimientos que coincidan con los filtros seleccionados.")

    st.markdown("---")
    st.markdown("#### 🔄 Auditoría de Movimientos Internos de Tesorería")
    df_t_vista = leer_tabla_turso("SELECT id, fecha, origen, destino, importe, concepto FROM traspasos_internos")
    with st.expander(f"📋 Ver Historial de Traspasos Internos de Fondos ({len(df_t_vista)} movimientos registrados)", expanded=False):
        dibujar_tabla_traspasos(df_t_vista)
with p_pre:
    st.markdown("#### 📊 Control Presupuestario del Ejercicio en Curso")
    df_pres = leer_tabla_turso("SELECT partida, importe_presupuestado FROM presupuestos")
    dict_pres = dict(zip(df_pres['partida'], df_pres['importe_presupuestado']))
    col_p1, col_p2 = st.columns((1, 2.3))
    with col_p1:
        st.markdown("**Asignar Presupuesto Anual**")
        p_tipo_sel = st.radio("Tipo de Partida:", ["Ingreso", "Gasto"], horizontal=True, key="pres_tipo")
        p_sel = st.selectbox("Seleccione Partida:", obtener_partidas(p_tipo_sel), key="pres_part")
        val_actual_p = float(dict_pres.get(p_sel, 0.0))
        nuevo_pres = st.number_input("Presupuesto Asignado (€):", min_value=0.0, value=val_actual_p, step=50.0, format="%.2f")
        if st.button("💾 Fijar Presupuesto", use_container_width=True):
            conn = conectar_bd(); cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO presupuestos (partida, tipo, importe_presupuestado) VALUES (?, ?, ?)", (p_sel, p_tipo_sel, nuevo_pres))
            conn.commit(); conn.sync()
            st.cache_data.clear()
            st.success("Presupuesto actualizado."); st.rerun()
        st.markdown("---")
        st.markdown("**🔒 Cierre de Ejercicio Anual**")
        st.warning("Genera el Acta Oficial en PDF y Excel del año, limpia el libro diario y traspasa el saldo final como fondo inicial del nuevo curso.")
        anio_cierre = st.text_input("Nombre del Ejercicio a cerrar:", value=str(date.today().year))
        if st.button("⚠️ EJECUTAR CIERRE ANUAL", use_container_width=True):
            if not df_global.empty:
                pdf_cierre_bytes = generar_pdf_cierre(df_global, anio_cierre, caja_ini, banco_ini, s_caja, s_banco).getvalue()
                st.session_state["ultimo_pdf_cierre"] = pdf_cierre_bytes
                st.session_state["ultimo_excel_cierre"] = generar_excel(df_global).getvalue()
                st.session_state["ultimo_anio_cierre"] = anio_cierre
                conn = conectar_bd(); cur = conn.cursor()
                cur.execute("UPDATE saldos_iniciales SET caja_inicio=?, banco_inicio=? WHERE id=1", (s_caja, s_banco))
                cur.execute("DELETE FROM contabilidad")
                cur.execute("DELETE FROM archivos_nube")
                cur.execute("DELETE FROM traspasos_internos")
                conn.commit(); conn.sync()
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("No hay apuntes que cerrar.")
        if "ultimo_pdf_cierre" in st.session_state:
            st.success(f"✅ Ejercicio {st.session_state['ultimo_anio_cierre']} cerrado. Descarga tus actas:")
            st.download_button(label=f"🖨️ DESCARGAR ACTA DE CIERRE {st.session_state['ultimo_anio_cierre']} (PDF)", data=st.session_state["ultimo_pdf_cierre"], file_name=f"Acta_Cierre_{st.session_state['ultimo_anio_cierre']}.pdf", mime="application/pdf", use_container_width=True)
            st.download_button(label=f"📊 DESCARGAR LIBRO DIARIO {st.session_state['ultimo_anio_cierre']} (EXCEL)", data=st.session_state["ultimo_excel_cierre"], file_name=f"Cierre_{st.session_state['ultimo_anio_cierre']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with col_p2:
        tablas_tot = dict()
        for tipo_comp in ["Ingreso", "Gasto"]:
            icono_t = "📈" if tipo_comp == "Ingreso" else "📉"
            st.markdown(f"##### {icono_t} Comparativa Presupuestado vs Ejecutado ({tipo_comp}s)")
            datos_comp = list()
            tot_p, tot_e = 0.0, 0.0
            todas_partidas = obtener_partidas(tipo_comp)
            for part in todas_partidas:
                cod_p = str(part).split(" - ")[0].strip()
                pres_directo = float(dict_pres.get(part, 0.0))
                ejec_directo = float(df_global.loc[(df_global['Tipo'] == tipo_comp) & (df_global['Partida'] == part), 'Importe (€)'].sum()) if not df_global.empty else 0.0
                tot_p += pres_directo
                tot_e += ejec_directo

                if len(cod_p) == 2 and cod_p.isalpha():
                    pres_v = sum(float(dict_pres.get(x, 0.0)) for x in todas_partidas if str(x).split(" - ")[0].strip().startswith(cod_p))
                    ejec_v = float(df_global.loc[(df_global['Tipo'] == tipo_comp) & (df_global['Partida'].str.startswith(cod_p)), 'Importe (€)'].sum()) if not df_global.empty else 0.0
                else:
                    pres_v = pres_directo
                    ejec_v = ejec_directo

                dif_v = (ejec_v - pres_v) if tipo_comp == "Ingreso" else (pres_v - ejec_v)
                datos_comp.append({"Partida": part, "Presupuestado (€)": pres_v, "Ejecutado (€)": ejec_v, "Diferencia (€)": dif_v})
            
            df_comp = pd.DataFrame(datos_comp)
            tot_d = (tot_e - tot_p) if tipo_comp == "Ingreso" else (tot_p - tot_e)
            df_tot = pd.concat([df_comp, pd.DataFrame([{"Partida": f"TOTAL {tipo_comp.upper()}S", "Presupuestado (€)": tot_p, "Ejecutado (€)": tot_e, "Diferencia (€)": tot_d}])], ignore_index=True)
            tablas_tot[tipo_comp] = df_tot
            st.dataframe(df_tot, use_container_width=True, hide_index=True)
            c_pdf, c_ex, c_gr = st.columns((1, 1, 1.5))
            with c_pdf:
                st.download_button(f"📄 PDF {tipo_comp}s", data=generar_pdf_presupuesto(df_tot, tipo_comp), file_name=f"Presupuestos_{tipo_comp}s.pdf", mime="application/pdf", key=f"btn_pdf_{tipo_comp}", use_container_width=True)
            with c_ex:
                st.download_button(f"📥 Excel {tipo_comp}s", data=generar_excel(df_tot), file_name=f"Presupuestos_{tipo_comp}s.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"btn_ex_{tipo_comp}", use_container_width=True)
            with st.expander(f"📊 Ver Gráfico de {tipo_comp}s", expanded=False):
                st.bar_chart(df_comp.set_index("Partida")[["Presupuestado (€)", "Ejecutado (€)"]])
            st.markdown("---")
        st.download_button(label="👑 IMPRIMIR INFORME PRESUPUESTARIO GLOBAL (CABILDO GENERAL - PDF)", data=generar_pdf_presupuesto_global(tablas_tot["Ingreso"], tablas_tot["Gasto"]), file_name="Informe_Presupuestario_Global_Cabildo.pdf", mime="application/pdf", use_container_width=True)
        st.markdown("---")
        with st.expander("⛪ Informe Oficial Archidiócesis de Sevilla (Grupos 3 dígitos y Subcuentas 8 dígitos)", expanded=False):
            df_r3, df_d8, excel_arz, pdf_arz_agrupado, pdf_arz_desarrollado = generar_informe_arzobispado(df_global, dict_pres)
            cp_arz1, cp_arz2, cp_arz3 = st.columns(3)
            with cp_arz1:
                st.download_button(label="📄 PDF Agrupado (3 dígitos)", data=pdf_arz_agrupado, file_name=f"Arzobispado_Agrupado_{date.today().year}.pdf", mime="application/pdf", use_container_width=True)
            with cp_arz2:
                st.download_button(label="📑 PDF Desarrollado (3 y 8 dígitos)", data=pdf_arz_desarrollado, file_name=f"Arzobispado_Desarrollado_{date.today().year}.pdf", mime="application/pdf", use_container_width=True)
            with cp_arz3:
                st.download_button(label="📊 Excel Oficial (3 y 8 dígitos)", data=excel_arz, file_name=f"Cuentas_Archidiocesis_Sevilla_{date.today().year}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            st.markdown("**1. Resumen Oficial Agrupado por Bloques de 3 Dígitos:**")
            st.dataframe(df_r3, use_container_width=True, hide_index=True)
            st.markdown("**2. Desglose Específico por Subcuentas de 8 Dígitos:**")
            st.dataframe(df_d8, use_container_width=True, hide_index=True)
with p_con:
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("**💰 Fondos Iniciales de Apertura**")
        caja_inf = st.number_input("Dinero inicial en Caja Física (€):", min_value=0.0, value=float(caja_ini), step=50.0, format="%.2f")
        banco_inf = st.number_input("Dinero inicial en Cuenta Bancaria (€):", min_value=0.0, value=float(banco_ini), step=50.0, format="%.2f")
        if st.button("💾 Guardar Saldos Iniciales", use_container_width=True):
            conn = conectar_bd(); cur = conn.cursor()
            cur.execute("UPDATE saldos_iniciales SET caja_inicio = ?, banco_inicio = ? WHERE id = 1", (caja_inf, banco_inf))
            conn.commit(); conn.sync()
            st.cache_data.clear()
            st.success("Saldos actualizados."); st.rerun()
        mostrar_panel_respaldos(df_global)
    with col_c2:
        st.markdown("**🎨 Crear Nuevas Partidas / Conceptos**")
        with st.expander("⛪ Cargar Plan Oficial Archidiócesis de Sevilla (Letras AH - VH)", expanded=False):
            st.caption("Carga los grupos principales (2 letras) y todas las subcuentas oficiales exigidas por Palacio Arzobispal.")
            if st.button("📥 Cargar Catálogo Oficial Palacio (Letras)", use_container_width=True, key="btn_plan_sevilla"):
                plan_palacio = [
                    # GASTOS (LH a VH)
                    ("Gasto", "LH - COMPRAS (para vender)"),
                    ("Gasto", "LH1 - Velones, velas, lamparillas, medallas, etc."),
                    ("Gasto", "LH2 - Publicaciones: folletos, libros, etc."),
                    ("Gasto", "LH3 - Otros (Compras)"),
                    ("Gasto", "MH - GASTOS DE PERSONAL"),
                    ("Gasto", "MH1 - Personal seglar habitual"),
                    ("Gasto", "MH2 - Seguridad Social del personal seglar"),
                    ("Gasto", "MH3 - Suplencias del personal seglar habitual"),
                    ("Gasto", "MH4 - Desplazamientos"),
                    ("Gasto", "MH5 - Cobranza"),
                    ("Gasto", "MH6 - Costaleros"),
                    ("Gasto", "NH - SUBSIDIO DEL SACERDOTE"),
                    ("Gasto", "NH1 - Subsidio del Sacerdote (Estipendio)"),
                    ("Gasto", "OH - GASTOS FINANCIEROS"),
                    ("Gasto", "OH1 - Intereses de préstamos recibidos"),
                    ("Gasto", "OH2 - Comisiones bancarias"),
                    ("Gasto", "OH3 - Otros gastos financieros"),
                    ("Gasto", "PH - IMPUESTOS Y TASAS"),
                    ("Gasto", "PH1 - De organismos estatales / autonómicos"),
                    ("Gasto", "PH2 - De organismos locales: Ayuntamiento, etc."),
                    ("Gasto", "PH3 - Otros impuestos o Tasas"),
                    ("Gasto", "QH - SUMINISTROS Y CONSERVACIÓN"),
                    ("Gasto", "QH1 - Agua, gas, electricidad"),
                    ("Gasto", "QH2 - Material de limpieza"),
                    ("Gasto", "QH3 - Reparaciones: obras en inmuebles y locales"),
                    ("Gasto", "QH4 - Asistencia técnica maquinaria: servicios y reparaciones"),
                    ("Gasto", "QH5 - Seguros: responsabilidad civil, multierriesgo, accidente y similares"),
                    ("Gasto", "QH6 - Cuotas alquiler de arrendamientos"),
                    ("Gasto", "QH7 - Portes mercancías"),
                    ("Gasto", "QH8 - Mantenimiento: Pasos, enseres..."),
                    ("Gasto", "QH9 - Otros suministros y conservación"),
                    ("Gasto", "RH - SALIDA DE LA COFRADÍA"),
                    ("Gasto", "RH1 - Cera"),
                    ("Gasto", "RH2 - Música"),
                    ("Gasto", "RH3 - Flores"),
                    ("Gasto", "RH4 - Otros gastos salida"),
                    ("Gasto", "RH5 - Salidas Extraordinarias de la Cofradía"),
                    ("Gasto", "SH - GASTOS DE FUNCIONAMIENTO"),
                    ("Gasto", "SH1 - Material de oficina: papelería, impresos oficiales, etc."),
                    ("Gasto", "SH2 - Correos y teléfono"),
                    ("Gasto", "SH3 - Atenciones a personas ajenas (no de caridad)"),
                    ("Gasto", "SH4 - Material de publicidad o propaganda"),
                    ("Gasto", "SH5 - Actos jurídicos: abogados, notarios, etc."),
                    ("Gasto", "TH - ACTIVIDADES PASTORALES Y ASISTENCIALES"),
                    ("Gasto", "TH1 - Material para culto: hostias, vino, cera, libros litúrgicos..."),
                    ("Gasto", "TH2 - Actividades de evangelización: catequesis y cultos"),
                    ("Gasto", "TH3 - Actividades asistenciales sociales (Bolsa de Caridad)"),
                    ("Gasto", "TH4 - Actividades culturales: conferencias, cursillos, etc."),
                    ("Gasto", "TH5 - Actividades Pastorales extraordinarias"),
                    ("Gasto", "TH6 - Obras asistenciales extraordinarias"),
                    ("Gasto", "UH - OTROS"),
                    ("Gasto", "UH1 - Obras extraordinarias"),
                    ("Gasto", "UH2 - Otros gastos: compra de mobiliario, etc."),
                    ("Gasto", "UH3 - Amortizaciones"),
                    ("Gasto", "UH4 - Provisiones"),
                    ("Gasto", "UH5 - Cuotas Incobrables"),
                    ("Gasto", "VH - COMUNICACIÓN DE BIENES"),
                    ("Gasto", "VH1 - Fondo Común Diocesano"),
                    ("Gasto", "VH2 - Cuotas a entidades diocesanas (Seminario, Casa Sacerdotal...)"),
                    ("Gasto", "VH3 - Ayudas a parroquias"),
                    ("Gasto", "VH4 - Ayudas a entidades extradiocesanas (Conventos, Manos Unidas, OMP...)"),
                    # INGRESOS (AH a IH)
                    ("Ingreso", "AH - POR SERVICIOS"),
                    ("Ingreso", "AH1 - Venta de cera y objetos religiosos, fotos, medallas, etc."),
                    ("Ingreso", "AH2 - Venta libros, publicaciones"),
                    ("Ingreso", "AH3 - Otros Ingresos por Servicios"),
                    ("Ingreso", "AH4 - Subvención Consejo Cofradías"),
                    ("Ingreso", "BH - RENTAS DEL PATRIMONIO INMOBILIARIO"),
                    ("Ingreso", "BH1 - Rentas de fincas, locales, etc."),
                    ("Ingreso", "CH - RENTAS DEL PATRIMONIO MOBILIARIO"),
                    ("Ingreso", "CH1 - Intereses de inversiones: acciones, IPF, etc."),
                    ("Ingreso", "CH2 - Intereses de cuentas en Bancos o Cajas"),
                    ("Ingreso", "CH3 - Intereses de préstamos concedidos"),
                    ("Ingreso", "DH - APORTACIÓN DE LOS FIELES"),
                    ("Ingreso", "DH1 - Cuota de Hermanos"),
                    ("Ingreso", "DH2 - Papeleta de Sitio"),
                    ("Ingreso", "EH - DONATIVOS Y LIMOSNAS"),
                    ("Ingreso", "EH1 - Cepillos"),
                    ("Ingreso", "EH2 - Otros donativos sin finalidad específica"),
                    ("Ingreso", "EH3 - Rifas, lotería y otros"),
                    ("Ingreso", "EH4 - Recibido con ocasión de Sacramentos y Sacramentales"),
                    ("Ingreso", "IH - ACTIVIDADES ECONOMICAS"),
                    ("Ingreso", "IH1 - Cuotas de museos, exposiciones artísticas"),
                    ("Ingreso", "IH2 - Otros ingresos de actividades económicas"),
                    ("Ingreso", "FH - SUBVENCIONES"),
                    ("Ingreso", "FH1 - De entidades no oficiales: Bancos, otras"),
                    ("Ingreso", "FH2 - De entidades oficiales: Estado, Autonomía, Locales"),
                    ("Ingreso", "GH - OBRAS ASISTENCIALES"),
                    ("Ingreso", "GH1 - OBRAS ASISTENCIALES: caridad o promoción (NO CÁRITAS)"),
                    ("Ingreso", "HH - OTROS INGRESOS"),
                    ("Ingreso", "HH1 - Donativos y cuotas con destino determinado"),
                    ("Ingreso", "HH2 - Colectas para casos parroquiales extraordinarios")
                ]
                conn = conectar_bd(); cur = conn.cursor()
                for t_s, n_s in plan_palacio:
                    cur.execute("INSERT OR IGNORE INTO partidas_personalizadas (tipo, nombre) VALUES (?, ?)", (t_s, n_s))
                conn.commit(); conn.sync()
                st.cache_data.clear()
                st.success("Catálogo oficial con letras (AH - VH) cargado."); st.rerun()
            st.markdown("---")
            if st.button("🧹 Limpiar Partidas Antiguas (Numéricas / Iniciales)", use_container_width=True, key="btn_limpiar_antiguas"):
                codigos_validos = ("AH", "BH", "CH", "DH", "EH", "FH", "GH", "HH", "IH", "LH", "MH", "NH", "OH", "PH", "QH", "RH", "SH", "TH", "UH", "VH")
                df_todas_p = leer_tabla_turso("SELECT id, nombre FROM partidas_personalizadas")
                if not df_todas_p.empty:
                    conn = conectar_bd(); cur = conn.cursor()
                    borradas = 0
                    for _, rp in df_todas_p.iterrows():
                        nom_p = str(rp.get('nombre', '')).strip()
                        if not nom_p.startswith(codigos_validos):
                            cur.execute("DELETE FROM partidas_personalizadas WHERE id = ?", (int(rp.get('id')),))
                            borradas += 1
                    conn.commit(); conn.sync()
                    st.cache_data.clear()
                    st.success(f"Se han eliminado {borradas} partidas antiguas."); st.rerun()
        c_tipo = st.selectbox("Asociar nueva partida a:", ["Ingreso", "Gasto"], key="new_part_tipo")
        c_nombre = st.text_input("Nombre de la nueva partida:", placeholder="Ej: 72200003 - Venta de dulces")
        if st.button("Guardar Nueva Partida", use_container_width=True):
            if not c_nombre.strip():
                st.error("Escriba el nombre de la partida.")
            else:
                try:
                    conn = conectar_bd(); cur = conn.cursor()
                    cur.execute("INSERT INTO partidas_personalizadas (tipo, nombre) VALUES (?, ?)", (c_tipo, c_nombre.strip()))
                    conn.commit(); conn.sync()
                    st.cache_data.clear()
                    st.success("Partida añadida."); st.rerun()
                except:
                    st.error("Este concepto ya existe.")
        st.markdown("---")
        st.markdown("**📋 Gestionar Todos los Conceptos (Predeterminados y Nuevos)**")
        df_p = leer_tabla_turso("SELECT id, tipo, nombre FROM partidas_personalizadas ORDER BY tipo, nombre")
        if df_p.empty:
            st.caption("No hay partidas registradas.")
        else:
            with st.expander("Desplegar / Ocultar Catálogo de Conceptos", expanded=True):
                for _, r_p in df_p.iterrows():
                    pid = r_p.get('id'); ptipo = r_p.get('tipo'); pnom = r_p.get('nombre')
                    with st.container(border=True):
                        cp1, cp2, cp3 = st.columns((3, 1, 1))
                        cp1.markdown(f"**{pnom}** <small style='color:gray;'>({ptipo})</small>", unsafe_allow_html=True)
                        with cp2:
                            with st.popover("✏️", use_container_width=True):
                                nuevo_nom = st.text_input("Nuevo nombre:", value=pnom, key=f"ed_p_{pid}")
                                if st.button("Guardar", key=f"sv_p_{pid}", use_container_width=True):
                                    if nuevo_nom.strip() and nuevo_nom.strip() != pnom:
                                        try:
                                            conn = conectar_bd(); cur = conn.cursor()
                                            cur.execute("UPDATE partidas_personalizadas SET nombre = ? WHERE id = ?", (nuevo_nom.strip(), pid))
                                            cur.execute("UPDATE contabilidad SET partida = ? WHERE partida = ? AND tipo = ?", (nuevo_nom.strip(), pnom, ptipo))
                                            cur.execute("UPDATE presupuestos SET partida = ? WHERE partida = ? AND tipo = ?", (nuevo_nom.strip(), pnom, ptipo))
                                            conn.commit(); conn.sync()
                                            st.cache_data.clear(); st.rerun()
                                        except:
                                            st.error("Ya existe un concepto con ese nombre.")
                        with cp3:
                            if st.button("❌", key=f"dl_p_{pid}", use_container_width=True):
                                conn = conectar_bd(); cur = conn.cursor()
                                cur.execute("DELETE FROM partidas_personalizadas WHERE id = ?", (pid,))
                                conn.commit(); conn.sync()
                                st.cache_data.clear(); st.rerun()

