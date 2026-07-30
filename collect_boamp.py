import requests, pandas as pd, json, time, re, ast, argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

BASE_URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"

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
    r'\b(barrage|berge|digue)\b',
    r'\b(ascenseur|escalier)\b',
    r'\bd[eé]samiantage\b',
    r'\b(pharmacie|h[oô]pital|chru?|ehpad)\b',
    r'\bstade\b', r'\btribune\b',
    r'\bcimeti[eè]re\b', r'\ba[eé]roport\b',
]

HORS_PERIMETRE_INFRA = [
    r'\bRN\s*\d+\b', r'\bautoroute\b',
    r'\bRD\s*\d+.{0,40}(hors agglo|route d[eé]partementale.{0,20}(entre|pr\s*\d|section))',
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
        if isinstance(lst, list):
            return [str(x).lower().strip() for x in lst]
    except:
        pass
    return [s.strip().lower() for s in str(val).split(',')]

def score_perimetre_l228(row):
    descs  = parse_descripteurs(row.get('descripteur_libelle', row.get('descripteur_str', '')))
    objet  = str(row.get('objet', '')).lower()
    nb_desc = len(descs)
    score  = 0

    has_voirie_fort = any(any(v in d for v in DESC_VOIRIE_FORT) for d in descs)
    if has_voirie_fort:
        if nb_desc > 8:
            score += 0
        elif nb_desc > 5:
            score += 1
        else:
            score += 2
    elif any(any(v in d for v in DESC_VOIRIE_FAIBLE) for d in descs):
        if nb_desc <= 4:
            score += 1

    for p in MOTS_REFECTION:
        if re.search(p, objet, re.IGNORECASE):
            score += 1
            break

    for p in EXCLUSIONS_FORTES:
        if re.search(p, objet, re.IGNORECASE):
            score -= 3
            break

    for p in HORS_PERIMETRE_INFRA:
        if re.search(p, objet, re.IGNORECASE):
            score -= 2
            break

    if re.search(r'\bconstruction\b.{0,30}\b(neuve|b[aâ]timent|logements|maisons?)\b', objet, re.IGNORECASE):
        score -= 1

    return score

def detecter_cyclable(texte):
    t = str(texte).lower()
    mots = []
    for p in KEYWORDS_CYCLABLE:
        m = re.findall(p, t, re.IGNORECASE)
        if m:
            mots.extend([str(x).lower() for x in m])
    return bool(mots), list(set(mots))

def detecter_faux_conforme(texte):
    t = str(texte).lower()
    for p in FAUX_CONF_PATTERNS:
        if re.search(p, t, re.IGNORECASE):
            return True
    return False

def extraire_textes_donnees(donnees_raw):
    if not donnees_raw:
        return ''
    try:
        d = json.loads(donnees_raw) if isinstance(donnees_raw, str) else donnees_raw
    except Exception:
        return str(donnees_raw)[:2000]

    textes = []
    def parcourir(obj, profondeur=0):
        if profondeur > 10:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.lower() in ('description', 'intitule', 'objet', 'complementinfos',
                                  'capacitetech', 'conditions', 'renseignements',
                                  'informcomplementaire'):
                    if isinstance(v, str) and len(v) > 20:
                        textes.append(v)
                elif isinstance(v, (dict, list)):
                    parcourir(v, profondeur + 1)
                elif isinstance(v, str) and len(v) > 50:
                    textes.append(v)
        elif isinstance(obj, list):
            for item in obj:
                parcourir(item, profondeur + 1)

    parcourir(d)
    return ' '.join(textes)

def fetch_period(date_start_str, date_end_str):
    where = f'dateparution >= "{date_start_str}" AND dateparution <= "{date_end_str}" AND type_marche:"TRAVAUX"'
    q = '"voirie" OR "chaussee" OR "trottoir" OR "revetement" OR "refection" OR "reamenagement"'
    records, offset = [], 0
    limit = 100
    while True:
        params = {
            'where': where, 'order_by': 'dateparution DESC',
            'limit': limit, 'offset': offset,
            'lang': 'fr', 'timezone': 'Europe/Paris',
            'q': q
        }
        try:
            r = requests.get(BASE_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"Erreur requête ({date_start_str} - {date_end_str}): {e}")
            break

        rec = data.get('results', [])
        total = data.get('total_count', 0)
        if not rec:
            break
        records.extend(rec)
        if len(records) >= total or offset + limit >= 10000:
            break
        offset += limit
        time.sleep(0.2)
    return records

def build_pdf_url(row):
    idweb = str(row.get('idweb', '')).strip()
    if not idweb or idweb == 'nan':
        return ''
    dateparution = pd.to_datetime(row.get('dateparution'), errors='coerce')
    if pd.isna(dateparution):
        return f"https://www.boamp.fr/pages/avis/pdf-detail/?idweb={idweb}"
    year = dateparution.strftime('%Y')
    month = dateparution.strftime('%m')
    schema = str(row.get('source_schema', ''))
    filename = str(row.get('filename', ''))
    if schema.startswith('3'):
        return f"https://www.boamp.fr/telechargements/FILES/PDF/{year}/{month}/{idweb}.pdf"
    elif filename and filename != 'nan':
        return f"https://www.boamp.fr/telechargements/PDF/{year}/{filename}/{idweb}.pdf"
    return f"https://www.boamp.fr/pages/avis/pdf-detail/?idweb={idweb}"

def collect_data(jours=365):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=jours)
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f"boamp_voirie_{datetime.now().strftime('%Y%m%d')}.csv"
    print(f"Collecte BOAMP sur {jours} jours ({start_date.strftime('%Y-%m-%d')} -> {end_date.strftime('%Y-%m-%d')})...")

    # Découpage par mois pour contourner les limites d'offset de l'API Opendatasoft (10 000 max)
    all_records = []
    curr_start = start_date
    while curr_start < end_date:
        curr_end = min(curr_start + timedelta(days=15), end_date)
        d_start = curr_start.strftime('%Y-%m-%d')
        d_end = curr_end.strftime('%Y-%m-%d')
        print(f" -> Fetch {d_start} à {d_end}...", end="")
        recs = fetch_period(d_start, d_end)
        print(f" {len(recs)} avis reçus.")
        all_records.extend(recs)
        curr_start = curr_end + timedelta(days=1)

    print(f"Total annonces brutes collectées: {len(all_records)}")
    if not all_records:
        print("Aucune donnée récupérée.")
        return

    df = pd.DataFrame(all_records)
    # Suppression des doublons par idweb si présent
    if 'idweb' in df.columns:
        df = df.drop_duplicates(subset=['idweb']).copy()

    # Nettoyage
    df['dateparution'] = pd.to_datetime(df['dateparution'], errors='coerce', utc=True).dt.tz_localize(None)
    if 'datelimitereponse' in df.columns:
        df['datelimitereponse'] = pd.to_datetime(df['datelimitereponse'], errors='coerce', utc=True).dt.tz_localize(None)

    def parse_dept(v):
        try:
            lst = ast.literal_eval(str(v))
            return str(lst[0]).zfill(2) if lst else '00'
        except:
            return str(v).zfill(2)[:2]

    df['dept'] = df.get('code_departement', pd.Series(['00']*len(df))).apply(parse_dept)
    if 'descripteur_libelle' in df.columns:
        df['descripteur_str'] = df['descripteur_libelle'].apply(lambda v: ', '.join(parse_descripteurs(v)))

    for col in ['objet', 'nomacheteur']:
        if col in df.columns:
            df[col] = df[col].fillna('').astype(str).str.strip()

    print("Extraction des descriptions complètes...")
    if 'donnees' in df.columns:
        df['description_donnees'] = df['donnees'].apply(extraire_textes_donnees)
    else:
        df['description_donnees'] = ''

    df['texte_complet'] = (
        df.get('objet', pd.Series(['']*len(df))).fillna('') + ' ' +
        df.get('descripteur_str', pd.Series(['']*len(df))).fillna('') + ' ' +
        df['description_donnees'].fillna('')
    )

    df['score_perimetre'] = df.apply(score_perimetre_l228, axis=1)
    df['dans_perimetre']  = df['score_perimetre'] >= 2

    results = df['texte_complet'].apply(detecter_cyclable)
    df['cyclable_detecte'] = results.apply(lambda x: x[0])
    df['cyclable_mots']    = results.apply(lambda x: ', '.join(x[1]) if x[1] else '')
    df['faux_conforme']    = df['texte_complet'].apply(detecter_faux_conforme)
    df['vrai_conforme']    = df['dans_perimetre'] & df['cyclable_detecte'] & ~df['faux_conforme']
    df['alerte_l228']      = df['dans_perimetre'] & ~df['cyclable_detecte']

    # URL d'avis BOAMP et PDF extrait
    if 'idweb' in df.columns:
        df['url_avis'] = 'https://www.boamp.fr/pages/avis/?q=idweb:' + df['idweb'].astype(str)
        df['url_pdf'] = df.apply(build_pdf_url, axis=1)

    cols_export = [
        'idweb', 'dateparution', 'datelimitereponse', 'dept', 'code_departement', 'nomacheteur', 'objet',
        'descripteur_str', 'famille_libelle', 'procedure_libelle', 'nature_libelle',
        'filename', 'source_schema',
        'score_perimetre', 'dans_perimetre', 'cyclable_detecte', 'cyclable_mots',
        'source_cyclable', 'alerte_l228', 'vrai_conforme', 'faux_conforme', 'url_avis', 'url_pdf'
    ]
    cols_existantes = [c for c in cols_export if c in df.columns]
    df_export = df[cols_existantes]

    output_path = Path(output_file)
    df_export.to_csv(output_path, index=False, lineterminator='\n')
    print(f"Fichier sauvegardé avec succès : {output_file} ({len(df_export)} lignes)")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Collecte des données BOAMP pour l'observatoire L228-2.")
    parser.add_argument(
        '--jours', '-j',
        type=int,
        default=365,
        help="Nombre de jours de recul pour la collecte (ex: 30 pour 30 jours, 365 par défaut)."
    )
    args = parser.parse_args()
    collect_data(jours=args.jours)
