#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pentru verificarea și ștergerea automată a folderelor
care conțin fișiere deja prezente pe Internet Archive,
folosind API-ul JSON al Archive.org (fără Selenium).
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
DELAY_BETWEEN_SEARCHES = 3   # secunde între cereri, redus pentru viteză
STATE_FILE = Path("archive_cleanup_state.json")
LOG_FILE = Path(f"archive_cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
RELEVANT_EXTENSIONS = ['.pdf', '.epub', '.mobi', '.djvu', '.docx',
                       '.doc', '.lit', '.rtf']

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
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            print(f"[LOAD STATE] {state}")
            return state
        except Exception as e:
            print(f"[WARN] Nu s-a putut încărca state: {e}")
    return {"processed_folders": [], "deleted_folders": [], "last_processed": None}

def save_state(state):
    state["last_processed"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[SAVE STATE] processed={len(state['processed_folders'])}, deleted={len(state['deleted_folders'])}")

def clean_title_for_search(filename: str) -> str:
    name = Path(filename).stem
    print(f"[CLEAN] original filename: {filename}")
    name = re.sub(r'[_-]\d{6,8}$', '', name)
    name = re.sub(r'\s*[\(\[].*?[\)\]]', '', name)
    name = re.sub(r'\b[vV]\.?\s*\d+([\.\-]\d+)*\b', '', name)
    suffixes = ['scan', 'ctrl', 'retail', r'cop\d+', 'Vp', 'draft',
                'final', 'ocr', 'edit', 'proof', 'beta', 'alpha',
                'test', 'demo', 'sample', 'preview', 'full', 'complete',
                'fix', 'corrected']
    pattern = r'\b(' + '|'.join(suffixes) + r')\b'
    name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+[-–]\s*', ' - ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    print(f"[CLEAN] cleaned title: {name}")
    return name

def scan_folders():
    tasks = []
    print(f"[SCAN] Scanez folderele din: {ARCHIVE_PATH}")
    for root, _, files in os.walk(ARCHIVE_PATH):
        folder = Path(root)
        relevant = [f for f in files if Path(f).suffix.lower() in RELEVANT_EXTENSIONS]
        if not relevant:
            continue
        print(f"[SCAN] în folder {folder.name}: {len(relevant)} fișiere relevante")
        groups = {}
        for fname in relevant:
            key = clean_title_for_search(fname)
            groups.setdefault(key, []).append(folder / fname)
        for title, flist in groups.items():
            tasks.append({"search_title": title, "folder": folder, "files": flist})
    print(f"[SCAN] total grupuri găsite: {len(tasks)}")
    return tasks

def exists_on_archive(title: str) -> bool:
    url = "https://archive.org/advancedsearch.php"
    params = {"q": f'title:"{title}"', "fl[]": "identifier", "rows": 1, "output": "json"}
    print(f"[API] Cerere pentru titlu: '{title}' → {url} params={params}")
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            num = data.get("response", {}).get("numFound", 0)
            found = num > 0
            print(f"[API] Răspuns: numFound={num}")
            print(f"[API] → {'GĂSIT' if found else 'NEINCLUS'}")
            return found
        except Exception as e:
            print(f"[API] Eroare attempt {attempt}: {e}")
            time.sleep(2)
    print(f"[API] Eșuat după 3 încercări pentru '{title}'")
    return False

def delete_folder(task: dict, state: dict):
    # Ștergem folderul sursă și, dacă e nevoie, și folderul autor
    folder = task['folder']
    # Determin directorul de nivel superior (autor)
    if folder.parent != ARCHIVE_PATH:
        root_to_delete = folder.parent
    else:
        root_to_delete = folder
    print(f"[DELETE] Șterg folder: {root_to_delete}")
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
        print("[DELETE] OK")
    except Exception as e:
        print(f"[ERROR] Ștergere eșuată: {e}")

def reset_processed_folders(state: dict):
    state["processed_folders"] = []
    save_state(state)
    print("[RESET] processed_folders golit")

def main():
    if not ARCHIVE_PATH.exists():
        print(f"[ERROR] Folderul {ARCHIVE_PATH} nu există!")
        return

    state = load_state()
    reset_processed_folders(state)

    tasks = scan_folders()
    for idx, task in enumerate(tasks, 1):
        folder_str = str(task["folder"])
        if folder_str in state["processed_folders"]:
            continue
        print(f"[PROGRES] {idx}/{len(tasks)} → {task['search_title']}")
        if exists_on_archive(task["search_title"]):
            delete_folder(task, state)
        state["processed_folders"].append(folder_str)
        save_state(state)
        if idx < len(tasks):
            print(f"[WAIT] {DELAY_BETWEEN_SEARCHES}s până la următorul...")
            time.sleep(DELAY_BETWEEN_SEARCHES)

    print("\n[REPORT] -----------------------------")
    print(f"Fișiere verificate: {len(tasks)}")
    print(f"Foldere șterse: {len(state['deleted_folders'])}")
    print("[REPORT] -----------------------------")

if __name__ == "__main__":
    main()
