#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script îmbunătățit pentru verificarea și ștergerea automată a folderelor
care conțin fișiere deja prezente pe Internet Archive.
Versiune stabilă cu gestionare completă a erorilor.
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
from typing import List, Dict, Any, Optional

# Configurații generale
ARCHIVE_PATH = Path(r"g:\ARHIVA\B")
DELAY_BETWEEN_SEARCHES = 3  # secunde între cereri
STATE_FILE = Path("archive_cleanup_state.json")
LOG_FILE = Path(f"archive_cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
RELEVANT_EXTENSIONS = ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc', '.lit', '.rtf']
MAX_API_ATTEMPTS = 3
API_TIMEOUT = 15

# Configurare logger avansată
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ArchiveCleaner")

class ArchiveCleaner:
    def __init__(self):
        self.state = self._load_state()
        self.deleted_count = 0
        self.checked_count = 0
        self.error_count = 0

    def _load_state(self) -> Dict[str, Any]:
        """Încarcă starea anterioară din fișier"""
        default_state = {
            "processed_folders": [],
            "deleted_folders": [],
            "last_processed": None,
            "stats": {
                "total_checked": 0,
                "total_deleted": 0,
                "total_space_saved_mb": 0.0
            }
        }

        try:
            if STATE_FILE.exists():
                with STATE_FILE.open('r', encoding='utf-8') as f:
                    state = json.load(f)
                    # Asigură compatibilitate cu versiuni anterioare
                    if "stats" not in state:
                        state["stats"] = default_state["stats"]
                    logger.info(f"Stare încărcată: {len(state.get('processed_folders', []))} intrări")
                    return state
        except Exception as e:
            logger.error(f"Eroare la încărcarea stării: {e}")

        return default_state

    def _save_state(self):
        """Salvează starea curentă în fișier"""
        self.state["last_processed"] = datetime.now().isoformat()
        try:
            with STATE_FILE.open('w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            logger.debug("Stare salvată cu succes")
        except Exception as e:
            logger.error(f"Eroare la salvarea stării: {e}")

    def _clean_title(self, filename: str) -> str:
        """Curăță titlul fișierului pentru căutare"""
        name = Path(filename).stem

        # Elimină modele comune de sufixe
        patterns = [
            r'[_-]\d{6,8}$',  # Data la sfârșit
            r'\s*[\(\[].*?[\)\]]',  # Conținut între paranteze
            r'\b[vV]\.?\s*\d+([\.\-]\d+)*\b',  # Numere de versiune
            r'\b(ed|edit|edition|version)\b.*$',  # Mențiuni de ediție
            r'\b(scan(ned)?|ocr|digital|copy|retail)\b',  # Termeni tehnici
            r'[_\s]+$'  # Spații sau underscore la sfârșit
        ]

        for pattern in patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)

        # Normalizare format
        name = re.sub(r'\s+[-–]\s*', ' - ', name)  # Uniformizare separator
        name = re.sub(r'\s+', ' ', name).strip()  # Elimină spații multiple

        logger.debug(f"Curățare titlu: '{filename}' → '{name}'")
        return name

    def _scan_folders(self) -> List[Dict[str, Any]]:
        """Scanează folderele și returnează lista de sarcini"""
        tasks = []
        logger.info(f"Scanare începută în: {ARCHIVE_PATH}")

        try:
            for root, _, files in os.walk(ARCHIVE_PATH):
                folder = Path(root)
                relevant_files = [
                    f for f in files
                    if Path(f).suffix.lower() in RELEVANT_EXTENSIONS
                ]

                if not relevant_files:
                    continue

                logger.debug(f"Folder {folder}: {len(relevant_files)} fișiere relevante")

                # Grupează fișiere după titlurile curățate
                file_groups = {}
                for fname in relevant_files:
                    clean_title = self._clean_title(fname)
                    if clean_title not in file_groups:
                        file_groups[clean_title] = []
                    file_path = folder / fname
                    try:
                        file_size = file_path.stat().st_size
                        file_groups[clean_title].append((file_path, file_size))
                    except OSError as e:
                        logger.warning(f"Eroare la accesarea {file_path}: {e}")

                # Creează sarcini pentru fiecare grup
                for title, file_list in file_groups.items():
                    if not file_list:
                        continue
                    tasks.append({
                        "search_title": title,
                        "folder": folder,
                        "files": [f[0] for f in file_list],
                        "size": sum(f[1] for f in file_list)
                    })

            logger.info(f"Scanare completă. Sarcini găsite: {len(tasks)}")
            return tasks

        except Exception as e:
            logger.error(f"Eroare la scanare: {e}")
            return []

    def _check_archive(self, title: str) -> bool:
        """Verifică existența titlului pe archive.org"""
        url = "https://archive.org/advancedsearch.php"
        params = {
            "q": f'title:"{title}"',
            "fl[]": "identifier",
            "rows": 1,
            "output": "json",
            "sort": "downloads desc"
        }

        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                logger.debug(f"Încercare {attempt}: Caut '{title}'")
                response = requests.get(url, params=params, timeout=API_TIMEOUT)
                response.raise_for_status()

                data = response.json()
                num_found = data.get("response", {}).get("numFound", 0)

                if num_found > 0:
                    logger.info(f"Găsit pe archive.org: '{title}'")
                    return True

                logger.debug(f"Negăsit pe archive.org: '{title}'")
                return False

            except requests.exceptions.RequestException as e:
                logger.warning(f"Eroare API (încercarea {attempt}): {e}")
                if attempt < MAX_API_ATTEMPTS:
                    time.sleep(2)

        logger.error(f"Eșuat după {MAX_API_ATTEMPTS} încercări pentru '{title}'")
        return False

    def _delete_folder(self, task: Dict[str, Any]):
        """Șterge folderul și actualizează starea"""
        folder = task['folder']
        try:
            # Verifică dacă folderul părinte este directorul rădăcină
            if folder.parent != ARCHIVE_PATH:
                root_to_delete = folder.parent
            else:
                root_to_delete = folder

            logger.warning(f"Ștergere folder: {root_to_delete}")

            # Calculează spațiul eliberat
            size_mb = task['size'] / (1024 * 1024)

            # Încercare ștergere
            shutil.rmtree(root_to_delete)

            # Actualizează starea
            self.state["deleted_folders"].append({
                "folder": str(root_to_delete),
                "title": task["search_title"],
                "files": [str(f) for f in task["files"]],
                "size_mb": round(size_mb, 2),
                "deleted_at": datetime.now().isoformat()
            })

            self.deleted_count += 1
            self.state["stats"]["total_deleted"] += 1
            self.state["stats"]["total_space_saved_mb"] = round(
                self.state["stats"]["total_space_saved_mb"] + size_mb, 2
            )
            logger.info(f"Șters cu succes: {root_to_delete} ({size_mb:.2f} MB)")

        except Exception as e:
            self.error_count += 1
            logger.error(f"Eroare la ștergerea {folder}: {e}")

    def _reset_processed(self):
        """Resetează lista de foldere procesate"""
        self.state["processed_folders"] = []
        self._save_state()
        logger.info("Lista foldere procesate a fost resetată")

    def _generate_report(self):
        """Generează un raport final"""
        report = [
            "\n" + "=" * 50,
            "RAPORT FINAL",
            "=" * 50,
            f"Foldere verificate: {self.checked_count}",
            f"Foldere șterse: {self.deleted_count}",
            f"Erori întâmpinate: {self.error_count}",
            f"Spațiu total eliberat: {self.state['stats']['total_space_saved_mb']:.2f} MB",
            ""
        ]

        logger.info("\n".join(report))

    def run(self) -> bool:
        """Rulează procesul principal"""
        if not ARCHIVE_PATH.exists():
            logger.error(f"Directorul {ARCHIVE_PATH} nu există!")
            return False

        logger.info("=" * 50)
        logger.info("Archive Cleaner - Proces început")
        logger.info("=" * 50)

        self._reset_processed()
        tasks = self._scan_folders()

        if not tasks:
            logger.info("Nu s-au găsit fișiere de procesat")
            return True

        for idx, task in enumerate(tasks, 1):
            folder_str = str(task["folder"])

            if folder_str in self.state["processed_folders"]:
                continue

            logger.info(f"\nProgres: {idx}/{len(tasks)} - {task['search_title']}")

            if self._check_archive(task["search_title"]):
                self._delete_folder(task)

            self.state["processed_folders"].append(folder_str)
            self.checked_count += 1
            self.state["stats"]["total_checked"] += 1

            if idx % 5 == 0:  # Salvează periodic
                self._save_state()

            if idx < len(tasks):
                logger.debug(f"Aștept {DELAY_BETWEEN_SEARCHES} secunde...")
                time.sleep(DELAY_BETWEEN_SEARCHES)

        self._save_state()
        self._generate_report()
        return True

def main():
    """Funcția principală"""
    try:
        cleaner = ArchiveCleaner()
        success = cleaner.run()
        exit_code = 0 if success else 1
    except KeyboardInterrupt:
        logger.warning("Proces întrerupt de utilizator")
        exit_code = 2
    except Exception as e:
        logger.critical(f"Eroare neașteptată: {str(e)}", exc_info=True)
        exit_code = 3
    finally:
        logging.shutdown()

    exit(exit_code)

if __name__ == "__main__":
    main()