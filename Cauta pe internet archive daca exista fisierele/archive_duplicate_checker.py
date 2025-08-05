#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pentru verificarea și ștergerea automată a folderelor
care conțin fișiere deja prezente pe Internet Archive,
folosind API-ul JSON al Archive.org.
"""

import os
import re
import time
import shutil
import json
import logging
import requests
from pathlib import Path
from datetime import datetime

# — Configurări generale —
ARCHIVE_PATH = Path(r"g:\ARHIVA\B")
DELAY_BETWEEN_SEARCHES = 5  # Ajustat la 5 secunde pentru echilibru
STATE_FILE = Path("archive_cleanup_state.json")
LOG_FILE = Path(f"archive_cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
RELEVANT_EXTENSIONS = ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc', '.lit', '.rtf']

# — Configurare logger —
logger = logging.getLogger("ArchiveChecker")
logger.setLevel(logging.DEBUG)
fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(fmt)
logger.addHandler(fh)
sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(sh)

def load_state():
    """Încarcă starea salvată anterior."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding="utf-8") as f:
                state = json.load(f)
            logger.info(f"Stare încărcată: {state}")
            return state
        except Exception as e:
            logger.warning(f"Nu s-a putut încărca starea: {e}")
    return {"processed_folders": [], "deleted_folders": [], "last_processed": None}

def save_state(state):
    """Salvează starea curentă."""
    state["last_processed"] = datetime.now().isoformat()
    with open(STATE_FILE, 'w', encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info(f"Stare salvată: processed={len(state['processed_folders'])}, deleted={len(state['deleted_folders'])}")

def clean_title_for_search(filename: str) -> str:
    """Curăță numele fișierului pentru căutare pe Internet Archive."""
    name = Path(filename).stem
    logger.debug(f"Curățare: fișier original = {filename}")
    name = re.sub(r'[_-]\d{6,8}$', '', name)
    name = re.sub(r'\s*[\(\[].*?[\)\]]', '', name)
    name = re.sub(r'\b[vV]\.?\s*\d+([\.\-]\d+)*\b', '', name)
    suffixes = ['scan', 'ctrl', 'retail', r'cop\d+', 'Vp', 'draft', 'final', 'ocr', 'edit',
                'proof', 'beta', 'alpha', 'test', 'demo', 'sample', 'preview', 'full',
                'complete', 'fix', 'corrected']
    pattern = r'\b(' + '|'.join(suffixes) + r')\b'
    name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+[-–]\s*', ' - ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    logger.debug(f"Curățare: titlu curățat = {name}")
    return name

def scan_folders():
    """Scanează recursiv toate folderele și returnează lista de fișiere de verificat."""
    tasks = []
    logger.info(f"Scanez folderele din: {ARCHIVE_PATH}")
    for root, _, files in os.walk(ARCHIVE_PATH):
        folder = Path(root)
        relevant = [f for f in files if Path(f).suffix.lower() in RELEVANT_EXTENSIONS]
        if not relevant:
            continue
        logger.debug(f"În folder {folder.name}: {len(relevant)} fișiere relevante")
        groups = {}
        for fname in relevant:
            key = clean_title_for_search(fname)
            groups.setdefault(key, []).append(folder / fname)
        for title, flist in groups.items():
            tasks.append({"search_title": title, "folder": folder, "files": flist})
    logger.info(f"Total grupuri găsite: {len(tasks)}")
    return tasks

def exists_on_archive(title: str) -> bool:
    """Verifică dacă un titlu există pe Internet Archive folosind API-ul."""
    url = "https://archive.org/advancedsearch.php"
    headers = {"User-Agent": "ArchiveDuplicateChecker/1.0 (contact@example.com)"}  # Adaugă User-Agent
    params = {
        "q": f'title:({title}*)',  # Căutare cu wildcard pentru variante
        "fl[]": "identifier",
        "rows": 5,  # Crește la 5 pentru a prinde mai multe rezultate
        "output": "json"
    }
    logger.info(f"Cerere API pentru titlu: '{title}' → {url} params={params}")
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            num_found = data.get("response", {}).get("numFound", 0)
            logger.info(f"Răspuns API: numFound={num_found}, raw={data}")
            return num_found > 0
        except requests.RequestException as e:
            logger.error(f"Eroare la cererea API (încercare {attempt}/3): {e}")
            time.sleep(2 ** attempt)  # Așteptare exponențială
    logger.error(f"Eșec după 3 încercări pentru '{title}'")
    return False

def delete_folder(task: dict, state: dict):
    """Șterge un folder și toate subfișierele sale, inclusiv folderul autor dacă e cazul."""
    folder = task['folder']
    # Determin directorul de nivel superior (autor) sau folderul curent
    root_to_delete = folder.parent if folder.parent != ARCHIVE_PATH else folder
    logger.warning(f"Șterg folderul: {root_to_delete}")
    try:
        shutil.rmtree(root_to_delete)
        entry = {
            "folder": str(root_to_delete),
            "title": task["search_title"],
            "files": [str(f) for f in task["files"]],
            "deleted_at": datetime.now().isoformat()
        }
        state["deleted_folders"].append(entry)
        save_state(state)
        logger.info(f"Folder șters cu succes: {root_to_delete}")
    except Exception as e:
        logger.error(f"Eroare la ștergere: {e}")

def reset_processed_folders(state: dict):
    """Resetează lista de foldere procesate pentru a le verifica din nou."""
    state["processed_folders"] = []
    save_state(state)
    logger.info("Lista processed_folders a fost resetată")

def main():
    """Funcția principală."""
    if not ARCHIVE_PATH.exists():
        logger.error(f"Folderul {ARCHIVE_PATH} nu există!")
        return

    state = load_state()
    reset_processed_folders(state)

    tasks = scan_folders()
    if not tasks:
        logger.info("Niciun fișier de verificat!")
        return

    for idx, task in enumerate(tasks, 1):
        folder_str = str(task["folder"])
        if folder_str in state["processed_folders"]:
            logger.debug(f"Salt folder procesat: {folder_str}")
            continue
        logger.info(f"Progres: {idx}/{len(tasks)} → {task['search_title']}")
        if exists_on_archive(task["search_title"]):
            delete_folder(task, state)
        state["processed_folders"].append(folder_str)
        save_state(state)
        if idx < len(tasks):
            logger.info(f"Aștept {DELAY_BETWEEN_SEARCHES} secunde până la următorul...")
            time.sleep(DELAY_BETWEEN_SEARCHES)

    logger.info("\n[RAPORT FINAL] -----------------------------")
    logger.info(f"Fișiere verificate: {len(tasks)}")
    logger.info(f"Foldere șterse: {len(state['deleted_folders'])}")
    logger.info("[RAPORT FINAL] -----------------------------")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Eroare fatală: {e}", exc_info=True)