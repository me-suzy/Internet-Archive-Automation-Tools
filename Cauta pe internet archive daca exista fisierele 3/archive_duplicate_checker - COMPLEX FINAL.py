#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARCHIVE DUPLICATE CLEANER v2.0
Script avansat pentru identificarea și ștergerea fișierelor disponibile pe Internet Archive.
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

# Configurații
CONFIG = {
    "archive_path": Path(r"g:\ARHIVA\B"),
    "delay": 3,  # secunde între cereri
    "state_file": Path("archive_cleanup_state.json"),
    "log_file": Path(f"archive_cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"),
    "extensions": ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc', '.lit', '.rtf'],
    "max_attempts": 3,
    "api_timeout": 15,
    "save_interval": 5  # salvare la fiecare X fișiere
}

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)-8s - %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(CONFIG['log_file'], encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ArchiveCleaner")

class ArchiveCleaner:
    def __init__(self):
        self.state = self._init_state()
        self.stats = {
            'checked': 0,
            'deleted': 0,
            'errors': 0,
            'space_saved': 0.0
        }

    def _init_state(self) -> Dict[str, Any]:
        """Initializează sau încarcă starea anterioară"""
        default_state = {
            "processed": [],
            "deleted": [],
            "stats": {
                "total_checked": 0,
                "total_deleted": 0,
                "total_space_saved_mb": 0.0
            }
        }

        try:
            if CONFIG['state_file'].exists():
                with CONFIG['state_file'].open('r', encoding='utf-8') as f:
                    state = json.load(f)
                    # Migrare stare versiuni anterioare
                    if "processed" not in state:
                        state["processed"] = state.get("processed_folders", [])
                    if "deleted" not in state:
                        state["deleted"] = state.get("deleted_folders", [])
                    if "stats" not in state:
                        state["stats"] = default_state["stats"]
                    logger.info(f"Stare încărcată: {len(state['processed'])} intrări")
                    return state
        except Exception as e:
            logger.error(f"Eroare la încărcarea stării: {str(e)}")

        return default_state

    def _save_state(self):
        """Salvează starea curentă"""
        self.state['stats'] = {
            "total_checked": self.state['stats'].get('total_checked', 0) + self.stats['checked'],
            "total_deleted": self.state['stats'].get('total_deleted', 0) + self.stats['deleted'],
            "total_space_saved_mb": round(
                self.state['stats'].get('total_space_saved_mb', 0.0) + self.stats['space_saved'], 2
            )
        }

        try:
            with CONFIG['state_file'].open('w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            logger.debug("Stare salvată")
        except Exception as e:
            logger.error(f"Eroare la salvarea stării: {str(e)}")

    def _normalize_title(self, filename: str) -> str:
        """Normalizează titlul pentru căutare"""
        name = Path(filename).stem

        # Elimină componente inutile
        patterns = [
            r'[_-]\d{6,8}$',  # Date
            r'[\(\[].*?[\)\]]',  # Paranteze
            r'\b(vol|volume|part|nr|no|v|ver|version)\.?\s*\d+\b',  # Volume/version
            r'\b(ed|edit|edition|rev|revised)\b.*$',  # Ediții
            r'\b(scan(ned)?|ocr|digital|copy|retail|draft|final|proof)\b',  # Metadata
            r'[_\s\-]+$'  # Separatori finale
        ]

        for pattern in patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)

        # Standardizează formatarea
        name = re.sub(r'[\s_\-]+', ' ', name).strip()
        name = re.sub(r'\s+-\s+', ' - ', name)  # Uniformizează separatorul principal

        logger.debug(f"Titlu normalizat: '{filename}' → '{name}'")
        return name

    def _scan_files(self) -> List[Dict[str, Any]]:
        """Identifică fișierele de procesat"""
        tasks = []
        logger.info(f"Scanare începută în: {CONFIG['archive_path']}")

        try:
            for root, _, files in os.walk(CONFIG['archive_path']):
                current_dir = Path(root)

                # Filtrează fișierele relevante
                relevant_files = [
                    f for f in files
                    if Path(f).suffix.lower() in CONFIG['extensions']
                ]

                if not relevant_files:
                    continue

                logger.debug(f"Director: {current_dir} - {len(relevant_files)} fișiere")

                # Grupează după titlu normalizat
                file_groups = {}
                for fname in relevant_files:
                    norm_title = self._normalize_title(fname)
                    file_path = current_dir / fname

                    try:
                        file_size = file_path.stat().st_size
                        file_groups.setdefault(norm_title, []).append((file_path, file_size))
                    except OSError as e:
                        logger.warning(f"Eroare acces fișier {file_path}: {str(e)}")

                # Creează intrări de procesat
                for title, files in file_groups.items():
                    if not files:
                        continue

                    tasks.append({
                        "title": title,
                        "folder": current_dir,
                        "files": [f[0] for f in files],
                        "size": sum(f[1] for f in files)
                    })

            logger.info(f"Scanare completă. Fișiere de verificat: {len(tasks)}")
            return tasks

        except Exception as e:
            logger.error(f"Eroare scanare: {str(e)}")
            return []

    def _check_archive(self, title: str) -> bool:
        """Verifică existența pe archive.org"""
        params = {
            "q": f'title:"{title}"',
            "fl[]": "identifier",
            "rows": 1,
            "output": "json",
            "sort": "downloads desc"
        }

        for attempt in range(1, CONFIG['max_attempts'] + 1):
            try:
                logger.debug(f"Încercare {attempt}: Caut '{title}'")
                response = requests.get(
                    "https://archive.org/advancedsearch.php",
                    params=params,
                    timeout=CONFIG['api_timeout']
                )
                response.raise_for_status()

                data = response.json()
                if data.get("response", {}).get("numFound", 0) > 0:
                    logger.info(f"Găsit: '{title}'")
                    return True

                logger.debug(f"Negăsit: '{title}'")
                return False

            except requests.RequestException as e:
                logger.warning(f"Eroare API (încercarea {attempt}): {str(e)}")
                if attempt < CONFIG['max_attempts']:
                    time.sleep(2)

        logger.error(f"Eșec verificare pentru '{title}'")
        return False

    def _delete_content(self, task: Dict[str, Any]):
        """Șterge conținutul duplicat"""
        target = task['folder']
        try:
            # Determină ce să ștergem
            if target.parent != CONFIG['archive_path']:
                to_delete = target.parent  # Șterge folderul autor
            else:
                to_delete = target  # Șterge doar folderul cărții

            logger.warning(f"Ștergere: {to_delete}")

            # Calculează spațiul
            size_mb = task['size'] / (1024 ** 2)

            # Execută ștergerea
            shutil.rmtree(to_delete)

            # Actualizează statistici
            self.stats['deleted'] += 1
            self.stats['space_saved'] += size_mb

            # Salvează detalii
            self.state["deleted"].append({
                "path": str(to_delete),
                "title": task["title"],
                "files": [str(f) for f in task["files"]],
                "size_mb": round(size_mb, 2),
                "timestamp": datetime.now().isoformat()
            })

            logger.info(f"Șters cu succes ({size_mb:.2f} MB)")

        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Eroare ștergere {target}: {str(e)}")

    def _show_report(self):
        """Afișează raport final"""
        report = [
            "\n" + "=" * 50,
            " RAPORT FINAL ",
            "=" * 50,
            f"Fișiere verificate: {self.stats['checked']}",
            f"Foldere șterse: {self.stats['deleted']}",
            f"Spațiu eliberat: {self.stats['space_saved']:.2f} MB",
            f"Erori întâlnite: {self.stats['errors']}",
            "\nTotal istoric:",
            f"Verificate: {self.state['stats']['total_checked']}",
            f"Șterse: {self.state['stats']['total_deleted']}",
            f"Spațiu total eliberat: {self.state['stats']['total_space_saved_mb']:.2f} MB",
            "=" * 50
        ]

        logger.info("\n".join(report))

    def run(self) -> bool:
        """Execută procesul principal"""
        if not CONFIG['archive_path'].exists():
            logger.error(f"Directorul {CONFIG['archive_path']} nu există!")
            return False

        logger.info("=" * 50)
        logger.info(" ARCHIVE DUPLICATE CLEANER v2.0 ")
        logger.info("=" * 50)

        # Resetăm doar lista de procesate, păstrând cele șterse
        self.state["processed"] = []
        self._save_state()

        tasks = self._scan_files()
        if not tasks:
            logger.info("Nu s-au găsit fișiere de procesat")
            return True

        for idx, task in enumerate(tasks, 1):
            task_path = str(task["folder"])

            if task_path in self.state["processed"]:
                continue

            logger.info(f"\nProgres: {idx}/{len(tasks)}")
            logger.info(f"Verific: '{task['title']}'")

            if self._check_archive(task["title"]):
                self._delete_content(task)

            self.state["processed"].append(task_path)
            self.stats['checked'] += 1

            # Salvare periodică
            if idx % CONFIG['save_interval'] == 0:
                self._save_state()

            # Pauză între cereri
            if idx < len(tasks):
                logger.debug(f"Aștept {CONFIG['delay']} secunde...")
                time.sleep(CONFIG['delay'])

        # Finalizare
        self._save_state()
        self._show_report()
        return True

def main():
    """Punctul de intrare principal"""
    try:
        cleaner = ArchiveCleaner()
        if cleaner.run():
            logger.info("Proces finalizat cu succes!")
            exit(0)
        else:
            logger.error("Proces finalizat cu erori!")
            exit(1)

    except KeyboardInterrupt:
        logger.warning("Operație întreruptă de utilizator")
        exit(2)

    except Exception as e:
        logger.critical(f"EROARE GRAVĂ: {str(e)}", exc_info=True)
        exit(3)

if __name__ == "__main__":
    main()