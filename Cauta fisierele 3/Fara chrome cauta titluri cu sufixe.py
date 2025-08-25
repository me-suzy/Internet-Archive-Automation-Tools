#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Internet Archive Duplicate Checker - Pure Web Method (No Chrome Required)
Detectează duplicate pe Archive.org folosind doar HTTP requests și parsing HTML.

Strategiile de detectare:
1. Căutare multiplă pe archive.org/search cu variante de titluri
2. Căutare directă pe pattern-uri de identifier-uri cu wildcard
3. Test direct de existență URL pentru sufixe comune

AVANTAJE:
- Nu necesită Chrome sau Selenium
- Mult mai rapid decât simularea upload
- Funcționează pe orice sistem
- Detectare inteligentă a duplicatelor
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
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

# ============= CONFIGURĂRI =============
ARCHIVE_PATH = Path(r"g:\ARHIVA\C")
SEARCH_BASE_URL = "https://archive.org/search"
DETAILS_BASE_URL = "https://archive.org/details"
API_BASE_URL = "https://archive.org/advancedsearch.php"

STATE_FILE = Path("archive_duplicate_pure_web_state.json")
LOG_FILE = Path(f"archive_duplicate_web_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

# Extensii prioritare pentru verificare (în ordinea priorității)
PRIORITY_EXTENSIONS = ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc', '.lit', '.rtf']

# Extensii de ignorat
IGNORE_EXTENSIONS = ['.jpg', '.png']

# Configurare requests
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15
DELAY_BETWEEN_REQUESTS = 1.5  # Secunde între requests pentru a nu suprasolicita serverul

# Sufixe comune de duplicate de testat
COMMON_DUPLICATE_SUFFIXES = [
    '_202508', '_20250806', '_202507', '_20250705', '_202506', '_20250604',
    '_202505', '_20250503', '_202504', '_20250402', '_202503', '_20250301',
    '_202502', '_20250201', '_202501', '_20250101', '_202412', '_20241201'
]

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
logger = logging.getLogger("ArchivePureWebChecker")


class ArchivePureWebChecker:
    def __init__(self):
        self.state = self.load_state()
        self.deleted_count = 0
        self.checked_count = 0
        self.error_count = 0

        # Statistici metode
        self.search_hits = 0
        self.api_hits = 0
        self.url_test_hits = 0

        # Session pentru requests cu retry și headers
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        # Adapter cu retry strategy
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

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
                "search_hits": 0,
                "api_hits": 0,
                "url_test_hits": 0
            }
        }

        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                    # Compatibilitate cu versiuni anterioare
                    for key in default_state:
                        if key not in state:
                            state[key] = default_state[key]

                    for key in default_state["stats"]:
                        if key not in state["stats"]:
                            state["stats"][key] = default_state["stats"][key]

                    logger.info(f"📋 Stare încărcată: {len(state.get('processed_folders', []))} foldere procesate anterior")
                    return state
            except Exception as e:
                logger.warning(f"⚠️ Nu s-a putut încărca starea: {e}")

        return default_state

    def save_state(self):
        """Salvează starea curentă"""
        self.state["last_processed"] = datetime.now().isoformat()
        self.state["stats"]["search_hits"] = self.search_hits
        self.state["stats"]["api_hits"] = self.api_hits
        self.state["stats"]["url_test_hits"] = self.url_test_hits

        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            logger.debug("💾 Stare salvată cu succes")
        except Exception as e:
            logger.error(f"❌ Eroare la salvarea stării: {e}")

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

    def generate_identifier_base(self, title: str) -> str:
        """Generează base identifier-ul așa cum l-ar genera Archive.org"""
        # Începe cu titlul
        identifier = title.lower()

        # Înlocuiește toate caracterele non-alfanumerice cu liniuțe
        identifier = re.sub(r'[^a-z0-9\s\.]', '-', identifier)

        # Înlocuiește spațiile cu liniuțe
        identifier = re.sub(r'\s+', '-', identifier)

        # Curăță liniuțele multiple
        identifier = re.sub(r'-+', '-', identifier)

        # Elimină liniuțele de la început și sfârșit
        identifier = identifier.strip('-')

        # Limitează lungimea (Archive.org are limite)
        if len(identifier) > 80:
            words = identifier.split('-')
            result_parts = []
            current_length = 0

            for word in words:
                if current_length + len(word) + 1 <= 80:  # +1 pentru liniuță
                    result_parts.append(word)
                    current_length += len(word) + 1
                else:
                    break

            identifier = '-'.join(result_parts)

        logger.debug(f"🔧 Base identifier generat: {identifier}")
        return identifier

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

                # Generează titlurile pentru căutare
                search_title = self.clean_title_for_search(priority_file.name)
                identifier_base = self.generate_identifier_base(search_title)

                folders_to_check.append({
                    "folder_path": folder_path,
                    "priority_file": priority_file,
                    "all_files": relevant_files,
                    "total_size": total_size,
                    "search_title": search_title,
                    "identifier_base": identifier_base
                })

                logger.debug(f"📁 {folder_path.name}: titlu='{search_title}', identifier='{identifier_base}'")

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

    def method_1_search_duplicates(self, folder_info: Dict[str, Any]) -> Tuple[bool, str]:
        """METODA 1: Căutare pe archive.org/search pentru duplicate"""
        search_title = folder_info["search_title"]

        logger.info(f"🔍 METODA 1 - Căutare duplicate pentru: {search_title}")

        # Construiește URL-ul de căutare
        query = quote_plus(search_title)
        search_url = f"{SEARCH_BASE_URL}?query={query}"

        logger.debug(f"🌐 URL căutare: {search_url}")

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
                        logger.info(f"   🎯 DUPLICAT GĂSIT prin căutare!")
                        logger.info(f"      Titlu duplicat: {title} (apare de {count} ori)")
                        return True, "search_duplicate"

            logger.info(f"   ✅ Un singur rezultat găsit - nu sunt duplicate evidente")
            return False, "single_result"

        except requests.RequestException as e:
            logger.warning(f"   ⚠️ Eroare la căutarea web: {e}")
            return False, "search_error"
        except Exception as e:
            logger.error(f"   ❌ Eroare neașteptată la căutarea web: {e}")
            return False, "search_error"

    def method_2_api_identifier_search(self, folder_info: Dict[str, Any]) -> Tuple[bool, str]:
        """METODA 2: Căutare prin API pentru identifier-uri cu sufixe"""
        identifier_base = folder_info["identifier_base"]

        logger.info(f"🔍 METODA 2 - Căutare API identifier pentru: {identifier_base}*")

        # Căutare prin API pentru identifier-uri care încep cu base-ul nostru
        params = {
            "q": f'identifier:({identifier_base}*)',
            "fl[]": "identifier",
            "rows": 100,
            "output": "json"
        }

        try:
            response = self.session.get(API_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            data = response.json()
            response_data = data.get("response", {})
            num_found = response_data.get("numFound", 0)
            docs = response_data.get("docs", [])

            if num_found == 0:
                logger.info(f"   ℹ️ Niciun identifier găsit pentru pattern-ul '{identifier_base}*'")
                return False, "no_identifiers"

            logger.info(f"   📊 Găsite {num_found} identifier-uri:")

            # Verifică fiecare identifier pentru sufixe duplicate
            found_duplicates = []
            for doc in docs:
                identifier = doc.get("identifier", "")
                logger.info(f"      - {identifier}")

                # Verifică dacă are sufixe de dată
                if re.search(r'_\d{6}$|_\d{8}$', identifier):
                    found_duplicates.append(identifier)
                    logger.info(f"        🎯 SUFIX DUPLICAT DETECTAT!")

            if found_duplicates:
                logger.info(f"   ✅ DUPLICATE GĂSITE prin API: {len(found_duplicates)} identifier-uri cu sufixe")
                for dup in found_duplicates[:3]:  # Afișează primele 3
                    logger.info(f"      🔸 {dup}")
                return True, "api_duplicate"
            else:
                logger.info(f"   ✅ Identifier-uri găsite dar fără sufixe duplicate")
                return False, "no_suffix_duplicates"

        except requests.RequestException as e:
            logger.warning(f"   ⚠️ Eroare la API search: {e}")
            return False, "api_error"
        except Exception as e:
            logger.error(f"   ❌ Eroare neașteptată la API search: {e}")
            return False, "api_error"

    def method_3_direct_url_test(self, folder_info: Dict[str, Any]) -> Tuple[bool, str]:
        """METODA 3: Test direct de existență URL pentru sufixe comune"""
        identifier_base = folder_info["identifier_base"]

        logger.info(f"🔍 METODA 3 - Test direct URL pentru: {identifier_base}")

        found_urls = []

        # Testează sufixele comune de duplicate
        for suffix in COMMON_DUPLICATE_SUFFIXES[:8]:  # Testează primele 8 sufixe
            test_identifier = f"{identifier_base}{suffix}"
            test_url = f"{DETAILS_BASE_URL}/{test_identifier}"

            logger.debug(f"   🔗 Testez: {test_url}")

            try:
                # HEAD request pentru a nu descărca conținutul
                response = self.session.head(test_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)

                if response.status_code == 200:
                    logger.info(f"   🎯 URL EXISTENT: {test_identifier}")
                    found_urls.append(test_identifier)
                elif response.status_code == 404:
                    logger.debug(f"   ❌ Nu există: {test_identifier}")
                else:
                    logger.debug(f"   ⚠️ Status {response.status_code}: {test_identifier}")

            except requests.RequestException as e:
                logger.debug(f"   ❌ Eroare pentru {test_identifier}: {e}")

            # Mică pauză între teste
            time.sleep(0.3)

        if found_urls:
            logger.info(f"   ✅ DUPLICATE GĂSITE prin test URL: {len(found_urls)} URL-uri existente")
            for url in found_urls[:3]:  # Afișează primele 3
                logger.info(f"      🔸 {url}")
            return True, "url_duplicate"
        else:
            logger.info(f"   ✅ Niciun URL duplicat găsit prin test direct")
            return False, "no_url_duplicates"

    def check_folder_web_only(self, folder_info: Dict[str, Any]) -> bool:
        """Verifică un folder folosind doar metodele web (fără Chrome)"""
        folder_path = folder_info["folder_path"]

        logger.info(f"\n📂 Verific folderul: {folder_path.name}")
        logger.info(f"📄 Titlu căutare: {folder_info['search_title']}")
        logger.info(f"🔗 Base identifier: {folder_info['identifier_base']}")

        # Sari peste folderele deja procesate
        folder_str = str(folder_path)
        if folder_str in self.state["processed_folders"]:
            logger.info(f"⏭️ Folder deja procesat, sar peste")
            return False

        try:
            # METODA 1: Căutare pe archive.org/search
            is_duplicate, method = self.method_1_search_duplicates(folder_info)

            if is_duplicate and method == "search_duplicate":
                logger.info("🎯 DUPLICAT DETECTAT prin căutare web!")
                self.search_hits += 1
                self.delete_folder(folder_info, "Duplicat găsit prin căutare web")
                return True

            time.sleep(DELAY_BETWEEN_REQUESTS)  # Pauză între metode

            # METODA 2: Căutare prin API pentru identifier-uri
            is_duplicate, method = self.method_2_api_identifier_search(folder_info)

            if is_duplicate and method == "api_duplicate":
                logger.info("🎯 DUPLICAT DETECTAT prin API identifier!")
                self.api_hits += 1
                self.delete_folder(folder_info, "Duplicat găsit prin API identifier")
                return True

            time.sleep(DELAY_BETWEEN_REQUESTS)  # Pauză între metode

            # METODA 3: Test direct URL
            is_duplicate, method = self.method_3_direct_url_test(folder_info)

            if is_duplicate and method == "url_duplicate":
                logger.info("🎯 DUPLICAT DETECTAT prin test direct URL!")
                self.url_test_hits += 1
                self.delete_folder(folder_info, "Duplicat găsit prin test direct URL")
                return True

            # Dacă nicio metodă nu a găsit duplicate
            logger.info("✅ NU sunt duplicate detectate - păstrez folderul")

            # Marchează ca procesat
            self.state["processed_folders"].append(folder_str)
            self.checked_count += 1
            self.state["stats"]["total_checked"] += 1

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
                "identifier_base": folder_info["identifier_base"],
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
                self.state["stats"] = {
                    "total_checked": 0, "total_deleted": 0, "total_space_saved_mb": 0.0,
                    "search_hits": 0, "api_hits": 0, "url_test_hits": 0
                }

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
        total_processed = self.checked_count + self.deleted_count

        report_lines = [
            "\n" + "=" * 60,
            "📊 RAPORT FINAL - Pure Web Archive Checker",
            "=" * 60,
            f"✅ Foldere verificate: {self.checked_count}",
            f"🗑️ Foldere șterse (duplicate): {self.deleted_count}",
            f"❌ Erori întâmpinate: {self.error_count}",
            f"💾 Spațiu eliberat în această sesiune: {sum(f.get('size_mb', 0) for f in self.state['deleted_folders'][-self.deleted_count:]):.2f} MB",
            "",
            "📈 STATISTICI METODE DETECTARE:",
            f"🔍 Duplicate găsite prin căutare web: {self.search_hits}",
            f"🔧 Duplicate găsite prin API identifier: {self.api_hits}",
            f"🌐 Duplicate găsite prin test direct URL: {self.url_test_hits}",
            "",
            "📊 EFICIENȚĂ METODE:",
            f"🔍 Căutare web: {(self.search_hits / max(total_processed, 1)) * 100:.1f}%",
            f"🔧 API identifier: {(self.api_hits / max(total_processed, 1)) * 100:.1f}%",
            f"🌐 Test direct URL: {(self.url_test_hits / max(total_processed, 1)) * 100:.1f}%",
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
        logger.info("🚀 START - Archive.org Pure Web Duplicate Checker")
        logger.info(f"📁 Folder verificat: {ARCHIVE_PATH}")
        logger.info("⚡ Metodă: 100% Web-based (fără Chrome)")
        logger.info("🔍 3 strategii: Search web + API identifier + Test direct URL")
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
                    self.check_folder_web_only(folder_info)

                    # Pauză între verificări pentru a nu suprasolicita serverul
                    if i < len(folders_to_check):
                        logger.info(f"⏳ Pauză {DELAY_BETWEEN_REQUESTS} secunde...")
                        time.sleep(DELAY_BETWEEN_REQUESTS)

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


def main():
    """Funcția principală"""
    try:
        checker = ArchivePureWebChecker()
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