import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re, ast, requests, json, math
from pathlib import Path
from datetime import datetime
from collections import Counter

st.set_page_config(
    page_title="VeloGuard — Conformité L228-2",
    page_icon="🚲", layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 2rem; }
.warning-banner {
    background:#fffbeb; border-left:4px solid #f59e0b;
    padding:10px 14px; border-radius:0 8px 8px 0; margin:8px 0; font-size:13px;
}
.commune-card {
    background:#f0fff4; border-left:3px solid #38a169;
    padding:8px 12px; border-radius:0 8px 8px 0; margin-bottom:6px;
}
.projet-pur {
    background:#ebf8ff; border-left:3px solid #3182ce;
    padding:8px 12px; border-radius:0 8px 8px 0; margin-bottom:6px;
}
div[data-testid="stColumn"] button {
    min-height: 28px !important;
    height: 28px !important;
    padding: 0px 2px !important;
    font-size: 12px !important;
    border-radius: 6px !important;
    margin-top: 0px !important;
    margin-bottom: 0px !important;
}
div[data-testid="stDataFrame"] {
    margin-bottom: 0px !important;
}
</style>
""", unsafe_allow_html=True)

# ── SCORING ───────────────────────────────────────────────────
DESC_VOIRIE_FORT   = ['voirie', 'voirie et réseaux divers', 'chaussée']
DESC_VOIRIE_FAIBLE = ['trottoir', 'revêtement', 'terrassement']
MOTS_REFECTION = [
    r'r[eé]fection.{0,30}(voirie|chauss[eé]e|trottoir|rue|avenue|boulevard)',
    r'r[eé]habilitation.{0,30}(voirie|chauss[eé]e|rue|avenue)',
    r'r[eé]am[eé]nagement.{0,30}(voirie|rue|avenue|boulevard|place|giratoire)',
    r'am[eé]nagement.{0,30}(voirie|rue|avenue|boulevard|place|giratoire|carrefour)',
    r'requalification.{0,30}(voirie|rue|avenue|boulevard|place)',
    r'travaux.{0,20}voirie', r'entretien.{0,20}voirie',
    r'am[eé]nagement urbain', r'enrob[eé]', r'enduit superficiel',
    r'rev[eê]tement.{0,20}(chauss[eé]e|voirie|rue)',
    r'trottoir', r'chauss[eé]e', r'giratoire',
    r'carrefour.{0,20}(am[eé]nag|s[eé]curis)',
]
EXCLUSIONS_FORTES = [
    r'\b(b[aâ]timent|r[eé]novation.{0,20}b[aâ]t|construction.{0,20}b[aâ]t)\b',
    r'\b(r[eé]seau.{0,15}(ftth|fibre|eau potable|gaz|assainissement))\b',
    r'\b(toiture|charpente|menuiserie|peinture.{0,10}b[aâ]t|plomberie)\b',
    r'\b(barrage|berge|digue)\b', r'\b(ascenseur|escalier)\b',
    r'\bd[eé]samiantage\b',
    r'\b(pharmacie|h[oô]pital|chru?|ehpad)\b',
    r'\bstade\b', r'\btribune\b', r'\bcimeti[eè]re\b', r'\ba[eé]roport\b',
]
HORS_PERIMETRE_INFRA = [
    r'\bautoroute\b', r'\bvoie rapide\b', r'\b2\s*x\s*2\b',
    r'\b(pont|viaduc|tablier|ouvrage d.art)\b.{0,40}(RN|RD|route)',
    r'\b(RN|RD)\b.{0,40}\b(pont|viaduc|tablier|ouvrage d.art)\b',
    r'\b(cloture|ecran acoustique|anticorrosion|potence)\b.{0,40}\b(RN|RD)\b',
    r'\b(RN|RD)\b.{0,40}\b(cloture|ecran acoustique|anticorrosion|potence)\b',
    r'\bcontournement\b.{0,20}\b(nord|sud|est|ouest)\b', r'\bechangeur\b',
]
KEYWORDS_CYCLABLE = [
    r'piste cyclable', r'bande cyclable', r'voie cyclable',
    r'itin[eé]raire cyclable', r'r[eé]seau cyclable',
    r'v[eé]loroute', r'voie verte', r'couloir v[eé]lo',
    r'am[eé]nagement cyclable', r'continuit[eé] cyclable',
    r'arceaux? v[eé]lo', r'stationnement v[eé]lo',
    r'abri v[eé]lo', r'box v[eé]lo', r'parking v[eé]lo',
    r'borne de recharge.{0,20}v[eé]lo',
    r'v[eé]lo\b', r'v[eé]los\b', r'cycliste',
    r'deux[-\s]roues', r'mobilit[eé] douce',
    r'cheminement doux', r'mode doux',
    r'usager.{0,15}v[eé]lo', r'L\.?228[-\s]2',
]
FAUX_CONF_PATTERNS = [
    r'cour.{0,20}(école|collège|lycée)',
    r'(abri|parking|arceaux).{0,20}v[eé]lo.{0,40}(école|collège|lycée|bâtiment)',
    r'centre aquatique', r'photovolta[iï]que', r'ombrière',
    r'r[eé]novation (énergétique|thermique)',
    r'(résidence|foyer).{0,20}(étudiant|jeune)',
]

def parse_descripteurs(val):
    try:
        lst = ast.literal_eval(str(val))
        return [str(x).lower().strip() for x in lst] if isinstance(lst, list) else [str(val).lower()]
    except:
        return [s.strip().lower() for s in str(val).split(',')]

def score_perimetre(row):
    descs   = parse_descripteurs(row.get('descripteur_str', ''))
    objet   = str(row.get('objet', '')).lower()
    nb_desc = len(descs)
    score   = 0
    has_fort = any(any(v in d for v in DESC_VOIRIE_FORT) for d in descs)
    if has_fort:
        score += 0 if nb_desc > 8 else (1 if nb_desc > 5 else 2)
    elif any(any(v in d for v in DESC_VOIRIE_FAIBLE) for d in descs) and nb_desc <= 4:
        score += 1
    for p in MOTS_REFECTION:
        if re.search(p, objet, re.IGNORECASE): score += 1; break
    for p in EXCLUSIONS_FORTES:
        if re.search(p, objet, re.IGNORECASE): score -= 3; break
    for p in HORS_PERIMETRE_INFRA:
        if re.search(p, objet, re.IGNORECASE): score -= 3; break
    if re.search(r'\bconstruction\b.{0,30}\b(neuve|b[aâ]timent|logements|maisons?)\b', objet, re.IGNORECASE):
        score -= 1
    return score

def detecter_cyclable(texte):
    t = str(texte).lower()
    mots = []
    for p in KEYWORDS_CYCLABLE:
        m = re.findall(p, t, re.IGNORECASE)
        if m: mots.extend([str(x).lower() for x in m])
    return bool(mots), list(set(mots))

def est_faux_conforme(row):
    if not row.get('cyclable_detecte'): return False
    objet = str(row.get('objet', ''))
    return any(re.search(p, objet, re.IGNORECASE) for p in FAUX_CONF_PATTERNS)

def render_pagination(current_page, total_pages, key_prefix="alertes"):
    if total_pages <= 1:
        return current_page

    if total_pages <= 7:
        page_nums = list(range(1, total_pages + 1))
    else:
        pages_set = {1, 2, total_pages - 1, total_pages}
        pages_set.update({max(1, current_page - 1), current_page, min(total_pages, current_page + 1)})
        sorted_p = sorted(list(pages_set))
        page_nums = []
        for i, p in enumerate(sorted_p):
            if i > 0 and p > sorted_p[i-1] + 1:
                page_nums.append("...")
            page_nums.append(p)

    items = ["«", "‹"] + page_nums + ["›", "»"]

    _, center_col, _ = st.columns([1, 2.5, 1])
    new_page = current_page

    with center_col:
        cols = st.columns(len(items))
        for idx, (col, item) in enumerate(zip(cols, items)):
            with col:
                if item == "«":
                    if st.button("«", key=f"{key_prefix}_first", disabled=(current_page == 1), use_container_width=True):
                        new_page = 1
                elif item == "‹":
                    if st.button("‹", key=f"{key_prefix}_prev", disabled=(current_page == 1), use_container_width=True):
                        new_page = current_page - 1
                elif item == "›":
                    if st.button("›", key=f"{key_prefix}_next", disabled=(current_page == total_pages), use_container_width=True):
                        new_page = current_page + 1
                elif item == "»":
                    if st.button("»", key=f"{key_prefix}_last", disabled=(current_page == total_pages), use_container_width=True):
                        new_page = total_pages
                elif item == "...":
                    st.button("…", key=f"{key_prefix}_dots_{idx}", disabled=True, use_container_width=True)
                else:
                    is_active = (item == current_page)
                    b_type = "primary" if is_active else "secondary"
                    if st.button(str(item), key=f"{key_prefix}_page_{item}", type=b_type, use_container_width=True):
                        new_page = item

    if new_page != current_page:
        st.session_state[f"{key_prefix}_page"] = new_page
        st.rerun()

    return new_page

# ── CHARGEMENT ────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load(path):
    df = pd.read_csv(path)
    def parse_dept(v):
        try:
            lst = ast.literal_eval(str(v))
            return str(lst[0]).zfill(2) if lst else "00"
        except:
            return str(v).zfill(2)[:2]
    if 'code_departement' in df.columns:
        df['dept'] = df['code_departement'].apply(parse_dept)
    df['dateparution'] = pd.to_datetime(df['dateparution'], errors='coerce', utc=True).dt.tz_localize(None)
    if 'datelimitereponse' in df.columns:
        df['datelimitereponse'] = pd.to_datetime(df['datelimitereponse'], errors='coerce', utc=True).dt.tz_localize(None)
    if 'url_pdf' not in df.columns:
        df['url_pdf'] = ''
    if 'url_avis' not in df.columns and 'idweb' in df.columns:
        df['url_avis'] = 'https://www.boamp.fr/pages/avis/?q=idweb:' + df['idweb'].astype(str)

    # Recalculer scores v5
    df['score_perimetre']  = df.apply(score_perimetre, axis=1)
    df['dans_perimetre']   = df['score_perimetre'] >= 2
    results = (df['objet'].fillna('') + ' ' + df.get('descripteur_str', pd.Series(['']*len(df))).fillna('')).apply(detecter_cyclable)
    df['cyclable_detecte'] = results.apply(lambda x: x[0])
    df['cyclable_mots']    = results.apply(lambda x: ', '.join(x[1]) if x[1] else '')
    df['faux_conforme']    = df.apply(est_faux_conforme, axis=1)
    # Vrai conforme = cyclable ET dans périmètre ET pas faux conforme
    df['vrai_conforme']    = df['dans_perimetre'] & df['cyclable_detecte'] & ~df['faux_conforme']
    df['alerte_l228']      = df['dans_perimetre'] & ~df['vrai_conforme']
    # Catégorie pour le tableau communes actives
    def categorie(row):
        if row['cyclable_detecte'] and not row['faux_conforme']:
            return 'L228-2 ✅' if row['dans_perimetre'] else 'Projet vélo pur 🚲'
        return ''
    df['categorie_velo'] = df.apply(categorie, axis=1)
    return df

@st.cache_data(ttl=86400)
def load_geo():
    try:
        return requests.get(
            "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson",
            timeout=10).json()
    except:
        return None

uploaded = st.sidebar.file_uploader("📂 Fichier CSV VeloGuard", type="csv")
csv_local = sorted(Path("data").glob("boamp_voirie_*.csv")) or sorted(Path(".").glob("boamp_voirie_*.csv"))
if uploaded:   df = load(uploaded)
elif csv_local: df = load(str(csv_local[-1]))
else:
    st.error("Aucun fichier CSV. Chargez-en un via la sidebar.")
    st.stop()

geo = load_geo()

# ── SIDEBAR ───────────────────────────────────────────────────
st.sidebar.title("🔍 Filtres")
dates = df['dateparution'].dropna()
d_min, d_max = dates.min().date(), dates.max().date()
plage = st.sidebar.date_input("Période", (d_min, d_max), min_value=d_min, max_value=d_max)
sel_depts = st.sidebar.multiselect("Département(s)", sorted(df['dept'].dropna().unique()), placeholder="Tous")
score_min = st.sidebar.slider("Score périmètre minimum", 0, 5, 0)
texte = st.sidebar.text_input("Recherche dans l'objet", placeholder="réfection, avenue…")

mask = pd.Series(True, index=df.index)
if len(plage) == 2:
    mask &= (df['dateparution'] >= pd.Timestamp(plage[0])) & (df['dateparution'] <= pd.Timestamp(plage[1]))
if sel_depts: mask &= df['dept'].isin(sel_depts)
if score_min: mask &= df['score_perimetre'] >= score_min
if texte:     mask &= df['objet'].str.contains(texte, case=False, na=False)
dff = df[mask].copy()

# ── HEADER ────────────────────────────────────────────────────
st.title("🚲 VeloGuard")
st.markdown(
    "Surveillance de la **conformité L228-2** — Tout réaménagement de voirie urbaine "
    "doit intégrer des aménagements cyclables *(Code de l'environnement, LOM 2019)*"
)
src_date = df['dateparution'].max()
st.caption(f"Données BOAMP/DILA · {src_date.strftime('%d/%m/%Y') if pd.notna(src_date) else 'N/A'} · Licence ouverte v2.0")
st.markdown("""<div class='warning-banner'>
⚠️ <strong>Limite</strong> : seul le titre du marché et sa description structurée (champ <code>donnees</code>) sont analysés,
pas le CCTP complet. Une vérification manuelle sur
<a href="https://www.boamp.fr" target="_blank">boamp.fr</a> est recommandée avant toute action.
</div>""", unsafe_allow_html=True)
st.divider()

# ── KPIs ─────────────────────────────────────────────────────
n_tot  = len(dff)
n_p    = int(dff['dans_perimetre'].sum())
n_a    = int(dff['alerte_l228'].sum())
n_c    = int(dff['vrai_conforme'].sum())
n_velo = int((dff['cyclable_detecte'] & ~dff['faux_conforme']).sum())
tx     = n_c / n_p * 100 if n_p else 0

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Marchés analysés",    f"{n_tot:,}", help="Total marchés TRAVAUX collectés")
c2.metric("Périmètre L228-2",    f"{n_p:,}",  help="Score ≥ 2 : obligation probable")
c3.metric("⚠️ Alertes",          f"{n_a:,}",
          delta=f"{n_a/n_p*100:.0f}% du périmètre" if n_p else None,
          delta_color="inverse")
c4.metric("✅ Conformes",         f"{n_c:,}",
          delta=f"{tx:.1f}%",
          delta_color="normal")
c5.metric("🚲 Projets cyclables", f"{n_velo:,}",
          help="Tous marchés mentionnant du vélo (périmètre L228-2 + projets purs)")
st.divider()

# ── ONGLETS PRINCIPAUX ────────────────────────────────────────
tab_alertes, tab_communes, tab_carte, tab_methodo = st.tabs([
    f"⚠️ Alertes L228-2 ({n_a})",
    f"🚲 Communes actives vélo ({n_velo})",
    "🗺️ Carte & stats",
    "📐 Méthodologie",
])

# ── ONGLET 1 : ALERTES ────────────────────────────────────────
with tab_alertes:
    alertes_dff = dff[dff['alerte_l228']].copy()
    if alertes_dff.empty:
        st.markdown(f"**{n_a} marchés de voirie urbaine sans mention d'aménagement cyclable** — soumis à l'obligation L228-2")
        st.info("Aucune alerte avec les filtres actuels.")
    else:
        cols_map = {
            'dateparution':'Publication', 'datelimitereponse':'Date limite',
            'dept':'Dept', 'score_perimetre':'Score',
            'nomacheteur':'Acheteur', 'objet':'Objet',
            'procedure_libelle':'Procédure', 'descripteur_str':'Descripteurs',
            'url_avis':'BOAMP', 'url_pdf':'Extrait PDF'
        }
        cols_ok = [c for c in cols_map if c in alertes_dff.columns]
        disp = alertes_dff[cols_ok].copy()
        if 'dateparution' in disp.columns:
            disp['dateparution'] = disp['dateparution'].dt.strftime('%d/%m/%Y')
        if 'datelimitereponse' in disp.columns:
            disp['datelimitereponse'] = disp['datelimitereponse'].apply(
                lambda d: d.strftime('%d/%m/%Y %H:%M') if pd.notna(d) else ''
            )
        disp = disp.rename(columns=cols_map).sort_values('Score', ascending=False)

        # Pagination : 25 éléments par page
        ITEMS_PER_PAGE = 25
        total_items = len(disp)
        total_pages = max(1, math.ceil(total_items / ITEMS_PER_PAGE))

        if "alertes_page" not in st.session_state:
            st.session_state.alertes_page = 1

        if st.session_state.alertes_page > total_pages:
            st.session_state.alertes_page = total_pages

        col_title, col_info = st.columns([3, 2])
        with col_title:
            st.markdown(f"**{n_a} marchés de voirie urbaine sans mention d'aménagement cyclable** — soumis à l'obligation L228-2")
        with col_info:
            st.markdown(
                f"<div style='text-align: right; font-size: 13px; color: #4b5563; padding-top: 2px;'>"
                f"Affichage de <strong>{ITEMS_PER_PAGE}</strong> par page · Page <strong>{st.session_state.alertes_page}</strong> sur <strong>{total_pages}</strong> ({total_items} alertes au total)"
                f"</div>",
                unsafe_allow_html=True
            )

        start_idx = (st.session_state.alertes_page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        disp_page = disp.iloc[start_idx:end_idx]

        st.dataframe(
            disp_page, use_container_width=True, height=500,
            column_config={
                "BOAMP":      st.column_config.LinkColumn("BOAMP", display_text="🌐 Avis BOAMP"),
                "Extrait PDF":st.column_config.LinkColumn("Extrait PDF", display_text="📄 PDF Extrait"),
                "Objet":      st.column_config.TextColumn(width="large"),
                "Acheteur":   st.column_config.TextColumn(width="medium"),
                "Score":      st.column_config.NumberColumn(format="%d ⭐"),
            }
        )

        render_pagination(st.session_state.alertes_page, total_pages, key_prefix="alertes")

        csv_dl = alertes_dff.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button("⬇️ Télécharger les alertes (CSV)", data=csv_dl,
            file_name=f"veloguard_alertes_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")

# ── ONGLET 2 : COMMUNES ACTIVES ───────────────────────────────
with tab_communes:
    actifs_dff = dff[(dff['cyclable_detecte'] == True) & (~dff['faux_conforme'])].copy()

    if actifs_dff.empty:
        st.info("Aucun marché cyclable avec les filtres actuels.")
    else:
        # Séparer L228-2 conformes et projets purs
        l228_conf  = actifs_dff[actifs_dff['dans_perimetre']].copy()
        projets_pur = actifs_dff[~actifs_dff['dans_perimetre']].copy()

        col_l, col_r = st.columns(2)

        with col_l:
            st.subheader(f"✅ Voirie conforme L228-2 ({len(l228_conf)})")
            st.caption("Marchés de réfection voirie avec aménagement cyclable intégré")
            for _, r in l228_conf.sort_values('score_perimetre', ascending=False).iterrows():
                mots = str(r.get('cyclable_mots','')).replace(', ', ' · ')
                src  = r.get('source_cyclable', '')
                src_badge = f"<span style='font-size:10px;color:#666'>(détecté dans : {src})</span>" if src else ""
                url  = r.get('url_avis','')
                url_pdf = r.get('url_pdf','')
                links = []
                if url: links.append(f"<a href='{url}' target='_blank' style='font-size:11px;margin-right:10px;'>🌐 BOAMP</a>")
                if url_pdf: links.append(f"<a href='{url_pdf}' target='_blank' style='font-size:11px;'>📄 Extrait PDF</a>")
                links_html = " ".join(links)
                dt_lim = r.get('datelimitereponse')
                lim_badge = f" · Limite : {pd.to_datetime(dt_lim).strftime('%d/%m/%Y')}" if pd.notna(dt_lim) else ""
                st.markdown(f"""<div class='commune-card'>
                    <div style='font-weight:600;font-size:14px'>{r.get('nomacheteur','')} <span style='font-size:11px;font-weight:400;color:#666'>{lim_badge}</span></div>
                    <div style='font-size:12px;color:#2d6a4f'>{mots}</div>
                    <div style='font-size:11px;color:#555;margin-top:2px'>{str(r.get('objet',''))[:75]} {src_badge}</div>
                    <div style='margin-top:4px;'>{links_html}</div>
                </div>""", unsafe_allow_html=True)

        with col_r:
            st.subheader(f"🚲 Projets vélo purs ({len(projets_pur)})")
            st.caption("Marchés dédiés à l'infrastructure cyclable (hors obligation L228-2)")
            for _, r in projets_pur.sort_values('dateparution', ascending=False).iterrows():
                mots = str(r.get('cyclable_mots','')).replace(', ', ' · ')
                url  = r.get('url_avis','')
                url_pdf = r.get('url_pdf','')
                links = []
                if url: links.append(f"<a href='{url}' target='_blank' style='font-size:11px;margin-right:10px;'>🌐 BOAMP</a>")
                if url_pdf: links.append(f"<a href='{url_pdf}' target='_blank' style='font-size:11px;'>📄 Extrait PDF</a>")
                links_html = " ".join(links)
                dt_lim = r.get('datelimitereponse')
                lim_badge = f" · Limite : {pd.to_datetime(dt_lim).strftime('%d/%m/%Y')}" if pd.notna(dt_lim) else ""
                st.markdown(f"""<div class='projet-pur'>
                    <div style='font-weight:600;font-size:14px'>{r.get('nomacheteur','')} <span style='font-size:11px;font-weight:400;color:#666'>{lim_badge}</span></div>
                    <div style='font-size:12px;color:#2b6cb0'>{mots}</div>
                    <div style='font-size:11px;color:#555;margin-top:2px'>{str(r.get('objet',''))[:75]}</div>
                    <div style='margin-top:4px;'>{links_html}</div>
                </div>""", unsafe_allow_html=True)

        # Carte des communes actives
        st.divider()
        st.subheader("🗺️ Répartition géographique des communes actives")
        dept_actif = actifs_dff.groupby('dept').size().reset_index(name='n_projets')
        if geo:
            fig_actif = px.choropleth(
                dept_actif, geojson=geo, locations='dept',
                featureidkey='properties.code', color='n_projets',
                color_continuous_scale=["#ebf8ff","#90cdf4","#3182ce","#1a365d"],
                labels={'n_projets':'Projets cyclables'},
                title="Départements avec des marchés cyclables publiés"
            )
            fig_actif.update_geos(fitbounds="locations", visible=False)
            fig_actif.update_layout(margin=dict(r=0,t=30,l=0,b=0), height=380,
                coloraxis_colorbar=dict(title="Projets",thickness=12,len=0.5))
            st.plotly_chart(fig_actif, use_container_width=True)

        # Top mots cyclables
        cpt = Counter()
        for mots in actifs_dff['cyclable_mots'].dropna():
            for m in str(mots).split(', '):
                if m.strip(): cpt[m.strip()] += 1
        if cpt:
            st.subheader("🏷️ Infrastructures cyclables mentionnées")
            df_mots = pd.DataFrame(cpt.most_common(15), columns=['Infrastructure','Nb marchés'])
            fig_mots = px.bar(df_mots, x='Nb marchés', y='Infrastructure', orientation='h',
                color='Nb marchés', color_continuous_scale='Blues',
                labels={'Infrastructure':'','Nb marchés':'Nb marchés'})
            fig_mots.update_layout(height=320, margin=dict(t=5), showlegend=False,
                coloraxis_showscale=False, yaxis=dict(autorange='reversed'))
            st.plotly_chart(fig_mots, use_container_width=True)

# ── ONGLET 3 : CARTE & STATS ──────────────────────────────────
with tab_carte:
    dept_stats = (dff[dff['dans_perimetre']].groupby('dept')
        .agg(total=('idweb','count'), alertes=('alerte_l228','sum'),
             conformes=('vrai_conforme','sum'))
        .reset_index())
    dept_stats['taux'] = (dept_stats['alertes'] / dept_stats['total'] * 100).round(1)

    col_map, col_bar = st.columns([1.5, 1])
    with col_map:
        st.subheader("Non conformité par département")
        if geo:
            fig = px.choropleth(dept_stats, geojson=geo, locations='dept',
                featureidkey='properties.code', color='alertes',
                color_continuous_scale=["#fff7ed","#fed7aa","#fb923c","#ea580c","#7c2d12"],
                hover_data={'dept':True,'alertes':True,'total':True,'taux':True},
                labels={'alertes':'Non conformités','total':'Total périmètre','taux':'% non conforme'})
            fig.update_geos(fitbounds="locations", visible=False)
            fig.update_layout(margin=dict(r=0,t=10,l=0,b=0), height=400,
                coloraxis_colorbar=dict(title="Non conformités",thickness=12,len=0.5))
            st.plotly_chart(fig, use_container_width=True)
    with col_bar:
        st.subheader("Top 15 départements")
        top = dept_stats.sort_values('alertes', ascending=False).head(15)
        fig_b = px.bar(top, x='alertes', y='dept', orientation='h',
            color='taux', color_continuous_scale=["#fed7aa","#ea580c","#7c2d12"],
            text='alertes', labels={'alertes':'Non conformités','dept':'Dept','taux':'% non conforme'})
        fig_b.update_traces(textposition='outside')
        fig_b.update_layout(height=400, margin=dict(t=10,b=10),
            yaxis=dict(autorange='reversed'),
            coloraxis_colorbar=dict(title="% non conforme",thickness=10))
        st.plotly_chart(fig_b, use_container_width=True)

    col_t, col_s = st.columns(2)
    with col_t:
        st.subheader("Publications par semaine")
        df_tw = dff[dff['dans_perimetre']].copy()
        df_tw['sem'] = df_tw['dateparution'].dt.to_period('W').astype(str)
        df_tw['statut'] = df_tw['vrai_conforme'].map({True:'✅ Conforme', False:'⚠️ Alerte'})
        tw = df_tw.groupby(['sem','statut']).size().reset_index(name='n')
        fig_t = px.bar(tw, x='sem', y='n', color='statut',
            color_discrete_map={'⚠️ Alerte':'#fb923c','✅ Conforme':'#34d399'},
            barmode='stack', labels={'n':'Marchés','sem':'Semaine','statut':''})
        fig_t.update_layout(height=280, margin=dict(t=5,b=40),
            legend=dict(orientation='h',y=-0.35))
        st.plotly_chart(fig_t, use_container_width=True)

    with col_s:
        st.subheader("Distribution des scores")
        sc = dff['score_perimetre'].value_counts().sort_index().reset_index()
        sc.columns = ['score','n']
        sc['perim'] = sc['score'].apply(lambda x: 'Dans périmètre' if x >= 2 else 'Hors périmètre')
        fig_s = px.bar(sc, x='score', y='n', text='n', color='perim',
            color_discrete_map={'Dans périmètre':'#fb923c','Hors périmètre':'#e2e8f0'},
            labels={'score':'Score L228-2','n':'Nb marchés','perim':''})
        fig_s.update_traces(textposition='outside')
        fig_s.update_layout(height=280, margin=dict(t=5), legend=dict(orientation='h',y=1.15))
        st.plotly_chart(fig_s, use_container_width=True)

# ── ONGLET 4 : MÉTHODOLOGIE ───────────────────────────────────
with tab_methodo:
    st.markdown("""
### 🧠 Fonctionnement de l'algorithme VeloGuard

L'application VeloGuard repose sur un algorithme de traitement automatisé des annonces du **BOAMP (Bulletin Officiel des Annonces des Marchés Publics)** pour identifier les manquements potentiels à l'**article L228-2 du Code de l'environnement** (issu de la loi LOM).

L'analyse s'effectue en **3 étapes clés** :

---

### 1️⃣ Étape 1 : Calcul du score de périmètre L228-2 (0 à 5)

L'article L228-2 impose la réalisation d'itinéraires cyclables lors de toute **réfection ou création de voie urbaine**. 
L'algorithme évalue l'objet du marché et ses descripteurs CPV/BOAMP pour déterminer si le marché entre dans ce périmètre d'obligation.

| Critère d'évaluation | Variation de score | Explications / Motifs |
|---|:---:|---|
| **Descripteur majeur "Voirie"** | **+2 pts** | Indique un marché centré sur la voirie (marché mono-lot ou bi-lot). |
| **Descripteur "Voirie" en accord-cadre** | **+1 pt** | Descripteur présent dans un accord-cadre multi-lots (5 à 8 lots). |
| **Descripteur "Voirie" noyé dans un TCE** | **0 pt** | Marché Tous Corps d'État (> 8 lots) où la voirie n'est qu'accessoire. |
| **Descripteurs secondaires** | **+1 pt** | Présence de mots-clés comme *"Chaussée"*, *"Trottoir"*, *"Revêtement"* (≤ 4 lots). |
| **Mots-clés de réfection/réaménagement** | **+1 pt** | Intitulé ciblant une réfection/aménagement (*réfection*, *réhabilitation*, *enrobé*, *giratoire*...). |
| **Exclusions bâtiment & réseaux** | **−3 pts** | Bâtiment, FTTH, eau/gaz, assainissement, cimetière, aéroport, désamiantage, etc. |
| **Exclusions hors agglomération / infrastructures** | **−3 pts** | Autoroutes, voies rapides, 2x2 voies, échangeurs, ponts/viaducs sur RN/RD hors agglomération. |
| **Construction neuve non routière** | **−1 pt** | Logements ou bâtiments neufs. |

> 🎯 **Décision de périmètre** :
> - **Score ≥ 2** ➔ **Marché DANS le périmètre L228-2** (Obligation légale très probable).
> - **Score < 2** ➔ **Marché HORS périmètre L228-2** (Travaux secondaires, bâtiment ou hors agglomération).

---

### 2️⃣ Étape 2 : Détection des aménagements cyclables & Faux positifs

L'algorithme parcourt le titre du marché (`objet`) et sa description synthétique (`donnees`) à la recherche d'éléments attestant de la prise en compte du vélo.

* **Recherche de mots-clés cyclables** : *piste cyclable, bande cyclable, voie verte, véloroute, aménagement cyclable, itinéraire cyclable, stationnement vélo, arceaux vélo, abri vélo, mode doux, cheminement doux, L228-2...*
* **Filtrage des faux conformes** :
  Certains marchés mentionnent du vélo mais ne répondent pas à l'obligation de voie cyclable sur la chaussée. Ils sont neutralisés si l'objet concerne :
  - Les cours d'écoles, collèges ou lycées (ex: *abri vélo dans la cour du collège*)
  - Les rénovations énergétiques, centres aquatiques, ombrières photovoltaïques
  - Les foyers ou résidences étudiantes

---

### 3️⃣ Étape 3 : Dispatching et classification des marchés

En croisant le **score de périmètre** (seuil à 2) et la **détection d'une mention cyclable** (hors faux conformes), l'algorithme catégorise automatiquement chaque marché public :

| Score Périmètre | Mention Cyclable Valide | Catégorie attribuée | Statut & Signification |
|:---:|:---:|:---:|---|
| **≥ 2** *(Périmètre L228-2)* | ❌ **Non** | ⚠️ **Alerte L228-2** | **Non conforme suspecté** — Réaménagement de voirie sans volet cyclable identifié. |
| **≥ 2** *(Périmètre L228-2)* | ✅ **Oui** | ✅ **Conforme L228-2** | **Conforme** — Réaménagement de voirie intégrant un aménagement cyclable. |
| **< 2** *(Hors périmètre)* | ✅ **Oui** | 🚲 **Projet vélo pur** | **Projet spécifique** — Aménagement cyclable dédié hors réfection de chaussée classique. |
| **< 2** *(Hors périmètre)* | ❌ **Non** | *(Hors périmètre)* | **Exclu** — Travaux non soumis à l'obligation L228-2 (bâtiment, réseaux, etc.). |

#### 📋 Détail des catégories :

1. ⚠️ **Alerte L228-2 (Non conforme suspecté)**
   - **Conditions** : `Score périmètre ≥ 2` **ET** `Aucune mention cyclable valide`.
   - **Interpretation** : Travaux de voirie urbaine identifiés sans aucune trace d'aménagement cyclable au BOAMP. Ces marchés nécessitent une vigilance et un contrôle prioritaire par les associations.

2. ✅ **Conforme L228-2**
   - **Conditions** : `Score périmètre ≥ 2` **ET** `Mention cyclable valide détectée`.
   - **Interpretation** : Requalification de voirie respectant l'article L228-2 en prévoyant explicitement un volet cyclable.

3. 🚲 **Projet vélo pur**
   - **Conditions** : `Score périmètre < 2` **ET** `Mention cyclable valide détectée`.
   - **Interpretation** : Marché dédié spécifiquement au vélo ou à des équipements mobilités (ex: création d'une voie verte autonome, fourniture d'arceaux vélo, location de vélos...).

---

### ⚠️ Limites méthodologiques

* **Portée de la recherche** : Seul le texte récapitulatif fourni par l'API BOAMP (titre et résumé `donnees`) est analysé. Les documents détaillés du CCTP (Cahier des Clauses Techniques Particulières) ne sont pas accessibles automatiquement.
* **Vérification recommandée** : Une mention cyclable peut être absente du titre tout en étant présente dans le CCTP, et inversement. Il est vivement conseillé de cliquer sur le lien BOAMP pour vérifier l'avis d'appel d'offres officiel avant toute démarche auprès de l'acheteur public.

---

### 📊 Source & Fréquence des données

* **Source** : API BOAMP / DILA — [boamp-datadila.opendatasoft.com](https://boamp-datadila.opendatasoft.com)
* **Licence** : Licence Ouverte v2.0 (Etalab)
* **Mise à jour** : Traitement et actualisation automatisés 2 fois par jour.
    """)

# ── FOOTER ────────────────────────────────────────────────────
st.divider()
st.markdown("<div style='text-align:center;color:#94a3b8;font-size:12px'>"
    "VeloGuard · BOAMP/DILA (Licence ouverte v2.0) · Art. L228-2 Code de l'environnement · LOM 2019"
    "</div>", unsafe_allow_html=True)
