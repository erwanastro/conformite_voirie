# 🚲 VeloGuard

**Surveillance automatique de la conformité des marchés publics de voirie à l'obligation d'aménagement cyclable**

> *Article L228-2 du Code de l'environnement (issu de la Loi d'Orientation des Mobilités, 2019) :*
> *"À l'occasion des réalisations ou des rénovations des voies urbaines, à l'exception des autoroutes et voies rapides, doivent être mis au point des itinéraires cyclables."*

---

## Contexte

La LOM de 2019 impose d'intégrer des aménagements cyclables dans tout projet de réfection ou de réaménagement de voirie urbaine. Cette obligation est souvent méconnue ou ignorée dans les appels d'offres publics.

VeloGuard collecte automatiquement les marchés publics de travaux publiés au BOAMP, identifie ceux qui relèvent du périmètre L228-2, et signale ceux qui ne mentionnent aucun aménagement cyclable. Il met également en valeur les collectivités qui intègrent le vélo dans leurs projets de voirie.

---

## Structure du projet

```
veloguard/
├── app.py                                    # Dashboard Streamlit
├── collect_boamp.py                          # Script de collecte des données BOAMP
├── requirements.txt                          # Dépendances Python
├── README.md
└── data/
    └── boamp_voirie_YYYYMMDD.csv             # Fichiers de données collectés
```

---

## Installation et démarrage rapide

### 1. Cloner le projet & créer l'environnement virtuel

```bash
git clone <URL_DU_REPO>
cd conformite_voirie

# Création de l'environnement virtuel
python3 -m venv .venv

# Activation de l'environnement virtuel
# Sur Linux / macOS :
source .venv/bin/activate
# Sur Windows (PowerShell) :
# .venv\Scripts\Activate.ps1
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Collecter les données (Scraper le BOAMP)

Exécutez le script `collect_boamp.py` en spécifiant le nombre de jours à remonter :

```bash
# Collecte des 30 derniers jours (recommandé pour un test rapide)
python collect_boamp.py --jours 30

# Collecte sur 1 an (365 jours par défaut)
python collect_boamp.py

# Afficher l'aide
python collect_boamp.py --help
```

Le script crée automatiquement le dossier `data/` si nécessaire et y génère un fichier CSV daté du jour (ex: `data/boamp_voirie_20260730.csv`).

### 4. Lancer l'application Streamlit

```bash
streamlit run app.py
```

L'application s'ouvre automatiquement dans votre navigateur à l'adresse `http://localhost:8501`.

---

## Déploiement sur Streamlit Cloud

1. Pousser ce repo sur GitHub avec `app.py`, `collect_boamp.py`, `requirements.txt` et un CSV généré à la racine.
2. Se connecter sur [share.streamlit.io](https://share.streamlit.io)
3. **New app** → Sélectionner le repo → Fichier principal : `app.py` → **Deploy**

---

## Collecte des données

### Source

**API BOAMP / DILA** — [boamp-datadila.opendatasoft.com](https://boamp-datadila.opendatasoft.com)  
Gratuite, sans clé, Licence ouverte v2.0 (Etalab).

### Options du script `collect_boamp.py`

- `--jours` / `-j` : Nombre de jours de recul pour la collecte (ex: `--jours 30` pour 30 jours, `365` par défaut).

> **Pourquoi remonter au moins 30-45 jours ?** Les numéros d'idweb BOAMP sont séquentiels. Remonter suffisamment dans le temps garantit de ne pas louper de marchés récents publiés avec un décalage d'indexation.

### Ce qui est collecté

Tous les marchés de type **TRAVAUX** dont l'objet ou les descripteurs contiennent des
mots-clés voirie (`voirie`, `chaussée`, `trottoir`, `réfection`, `réaménagement`...).

### Champ `donnees` — description complète

Depuis la v7, le champ `donnees` est récupéré lors de la collecte. Il contient le JSON
structuré complet de l'avis, dont la description complète du marché sous :

```
donnees > FNSimple > initial > natureMarche > description
```

Cela permet de détecter les aménagements cyclables mentionnés dans la description
mais absents du titre — cas fréquent en pratique.

**Exemple concret** : le marché 26-32199 a pour titre
*"Travaux d'aménagement de voirie phase 4"* (aucun mot cyclable),
mais sa description précise *"reprise des structures de chaussées, des quais de bus,
de trottoirs, de piste cyclable, d'îlots..."* — détectable uniquement via `donnees`.

---

## Logique d'analyse

### Étape 1 — Score de périmètre L228-2

Chaque marché reçoit un score de **−3 à +5** évaluant la probabilité qu'il soit soumis à l'obligation.

| Condition | Points |
|---|---|
| Descripteur "Voirie" ou "Voirie et réseaux divers" (marché mono ou bi-lot) | **+2** |
| Même descripteur dans un accord-cadre 5–8 lots | **+1** |
| Voirie noyée dans un accord-cadre TCE (> 8 lots) | **0** |
| Descripteur "Chaussée", "Trottoir" ou "Revêtement" (≤ 4 lots) | **+1** |
| Objet : réfection/réaménagement + voirie/rue/avenue/chaussée | **+1** |
| Objet : bâtiment, FTTH, toiture, hôpital, pharmacie, cimetière, aéroport... | **−3** |
| Objet : autoroute, voie rapide, 2×2 voies, pont/viaduc sur RN/RD, échangeur | **−3** |
| Objet : construction neuve + bâtiment/logements | **−1** |

**Seuil retenu : score ≥ 2 = dans le périmètre L228-2**

> **Note sur les RD/RN** : la loi exclut uniquement les autoroutes et voies rapides.
> Une route départementale ou nationale traversant une agglomération est une voie urbaine —
> L228-2 s'applique. Seuls les ouvrages d'art (ponts, viaducs), échangeurs et
> contournements hors agglomération sont exclus.

### Étape 2 — Détection d'aménagement cyclable

L'objet, les descripteurs et la description structurée (`donnees`) sont analysés.

Mots recherchés : *piste cyclable, bande cyclable, voie verte, véloroute, couloir vélo,
aménagement cyclable, continuité cyclable, vélo, cycliste, arceaux vélo, abri vélo,
mode doux, cheminement doux, L228-2...*

La source de la détection est tracée dans la colonne `source_cyclable` :
- `titre` — détecté dans le titre du marché
- `description` — détecté dans la description complète (`donnees`)

### Étape 3 — Filtrage des faux conformes

Certains marchés mentionnent le vélo dans un contexte hors voirie
(cour d'école, bâtiment, centre aquatique, centrale photovoltaïque...).
Ces cas sont identifiés et exclus des "conformes L228-2".

### Classification finale

| Catégorie | Définition |
|---|---|
| ⚠️ **Alerte L228-2** | Score ≥ 2 ET aucune mention cyclable pertinente → à vérifier |
| ✅ **Conforme L228-2** | Score ≥ 2 ET mention cyclable dans le titre ou la description |
| 🚲 **Projet vélo pur** | Mention cyclable mais hors périmètre L228-2 (projet dédié vélo) |

### Taux de conformité observé

Sur les données de référence (avril 2026, 272 marchés dans le périmètre) :
- **~6% de conformité** (16 marchés avec mention cyclable)
- **~94% de non-conformité** (255 marchés sans mention cyclable)

Ce taux est cohérent avec les observations de terrain sur l'application de la LOM.

---

## Fonctionnalités du dashboard

- **⚠️ Alertes L228-2** : tableau filtrable des marchés à risque, date limite de réponse, liens directs vers la fiche BOAMP et vers l'**extrait PDF officiel** de l'appel d'offres, export CSV.
- **🚲 Communes actives vélo** : collectivités qui intègrent le cyclable (conformes L228-2 + projets purs), date limite, extrait PDF & liens BOAMP, carte géo, types d'infrastructures mentionnées.
- **🗺️ Carte & stats** : choroplèthe par département, timeline, distribution des scores.
- **📐 Méthodologie** : explication complète du scoring.

Filtres disponibles : département, période, périmètre L228-2 (dans/hors périmètre), recherche textuelle.

---

## Limites connues

- La description complète du CCTP n'est pas accessible via l'API — seuls le titre et le champ `donnees` (description structurée) sont analysés. Des marchés conformes peuvent rester classés en alerte si la mention cyclable n'est que dans le CCTP.
- Le scoring est heuristique. Des cas limites existent — la vérification manuelle du PDF d'extrait sur [boamp.fr](https://www.boamp.fr) reste recommandée avant toute action.
- Couverture BOAMP : principalement les marchés > 40 000 € HT. Les MAPA inférieurs à ce seuil peuvent ne pas y figurer.

---

## Colonnes du CSV produit

| Colonne | Description |
|---|---|
| `idweb` | Identifiant unique BOAMP |
| `dateparution` | Date de publication |
| `datelimitereponse` | Date limite de dépôt des offres / réponses |
| `dept` | Département (2 caractères) |
| `nomacheteur` | Nom de l'acheteur public |
| `objet` | Titre du marché |
| `descripteur_str` | Descripteurs BOAMP |
| `procedure_libelle` | Type de procédure |
| `score_perimetre` | Score L228-2 (−3 à +5) |
| `dans_perimetre` | True si score ≥ 2 |
| `cyclable_detecte` | True si mention d'aménagement cyclable |
| `cyclable_mots` | Mots cyclables détectés |
| `source_cyclable` | Source de la détection (titre ou description) |
| `alerte_l228` | True si marché sous obligation sans vélo |
| `vrai_conforme` | True si marché conforme L228-2 |
| `url_avis` | Lien vers l'annonce web BOAMP |
| `url_pdf` | Lien de téléchargement direct de l'extrait PDF de l'avis |
| `source_cyclable` | `titre` ou `description` |
| `alerte_l228` | **True = à vérifier** |
| `url_avis` | Lien direct vers l'annonce BOAMP |

---

## Historique des versions

| Version | Évolution principale |
|---|---|
| v1–v3 | Collecte BOAMP, débogage API ODS (noms de champs réels) |
| v4 | Suppression de LOM comme mot-clé (faussait 187 détections via "Plomberie") |
| v5 | Score périmètre L228-2, exclusion accord-cadres TCE, RD/RN correctement traitées |
| v6 | Tentative scraping HTML boamp.fr (abandonné) |
| **v7** | **Champ `donnees` : description complète sans scraping** |

---

## Sources et références

- [Article L228-2 du Code de l'environnement](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000039784296)
- [Loi d'Orientation des Mobilités (LOM)](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000039666574)
- [API BOAMP / DILA](https://boamp-datadila.opendatasoft.com)
- [Guide FUB — obligation L228-2](https://www.fub.fr)

---

## Licence

Code source : MIT
Données BOAMP : [Licence ouverte v2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence) (Etalab / DILA)
