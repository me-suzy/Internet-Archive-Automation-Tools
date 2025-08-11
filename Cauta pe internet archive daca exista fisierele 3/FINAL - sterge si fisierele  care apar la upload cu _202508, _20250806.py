#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pentru verificarea și ștergerea automată a folderelor
care conțin fișiere deja prezente pe Internet Archive.
Folosește API-ul JSON al Archive.org pentru verificare rapidă.

Șterge fișierul archive_cleanup_state.json înainte de a rula scriptul, sau adaugă această funcție și apeleaz-o:

de ce nu imi spui niciodata unde anume sa adaug bucatile de cod? Daca este o functie noua care nu exista in codul precedent, si deci nu am cum sa o caut ni cod, te rog frumos sa imi spui unde anume sa o adaug in cod. DUpa ce linie sau intre ce linii, sau dupa ce functie sau intre ce functiii.
foarte bine. Pe viitor sa scrii functia noua, si sa-mi spui ca aici: Adaugă funcția  def reset_all_state(self): - imediat DUPĂ funcția save_state și ÎNAINTE de funcția clean_title_for_search . Asa e cel mai usor de inteles. Dar daca imi dau sa adaug linii noi intr-o functie, imi spui exact intre ce linii sa introduc acele linii noi, sau de unde pana unde trebuie sa le inlocuiesc.
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

# ============= CONFIGURĂRI =============
ARCHIVE_PATH = Path(r"g:\ARHIVA\B")
DELAY_BETWEEN_SEARCHES = 2  # secunde între căutări pentru a nu suprasolicita serverul
STATE_FILE = Path("archive_cleanup_state.json")
LOG_FILE = Path(f"archive_cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
RELEVANT_EXTENSIONS = ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc', '.lit', '.rtf']
MAX_API_ATTEMPTS = 3
API_TIMEOUT = 15

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
logger = logging.getLogger("ArchiveDuplicateChecker")


class ArchiveDuplicateChecker:
    def __init__(self):
        self.state = self.load_state()
        self.deleted_count = 0
        self.checked_count = 0
        self.error_count = 0
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ArchiveDuplicateChecker/1.0 (Python Script)'
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
                "total_space_saved_mb": 0.0
            }
        }

        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                    # IMPORTANT: Asigură compatibilitate cu versiuni anterioare
                    # Adaugă cheile lipsă din starea veche
                    if "deleted_folders" not in state:
                        state["deleted_folders"] = []

                    if "stats" not in state:
                        state["stats"] = default_state["stats"]

                    if "processed_folders" not in state:
                        state["processed_folders"] = []

                    if "last_processed" not in state:
                        state["last_processed"] = None

                    logger.info(f"📋 Stare încărcată: {len(state.get('processed_folders', []))} foldere procesate anterior")
                    return state
            except Exception as e:
                logger.warning(f"⚠️ Nu s-a putut încărca starea: {e}")
                logger.info("📝 Creez o stare nouă...")

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

    def reset_all_state(self):
        """Resetează complet toată starea salvată"""
        logger.warning("🔄 RESETARE COMPLETĂ A STĂRII!")
        self.state = {
            "processed_folders": [],
            "deleted_folders": [],
            "last_processed": None,
            "stats": {
                "total_checked": 0,
                "total_deleted": 0,
                "total_space_saved_mb": 0.0
            }
        }
        self.save_state()


    def clean_title_for_search(self, filename: str) -> str:
        """
        Curăță numele fișierului pentru căutare pe Internet Archive:
        - Elimină extensia
        - Elimină versiunile (v.0.9, v.0.9.8.5-161, v.0.9.8 MMXII, etc.)
        - Elimină sufixele (scan, ctrl, retail, cop1, etc.)
        - Elimină parantezele și conținutul lor
        - Elimină numerele de la început din titlu
        - Păstrează doar formatul "Nume, Prenume - Titlu"
        """
        # Elimină extensia
        name = Path(filename).stem

        logger.debug(f"🔧 Curățare titlu original: {filename}")

        # Elimină sufixele de tipul _202508, _20250804, etc.
        name = re.sub(r'[_-]\d{6,8}$', '', name)

        # Elimină parantezele rotunde și tot conținutul lor
        name = re.sub(r'\s*\([^)]*\)', '', name)

        # Elimină și parantezele pătrate dacă există
        name = re.sub(r'\s*\[[^\]]*\]', '', name)

        # Elimină versiunile complexe care pot apărea după " - "
        # Acoperă: v.0.9, v.0.9.8.5-161, v.0.9.8 MMXII, v.1.0, etc.
        name = re.sub(r'\s*[-–]\s*[vV]\.?\s*[\d\.]+[\d\.\-]*(?:\s+[A-Z]+)?(?:\s*[-–]\s*\d+)?$', '', name)

        # Elimină versiunile care pot apărea și fără liniuță înainte
        name = re.sub(r'\s+[vV]\.?\s*[\d\.]+[\d\.\-]*(?:\s+[A-Z]+)?$', '', name)

        # Lista completă de sufixe de eliminat
        suffixes_to_remove = [
            'scan', 'ctrl', 'retail', r'cop\d+', 'Vp', 'draft', 'final',
            'ocr', 'OCR', 'edit', 'edited', 'rev', 'revised', 'proof',
            'beta', 'alpha', 'test', 'demo', 'sample', 'preview',
            'full', 'complete', 'fix', 'fixed', 'corrected'
        ]

        # Construiește pattern-ul pentru toate sufixele
        suffix_pattern = '|'.join(suffixes_to_remove)

        # Elimină sufixele care apar după ultima " - "
        parts = name.rsplit(' - ', 1)
        if len(parts) == 2:
            last_part = parts[1].strip()
            if re.match(f'^({suffix_pattern})$', last_part, re.IGNORECASE):
                name = parts[0]

        # Elimină numerele de la început din titlu (ex: "4. Comosicus" -> "Comosicus")
        if ' - ' in name:
            parts = name.split(' - ', 1)
            if len(parts) == 2:
                # Curăță partea de titlu de numere de la început
                title = re.sub(r'^\d+\.\s*', '', parts[1])
                name = f"{parts[0]} - {title}"

        # Curăță spațiile multiple și spațiile de la început/sfârșit
        name = re.sub(r'\s+', ' ', name).strip()

        # Elimină eventuale liniuțe rămase la sfârșit
        name = re.sub(r'\s*[-–]\s*$', '', name)

        logger.debug(f"✨ Titlu curățat: {name}")

        return name

    def extract_base_name_for_identifier(self, title: str) -> List[str]:
        """Extrage pattern-uri simple și scurte pentru căutarea identifier-urilor pe Archive.org"""
        base_names = []

        # Începe cu titlul original
        working_title = title.lower()

        # Curăță și generează base name
        clean_name = re.sub(r'[^a-z0-9\s\.]', ' ', working_title)
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()
        clean_name = clean_name.replace(' ', '-')

        # Eliminăm sufixele cunoscute pentru a avea un base name curat
        clean_name = re.sub(r'-(retail|scan|ctrl|cop\d+|v\d+.*?)$', '', clean_name)
        clean_name = re.sub(r'-#\w+$', '', clean_name)  # Elimină #ISTOR, etc.

        words = clean_name.split('-')

        # Genereaza variante de căutare începând cu cele mai simple
        # Pattern 1: Doar autorul (primele 2 cuvinte)
        if len(words) >= 2:
            base_names.append(f"{words[0]}-{words[1]}")

        # Pattern 2: Autor + primul cuvânt din titlu (primele 3-4 cuvinte)
        for i in range(3, min(6, len(words) + 1)):
            pattern = '-'.join(words[:i])
            base_names.append(pattern)

        # Pattern 3: Variante mai lungi, dar nu peste 50 de caractere
        for length in [30, 40, 50, 60]:
            if len(clean_name) > length:
                # Găsește ultima liniuță înainte de lungimea specificată
                truncated = clean_name[:length]
                last_dash = truncated.rfind('-')
                if last_dash > length - 10:  # Dacă liniuța e aproape de sfârșit
                    truncated = truncated[:last_dash]
                base_names.append(truncated)

        # Elimină duplicatele și păstrează ordinea
        unique_names = []
        for name in base_names:
            if name and name not in unique_names and len(name) >= 10:  # Minim 10 caractere
                unique_names.append(name)

        logger.debug(f"🔧 Pattern-uri de căutare generate: {unique_names}")
        return unique_names

    def scan_folders(self) -> List[Dict[str, Any]]:
        """Scanează recursiv toate folderele și returnează lista de fișiere de verificat"""
        tasks = []
        logger.info(f"📂 Scanez folderul: {ARCHIVE_PATH}")

        try:
            for root, dirs, files in os.walk(ARCHIVE_PATH):
                folder = Path(root)

                # Găsește fișierele relevante
                relevant_files = []
                for file in files:
                    if Path(file).suffix.lower() in RELEVANT_EXTENSIONS:
                        file_path = folder / file
                        relevant_files.append(file_path)

                if not relevant_files:
                    continue

                logger.debug(f"📁 Folder {folder.name}: {len(relevant_files)} fișiere relevante")

                # Grupează fișierele după numele principal (fără extensie și versiune)
                file_groups = {}
                for file_path in relevant_files:
                    clean_name = self.clean_title_for_search(file_path.name)
                    if clean_name not in file_groups:
                        file_groups[clean_name] = []
                    file_groups[clean_name].append(file_path)

                # Adaugă fiecare grup unic pentru verificare
                for clean_name, file_list in file_groups.items():
                    # Calculează dimensiunea totală
                    total_size = sum(f.stat().st_size for f in file_list if f.exists())

                    tasks.append({
                        "search_title": clean_name,
                        "folder": folder,
                        "files": file_list,
                        "size": total_size
                    })

            logger.info(f"📊 Găsite {len(tasks)} titluri unice de verificat")
            return tasks

        except Exception as e:
            logger.error(f"❌ Eroare la scanarea folderelor: {e}")
            return []

    def check_archive_api(self, title: str) -> bool:
        """Verifică dacă un titlu există pe Internet Archive folosind API-ul JSON și căutare după identifier"""

        # Primul pas: căutare normală după titlu
        if self._search_by_title(title):
            return True

        # Al doilea pas: căutare după identifier cu sufixe duplicate
        if self.check_for_duplicate_identifiers(title):
            return True

        return False

    def _search_by_title(self, title: str) -> bool:
        """Căutare normală după titlu (funcția originală)"""
        url = "https://archive.org/advancedsearch.php"

        # Pregătește parametrii pentru API
        params = {
            "q": f'title:("{title}")',  # Căutare exactă cu ghilimele
            "fl[]": ["identifier", "title"],  # Returnează ID și titlu
            "rows": 10,  # Verifică primele 10 rezultate
            "output": "json",
            "sort": "downloads desc"  # Sortează după popularitate
        }

        logger.info(f"🔍 Caut pe Archive.org: '{title}'")
        logger.debug(f"   URL: {url}")
        logger.debug(f"   Parametri: {params}")

        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                response = self.session.get(url, params=params, timeout=API_TIMEOUT)
                response.raise_for_status()

                data = response.json()
                response_data = data.get("response", {})
                num_found = response_data.get("numFound", 0)
                docs = response_data.get("docs", [])

                logger.debug(f"   📊 Rezultate găsite: {num_found}")

                if num_found > 0:
                    # Verifică dacă vreun rezultat se potrivește
                    for doc in docs:
                        doc_title = doc.get("title", "")
                        doc_id = doc.get("identifier", "")

                        # Curăță și titlul din rezultat pentru comparație
                        clean_doc_title = self.clean_title_for_search(doc_title)

                        # Normalizează pentru comparație
                        search_normalized = re.sub(r'[^a-z0-9\s]', '', title.lower())
                        search_normalized = re.sub(r'\s+', ' ', search_normalized).strip()

                        doc_normalized = re.sub(r'[^a-z0-9\s]', '', clean_doc_title.lower())
                        doc_normalized = re.sub(r'\s+', ' ', doc_normalized).strip()

                        # Verifică similaritatea
                        if self.are_titles_similar(search_normalized, doc_normalized):
                            logger.info(f"   ✅ GĂSIT pe Archive.org prin căutare după titlu!")
                            logger.info(f"      ID: {doc_id}")
                            logger.info(f"      Titlu: {doc_title}")
                            return True

                    logger.info(f"   ❌ Nu s-a găsit potrivire exactă după titlu dintre {num_found} rezultate")
                else:
                    logger.info(f"   ℹ️ Niciun rezultat găsit după titlu")

                return False

            except requests.RequestException as e:
                logger.warning(f"   ⚠️ Eroare API la căutare titlu (încercarea {attempt}/{MAX_API_ATTEMPTS}): {e}")
                if attempt < MAX_API_ATTEMPTS:
                    time.sleep(2 ** attempt)
            except json.JSONDecodeError as e:
                logger.error(f"   ❌ Eroare la parsarea răspunsului JSON: {e}")
                return False

        logger.error(f"   ❌ Căutare titlu eșuată după {MAX_API_ATTEMPTS} încercări")
        return False

    def are_titles_similar(self, title1: str, title2: str) -> bool:
        """Verifică dacă două titluri sunt similare (tolerant la mici diferențe)"""
        # Elimină toate spațiile pentru comparație
        t1 = title1.replace(" ", "")
        t2 = title2.replace(" ", "")

        # Verifică egalitate exactă
        if t1 == t2:
            return True

        # Verifică dacă unul este conținut în celălalt
        if len(t1) > 3 and len(t2) > 3:  # Minim 4 caractere
            if t1 in t2 or t2 in t1:
                return True

        # Verifică dacă toate cuvintele din titlul căutat sunt în rezultat
        words1 = set(title1.split())
        words2 = set(title2.split())

        # Elimină cuvintele scurte (articole, prepoziții)
        words1 = {w for w in words1 if len(w) > 2}
        words2 = {w for w in words2 if len(w) > 2}

        if words1 and words2:
            # Verifică dacă cel puțin 80% din cuvinte se potrivesc
            common_words = words1.intersection(words2)
            if len(common_words) / len(words1) >= 0.8:
                return True

        return False

    def check_for_duplicate_identifiers(self, title: str) -> bool:
        """Verifică dacă există identifier-uri cu sufixe duplicate pe Internet Archive"""

        # Primul pas: generez identifier-ul probabil și testez direct URL-ul
        base_names = self.extract_base_name_for_identifier(title)

        if base_names:
            # Iau cel mai lung base name și testez cu sufixe comune
            primary_base = base_names[-1]  # Cel mai lung/detaliat

            # Testez sufixe comune de duplicate
            common_suffixes = ['_202508', '_20250806', '_202507', '_20250805', '_202506']

            logger.info(f"🎯 TESTEZ DIRECT URL-uri pentru sufixe duplicate:")
            for suffix in common_suffixes:
                test_identifier = f"{primary_base}{suffix}"
                archive_url = f"https://archive.org/details/{test_identifier}"

                logger.info(f"   🔗 Testez: {test_identifier}")

                try:
                    response = self.session.head(archive_url, timeout=8, allow_redirects=True)

                    if response.status_code == 200:
                        logger.info(f"   ✅ GĂSIT DUPLICAT prin URL direct!")
                        logger.info(f"      URL existent: {archive_url}")
                        logger.info(f"      Status: {response.status_code}")
                        return True
                    elif response.status_code == 404:
                        logger.debug(f"   ❌ NU există: {test_identifier}")
                    else:
                        logger.debug(f"   ⚠️ Status {response.status_code} pentru: {test_identifier}")

                except requests.RequestException as e:
                    logger.debug(f"   ❌ Eroare pentru {test_identifier}: {e}")

                time.sleep(0.5)  # Pauză între teste

        # Al doilea pas: căutare prin API (ca înainte) - doar dacă testul direct a eșuat
        logger.info(f"🔍 Testez și prin API-ul de căutare...")

        if not base_names:
            logger.debug("   ⚠️ Nu s-au putut extrage base names pentru identifier")
            return False

        url = "https://archive.org/advancedsearch.php"

        # Testez doar primele 3 pattern-uri pentru a fi mai rapid
        for i, base_name in enumerate(base_names[:3], 1):
            logger.debug(f"   🔍 API pattern {i}/3: '{base_name}*'")

            params = {
                "q": f'identifier:({base_name}*)',
                "fl[]": ["identifier"],
                "rows": 50,
                "output": "json"
            }

            try:
                response = self.session.get(url, params=params, timeout=API_TIMEOUT)
                response.raise_for_status()

                data = response.json()
                response_data = data.get("response", {})
                num_found = response_data.get("numFound", 0)
                docs = response_data.get("docs", [])

                if num_found > 0:
                    logger.debug(f"      📊 Găsite {num_found} identifier-uri prin API")
                    for doc in docs:
                        identifier = doc.get("identifier", "")
                        if self._has_date_suffix(identifier):
                            logger.info(f"   ✅ GĂSIT DUPLICAT prin API!")
                            logger.info(f"      Identifier cu sufix: {identifier}")
                            return True
                else:
                    logger.debug(f"      ℹ️ Niciun rezultat prin API pentru '{base_name}*'")

            except Exception as e:
                logger.debug(f"      ❌ Eroare API pentru pattern {i}: {e}")

            time.sleep(0.5)

        logger.info(f"   ❌ Nu s-au găsit duplicate prin nicio metodă")
        return False

    def _has_date_suffix(self, identifier: str) -> bool:
        """Verifică dacă un identifier are sufix de dată (indicând un duplicat)"""
        # Pattern-uri de sufixe care indică duplicate
        date_patterns = [
            r'_\d{6}$',          # _202508
            r'_\d{8}$',          # _20250806
            r'_\d{4}\d{2}$',     # _202508 (alt format)
            r'_\d{4}\d{2}\d{2}$' # _20250806 (alt format)
        ]

        for pattern in date_patterns:
            if re.search(pattern, identifier):
                logger.debug(f"      ✅ Sufix de dată găsit în '{identifier}': pattern {pattern}")
                return True

        return False

    def test_direct_search(self):
        """Test direct pentru identifier-ul cunoscut"""
        logger.info("🧪 TEST DIRECT - caut identifier-ul exact cunoscut:")

        # Testez direct dacă identifier-ul există
        test_identifier = "berthon-simon-razboi-intre-aliati.-povestea-rivalitatii-dintre-churchill-rooseve_202508"

        url = "https://archive.org/advancedsearch.php"
        params = {
            "q": f'identifier:({test_identifier})',
            "fl[]": ["identifier"],
            "rows": 1,
            "output": "json"
        }

        try:
            response = self.session.get(url, params=params, timeout=API_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            response_data = data.get("response", {})
            num_found = response_data.get("numFound", 0)
            docs = response_data.get("docs", [])

            logger.info(f"   🎯 Căutare directă pentru '{test_identifier[:50]}...': {num_found} rezultate")

            if docs:
                for doc in docs:
                    logger.info(f"      ✅ GĂSIT: {doc.get('identifier', '')}")
            else:
                logger.info(f"   ❌ Identifier-ul exact NU a fost găsit în Archive.org")
                logger.info(f"   💡 Probabil nu este încă indexat sau nu este public")

        except Exception as e:
            logger.error(f"   ❌ Eroare la testul direct: {e}")

    def test_direct_url_access(self):
        """Testez direct dacă URL-ul Archive.org răspunde (chiar dacă nu e în căutare)"""
        logger.info("🌐 TEST DIRECT URL - verific dacă pagina Archive.org existe:")

        test_identifier = "berthon-simon-razboi-intre-aliati.-povestea-rivalitatii-dintre-churchill-rooseve_202508"
        archive_url = f"https://archive.org/details/{test_identifier}"

        logger.info(f"   🔗 Testez URL-ul: {archive_url}")

        try:
            # Folosesc HEAD request pentru a nu descărca toată pagina
            response = self.session.head(archive_url, timeout=10, allow_redirects=True)

            logger.info(f"   📡 Status HTTP: {response.status_code}")
            logger.info(f"   📋 Headers: {dict(list(response.headers.items())[:5])}")  # Primele 5 header-uri

            if response.status_code == 200:
                logger.info(f"   ✅ URL-UL EXISTĂ pe Archive.org!")
                logger.info(f"   🎯 CONFIRMAT: Fișierul există în sistem (chiar dacă nu e în căutare publică)")
                return True
            elif response.status_code == 404:
                logger.info(f"   ❌ URL-ul NU există (404 Not Found)")
                return False
            else:
                logger.info(f"   ⚠️ Status neașteptat: {response.status_code}")
                return False

        except requests.RequestException as e:
            logger.error(f"   ❌ Eroare la testarea URL-ului: {e}")
            return False

    def _matches_duplicate_pattern(self, identifier: str, base_name: str) -> bool:
        """Verifică dacă un identifier se potrivește cu pattern-ul de duplicat"""
        # Verifică dacă identifier-ul începe cu base_name
        if not identifier.lower().startswith(base_name.lower()):
            return False

        # Extrage sufixul
        suffix = identifier[len(base_name):]

        # Verifică pattern-urile de duplicat
        # Pattern 1: _YYYYMM (ex: _202508)
        if re.match(r'^_\d{6}$', suffix):
            logger.debug(f"      ✅ Găsit pattern YYYYMM: {suffix}")
            return True

        # Pattern 2: _YYYYMMDD (ex: _20250806)
        if re.match(r'^_\d{8}$', suffix):
            logger.debug(f"      ✅ Găsit pattern YYYYMMDD: {suffix}")
            return True

        # Pattern 3: verifică și alte variante comune de duplicat
        # De exemplu: -v2, -copy, -duplicate, etc.
        duplicate_patterns = [
            r'^[-_]v\d+$',           # -v1, _v2, etc.
            r'^[-_]copy\d*$',        # -copy, _copy1, etc.
            r'^[-_]duplicate\d*$',   # -duplicate, _duplicate1, etc.
            r'^[-_]\d+$'             # -1, _2, etc.
        ]

        for pattern in duplicate_patterns:
            if re.match(pattern, suffix, re.IGNORECASE):
                logger.debug(f"      ✅ Găsit pattern duplicat: {suffix}")
                return True

        return False

    def delete_folder(self, task: Dict[str, Any]):
        """Șterge un folder și toate subfișierele sale"""
        folder = task['folder']

        # Determină ce folder să ștergem
        if folder.parent != ARCHIVE_PATH:
            folder_to_delete = folder.parent
        else:
            folder_to_delete = folder

        try:
            logger.warning(f"🗑️ Șterg folderul: {folder_to_delete}")
            logger.info(f"   Motivul: Fișierul '{task['search_title']}' există pe Archive.org")

            # Calculează spațiul eliberat (în MB)
            size_mb = task.get('size', 0) / (1024 * 1024)

            # Creează backup în state înainte de ștergere
            backup_info = {
                "folder": str(folder_to_delete),
                "title": task['search_title'],
                "files": [str(f) for f in task['files']],
                "size_mb": round(size_mb, 2),
                "deleted_at": datetime.now().isoformat()
            }

            # Șterge folderul
            shutil.rmtree(folder_to_delete)

            # Asigură că deleted_folders există înainte de a adăuga
            if "deleted_folders" not in self.state:
                self.state["deleted_folders"] = []

            # Actualizează statisticile
            self.state["deleted_folders"].append(backup_info)
            self.deleted_count += 1

            # Asigură că stats există
            if "stats" not in self.state:
                self.state["stats"] = {
                    "total_checked": 0,
                    "total_deleted": 0,
                    "total_space_saved_mb": 0.0
                }

            self.state["stats"]["total_deleted"] += 1
            self.state["stats"]["total_space_saved_mb"] = round(
                self.state["stats"]["total_space_saved_mb"] + size_mb, 2
            )

            logger.info(f"   ✅ Folder șters cu succes! ({size_mb:.2f} MB eliberat)")

            # Salvează starea imediat după ștergere
            self.save_state()

            return True

        except Exception as e:
            logger.error(f"   ❌ Eroare la ștergerea folderului: {e}")
            self.error_count += 1
            return False

    def reset_processed_folders(self):
        """Resetează lista de foldere procesate pentru a le verifica din nou"""
        logger.info("🔄 Resetez lista de foldere procesate pentru reverificare...")
        self.state["processed_folders"] = []
        self.save_state()

    def generate_report(self):
        """Generează un raport final detaliat"""
        report_lines = [
            "\n" + "=" * 60,
            "📊 RAPORT FINAL",
            "=" * 60,
            f"✅ Fișiere verificate: {self.checked_count}",
            f"🗑️ Foldere șterse: {self.deleted_count}",
            f"❌ Erori întâmpinate: {self.error_count}",
            f"💾 Spațiu total eliberat: {self.state['stats']['total_space_saved_mb']:.2f} MB",
            f"📈 Total istoric foldere șterse: {self.state['stats']['total_deleted']}",
            "=" * 60
        ]

        for line in report_lines:
            logger.info(line)

        if self.state["deleted_folders"]:
            logger.info("\n📋 FOLDERE ȘTERSE ÎN ACEASTĂ SESIUNE:")
            for i, folder_info in enumerate(self.state["deleted_folders"][-self.deleted_count:], 1):
                logger.info(f"   {i}. {folder_info['folder']}")
                logger.info(f"      Titlu: {folder_info['title']}")
                logger.info(f"      Spațiu eliberat: {folder_info.get('size_mb', 0):.2f} MB")

    def run(self):
        """Rulează procesul principal"""
        logger.info("=" * 60)
        logger.info("🚀 START - Internet Archive Duplicate Checker")
        logger.info(f"📁 Folder verificat: {ARCHIVE_PATH}")
        logger.info(f"⏱️ Delay între căutări: {DELAY_BETWEEN_SEARCHES} secunde")
        logger.info("=" * 60)

        # Verifică dacă folderul există
        if not ARCHIVE_PATH.exists():
            logger.error(f"❌ Folderul {ARCHIVE_PATH} nu există!")
            return False

        # Resetează folderele procesate pentru a le verifica din nou
        self.reset_processed_folders()
        # Înlocuiește linia self.test_direct_search() cu aceste două linii:
        self.test_direct_search()
        self.test_direct_url_access()

        try:
            # Scanează folderele
            tasks = self.scan_folders()

            if not tasks:
                logger.info("✅ Nu sunt fișiere de verificat!")
                return True

            # Procesează fiecare task
            for i, task in enumerate(tasks, 1):
                folder_str = str(task["folder"])

                # Sari peste folderele deja procesate în această sesiune
                if folder_str in self.state["processed_folders"]:
                    logger.debug(f"⏭️ Folder deja procesat: {folder_str}")
                    continue

                logger.info(f"\n📊 Progres: {i}/{len(tasks)}")
                logger.info(f"📂 Folder: {task['folder'].name}")
                logger.info(f"📄 Titlu căutat: {task['search_title']}")

                # Verifică pe Archive.org
                found = self.check_archive_api(task['search_title'])

                if found:
                    # Șterge folderul
                    self.delete_folder(task)
                else:
                    logger.info(f"   ℹ️ Păstrez folderul - nu există pe Archive.org")

                # Marchează ca procesat
                self.state["processed_folders"].append(folder_str)
                self.checked_count += 1
                self.state["stats"]["total_checked"] += 1

                # Salvează starea periodic (la fiecare 5 foldere)
                if i % 5 == 0:
                    self.save_state()

                # Așteaptă între căutări (exceptând ultima)
                if i < len(tasks):
                    logger.info(f"⏳ Aștept {DELAY_BETWEEN_SEARCHES} secunde...")
                    time.sleep(DELAY_BETWEEN_SEARCHES)

            # Salvează starea finală
            self.save_state()

            # Generează raportul final
            self.generate_report()

            return True

        except KeyboardInterrupt:
            logger.warning("\n⚠️ Proces întrerupt de utilizator")
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
        checker = ArchiveDuplicateChecker()
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