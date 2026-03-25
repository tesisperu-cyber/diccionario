import re
import requests
import streamlit as st
from bs4 import BeautifulSoup
from groq import Groq

st.set_page_config(page_title="Buscador de Palabras", page_icon="📖", layout="centered")
st.title("📖 Buscador de Palabras")
st.caption("Definición RAE (DLE) · Sinónimos Lexus · Groq")

with st.sidebar:
    st.header("⚙️ Configuración")
    api_key = st.text_input("Groq API Key", type="password", placeholder="gsk_...",
                            help="Gratis en https://console.groq.com")
    if api_key and (not api_key.startswith("gsk_") or len(api_key) < 20):
        st.error("Formato inválido — debe empezar con gsk_")
        api_key = ""
    elif api_key:
        st.success("✅ Clave lista")
    st.divider()
    st.markdown("**Fuentes:**")
    st.markdown("- 📡 **RAE** — definición oficial del DLE")
    st.markdown("- 📚 **Lexus** — 15.869 sinónimos")
    st.markdown("- 🤖 **Groq** — presenta la info real")

@st.cache_resource
def cargar_lexus():
    lexus = {}
    try:
        with open("sinonimos.txt", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea or linea.startswith("#"):
                    continue
                sep = linea.find(":")
                if sep < 1:
                    continue
                clave = linea[:sep].strip().lower()
                sins  = [s.strip() for s in linea[sep+1:].split(",") if s.strip()]
                if clave and sins:
                    lexus[clave] = sins
    except FileNotFoundError:
        st.error("❌ No se encontró sinonimos.txt")
    return lexus

LEXUS = cargar_lexus()

def _norm(w):
    return w.lower()\
        .replace("á","a").replace("é","e").replace("í","i")\
        .replace("ó","o").replace("ú","u").replace("ü","u").replace("ñ","n")

def buscar_lexus(palabra):
    n = _norm(palabra)
    for clave, sins in LEXUS.items():
        if _norm(clave) == n:
            return sins
    variantes = []
    if n.endswith("mente"):  variantes.append(n[:-5])
    if n.endswith("cion"):   variantes.append(n[:-4])
    if n.endswith("ando"):   variantes.append(n[:-4]+"ar")
    if n.endswith("iendo"):  variantes += [n[:-5]+"er", n[:-5]+"ir"]
    if n.endswith("ado"):    variantes.append(n[:-3]+"ar")
    if n.endswith("ido"):    variantes += [n[:-3]+"er", n[:-3]+"ir"]
    if n.endswith("s") and len(n) > 3:
        variantes.append(n[:-1])
    for v in variantes:
        for clave, sins in LEXUS.items():
            if _norm(clave) == v:
                return sins
    return []

# ── RAE: funciona desde Streamlit Cloud (IPs no bloqueadas) ──
HEADERS_RAE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://dle.rae.es/",
    "DNT": "1",
}

def consultar_rae(palabra):
    url = f"https://dle.rae.es/{requests.utils.quote(palabra.lower())}"
    out = {"definiciones": [], "sinonimos_rae": [], "url": url, "error": None}
    try:
        res = requests.get(url, headers=HEADERS_RAE, timeout=10)
        if res.status_code == 404:
            out["error"] = f'"{palabra}" no está en el DLE de la RAE.'
            return out
        if res.status_code == 403:
            out["error"] = "La RAE rechazó la consulta. Intenta de nuevo en unos segundos."
            return out
        if res.status_code != 200:
            out["error"] = f"Error HTTP {res.status_code}."
            return out

        soup     = BeautifulSoup(res.text, "html.parser")
        articulo = soup.find("article")
        if not articulo:
            out["error"] = "La RAE no devolvió resultados. Intenta de nuevo."
            return out

        for p in articulo.find_all("p", class_=re.compile(r"^j")):
            num_tag = p.find("span", class_="n_acep")
            num     = num_tag.get_text(strip=True) if num_tag else ""
            cat     = " ".join(
                a.get("title", a.get_text(strip=True)) for a in p.find_all("abbr")
            ).strip()
            texto = p.get_text(separator=" ", strip=True)
            if num and texto.startswith(num):
                texto = texto[len(num):].strip()
            if texto:
                out["definiciones"].append({"num": num, "categoria": cat, "texto": texto})

        sins = set()
        for tag in articulo.find_all(class_="sin"):
            for s in re.split(r"[,;]", tag.get_text()):
                s = s.strip().lower()
                if s and 1 < len(s) < 40:
                    sins.add(s)
        out["sinonimos_rae"] = sorted(sins)

        if not out["definiciones"]:
            out["error"] = f'Sin definiciones para "{palabra}" en la RAE.'

    except requests.exceptions.Timeout:
        out["error"] = "La RAE tardó demasiado. Intenta de nuevo."
    except Exception as e:
        out["error"] = f"Error: {e}"
    return out

# ── Groq: SOLO presenta la info real, NO inventa ─────────
def preguntar_groq(palabra, rae, sins_lexus, api_key):
    if rae["error"]:
        if not sins_lexus:
            return f'No se encontró información para **"{palabra}"** en ninguna fuente.'
        prompt = (
            f"Palabra: **{palabra.upper()}**\n\n"
            f"RAE no disponible: {rae['error']}\n\n"
            f"SINÓNIMOS (LEXUS): {', '.join(sins_lexus[:20])}\n\n"
            "Presenta solo los sinónimos del Lexus. NO inventes definiciones. Formato Markdown."
        )
    else:
        defs = "\n".join(
            f"  {d['num']}. " + (f"*{d['categoria']}* — " if d["categoria"] else "") + d["texto"]
            for d in rae["definiciones"][:8]
        )
        prompt = (
            f"Organiza esta información sobre **{palabra.upper()}** en Markdown:\n\n"
            f"DEFINICIONES EXACTAS DE LA RAE (DLE):\n{defs}\n\n"
            f"SINÓNIMOS (RAE): {', '.join(rae['sinonimos_rae']) or 'ninguno'}\n\n"
            f"SINÓNIMOS (LEXUS): {', '.join(sins_lexus[:20]) if sins_lexus else 'sin entrada'}\n\n"
            "INSTRUCCIONES ESTRICTAS:\n"
            "- Copia las definiciones de la RAE EXACTAMENTE, sin cambiar una sola palabra.\n"
            "- NO agregues definiciones propias ni uses tu conocimiento.\n"
            "- Agrupa todos los sinónimos al final indicando la fuente.\n"
            "- Agrega un ejemplo de uso académico al final.\n"
            '- Indica "Fuente: RAE — DLE" y "Fuente: Diccionario Lexus".'
        )

    cliente = Groq(api_key=api_key)
    resp    = cliente.chat.completions.create(
        model       = "llama-3.3-70b-versatile",
        messages    = [{"role": "user", "content": prompt}],
        temperature = 0.1,
        max_tokens  = 900,
    )
    return resp.choices[0].message.content

# ── Interfaz ──────────────────────────────────────────────
st.divider()

col1, col2 = st.columns([4, 1])
with col1:
    palabra = st.text_input("Palabra", placeholder="Ej: canción, investigación, método...",
                            label_visibility="collapsed")
with col2:
    buscar = st.button("🔍 Buscar", use_container_width=True, type="primary")

if LEXUS:
    st.caption(f"📚 Diccionario Lexus — {len(LEXUS):,} entradas cargadas")
else:
    st.warning("⚠️ sinonimos.txt no encontrado en la carpeta del proyecto")

if buscar and palabra.strip():
    if not api_key:
        st.error("⚠️ Ingresa tu API Key de Groq en el panel izquierdo.")
        st.stop()

    palabra = palabra.strip()

    col_r, col_l = st.columns(2)
    with col_r:
        with st.spinner("Consultando RAE..."):
            rae = consultar_rae(palabra)
    with col_l:
        sins_lexus = buscar_lexus(palabra)

    tab1, tab2, tab3 = st.tabs(["🤖 Respuesta completa", "📡 RAE", "📚 Lexus"])

    with tab1:
        with st.spinner("Consultando Groq..."):
            try:
                respuesta = preguntar_groq(palabra, rae, sins_lexus, api_key)
                st.markdown(respuesta)
            except Exception as e:
                st.error(f"Error Groq: {e}")

    with tab2:
        st.markdown(f"**[Ver en DLE →]({rae['url']})**")
        if rae["error"]:
            st.warning(rae["error"])
        else:
            for d in rae["definiciones"]:
                num = f"**{d['num']}.** " if d["num"] else "• "
                cat = f"*{d['categoria']}* " if d["categoria"] else ""
                st.markdown(f"{num}{cat}{d['texto']}")
            if rae["sinonimos_rae"]:
                st.divider()
                st.markdown("**Sinónimos según la RAE:**")
                st.markdown(", ".join(rae["sinonimos_rae"]))

    with tab3:
        if sins_lexus:
            st.markdown(f"**{len(sins_lexus)} sinónimos encontrados:**")
            st.markdown(", ".join(sins_lexus))
        else:
            st.info(f'"{palabra}" no tiene entrada directa en el Diccionario Lexus.')

elif buscar and not palabra.strip():
    st.warning("Escribe una palabra para buscar.")
