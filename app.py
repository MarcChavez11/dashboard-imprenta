import io
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
import plotly.express as px
import scipy.stats as stats
import numpy as np
from sqlalchemy import text

# ----------------------------------------------------------------------
# CONFIGURACIÓN - Base de datos en la nube (Neon / PostgreSQL)
# ----------------------------------------------------------------------
REFRESCO = 5             # Segundos para actualización automática en pantalla
ZONA_PERU = ZoneInfo("America/Lima")

st.set_page_config(page_title="Imprenta Flores", layout="centered")

# Estilo de letra elegante (Tipografía general)
st.markdown("""
<style>
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    h1 {
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    h2, h3 {
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

st.sidebar.title("Imprenta Flores")
menu = st.sidebar.radio("¿Qué deseas hacer?", [
    "⏱️ Registrar un cliente",
    "✏️ Editar un registro",
    "📊 Dashboard Descriptivo",
    "📈 Análisis Inferencial",
    "🛠️ Modo Ingeniero (Ver Excel)"
])

# ----------------------------------------------------------------------
# CONFIGURACIÓN GLOBAL DE METAS
# ----------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Configuración de Metas")

REF_TIEMPO_G1 = st.sidebar.number_input(
    "Meta máx. Grupo 1: Copias (min)", 
    min_value=0.5, max_value=60.0, value=2.0, step=0.5, key="ref_g1"
)

REF_TIEMPO_G2 = st.sidebar.number_input(
    "Meta máx. Grupo 2: Trámites (min)", 
    min_value=0.5, max_value=60.0, value=8.0, step=0.5, key="ref_g2"
)

REF_SAT = st.sidebar.number_input(
    "Meta mín. satisfacción (%)", 
    min_value=1, 
    max_value=100, 
    value=90, 
    step=5, 
    key="ref_sat"
)

# ----------------------------------------------------------------------
# CONEXIÓN A BASE DE DATOS EN LA NUBE (NEON)
# ----------------------------------------------------------------------
conn = st.connection("postgresql", type="sql")


def inicializar_bd():
    """Crea la tabla automáticamente en Neon si aún no existe."""
    query_crear = text("""
        CREATE TABLE IF NOT EXISTS registros (
            id SERIAL PRIMARY KEY,
            grupo_servicio INT NOT NULL,
            servicio TEXT NOT NULL,
            minutos NUMERIC(10, 4) NOT NULL,
            sexo VARCHAR(5) NOT NULL,
            satisfaccion VARCHAR(20) NOT NULL,
            fecha_hora VARCHAR(30) NOT NULL
        );
    """)
    with conn.session as s:
        s.execute(query_crear)
        s.commit()


inicializar_bd()


def _formatear_minutos_a_mmss(minutos_decimal):
    try:
        total_segundos = int(round(float(minutos_decimal) * 60))
        m, s = divmod(total_segundos, 60)
        return f"{m:02d}:{s:02d}"
    except Exception:
        return str(minutos_decimal)


def cargar_datos():
    try:
        df = conn.query("SELECT * FROM registros ORDER BY id ASC;", ttl=0)
        
        if df.empty:
            return pd.DataFrame(columns=[
                'GRUPO DE SERVICIO', 'SERVICIO', 'Minutos', 'SEXO', 'SATISFACCION', 'FECHA_HORA'
            ])

        df = df.rename(columns={
            'grupo_servicio': 'GRUPO DE SERVICIO',
            'servicio': 'SERVICIO',
            'minutos': 'Minutos',
            'sexo': 'SEXO',
            'satisfaccion': 'SATISFACCION',
            'fecha_hora': 'FECHA_HORA'
        })
        
        df['Minutos'] = df['Minutos'].astype(float)
        df['SATISFACCION'] = df['SATISFACCION'].astype(str).str.strip()
        df = df.set_index('id')
        return df

    except Exception as e:
        st.error(f"Error al conectar con la base de datos en la nube: {e}")
        st.stop()


def guardar_registro(grupo, servicio, sexo, minutos, satisfaccion):
    fecha_actual_peru = datetime.now(ZONA_PERU).strftime("%Y-%m-%d %H:%M:%S")
    
    query = text("""
        INSERT INTO registros (grupo_servicio, servicio, minutos, sexo, satisfaccion, fecha_hora)
        VALUES (:grupo, :servicio, :minutos, :sexo, :satisfaccion, :fecha_hora)
    """)
    
    with conn.session as s:
        s.execute(query, {
            "grupo": int(grupo),
            "servicio": str(servicio),
            "minutos": float(minutos),
            "sexo": str(sexo),
            "satisfaccion": str(satisfaccion),
            "fecha_hora": fecha_actual_peru
        })
        s.commit()


def actualizar_registro(id_registro, grupo, servicio, sexo, minutos, satisfaccion):
    fecha_actual_peru = datetime.now(ZONA_PERU).strftime("%Y-%m-%d %H:%M:%S")
    
    query = text("""
        UPDATE registros
        SET grupo_servicio = :grupo,
            servicio = :servicio,
            minutos = :minutos,
            sexo = :sexo,
            satisfaccion = :satisfaccion,
            fecha_hora = :fecha_hora
        WHERE id = :id
    """)
    
    with conn.session as s:
        s.execute(query, {
            "id": int(id_registro),
            "grupo": int(grupo),
            "servicio": str(servicio),
            "minutos": float(minutos),
            "sexo": str(sexo),
            "satisfaccion": str(satisfaccion),
            "fecha_hora": fecha_actual_peru
        })
        s.commit()


def intervalo_wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z**2 / n
    centro = (p + z**2 / (2 * n)) / den
    mitad = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return centro - mitad, centro + mitad


def es_optimo(serie):
    return serie.str.contains('OPTIMO', case=False, na=False)


# ----------------------------------------------------------------------
# COMPONENTE VISUAL: SEMÁFORO ESTADÍSTICO DE 3 LUCES
# ----------------------------------------------------------------------
def _evaluar_grupo(serie_tiempos, meta, nombre_grupo):
    n = len(serie_tiempos)
    media = serie_tiempos.mean() if n > 0 else 0.0
    std = serie_tiempos.std() if n > 1 else 0.0

    if n < 5 or std == 0:
        return "WARN", f"{nombre_grupo}: muestra insuficiente ({n} datos, prom. {media:.2f} min)."

    # Prueba t de dos colas para detectar si es significativamente menor o mayor a la meta
    _, p_val = stats.ttest_1samp(serie_tiempos, meta)

    if media < meta and p_val < 0.05:
        return "OK", f"{nombre_grupo}: óptimo ({media:.2f} min < {meta:.1f} min, p={p_val:.3f})."
    elif media > meta and p_val < 0.05:
        return "CRIT", f"{nombre_grupo}: crítico ({media:.2f} min > {meta:.1f} min, p={p_val:.3f})."
    else:
        return "WARN", f"{nombre_grupo}: en precaución ({media:.2f} min vs meta {meta:.1f} min, p={p_val:.3f})."


def _tarjeta_semaforo_individual(serie_tiempos, meta, titulo_grupo):
    estado, mensaje = _evaluar_grupo(serie_tiempos, meta, titulo_grupo)

    if estado == "CRIT":
        color_luz, titulo_estado = "rojo", "🔴 CRÍTICO"
    elif estado == "WARN":
        color_luz, titulo_estado = "amarillo", "🟡 PRECAUCIÓN"
    else:
        color_luz, titulo_estado = "verde", "🟢 ÓPTIMO"

    c_rojo = "#ff4d4d" if color_luz == "rojo" else "#4d1a1a"
    op_rojo = "1" if color_luz == "rojo" else "0.3"
    c_amarillo = "#ffcc00" if color_luz == "amarillo" else "#4d4d00"
    op_amarillo = "1" if color_luz == "amarillo" else "0.3"
    c_verde = "#2ecc71" if color_luz == "verde" else "#143d21"
    op_verde = "1" if color_luz == "verde" else "0.3"

    return f"""
    <div style="padding: 15px; border-radius: 12px; border: 1px solid rgba(128,128,128,0.3); text-align: center; height: 100%;">
        <h4 style="margin: 0 0 10px 0; font-size: 16px;">{titulo_grupo}</h4>
        <div style="display: inline-flex; gap: 10px; background: rgba(0,0,0,0.1); padding: 8px 14px; border-radius: 25px; border: 2px solid rgba(128,128,128,0.4); margin-bottom: 10px;">
            <div style="width: 24px; height: 24px; background-color: {c_rojo}; opacity: {op_rojo}; border-radius: 50%; box-shadow: 0 0 {'12px ' + c_rojo if color_luz=='rojo' else 'none'};"></div>
            <div style="width: 24px; height: 24px; background-color: {c_amarillo}; opacity: {op_amarillo}; border-radius: 50%; box-shadow: 0 0 {'12px ' + c_amarillo if color_luz=='amarillo' else 'none'};"></div>
            <div style="width: 24px; height: 24px; background-color: {c_verde}; opacity: {op_verde}; border-radius: 50%; box-shadow: 0 0 {'12px ' + c_verde if color_luz=='verde' else 'none'};"></div>
        </div>
        <div style="font-weight: 700; font-size: 15px; margin-bottom: 4px;">{titulo_estado}</div>
        <p style="margin: 0; font-size: 13px; opacity: 0.85;">{mensaje}</p>
    </div>
    """


def mostrar_semaforo_visual(df, meta_g1=2.0, meta_g2=8.0):
    g1_tiempos = df[df['GRUPO DE SERVICIO'] == 1]['Minutos']
    g2_tiempos = df[df['GRUPO DE SERVICIO'] == 2]['Minutos']

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.markdown(_tarjeta_semaforo_individual(g1_tiempos, meta_g1, "Grupo 1: Copias"), unsafe_allow_html=True)
    with col_g2:
        st.markdown(_tarjeta_semaforo_individual(g2_tiempos, meta_g2, "Grupo 2: Trámites"), unsafe_allow_html=True)
    st.write("")  # Pequeño espacio inferior



# ----------------------------------------------------------------------
# PANTALLA 1: REGISTRO
# ----------------------------------------------------------------------
def vista_registro():
    st.title("Registrar Atención")

    with st.form("registro_sencillo", clear_on_submit=True):
        grupo = st.radio("¿Qué tipo de servicio fue?",
                         ["Grupo 1 (Copias/Impresiones)", "Grupo 2 (Trámites/Pasaporte)"])
        servicio = st.text_input("¿Qué servicio exacto fue? (Ej. Copia, Foto, Pasaporte)")
        sexo = st.radio("Sexo del cliente:", ["F", "M"], horizontal=True)
        tiempo = st.number_input("¿Cuántos minutos demoró en total?",
                                 min_value=0.1, value=1.0, step=0.5)
        satisfaccion = st.radio("¿El cliente se fue contento con el servicio?",
                                ["Sí, OPTIMO 😊", "NO, hubo molestias 😞"])
        enviar = st.form_submit_button("Guardar en el sistema ✔️", use_container_width=True)

    if enviar:
        try:
            guardar_registro(
                grupo=1 if "Grupo 1" in grupo else 2,
                servicio=servicio.strip() if servicio.strip() else "Varios",
                sexo=sexo,
                minutos=tiempo,
                satisfaccion='OPTIMO' if "Sí" in satisfaccion else 'REGULAR',
            )
            st.success("¡Listo! Registro guardado permanentemente en la nube con hora de Perú.")
        except Exception as e:
            st.error(f"No se pudo guardar el registro: {e}")

    st.divider()
    st.subheader("Últimos registros")
    mostrar_ultimos()


# ----------------------------------------------------------------------
# PANTALLA: EDITAR UN REGISTRO
# ----------------------------------------------------------------------
def vista_editar():
    st.title("✏️ Editar Registro de Cliente")
    df = cargar_datos()

    if len(df) == 0:
        st.warning("No hay registros disponibles para editar.")
        return

    opciones = [f"Registro #{idx} - {row['SERVICIO']} ({row['Minutos']:.2f} min)" for idx, row in df.iterrows()]
    seleccion = st.selectbox("Selecciona el registro que deseas modificar:", opciones)
    id_registro = int(seleccion.split("#")[1].split(" -")[0])

    registro_actual = df.loc[id_registro]
    grupo_previo = int(registro_actual['GRUPO DE SERVICIO'])
    servicio_previo = str(registro_actual['SERVICIO'])
    sexo_previo = str(registro_actual['SEXO'])
    minutos_previos = float(registro_actual['Minutos'])
    sat_previa = str(registro_actual['SATISFACCION'])

    st.markdown("---")
    st.subheader(f"Modificando Registro #{id_registro}")

    with st.form("form_editar"):
        idx_grupo = 0 if grupo_previo == 1 else 1
        nuevo_grupo = st.radio("Tipo de servicio:",
                               ["Grupo 1 (Copias/Impresiones)", "Grupo 2 (Trámites/Pasaporte)"],
                               index=idx_grupo)

        nuevo_servicio = st.text_input("Servicio exacto:", value=servicio_previo)

        idx_sexo = 0 if sexo_previo.upper() == "F" else 1
        nuevo_sexo = st.radio("Sexo del cliente:", ["F", "M"], index=idx_sexo, horizontal=True)

        nuevo_tiempo = st.number_input("Minutos de demora:", min_value=0.1, value=minutos_previos, step=0.5)

        idx_sat = 0 if es_optimo(pd.Series([sat_previa]))[0] else 1
        nueva_satisfaccion = st.radio("Satisfacción del cliente:",
                                      ["Sí, OPTIMO 😊", "NO, hubo molestias 😞"],
                                      index=idx_sat)

        guardar_cambios = st.form_submit_button("Actualizar Registro en la Nube 💾", use_container_width=True)

    if guardar_cambios:
        try:
            actualizar_registro(
                id_registro=id_registro,
                grupo=1 if "Grupo 1" in nuevo_grupo else 2,
                servicio=nuevo_servicio.strip() if nuevo_servicio.strip() else "Varios",
                sexo=nuevo_sexo,
                minutos=nuevo_tiempo,
                satisfaccion='OPTIMO' if "Sí" in nueva_satisfaccion else 'REGULAR',
            )
            st.success(f"¡Registro #{id_registro} actualizado correctamente!")
            st.rerun()
        except Exception as e:
            st.error(f"Error al actualizar el registro: {e}")


@st.fragment(run_every=REFRESCO)
def mostrar_ultimos():
    df = cargar_datos()
    st.caption(f"Total de clientes registrados: {len(df)}")
    
    if len(df) == 0:
        st.info("Aún no hay registros guardados.")
        return

    cols_mostrar = [c for c in ['GRUPO DE SERVICIO', 'SERVICIO', 'Minutos', 'SEXO', 'SATISFACCION', 'FECHA_HORA'] if c in df.columns]
    df_visual = df[cols_mostrar].tail(5).iloc[::-1].copy()
    if 'Minutos' in df_visual.columns:
        df_visual['TIEMPO (MM:SS)'] = df_visual['Minutos'].apply(_formatear_minutos_a_mmss)
        cols_orden = [c if c != 'Minutos' else 'TIEMPO (MM:SS)' for c in cols_mostrar]
        df_visual = df_visual[cols_orden]
    
    st.dataframe(df_visual, use_container_width=True)


# ----------------------------------------------------------------------
# PANTALLA 2: DASHBOARD DESCRIPTIVO
# ----------------------------------------------------------------------
@st.fragment(run_every=REFRESCO)
def vista_dashboard():
    st.title("Resumen de tu negocio")
    df = cargar_datos()
    st.caption(f"🔄 Actualización automática cada {REFRESCO} s · "
               f"Última lectura: {datetime.now(ZONA_PERU).strftime('%H:%M:%S')}")

    if len(df) == 0:
        st.warning("Registra al menos un cliente para visualizar el resumen.")
        return

    tiempo_promedio = df['Minutos'].mean()
    felices = int(es_optimo(df['SATISFACCION']).sum())
    porcentaje_felices = felices / len(df) * 100

    mostrar_semaforo_visual(df=df, meta_g1=REF_TIEMPO_G1, meta_g2=REF_TIEMPO_G2)

    col1, col2, col3 = st.columns(3)
    col1.metric("Clientes atendidos", len(df))
    col2.metric("Tiempo Promedio General", f"{_formatear_minutos_a_mmss(tiempo_promedio)} min")
    col3.metric("Clientes Felices", f"{porcentaje_felices:.0f}%")
    st.divider()

    st.subheader("Comparación por Grupo de Servicio")
    df_grupos = df.groupby('GRUPO DE SERVICIO')['Minutos'].mean().reset_index()
    df_grupos['GRUPO DE SERVICIO'] = "Grupo " + df_grupos['GRUPO DE SERVICIO'].astype(int).astype(str)
    df_grupos['Tiempo_Texto'] = df_grupos['Minutos'].apply(_formatear_minutos_a_mmss)
    
    fig1 = px.bar(df_grupos, x='GRUPO DE SERVICIO', y='Minutos',
                  color='GRUPO DE SERVICIO', text='Tiempo_Texto')
    st.plotly_chart(fig1, use_container_width=True)


# ----------------------------------------------------------------------
# PANTALLA 3: INFERENCIA ESTADÍSTICA
# ----------------------------------------------------------------------
@st.fragment(run_every=REFRESCO)
def vista_inferencial():
    st.title("Análisis Estadístico del Negocio")
    st.caption(f"🔄 Actualización automática cada {REFRESCO} s · "
               f"Última lectura: {datetime.now(ZONA_PERU).strftime('%H:%M:%S')}")

    df = cargar_datos()
    n_total = len(df)

    if n_total < 2:
        st.warning("Se necesitan al menos 2 registros para hacer el análisis.")
        return

    st.subheader("1. Estimación General del Servicio")
    mean_time = df['Minutos'].mean()
    std_time = df['Minutos'].std()
    if std_time > 0:
        ci_time = stats.t.interval(0.95, n_total - 1, loc=mean_time,
                                    scale=std_time / np.sqrt(n_total))
    else:
        ci_time = (mean_time, mean_time)

    felices = int(es_optimo(df['SATISFACCION']).sum())
    lo, hi = intervalo_wilson(felices, n_total, z=1.96)
    ci_prop = (lo * 100, hi * 100)

    t_inf_str = f"{_formatear_minutos_a_mmss(ci_time[0])} a {_formatear_minutos_a_mmss(ci_time[1])}"
    st.info(f"🕒 **Tiempo de atención:** Con un 95% de seguridad, el tiempo real promedio por cliente se encuentra entre **{t_inf_str} min**.")
    st.info(f"😊 **Satisfacción del cliente (Intervalo de Wilson):** Con un 95% de seguridad, el porcentaje real de clientes satisfechos está entre **{ci_prop[0]:.2f}% y {ci_prop[1]:.2f}%**.")

    st.divider()

    st.subheader("2. Comparación entre Grupos de Servicio")
    g1 = df[df['GRUPO DE SERVICIO'] == 1]
    g2 = df[df['GRUPO DE SERVICIO'] == 2]

    if len(g1) > 1 and len(g2) > 1:
        n1, n2 = len(g1), len(g2)
        v1, v2 = g1['Minutos'].var(), g2['Minutos'].var()

        diff_mean = g1['Minutos'].mean() - g2['Minutos'].mean()
        se_diff = np.sqrt(v1 / n1 + v2 / n2)
        if se_diff > 0:
            gl = se_diff**4 / ((v1 / n1)**2 / (n1 - 1) + (v2 / n2)**2 / (n2 - 1))
            tcrit = stats.t.ppf(0.975, gl)
            ci_m = (diff_mean - tcrit * se_diff, diff_mean + tcrit * se_diff)
        else:
            ci_m = (diff_mean, diff_mean)

        if ci_m[1] < 0:
            concl = "El **Grupo 1** es significativamente más rápido."
        elif ci_m[0] > 0:
            concl = "El **Grupo 2** es significativamente más rápido."
        else:
            concl = "No hay diferencia de velocidad importante."
        st.success(f"⚖️ **Diferencia de tiempos:** Entre {ci_m[0]:.2f} a {ci_m[1]:.2f} min. {concl}")
    else:
        st.warning("Se necesitan al menos 2 datos en cada grupo para comparar.")

    st.divider()

    st.subheader("3. Evaluación de Metas del Negocio")
    for num_g, meta_g, nombre_g in [(1, REF_TIEMPO_G1, "Grupo 1"), (2, REF_TIEMPO_G2, "Grupo 2")]:
        sub = df[df['GRUPO DE SERVICIO'] == num_g]['Minutos']
        if len(sub) > 1 and sub.std() > 0:
            _, p_val = stats.ttest_1samp(sub, meta_g, alternative='less')
            if p_val < 0.05:
                st.success(f"🟢 **Meta {nombre_g} Cumplida:** Promedio por debajo de {meta_g} min (p={p_val:.3f}).")
            else:
                st.error(f"🔴 **Meta {nombre_g} No Superada:** Promedio no es menor a {meta_g} min (p={p_val:.3f}).")

    p_0 = REF_SAT / 100
    p_val_prop = stats.binomtest(felices, n_total, p_0, alternative='greater').pvalue
    if p_val_prop < 0.05:
        st.success(f"🟢 **Meta de Satisfacción Cumplida:** Supera el {REF_SAT}%.")
    else:
        st.error(f"🔴 **Meta de Satisfacción No Alcanzada.**")


# ----------------------------------------------------------------------
# PANTALLA 4: TABLA Y DESCARGA
# ----------------------------------------------------------------------
@st.fragment(run_every=REFRESCO)
def vista_excel():
    st.title("Base de datos en tiempo real (Nube)")
    df = cargar_datos()
    st.caption(f"🔄 Actualización automática cada {REFRESCO} s · "
               f"{len(df)} registros · Última lectura: {datetime.now(ZONA_PERU).strftime('%H:%M:%S')}")
    st.dataframe(df, use_container_width=True)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=True, sheet_name='Registros')

    st.download_button(
        label="⬇️ Descargar respaldo en Excel",
        data=buffer.getvalue(),
        file_name=f"Datos_Imprenta_{datetime.now(ZONA_PERU).strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )




# ----------------------------------------------------------------------
# ENRUTADOR
# ----------------------------------------------------------------------
if menu == "⏱️ Registrar un cliente":
    vista_registro()
elif menu == "✏️ Editar un registro":
    vista_editar()
elif menu == "📊 Dashboard Descriptivo":
    vista_dashboard()
elif menu == "📈 Análisis Inferencial":
    vista_inferencial()
else:
    vista_excel()
