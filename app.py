import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re, ast, requests, json
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
    df['dateparution'] = pd.to_datetime(df['dateparution'], errors='coerce')
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
    st.markdown(f"**{n_a} marchés de voirie urbaine sans mention d'aménagement cyclable** — soumis à l'obligation L228-2")

    alertes_dff = dff[dff['alerte_l228']].copy()
    if alertes_dff.empty:
        st.info("Aucune alerte avec les filtres actuels.")
    else:
        cols_map = {
            'dateparution':'Date','dept':'Dept','score_perimetre':'Score',
            'nomacheteur':'Acheteur','objet':'Objet',
            'descripteur_str':'Descripteurs','url_avis':'BOAMP'
        }
        cols_ok = [c for c in cols_map if c in alertes_dff.columns]
        disp = alertes_dff[cols_ok].copy()
        disp['dateparution'] = disp['dateparution'].dt.strftime('%d/%m/%Y')
        disp = disp.rename(columns=cols_map).sort_values('Score', ascending=False)
        st.dataframe(
            disp, use_container_width=True, height=500,
            column_config={
                "BOAMP":   st.column_config.LinkColumn("BOAMP"),
                "Objet":   st.column_config.TextColumn(width="large"),
                "Acheteur":st.column_config.TextColumn(width="medium"),
                "Score":   st.column_config.NumberColumn(format="%d ⭐"),
            }
        )
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
                link = f"<a href='{url}' target='_blank' style='font-size:11px'>→ BOAMP</a>" if url else ""
                st.markdown(f"""<div class='commune-card'>
                    <div style='font-weight:600;font-size:14px'>{r.get('nomacheteur','')}</div>
                    <div style='font-size:12px;color:#2d6a4f'>{mots}</div>
                    <div style='font-size:11px;color:#555;margin-top:2px'>{str(r.get('objet',''))[:75]} {src_badge}</div>
                    <div>{link}</div>
                </div>""", unsafe_allow_html=True)

        with col_r:
            st.subheader(f"🚲 Projets vélo purs ({len(projets_pur)})")
            st.caption("Marchés dédiés à l'infrastructure cyclable (hors obligation L228-2)")
            for _, r in projets_pur.sort_values('dateparution', ascending=False).iterrows():
                mots = str(r.get('cyclable_mots','')).replace(', ', ' · ')
                url  = r.get('url_avis','')
                link = f"<a href='{url}' target='_blank' style='font-size:11px'>→ BOAMP</a>" if url else ""
                st.markdown(f"""<div class='projet-pur'>
                    <div style='font-weight:600;font-size:14px'>{r.get('nomacheteur','')}</div>
                    <div style='font-size:12px;color:#2b6cb0'>{mots}</div>
                    <div style='font-size:11px;color:#555;margin-top:2px'>{str(r.get('objet',''))[:75]}</div>
                    <div>{link}</div>
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
        st.subheader("Alertes L228-2 par département")
        if geo:
            fig = px.choropleth(dept_stats, geojson=geo, locations='dept',
                featureidkey='properties.code', color='alertes',
                color_continuous_scale=["#fff7ed","#fed7aa","#fb923c","#ea580c","#7c2d12"],
                hover_data={'dept':True,'alertes':True,'total':True,'taux':True},
                labels={'alertes':'Alertes','total':'Total périmètre','taux':'% alerte'})
            fig.update_geos(fitbounds="locations", visible=False)
            fig.update_layout(margin=dict(r=0,t=10,l=0,b=0), height=400,
                coloraxis_colorbar=dict(title="Alertes",thickness=12,len=0.5))
            st.plotly_chart(fig, use_container_width=True)
    with col_bar:
        st.subheader("Top 15 départements")
        top = dept_stats.sort_values('alertes', ascending=False).head(15)
        fig_b = px.bar(top, x='alertes', y='dept', orientation='h',
            color='taux', color_continuous_scale=["#fed7aa","#ea580c","#7c2d12"],
            text='alertes', labels={'alertes':'Alertes','dept':'Dept','taux':'% alerte'})
        fig_b.update_traces(textposition='outside')
        fig_b.update_layout(height=400, margin=dict(t=10,b=10),
            yaxis=dict(autorange='reversed'),
            coloraxis_colorbar=dict(title="% alerte",thickness=10))
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
### Score de périmètre L228-2 (0 à 5)

| Condition | Points |
|---|---|
| Descripteur "Voirie" ou "Voirie et réseaux divers" (marché mono ou bi-lot) | **+2** |
| Même descripteur dans un accord-cadre 5–8 lots | **+1** |
| Voirie noyée dans accord-cadre TCE (> 8 lots) | **0** |
| Descripteur "Chaussée", "Trottoir", "Revêtement" (≤ 4 lots) | **+1** |
| Objet : réfection/réaménagement + voirie/rue/avenue/chaussée | **+1** |
| Objet : bâtiment, FTTH, toiture, hôpital, pharmacie, cimetière, aéroport… | **−3** |
| Objet : autoroute, voie rapide, 2×2 voies, pont/viaduc sur RN/RD, échangeur | **−3** |
| Objet : construction neuve + bâtiment/logements | **−1** |

**Seuil : score ≥ 2 = dans le périmètre L228-2**

> Les routes départementales et nationales **en agglomération** restent dans le périmètre
> (la loi exclut autoroutes et voies rapides, pas les RD/RN en zone urbaine).

---

### Détection d'aménagement cyclable

L'analyse porte sur le **titre** (`objet`) et la **description structurée** (`donnees`) de l'annonce.
Le texte intégral du CCTP n'est pas disponible via l'API.

Mots recherchés : *piste cyclable, bande cyclable, voie verte, véloroute, vélo, cycliste,
aménagement cyclable, arceaux vélo, abri vélo, mode doux, L228-2…*

---

### Classification des résultats

| Catégorie | Définition |
|---|---|
| ⚠️ **Alerte L228-2** | Score ≥ 2 ET aucune mention cyclable → à vérifier |
| ✅ **Conforme L228-2** | Score ≥ 2 ET mention cyclable pertinente |
| 🚲 **Projet vélo pur** | Mention cyclable mais hors périmètre L228-2 (projet dédié) |

---

### Source des données

API BOAMP / DILA — [boamp-datadila.opendatasoft.com](https://boamp-datadila.opendatasoft.com)
Licence ouverte v2.0 (Etalab) · Mise à jour 2×/jour
    """)

# ── FOOTER ────────────────────────────────────────────────────
st.divider()
st.markdown("<div style='text-align:center;color:#94a3b8;font-size:12px'>"
    "VeloGuard · BOAMP/DILA (Licence ouverte v2.0) · Art. L228-2 Code de l'environnement · LOM 2019"
    "</div>", unsafe_allow_html=True)
