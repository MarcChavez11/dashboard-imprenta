import os
import threading
from datetime import datetime, time as dtime

import streamlit as st
import pandas as pd
import plotly.express as px
import scipy.stats as stats
import numpy as np
from openpyxl import load_workbook

# ----------------------------------------------------------------------
# CONFIGURACIÓN - CONFIGURACION - Base de datos
# ----------------------------------------------------------------------
ARCHIVO = "Datos.xlsx"   # Base de datos (debe estar junto a este archivo)
REFRESCO = 5             # Cada cuántos segundos se actualizan las pantallas

st.set_page_config(page_title="Imprenta Flores", layout="centered")

st.sidebar.title("Imprenta Flores")

# ----------------------------------------------------------------------
# COMPONENTE: SEMÁFORO GLOBAL EN LA BARRA LATERAL
# ----------------------------------------------------------------------
def mostrar_semaforo_sidebar():
    """Muestra un semáforo general y actualizado en la barra lateral."""
    try:
        df_temp = cargar_datos()
        if len(df_temp) > 0:
            t_prom = df_temp['Minutos'].mean()
            tiempo_ideal = 5.0
            tolerancia = 1.2
            umbral_amarillo = tiempo_ideal * tolerancia

            st.sidebar.markdown("---")
            st.sidebar.markdown("### 🚦 Estado del Negocio")
            
            if t_prom <= tiempo_ideal:
                st.sidebar.success(
                    f"**🟢 ÓPTIMO**\n\n"
                    f"Promedio: **{t_prom:.1f} min**\n\n"
                    f"¡Excelente ritmo! Estamos cumpliendo la meta (≤ {tiempo_ideal:.0f} min)."
                )
            elif t_prom <= umbral_amarillo:
                st.sidebar.warning(
                    f"**🟡 PRECAUCIÓN**\n\n"
                    f"Promedio: **{t_prom:.1f} min**\n\n"
                    f"Los tiempos subieron un poco. Conviene agilizar la atención."
                )
            else:
                st.sidebar.error(
                    f"**🔴 DEMORADO**\n\n"
                    f"Promedio: **{t_prom:.1f} min**\n\n"
                    f"¡Alerta! Los tiempos son muy altos (> {umbral_amarillo:.0f} min)."
                )
    except Exception:
        pass

menu = st.sidebar.radio("¿Qué deseas hacer?", [
    "⏱️ Registrar un cliente",
    "📊 Dashboard Descriptivo",
    "📈 Análisis Inferencial",
    "🛠️ Modo Ingeniero (Ver Excel)"
])

# Ejecutamos el semáforo global en la barra lateral
mostrar_semaforo_sidebar()


# ----------------------------------------------------------------------
# BASE DE DATOS (EXCEL)
# ----------------------------------------------------------------------
@st.cache_resource
def obtener_candado():
    """Un solo candado compartido por todas las sesiones, para que dos
    registros simultáneos no se pisen al escribir el Excel."""
    return threading.Lock()


def _convertir_a_minutos(t):
    try:
        return t.hour * 60 + t.minute + t.second / 60
    except Exception:
        partes = str(t).split(':')
        return int(partes[0]) * 60 + int(partes[1]) + float(partes[2]) / 60


@st.cache_data
def _leer_excel(ruta, fecha_modificacion):
    """La caché depende de la fecha de modificación del archivo: si el Excel
    cambia (por la app o editado a mano), se vuelve a leer automáticamente."""
    df = pd.read_excel(ruta)
    df = df.iloc[:, :5]
    df.columns = ['GRUPO DE SERVICIO', 'SERVICIO', 'TIEMPO_EXCEL', 'SEXO', 'SATISFACCION']
    df = df.dropna(subset=['GRUPO DE SERVICIO'])
    df['Minutos'] = df['TIEMPO_EXCEL'].apply(_convertir_a_minutos)
    df['SATISFACCION'] = df['SATISFACCION'].astype(str).str.strip()
    df.index = range(1, len(df) + 1)
    return df


def cargar_datos():
    try:
        return _leer_excel(ARCHIVO, os.path.getmtime(ARCHIVO))
    except FileNotFoundError:
        st.error(f"No encuentro el archivo {ARCHIVO}. Debe estar en la misma carpeta que app.py.")
        st.stop()
    except Exception as e:
        st.warning(f"No pude leer el Excel en este momento (¿se está guardando?). Reintentando... ({e})")
        st.stop()


def guardar_registro(grupo, servicio, sexo, minutos, satisfaccion):
    """Agrega una fila al final del Excel sin reescribir todo el archivo."""
    total_seg = int(round(minutos * 60))
    m, s = divmod(total_seg, 60)
    h, m = divmod(m, 60)

    with obtener_candado():
        wb = load_workbook(ARCHIVO)
        ws = wb.active
        fila = ws.max_row
        while fila > 1 and ws.cell(fila, 1).value is None:
            fila -= 1
        fila += 1

        ws.cell(fila, 1, grupo)
        ws.cell(fila, 2, servicio)
        celda_tiempo = ws.cell(fila, 3, dtime(h, m, s))
        celda_tiempo.number_format = "h:mm:ss"
        ws.cell(fila, 4, sexo)
        ws.cell(fila, 5, satisfaccion)
        wb.save(ARCHIVO)


def intervalo_wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z**2 / n
    centro = (p + z**2 / (2 * n)) / den
    mitad = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return centro - mitad, centro + mitad


def es_optimo(serie):
    return serie.str.contains('OPTIMO', case=False, na=False)


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
                                ["Sí, OPTIMO 😊", "No hubo molestias 😞"])
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
            st.success("¡Listo! Registro guardado. El dashboard y el análisis se actualizan solos.")
        except PermissionError:
            st.error("No se pudo guardar: el Excel está abierto en otro programa. "
                     "Ciérralo e inténtalo de nuevo.")
        except Exception as e:
            st.error(f"No se pudo guardar el registro: {e}")

    st.divider()
    st.subheader("Últimos registros")
    mostrar_ultimos()


@st.fragment(run_every=REFRESCO)
def mostrar_ultimos():
    df = cargar_datos()
    st.caption(f"Total de clientes registrados: {len(df)}")
    st.dataframe(
        df[['GRUPO DE SERVICIO', 'SERVICIO', 'Minutos', 'SEXO', 'SATISFACCION']].tail(5).iloc[::-1],
        use_container_width=True,
    )


# ----------------------------------------------------------------------
# PANTALLA 2: DASHBOARD DESCRIPTIVO (se actualiza solo)
# ----------------------------------------------------------------------
@st.fragment(run_every=REFRESCO)
def vista_dashboard():
    st.title("Resumen de tu negocio")
    df = cargar_datos()
    st.caption(f"🔄 Actualización automática cada {REFRESCO} s · "
               f"Última lectura: {datetime.now().strftime('%H:%M:%S')}")

    tiempo_promedio = df['Minutos'].mean()
    felices = int(es_optimo(df['SATISFACCION']).sum())
    porcentaje_felices = felices / len(df) * 100

    col1, col2, col3 = st.columns(3)
    col1.metric("Clientes atendidos", len(df))
    col2.metric("Tiempo Promedio General", f"{tiempo_promedio:.2f} min")
    col3.metric("Clientes Felices", f"{porcentaje_felices:.0f}%")
    st.divider()

    st.subheader("Comparación por Grupo de Servicio")
    df_grupos = df.groupby('GRUPO DE SERVICIO')['Minutos'].mean().reset_index()
    df_grupos['GRUPO DE SERVICIO'] = "Grupo " + df_grupos['GRUPO DE SERVICIO'].astype(int).astype(str)
    fig1 = px.bar(df_grupos, x='GRUPO DE SERVICIO', y='Minutos',
                  color='GRUPO DE SERVICIO', text_auto='.2f')
    st.plotly_chart(fig1, use_container_width=True)


# ----------------------------------------------------------------------
# PANTALLA 3: INFERENCIA ESTADÍSTICA (se actualiza sola)
# ----------------------------------------------------------------------
@st.fragment(run_every=REFRESCO)
def vista_inferencial():
    st.title("Análisis Estadístico del Negocio")
    st.caption(f"🔄 Actualización automática cada {REFRESCO} s · "
               f"Última lectura: {datetime.now().strftime('%H:%M:%S')}")

    df = cargar_datos()
    n_total = len(df)

    if n_total < 2:
        st.warning("Se necesitan al menos 2 registros para hacer el análisis.")
        return

    # ---------------- OBJETIVO 1 ----------------
    st.subheader("1. Estimación General del Servicio")
    st.write("Confiabilidad estadística basada en las atenciones actuales:")

    mean_time = df['Minutos'].mean()
    std_time = df['Minutos'].std()
    if std_time > 0:
        ci_time = stats.t.interval(0.95, n_total - 1, loc=mean_time,
                                    scale=std_time / np.sqrt(n_total))
    else:
        ci_time = (mean_time, mean_time)

    felices = int(es_optimo(df['SATISFACCION']).sum())

    lo = stats.beta.ppf(0.025, felices, n_total - felices + 1) if felices > 0 else 0.0
    hi = stats.beta.ppf(0.975, felices + 1, n_total - felices) if felices < n_total else 1.0
    ci_prop = (lo * 100, hi * 100)

    st.info(f"🕒 **Tiempo de atención:** Con un 95% de seguridad, el tiempo real promedio por cliente se encuentra entre **{ci_time[0]:.2f} y {ci_time[1]:.2f} minutos**.")
    st.info(f"😊 **Satisfacción del cliente:** Con un 95% de seguridad, el porcentaje real de clientes satisfechos está entre **{ci_prop[0]:.2f}% y {ci_prop[1]:.2f}%**.")

    st.divider()

    # ---------------- OBJETIVO 2 ----------------
    st.subheader("2. Comparación entre Grupos de Servicio")
    st.write("Evaluando cuál grupo de servicio rinde mejor:")

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
            concl = "No hay una diferencia de velocidad importante entre ambos grupos."
        st.success(f"⚖️ **Diferencia de tiempos (G1 vs G2):** [{ci_m[0]:.2f}, {ci_m[1]:.2f}] min. {concl}")

        k1 = int(es_optimo(g1['SATISFACCION']).sum())
        k2 = int(es_optimo(g2['SATISFACCION']).sum())
        p1, p2 = k1 / n1, k2 / n2
        l1, u1 = intervalo_wilson(k1, n1)
        l2, u2 = intervalo_wilson(k2, n2)
        dp = p1 - p2
        ci_p = (dp - np.sqrt((p1 - l1)**2 + (u2 - p2)**2),
                dp + np.sqrt((u1 - p1)**2 + (p2 - l2)**2))
        st.success(f"⚖️ **Diferencia de satisfacción:** El margen de diferencia en clientes felices entre G1 y G2 es de **[{ci_p[0] * 100:.1f}%, {ci_p[1] * 100:.1f}%]**.")

        if min(n1, n2) < 10:
            st.warning(f"⚠️ Precaución: Un grupo tiene pocos datos ({min(n1, n2)} registros). Se recomienda registrar más atenciones para mayor precisión.")
    else:
        st.warning("Se necesitan al menos 2 datos en cada grupo para hacer comparaciones.")

    st.divider()

    # ---------------- OBJETIVO 3 ----------------
    st.subheader("3. Evaluación de Metas del Negocio")
    st.write("Verificación frente a los estándares esperados:")

    col_a, col_b = st.columns(2)
    ref_tiempo = col_a.number_input("Meta máxima de tiempo esperada (min)",
                                    value=6.0, step=0.5, key="ref_tiempo")
    ref_sat = col_b.number_input("Meta mínima de satisfacción (%)",
                                 value=90, step=5, key="ref_sat")

    if std_time > 0:
        _, p_val = stats.ttest_1samp(df['Minutos'], ref_tiempo, alternative='less')
        if p_val < 0.05:
            st.success(f"🟢 **Meta de Tiempo Cumplida:** El tiempo promedio está por debajo de los {ref_tiempo} min establecidos (Demostrado estadísticamente).")
        else:
            st.error(f"🔴 **Meta de Tiempo No Superada:** Todavía no hay evidencia suficiente de que estemos por debajo de los {ref_tiempo} min.")
    else:
        st.warning("No hay suficiente variación de datos para probar la media.")

    p_0 = ref_sat / 100
    p_val_prop = stats.binomtest(felices, n_total, p_0, alternative='greater').pvalue
    if p_val_prop < 0.05:
        st.success(f"🟢 **Meta de Satisfacción Cumplida:** Superamos con éxito la meta del {ref_sat}% de clientes felices.")
    else:
        st.error(f"🔴 **Meta de Satisfacción No Alcanzada:** Aún no alcanzamos consistentemente la meta del {ref_sat}% de satisfacción.")


# ----------------------------------------------------------------------
# PANTALLA 4: TABLA (se actualiza sola)
# ----------------------------------------------------------------------
@st.fragment(run_every=REFRESCO)
def vista_excel():
    st.title("Base de datos en tiempo real")
    df = cargar_datos()
    st.caption(f"🔄 Actualización automática cada {REFRESCO} s · "
               f"{len(df)} registros · Última lectura: {datetime.now().strftime('%H:%M:%S')}")
    st.dataframe(df, use_container_width=True)

    with open(ARCHIVO, "rb") as f:
        st.download_button("⬇️ Descargar Excel", f.read(), file_name="Datos.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ----------------------------------------------------------------------
# ENRUTADOR
# ----------------------------------------------------------------------
if menu == "⏱️ Registrar un cliente":
    vista_registro()
elif menu == "📊 Dashboard Descriptivo":
    vista_dashboard()
elif menu == "📈 Análisis Inferencial":
    vista_inferencial()
else:
    vista_excel()
