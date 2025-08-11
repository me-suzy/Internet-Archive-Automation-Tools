#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Internet Archive Duplicate Checker - Chrome Upload Simulation
Simulează upload-ul pe Archive.org pentru a detecta sufixele duplicate în Page URL.

Înainte de rulare:
1. Rulează start_chrome_debug.bat pentru a porni Chrome în debug mode
2. Rulează acest script

Logica:
- Pentru fiecare folder, simulează upload-ul pe archive.org/upload
- Verifică Page URL generat automat după 5 secunde
- Dacă Page URL conține _YYYYMM sau _YYYYMMDD → șterge folderul (duplicat)
- Închide tab-ul după fiecare verificare
"""

import os
import re
import time
import shutil
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException

# ============= CONFIGURĂRI =============
ARCHIVE_PATH = Path(r"g:\ARHIVA\B+")
ARCHIVE_URL = "https://archive.org/upload"
STATE_FILE = Path("archive_duplicate_state_chrome.json")
LOG_FILE = Path(f"archive_duplicate_chrome_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

# Extensii prioritare pentru verificare (în ordinea priorității)
PRIORITY_EXTENSIONS = ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc', '.lit', '.rtf']

# Extensii de ignorat
IGNORE_EXTENSIONS = ['.jpg', '.png']

# ============= CONFIGURARE LOGGER =============
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ArchiveChromeChecker")


class ArchiveChromeChecker:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.driver = None
        self.wait = None
        self.state = self.load_state()
        self.deleted_count = 0
        self.checked_count = 0
        self.error_count = 0
        self.base_window = None

    def load_state(self) -> Dict[str, Any]:
        """Încarcă starea salvată anterior"""
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

        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                    # Compatibilitate cu versiuni anterioare
                    if "deleted_folders" not in state:
                        state["deleted_folders"] = []
                    if "stats" not in state:
                        state["stats"] = default_state["stats"]
                    if "processed_folders" not in state:
                        state["processed_folders"] = []

                    logger.info(f"📋 Stare încărcată: {len(state.get('processed_folders', []))} foldere procesate anterior")
                    return state
            except Exception as e:
                logger.warning(f"⚠️ Nu s-a putut încărca starea: {e}")

        return default_state

    def save_state(self):
        """Salvează starea curentă"""
        self.state["last_processed"] = datetime.now().isoformat()
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            logger.debug("💾 Stare salvată cu succes")
        except Exception as e:
            logger.error(f"❌ Eroare la salvarea stării: {e}")

    def setup_chrome_driver(self):
        """Conectează la instanța Chrome cu debugging activată"""
        try:
            logger.info("🔧 Conectare la Chrome debug mode...")
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

            # Configurări pentru upload
            prefs = {
                "download.default_directory": os.path.abspath(os.getcwd()),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
            }
            chrome_options.add_experimental_option("prefs", prefs)

            self.driver = webdriver.Chrome(options=chrome_options)
            self.wait = WebDriverWait(self.driver, self.timeout)

            # Păstrează referința la primul tab (tab-ul de bază)
            self.base_window = self.driver.current_window_handle

            logger.info("✅ Conectat la Chrome cu succes")
            logger.info(f"🏠 Tab de bază: {self.base_window}")
            return True

        except WebDriverException as e:
            logger.error(f"❌ Eroare la conectarea la Chrome: {e}")
            logger.error("💡 Asigură-te că ai rulat start_chrome_debug.bat înainte!")
            return False

    def scan_folders(self) -> List[Dict[str, Any]]:
        """Scanează folderele și returnează lista de foldere de verificat"""
        folders_to_check = []
        logger.info(f"📂 Scanez folderul: {ARCHIVE_PATH}")

        try:
            for folder_path in ARCHIVE_PATH.iterdir():
                if not folder_path.is_dir():
                    continue

                # Găsește fișierele relevante recursiv
                relevant_files = []
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = Path(root) / file
                        if file_path.suffix.lower() in PRIORITY_EXTENSIONS:
                            relevant_files.append(file_path)

                if not relevant_files:
                    logger.debug(f"📁 {folder_path.name}: Nu are fișiere relevante")
                    continue

                # Găsește primul fișier cu prioritatea cea mai mare
                priority_file = self.find_priority_file(relevant_files)
                if not priority_file:
                    logger.debug(f"📁 {folder_path.name}: Nu are fișiere cu extensii prioritare")
                    continue

                # Calculează dimensiunea totală
                total_size = sum(f.stat().st_size for f in relevant_files if f.exists())

                folders_to_check.append({
                    "folder_path": folder_path,
                    "priority_file": priority_file,
                    "all_files": relevant_files,
                    "total_size": total_size
                })

                logger.debug(f"📁 {folder_path.name}: {len(relevant_files)} fișiere, prioritar: {priority_file.name}")

            logger.info(f"📊 Găsite {len(folders_to_check)} foldere de verificat")
            return folders_to_check

        except Exception as e:
            logger.error(f"❌ Eroare la scanarea folderelor: {e}")
            return []

    def find_priority_file(self, files: List[Path]) -> Path:
        """Găsește primul fișier conform priorității"""
        for ext in PRIORITY_EXTENSIONS:
            for file in files:
                if file.suffix.lower() == ext:
                    return file
        return None

    def check_folder_for_duplicate(self, folder_info: Dict[str, Any]) -> bool:
        """Verifică un folder prin simularea upload-ului pe Archive.org"""
        folder_path = folder_info["folder_path"]
        priority_file = folder_info["priority_file"]

        logger.info(f"\n📂 Verific folderul: {folder_path.name}")
        logger.info(f"📄 Fișier de test: {priority_file.name}")

        # Sari peste folderele deja procesate
        folder_str = str(folder_path)
        if folder_str in self.state["processed_folders"]:
            logger.info(f"⏭️ Folder deja procesat, sar peste")
            return False

        try:
            # Deschide un nou tab pentru upload
            logger.info("🌐 Deschid tab nou pentru archive.org/upload...")
            self.driver.execute_script("window.open('');")
            new_window = self.driver.window_handles[-1]
            self.driver.switch_to.window(new_window)

            # Navighează la pagina de upload
            self.driver.get(ARCHIVE_URL)

            # Așteaptă ca pagina să se încarce
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]')))
            logger.info("✅ Pagina de upload încărcată")

            # Găsește input-ul pentru fișiere
            file_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]')))

            # Încarcă fișierul
            logger.info(f"📤 Încarcă fișierul: {priority_file.name}")
            file_input.send_keys(str(priority_file.absolute()))

            # Așteaptă ca fișierul să se proceseze și să se genereze Page URL
            logger.info("⏳ Aștept 8 secunde pentru generarea Page URL...")
            time.sleep(8)

            # Verifică Page URL pentru sufixe duplicate
            is_duplicate = self.check_page_url_for_suffix()

            if is_duplicate:
                # Închide tab-ul înainte de ștergere
                self.close_current_tab_and_return_to_base()

                # Șterge folderul
                self.delete_folder(folder_info)
                return True
            else:
                logger.info("✅ Fișierul nu are sufix duplicat - păstrez folderul")

                # Marchează ca procesat
                self.state["processed_folders"].append(folder_str)
                self.checked_count += 1
                self.state["stats"]["total_checked"] += 1

                # Închide tab-ul
                self.close_current_tab_and_return_to_base()
                return False

        except Exception as e:
            logger.error(f"❌ Eroare la verificarea folderului {folder_path.name}: {e}")
            self.error_count += 1

            # Încearcă să închidă tab-ul chiar și în caz de eroare
            try:
                self.close_current_tab_and_return_to_base()
            except:
                pass

            return False

    def check_page_url_for_suffix(self) -> bool:
        """Verifică dacă Page URL-ul conține sufixe duplicate"""
        try:
            # Găsește elementul cu ID-ul item_id care conține identifier-ul
            item_id_element = self.wait.until(
                EC.presence_of_element_located((By.ID, "item_id"))
            )

            page_identifier = item_id_element.text.strip() or item_id_element.get_attribute("title") or ""

            if not page_identifier:
                logger.warning("⚠️ Nu am putut extrage Page URL identifier")
                return False

            logger.info(f"📋 Page URL identifier: {page_identifier}")

            # Verifică sufixele duplicate
            if re.search(r'_\d{6}$|_\d{8}$', page_identifier):
                logger.info(f"🚫 GĂSIT SUFIX DUPLICAT în identifier: {page_identifier}")
                return True
            else:
                logger.info(f"✅ Identifier OK (fără sufix duplicat): {page_identifier}")
                return False

        except TimeoutException:
            logger.warning("⚠️ Timeout la așteptarea Page URL - probabil nu s-a generat încă")
            return False
        except Exception as e:
            logger.error(f"❌ Eroare la verificarea Page URL: {e}")
            return False

    def close_current_tab_and_return_to_base(self):
        """Închide tab-ul curent și revine la tab-ul de bază"""
        try:
            current_window = self.driver.current_window_handle

            if current_window != self.base_window:
                logger.info("🗂️ Închid tab-ul curent...")
                self.driver.close()

                # Revine la tab-ul de bază
                self.driver.switch_to.window(self.base_window)
                logger.info("🏠 Revenit la tab-ul de bază")
            else:
                logger.warning("⚠️ Sunt deja pe tab-ul de bază")

        except Exception as e:
            logger.error(f"❌ Eroare la închiderea tab-ului: {e}")
            # Încearcă să revină la primul tab disponibil
            try:
                if self.driver.window_handles:
                    self.driver.switch_to.window(self.driver.window_handles[0])
                    self.base_window = self.driver.current_window_handle
            except:
                pass

    def delete_folder(self, folder_info: Dict[str, Any]):
        """Șterge folderul cu duplicat"""
        folder_path = folder_info["folder_path"]

        try:
            logger.warning(f"🗑️ Șterg folderul duplicat: {folder_path}")

            # Calculează spațiul eliberat
            size_mb = folder_info.get('total_size', 0) / (1024 * 1024)

            # Creează backup info
            backup_info = {
                "folder": str(folder_path),
                "priority_file": str(folder_info["priority_file"]),
                "all_files": [str(f) for f in folder_info["all_files"]],
                "size_mb": round(size_mb, 2),
                "deleted_at": datetime.now().isoformat(),
                "reason": "Sufix duplicat detectat în Page URL"
            }

            # Șterge folderul
            shutil.rmtree(folder_path)

            # Actualizează statisticile
            if "deleted_folders" not in self.state:
                self.state["deleted_folders"] = []

            self.state["deleted_folders"].append(backup_info)
            self.deleted_count += 1

            if "stats" not in self.state:
                self.state["stats"] = {"total_checked": 0, "total_deleted": 0, "total_space_saved_mb": 0.0}

            self.state["stats"]["total_deleted"] += 1
            self.state["stats"]["total_space_saved_mb"] = round(
                self.state["stats"]["total_space_saved_mb"] + size_mb, 2
            )

            logger.info(f"✅ Folder șters cu succes! ({size_mb:.2f} MB eliberat)")

            # Salvează starea imediat
            self.save_state()

        except Exception as e:
            logger.error(f"❌ Eroare la ștergerea folderului: {e}")
            self.error_count += 1

    def generate_report(self):
        """Generează raportul final"""
        report_lines = [
            "\n" + "=" * 60,
            "📊 RAPORT FINAL - Chrome Upload Simulation",
            "=" * 60,
            f"✅ Foldere verificate: {self.checked_count}",
            f"🗑️ Foldere șterse (duplicate): {self.deleted_count}",
            f"❌ Erori întâmpinate: {self.error_count}",
            f"💾 Spațiu eliberat în această sesiune: {sum(f.get('size_mb', 0) for f in self.state['deleted_folders'][-self.deleted_count:]):.2f} MB",
            f"📈 Total istoric foldere șterse: {self.state['stats']['total_deleted']}",
            f"📈 Total spațiu istoric eliberat: {self.state['stats']['total_space_saved_mb']:.2f} MB",
            "=" * 60
        ]

        for line in report_lines:
            logger.info(line)

        if self.deleted_count > 0:
            logger.info(f"\n📋 FOLDERE ȘTERSE ÎN ACEASTĂ SESIUNE:")
            recent_deleted = self.state["deleted_folders"][-self.deleted_count:]
            for i, folder_info in enumerate(recent_deleted, 1):
                logger.info(f"   {i}. {Path(folder_info['folder']).name}")
                logger.info(f"      Fișier test: {Path(folder_info['priority_file']).name}")
                logger.info(f"      Spațiu eliberat: {folder_info.get('size_mb', 0):.2f} MB")

    def run(self):
        """Rulează procesul principal"""
        logger.info("=" * 60)
        logger.info("🚀 START - Archive.org Duplicate Checker (Chrome Simulation)")
        logger.info(f"📁 Folder verificat: {ARCHIVE_PATH}")
        logger.info("=" * 60)

        # Verifică folderul sursă
        if not ARCHIVE_PATH.exists():
            logger.error(f"❌ Folderul {ARCHIVE_PATH} nu există!")
            return False

        # Configurează Chrome
        if not self.setup_chrome_driver():
            return False

        try:
            # Scanează folderele
            folders_to_check = self.scan_folders()

            if not folders_to_check:
                logger.info("✅ Nu sunt foldere de verificat!")
                return True

            # Procesează fiecare folder
            for i, folder_info in enumerate(folders_to_check, 1):
                logger.info(f"\n📊 Progres: {i}/{len(folders_to_check)}")

                try:
                    self.check_folder_for_duplicate(folder_info)

                    # Pauză între verificări pentru a nu suprasolicita serverul
                    if i < len(folders_to_check):
                        logger.info("⏳ Pauză 3 secunde...")
                        time.sleep(3)

                except KeyboardInterrupt:
                    logger.warning("\n⚠️ Întrerupt de utilizator")
                    break
                except Exception as e:
                    logger.error(f"❌ Eroare la procesarea folderului: {e}")
                    continue

            # Salvează starea finală
            self.save_state()

            # Generează raportul
            self.generate_report()

            return True

        except KeyboardInterrupt:
            logger.warning("\n⚠️ Proces întrerupt manual")
            self.save_state()
            self.generate_report()
            return False
        except Exception as e:
            logger.error(f"\n❌ Eroare fatală: {e}", exc_info=True)
            self.save_state()
            return False
        finally:
            # Închide Chrome doar dacă l-am conectat noi
            if self.driver:
                try:
                    # Închide toate tab-urile deschise de script (păstrează tab-ul de bază)
                    current_windows = self.driver.window_handles
                    for window in current_windows:
                        if window != self.base_window:
                            try:
                                self.driver.switch_to.window(window)
                                self.driver.close()
                            except:
                                pass

                    # Revine la tab-ul de bază
                    if self.base_window in self.driver.window_handles:
                        self.driver.switch_to.window(self.base_window)

                    logger.info("🧹 Tab-uri cleanup completat")
                except Exception as cleanup_error:
                    logger.warning(f"⚠️ Eroare la cleanup: {cleanup_error}")


def main():
    """Funcția principală"""
    try:
        checker = ArchiveChromeChecker()
        success = checker.run()

        if success:
            print("\n✅ Proces finalizat cu succes!")
        else:
            print("\n❌ Proces finalizat cu erori!")

    except Exception as e:
        print(f"❌ Eroare fatală: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()