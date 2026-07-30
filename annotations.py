import os
import sqlite3
import json
import requests
import pandas as pd
import streamlit as st
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data") / "annotations.db"

def get_secret(key: str, default=None):
    """Accès sécurisé aux secrets Streamlit sans lever d'exception si secrets.toml est absent."""
    # 1. Variable d'environnement OS
    if key in os.environ:
        return os.environ[key]

    # 2. st.secrets (Streamlit)
    try:
        if hasattr(st, 'runtime') and hasattr(st.runtime, 'exists') and st.runtime.exists():
            sec = getattr(st, 'secrets', None)
            if sec:
                if key in sec:
                    return sec[key]
                if "gsheets" in sec and key in sec["gsheets"]:
                    return sec["gsheets"][key]
    except Exception:
        pass
    return default

def init_db():
    """Initialise la table des annotations en base SQLite locale."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS annotations (
                idweb TEXT PRIMARY KEY,
                relecture TEXT DEFAULT '🔳 Non relu',
                commentaire TEXT DEFAULT '',
                updated_at TEXT
            )
        """)
        conn.commit()

def load_annotations() -> pd.DataFrame:
    """
    Charge les annotations depuis Google Sheets (si GSHEETS_CSV_URL configuré)
    sinon depuis la base SQLite locale.
    """
    # 1. Option Google Sheets via Webhook ou CSV public
    gsheets_url = get_secret("GSHEETS_CSV_URL") or get_secret("csv_url")
    if gsheets_url:
        try:
            df_gsheet = pd.read_csv(gsheets_url, dtype=str)
            needed_cols = {'idweb', 'relecture', 'commentaire'}
            if needed_cols.issubset(df_gsheet.columns):
                return df_gsheet[['idweb', 'relecture', 'commentaire']].fillna({
                    'relecture': '🔳 Non relu',
                    'commentaire': ''
                })
        except Exception as e:
            st.warning(f"Impossible de charger Google Sheets: {e}. Bascule sur SQLite local.")

    # 2. Option par défaut: SQLite local
    init_db()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query("SELECT idweb, relecture, commentaire FROM annotations", conn)
            df['relecture'] = df['relecture'].fillna('🔳 Non relu').replace('', '🔳 Non relu')
            df['commentaire'] = df['commentaire'].fillna('')
            return df
    except Exception as e:
        print(f"Erreur lors du chargement des annotations SQLite: {e}")
        return pd.DataFrame(columns=['idweb', 'relecture', 'commentaire'])

def save_annotation(idweb: str, relecture: str, commentaire: str):
    """
    Sauvegarde l'annotation pour un marché donné (idweb).
    Sauvegarde d'abord en local SQLite, puis envoie au Webhook Google Sheets si configuré.
    """
    now_str = datetime.now().isoformat()
    relecture_clean = relecture if relecture else '🔳 Non relu'
    commentaire_clean = commentaire if commentaire else ''

    # 1. Sauvegarde SQLite local
    init_db()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO annotations (idweb, relecture, commentaire, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(idweb) DO UPDATE SET
                    relecture = excluded.relecture,
                    commentaire = excluded.commentaire,
                    updated_at = excluded.updated_at
            """, (str(idweb), relecture_clean, commentaire_clean, now_str))
            conn.commit()
    except Exception as e:
        st.error(f"Erreur sauvegarde SQLite: {e}")

    # 2. Sauvegarde Webhook Google Sheets si disponible
    webhook_url = get_secret("GSHEETS_WEBHOOK_URL") or get_secret("webhook_url")
    if webhook_url:
        try:
            payload = {
                "idweb": str(idweb),
                "relecture": relecture_clean,
                "commentaire": commentaire_clean,
                "updated_at": now_str
            }
            requests.post(webhook_url, json=payload, timeout=3)
        except Exception as e:
            st.warning(f"Erreur synchro Webhook Google Sheets: {e}")
