#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Internet Archive Duplicate Checker - Hybrid Fast Method
Combinează căutarea rapidă pe archive.org/search cu simularea Chrome upload.

Strategia hibridă:
1. Nivel 1: Căutare rapidă pe archive.org/search - analizează HTML pentru duplicate
2. Nivel 2: Simulare Chrome upload - doar pentru cazurile incerte

Înainte de rulare:
1. Rulează start_chrome_debug.bat pentru a porni Chrome în debug mode
2. Rulează acest script
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
from typing import List, Dict, Any, Tuple
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException

# ============= CONFIGURĂRI =============
ARCHIVE_PATH = Path(r"g:\ARHIVA\B+")
ARCHIVE_URL = "https://archive.org/upload"
SEARCH_BASE_URL = "https://archive.org/search"
STATE_FILE = Path("archive_duplicate_hybrid_state.json")
LOG_FILE = Path(f"archive_duplicate_hybrid_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

# Extensii prioritare pentru verificare (în ordinea priorității)
PRIORITY_EXTENSIONS = ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc', '.lit', '.rtf']

# Extensii de ignorat
IGNORE_EXTENSIONS = ['.jpg', '.png']

# Configurare requests
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15

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
logger = logging.getLogger("ArchiveHybridChecker")


class ArchiveHybridChecker:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.driver = None
        self.wait = None
        self.state = self.load_state()
        self.deleted_count = 0
        self.checked_count = 0
        self.error_count = 0
        self.base_window = None
        self.chrome_needed = False

        # Statistici metode
        self.fast_search_hits = 0
        self.chrome_fallback_used = 0

        # Session pentru requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def load_state(self) -> Dict[str, Any]:
        """Încarcă starea salvată anterior"""
        default_state = {
            "processed_folders": [],
            "deleted_folders": [],
            "last_processed": None,
            "stats": {
                "total_checked": 0,
                "total_deleted": 0,
                "total_space_saved_mb": 0.0,
                "fast_search_hits": 0,
                "chrome_fallback_used": 0
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
        self.state["stats"]["fast_search_hits"] = self.fast_search_hits
        self.state["stats"]["chrome_fallback_used"] = self.chrome_fallback_used

        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            logger.debug("💾 Stare salvată cu succes")
        except Exception as e:
            logger.error(f"❌ Eroare la salvarea stării: {e}")

    def setup_chrome_driver(self):
        """Conectează la instanța Chrome cu debugging activată (doar când e necesar)"""
        if self.driver:
            return True  # Deja conectat

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

    def clean_title_for_search(self, filename: str) -> str:
        """Curăță titlul pentru căutare pe Archive.org"""
        name = Path(filename).stem
        logger.debug(f"🔧 Curățare titlu original: {filename}")

        # Elimină sufixele de data
        name = re.sub(r'[_-]\d{6,8}$', '', name)

        # Elimină parantezele și conținutul lor
        name = re.sub(r'\s*\([^)]*\)', '', name)
        name = re.sub(r'\s*\[[^\]]*\]', '', name)

        # Elimină versiunile
        name = re.sub(r'\s*[-–]\s*[vV]\.?\s*[\d\.]+[\d\.\-]*(?:\s+[A-Z]+)?(?:\s*[-–]\s*\d+)?$', '', name)
        name = re.sub(r'\s+[vV]\.?\s*[\d\.]+[\d\.\-]*(?:\s+[A-Z]+)?$', '', name)

        # Elimină sufixele tehnice
        suffixes = ['scan', 'ctrl', 'retail', r'cop\d+', 'Vp', 'draft', 'final',
                   'ocr', 'OCR', 'edit', 'edited', 'rev', 'revised', 'proof',
                   'beta', 'alpha', 'test', 'demo', 'sample', 'preview',
                   'full', 'complete', 'fix', 'fixed', 'corrected']

        # Elimină sufixele care apar după ultima " - "
        parts = name.rsplit(' - ', 1)
        if len(parts) == 2:
            last_part = parts[1].strip()
            suffix_pattern = '|'.join(suffixes)
            if re.match(f'^({suffix_pattern})$', last_part, re.IGNORECASE):
                name = parts[0]

        # Elimină #TAGS (ex: #ISTOR)
        name = re.sub(r'\s*#\w+', '', name)

        # Curăță spațiile
        name = re.sub(r'\s+', ' ', name).strip()
        name = re.sub(r'\s*[-–]\s*$', '', name)

        logger.debug(f"✨ Titlu curățat: {name}")
        return name

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

                # Generează titlul pentru căutare
                search_title = self.clean_title_for_search(priority_file.name)

                folders_to_check.append({
                    "folder_path": folder_path,
                    "priority_file": priority_file,
                    "all_files": relevant_files,
                    "total_size": total_size,
                    "search_title": search_title
                })

                logger.debug(f"📁 {folder_path.name}: {len(relevant_files)} fișiere, titlu căutare: {search_title}")

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

    def search_archive_org_web(self, folder_info: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Căutare rapidă pe archive.org/search pentru a detecta duplicate
        Returns: (is_duplicate, method_used)
        """
        search_title = folder_info["search_title"]
        folder_path = folder_info["folder_path"]

        logger.info(f"🔍 NIVEL 1 - Căutare rapidă pentru: {search_title}")

        # Construiește URL-ul de căutare
        query = quote_plus(search_title)
        search_url = f"{SEARCH_BASE_URL}?query={query}"

        logger.debug(f"🌐 URL căutare: {search_url}")

        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(search_url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()

                # Parse HTML cu BeautifulSoup
                soup = BeautifulSoup(response.content, 'html.parser')

                # Găsește toate elementele <h4> cu clasa "truncated"
                title_elements = soup.find_all('h4', class_='truncated')

                if not title_elements:
                    logger.info(f"   ℹ️ Niciun rezultat găsit în căutare")
                    return False, "no_results"

                # Extrage titlurile și verifică duplicate
                found_titles = []
                for h4 in title_elements:
                    title_attr = h4.get('title', '').strip()
                    title_text = h4.get_text().strip()

                    # Folosește titlul din attribute sau text
                    final_title = title_attr if title_attr else title_text
                    if final_title:
                        found_titles.append(final_title)

                logger.info(f"   📊 Găsite {len(found_titles)} rezultate:")
                for i, title in enumerate(found_titles[:5], 1):  # Afișează primele 5
                    logger.info(f"      {i}. {title}")

                # Verifică duplicate - căută titluri identice
                if len(found_titles) >= 2:
                    # Verifică dacă sunt cel puțin 2 titluri identice
                    title_counts = {}
                    for title in found_titles:
                        # Normalizează titlul pentru comparație
                        normalized = re.sub(r'[^\w\s]', ' ', title.lower())
                        normalized = re.sub(r'\s+', ' ', normalized).strip()

                        title_counts[normalized] = title_counts.get(normalized, 0) + 1

                    # Verifică dacă vreun titlu apare de mai multe ori
                    for title, count in title_counts.items():
                        if count >= 2:
                            logger.info(f"   🎯 DUPLICAT GĂSIT prin căutare rapidă!")
                            logger.info(f"      Titlu duplicat: {title} (apare de {count} ori)")
                            return True, "fast_search"

                logger.info(f"   ✅ Un singur rezultat găsit - nu sunt duplicate evidente")
                return False, "single_result"

            except requests.RequestException as e:
                logger.warning(f"   ⚠️ Eroare la căutarea web (încercarea {attempt + 1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                else:
                    logger.error(f"   ❌ Căutare web eșuată după {MAX_RETRIES} încercări")
                    return False, "search_error"

            except Exception as e:
                logger.error(f"   ❌ Eroare neașteptată la căutarea web: {e}")
                return False, "search_error"

    def check_folder_with_chrome(self, folder_info: Dict[str, Any]) -> bool:
        """NIVEL 2: Verifică prin simularea upload-ului Chrome (fallback)"""
        folder_path = folder_info["folder_path"]
        priority_file = folder_info["priority_file"]

        logger.info(f"🔧 NIVEL 2 - Chrome simulation pentru: {folder_path.name}")

        # Asigură-te că Chrome este conectat
        if not self.setup_chrome_driver():
            logger.error("❌ Nu pot conecta la Chrome pentru fallback")
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

            # Închide tab-ul
            self.close_current_tab_and_return_to_base()

            if is_duplicate:
                logger.info("🎯 DUPLICAT CONFIRMAT prin Chrome simulation!")
                return True
            else:
                logger.info("✅ Nu e duplicat conform Chrome simulation")
                return False

        except Exception as e:
            logger.error(f"❌ Eroare la Chrome simulation: {e}")

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
                if self.driver and self.driver.window_handles:
                    self.driver.switch_to.window(self.driver.window_handles[0])
                    self.base_window = self.driver.current_window_handle
            except:
                pass

    def check_folder_hybrid(self, folder_info: Dict[str, Any]) -> bool:
        """Verifică un folder folosind strategia hibridă (fast search + Chrome fallback)"""
        folder_path = folder_info["folder_path"]

        logger.info(f"\n📂 Verific folderul: {folder_path.name}")
        logger.info(f"📄 Titlu căutare: {folder_info['search_title']}")

        # Sari peste folderele deja procesate
        folder_str = str(folder_path)
        if folder_str in self.state["processed_folders"]:
            logger.info(f"⏭️ Folder deja procesat, sar peste")
            return False

        try:
            # NIVEL 1: Căutare rapidă pe archive.org/search
            is_duplicate, method = self.search_archive_org_web(folder_info)

            if is_duplicate and method == "fast_search":
                logger.info("🎯 DUPLICAT DETECTAT prin căutare rapidă!")
                self.fast_search_hits += 1
                self.delete_folder(folder_info, "Duplicat găsit prin căutare rapidă")
                return True

            elif method in ["no_results", "single_result"]:
                # NIVEL 2: Chrome simulation pentru confirmare
                logger.info("🔧 Trec la Chrome simulation pentru confirmare...")
                self.chrome_fallback_used += 1

                is_duplicate_chrome = self.check_folder_with_chrome(folder_info)

                if is_duplicate_chrome:
                    logger.info("🎯 DUPLICAT CONFIRMAT prin Chrome simulation!")
                    self.delete_folder(folder_info, "Duplicat confirmat prin Chrome simulation")
                    return True
                else:
                    logger.info("✅ NU e duplicat - păstrez folderul")
                    # Marchează ca procesat
                    self.state["processed_folders"].append(folder_str)
                    self.checked_count += 1
                    self.state["stats"]["total_checked"] += 1
                    return False

            elif method == "search_error":
                logger.warning("⚠️ Eroare la căutarea web - încerc Chrome simulation...")
                self.chrome_fallback_used += 1

                is_duplicate_chrome = self.check_folder_with_chrome(folder_info)

                if is_duplicate_chrome:
                    self.delete_folder(folder_info, "Duplicat găsit prin Chrome simulation (după eroare search)")
                    return True
                else:
                    # Marchează ca procesat
                    self.state["processed_folders"].append(folder_str)
                    self.checked_count += 1
                    self.state["stats"]["total_checked"] += 1
                    return False

            else:
                logger.warning(f"⚠️ Rezultat neașteptat: {method}")
                return False

        except Exception as e:
            logger.error(f"❌ Eroare la verificarea folderului {folder_path.name}: {e}")
            self.error_count += 1
            return False

    def delete_folder(self, folder_info: Dict[str, Any], reason: str):
        """Șterge folderul cu duplicat"""
        folder_path = folder_info["folder_path"]

        try:
            logger.warning(f"🗑️ Șterg folderul duplicat: {folder_path}")
            logger.info(f"   Motiv: {reason}")

            # Calculează spațiul eliberat
            size_mb = folder_info.get('total_size', 0) / (1024 * 1024)

            # Creează backup info
            backup_info = {
                "folder": str(folder_path),
                "priority_file": str(folder_info["priority_file"]),
                "search_title": folder_info["search_title"],
                "all_files": [str(f) for f in folder_info["all_files"]],
                "size_mb": round(size_mb, 2),
                "deleted_at": datetime.now().isoformat(),
                "reason": reason
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
            "📊 RAPORT FINAL - Hybrid Archive Checker",
            "=" * 60,
            f"✅ Foldere verificate: {self.checked_count}",
            f"🗑️ Foldere șterse (duplicate): {self.deleted_count}",
            f"❌ Erori întâmpinate: {self.error_count}",
            f"💾 Spațiu eliberat în această sesiune: {sum(f.get('size_mb', 0) for f in self.state['deleted_folders'][-self.deleted_count:]):.2f} MB",
            "",
            "📈 STATISTICI METODE:",
            f"⚡ Căutări rapide cu succes: {self.fast_search_hits}",
            f"🔧 Chrome simulation folosit: {self.chrome_fallback_used}",
            f"📊 Eficiență căutare rapidă: {(self.fast_search_hits / max(self.checked_count + self.deleted_count, 1)) * 100:.1f}%",
            "",
            f"📈 STATISTICI TOTALE:",
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
                logger.info(f"      Titlu: {folder_info.get('search_title', 'N/A')}")
                logger.info(f"      Motiv: {folder_info.get('reason', 'N/A')}")
                logger.info(f"      Spațiu eliberat: {folder_info.get('size_mb', 0):.2f} MB")

    def run(self):
        """Rulează procesul principal"""
        logger.info("=" * 60)
        logger.info("🚀 START - Archive.org Hybrid Duplicate Checker")
        logger.info(f"📁 Folder verificat: {ARCHIVE_PATH}")
        logger.info("⚡ Strategia hibridă: Căutare rapidă + Chrome fallback")
        logger.info("=" * 60)

        # Verifică folderul sursă
        if not ARCHIVE_PATH.exists():
            logger.error(f"❌ Folderul {ARCHIVE_PATH} nu există!")
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
                    self.check_folder_hybrid(folder_info)

                    # Pauză între verificări
                    if i < len(folders_to_check):
                        logger.info("⏳ Pauză 2 secunde...")
                        time.sleep(2)

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
            # Cleanup Chrome
            if self.driver:
                try:
                    # Închide toate tab-urile deschise de script
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

                    logger.info("🧹 Chrome cleanup completat")
                except Exception as cleanup_error:
                    logger.warning(f"⚠️ Eroare la cleanup: {cleanup_error}")


def main():
    """Funcția principală"""
    try:
        checker = ArchiveHybridChecker()
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