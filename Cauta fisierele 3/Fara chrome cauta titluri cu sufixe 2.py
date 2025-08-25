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
DELAY_BETWEEN_REQUESTS = 0.3   # Secunde între requests pentru a nu suprasolicita serverul

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
        """Curăță titlul pentru căutare SIMPLĂ pe Archive.org"""
        name = Path(filename).stem
        logger.debug(f"🔧 Curățare titlu original: {filename}")

        # ⚡ PRIMUL: Elimină COMPLET parantezele și conținutul lor
        name = re.sub(r'\s*\([^)]*\)', '', name)  # (trad.) dispare complet
        name = re.sub(r'\s*\[[^\]]*\]', '', name)  # [ceva] dispare complet

        # ⚡ AL DOILEA: Elimină sufixele tehnice de la sfârșit
        # retail, scan, ctrl, ocr, vp, draft, final
        technical_suffixes = ['retail', 'scan', 'ctrl', 'ocr', 'vp', 'draft', 'final', 'edit', 'copy', 'backup']

        # Elimină după ultima " - " dacă este sufix tehnic
        parts = name.rsplit(' - ', 1)
        if len(parts) == 2:
            last_part = parts[1].strip().lower()
            if last_part in technical_suffixes:
                name = parts[0]  # Păstrează doar partea din față

        # ⚡ AL TREILEA: Elimină toate punctuațiile rămase
        # Păstrează doar literele, cifrele și spațiile
        name = re.sub(r'[^\w\s]', ' ', name)

        # ⚡ AL PATRULEA: Elimină versiunile (v1, v.1.0, etc.)
        words = name.split()
        words = [w for w in words if not re.match(r'^v\.?\d', w.lower())]

        # Curăță spațiile multiple
        result = ' '.join(words)
        result = re.sub(r'\s+', ' ', result).strip()

        logger.debug(f"✨ Titlu pentru căutare simplă: '{result}'")
        return result

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

    def remove_diacritics(self, text: str) -> str:
        """Elimină diacriticele din text"""
        import unicodedata
        return ''.join(c for c in unicodedata.normalize('NFD', text)
                      if unicodedata.category(c) != 'Mn')

    def generate_search_variants(self, title: str) -> List[str]:
        """Generează variante de căutare pentru un titlu"""
        variants = [title]  # Titlul original

        # Varianta fără diacritice
        no_diacritics = self.remove_diacritics(title)
        if no_diacritics != title:
            variants.append(no_diacritics)

        # Varianta fără punctuație în nume
        no_punct = re.sub(r'([A-Z])\.([A-Z])\.', r'\1 \2', title)  # "J.C." -> "J C"
        if no_punct != title:
            variants.append(no_punct)

        # Variante cu Case diferit
        variants.append(title.title())  # Title Case
        variants.append(title.lower())   # lower case

        # Elimină duplicatele păstrând ordinea
        seen = set()
        unique_variants = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique_variants.append(v)

        return unique_variants[:5]  # Max 5 variante

    def test_url_exists(self, url: str, identifier: str) -> bool:
        """Testează dacă un URL există pe Archive.org"""
        try:
            response = self.session.head(url, timeout=10, allow_redirects=True)
            if response.status_code == 200:
                logger.info(f"   🎯 URL EXISTENT: {identifier}")
                return True
            return False
        except:
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
        """METODA 1 SIMPLĂ - Căutare directă pe titlu și verificare sufixe dată"""
        search_title = folder_info["search_title"]

        logger.info(f"🔍 METODA 1 - Căutare simplă pentru: {search_title}")

        try:
            # ⚡ CĂUTARE SIMPLĂ fără field restriction
            encoded_query = quote_plus(search_title)
            search_url = f"{SEARCH_BASE_URL}?query={encoded_query}"

            logger.info(f"   🌐 URL căutare: {search_url}")

            response = self.session.get(search_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            title_elements = soup.find_all('h4', class_='truncated')

            if not title_elements:
                logger.info(f"   ℹ️ Niciun rezultat găsit pentru '{search_title}'")
                return False, "no_results"

            logger.info(f"   📊 Găsite {len(title_elements)} rezultate")

            # ⚡ EXTRAGE IDENTIFIER-URILE din link-uri
            found_identifiers = []

            for h4 in title_elements:
                title_text = h4.get('title') or h4.get_text().strip()
                logger.info(f"      📖 Rezultat: {title_text}")

                # Găsește link-ul parent sau din apropierea h4
                link_element = h4.find_parent('a') or h4.find_next('a') or h4.find_previous('a')
                if link_element and 'href' in link_element.attrs:
                    href = link_element['href']
                    # Extrage identifier-ul din href (ex: /details/certo-samuel-managementul-modern_202508)
                    if '/details/' in href:
                        identifier = href.split('/details/')[-1]
                        found_identifiers.append(identifier)
                        logger.info(f"         🔗 Identifier: {identifier}")

            # ⚡ VERIFICĂ SUFIXELE DE DATĂ
            date_suffix_identifiers = []
            for identifier in found_identifiers:
                # Verifică sufixele din COMMON_DUPLICATE_SUFFIXES
                for suffix in COMMON_DUPLICATE_SUFFIXES:
                    if identifier.endswith(suffix):
                        date_suffix_identifiers.append(identifier)
                        logger.info(f"         🎯 SUFIX DE DATĂ GĂSIT: {identifier}")
                        break

            if date_suffix_identifiers:
                logger.info(f"   ✅ DUPLICATE GĂSITE: {len(date_suffix_identifiers)} cu sufixe de dată")
                return True, "search_duplicate_with_date_suffix"
            else:
                logger.info(f"   ✅ Rezultate găsite dar fără sufixe de dată")
                return False, "results_no_date_suffix"

        except Exception as e:
            logger.warning(f"   ⚠️ Eroare la căutarea HTML: {e}")
            return False, "search_error"

    def method_2_api_identifier_search(self, folder_info: Dict[str, Any]) -> Tuple[bool, str]:
        """METODA 2: Căutare prin API pentru identifier-uri cu sufixe"""
        identifier_base = folder_info["identifier_base"]

        logger.info(f"🔍 METODA 2 - Căutare API identifier pentru: {identifier_base}*")

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

            # ⚡ LISTĂ EXTINSĂ DE SUFIXE DUPLICATE
            duplicate_suffixes = [
                '-istor', '-ctrl', '-retail', '-scan', '-ocr', '-vp',
                '-retail-istor', '-scan-istor', '-ctrl-istor',
                '_202508', '_20250806', '_202507', '_202506'
            ]

            # Verifică fiecare identifier pentru sufixe duplicate
            found_duplicates = []
            for doc in docs:
                identifier = doc.get("identifier", "")
                logger.info(f"      - {identifier}")

                # Verifică dacă are sufixe de dată SAU sufixe cunoscute
                has_date_suffix = bool(re.search(r'_\d{6}$|_\d{8}$', identifier))
                has_known_suffix = any(identifier.endswith(suffix) for suffix in duplicate_suffixes)

                if has_date_suffix or has_known_suffix:
                    found_duplicates.append(identifier)
                    logger.info(f"        🎯 SUFIX DUPLICAT DETECTAT!")

            if found_duplicates:
                logger.info(f"   ✅ DUPLICATE GĂSITE prin API: {len(found_duplicates)} identifier-uri cu sufixe")
                for dup in found_duplicates[:3]:
                    logger.info(f"      🔸 {dup}")
                return True, "api_duplicate"
            else:
                logger.info(f"   ✅ Identifier-uri găsite dar fără sufixe duplicate")
                return False, "no_suffix_duplicates"

        except Exception as e:
            logger.error(f"   ❌ Eroare la API search: {e}")
            return False, "api_error"

    def method_3_direct_url_test(self, folder_info: Dict[str, Any]) -> Tuple[bool, str]:
        """METODA 3 GENERALĂ - Test direct URL-uri cu variante inteligente"""
        identifier_base = folder_info["identifier_base"]

        logger.info(f"🔍 METODA 3 - Test rapid URL pentru: {identifier_base}")

        found_urls = []

        # ⚡ GENEREAZĂ VARIANTE INTELIGENTE
        quick_variants = [
            identifier_base,  # Varianta de bază
        ]



        # ⚡ ADAUGĂ variante cu conținutul din paranteze (dacă există)
        if hasattr(self, '_parentheses_content') and self._parentheses_content:
            parentheses_clean = re.sub(r'[^\w\s]', '', self._parentheses_content.lower())  # "trad." -> "trad"
            parentheses_with_dot = self._parentheses_content.lower()  # "trad."

            logger.debug(f"🔍 Generez variante cu paranteze: '{parentheses_clean}' și '{parentheses_with_dot}'")

            # Găsește primul " - " și inserează conținutul din paranteze
            if ' - ' in identifier_base:
                parts = identifier_base.split(' - ', 1)
                base_part = parts[0]  # "chelaru-marius"
                rest_part = parts[1]  # "poarta-catre-poezia-araba"

                # Adaugă variante cu conținutul din paranteze
                quick_variants.extend([
                    f"{base_part}-{parentheses_clean}-{rest_part}",      # chelaru-marius-trad-poarta...
                    f"{base_part}-{parentheses_with_dot}-{rest_part}",   # chelaru-marius-trad.-poarta...
                ])

                logger.debug(f"🔧 Variante cu paranteze generate:")
                logger.debug(f"   - {base_part}-{parentheses_clean}-{rest_part}")
                logger.debug(f"   - {base_part}-{parentheses_with_dot}-{rest_part}")

        # ⚡ ADAUGĂ sufixe comune pentru toate variantele
        base_variants = quick_variants.copy()
        for base in base_variants:
            quick_variants.extend([
                base + '-ctrl',
                base + '-retail',
                base + '-scan',
                base + '-ocr',
                base + '-vp',
            ])

        # ⚡ ADAUGĂ variante cu modificări de punctuație
        extra_variants = []
        for variant in quick_variants:
            extra_variants.extend([
                variant.replace('j.c.', 'j.-c.'),
                variant.replace('-', ''),
                variant.replace('.', ''),
            ])
        quick_variants.extend(extra_variants)

        # ⚡ ELIMINĂ DUPLICATELE
        quick_variants = list(dict.fromkeys(quick_variants))  # Păstrează ordinea

        logger.debug(f"🔍 Testez {len(quick_variants)} variante pentru {identifier_base}")

        # ⚡ TESTEAZĂ TOATE VARIANTELE
        for variant in quick_variants:
            test_url = f"{DETAILS_BASE_URL}/{variant}"
            if self.test_url_exists(test_url, variant):
                found_urls.append(variant)
                logger.info(f"   🎯 GĂSIT: {variant}")
                break  # Stop la primul găsit

        if found_urls:
            logger.info(f"   ✅ DUPLICAT GĂSIT: {found_urls[0]}")
            return True, "url_duplicate"
        else:
            logger.info(f"   ✅ Niciun duplicat găsit")
            return False, "no_duplicates"

    def method_3_direct_url_test_enhanced(self, folder_info: Dict[str, Any]) -> Tuple[bool, str]:
        """METODA 3 ÎMBUNĂTĂȚITĂ - Test direct URL cu toate variantele posibile"""
        identifier_base = folder_info["identifier_base"]
        search_title = folder_info["search_title"]

        logger.info(f"🔍 METODA 3 ÎMBUNĂTĂȚITĂ - Test URL pentru: {identifier_base}")

        # ⚡ GENEREAZĂ TOATE VARIANTELE POSIBILE
        variants_to_test = [
            identifier_base,  # Base original
        ]

        # ⚡ ADAUGĂ VARIANTE cu sufixe comune
        common_suffixes = ['-retail', '-scan', '-ctrl', '-ocr', '-vp', '-istor']
        for suffix in common_suffixes:
            variants_to_test.append(identifier_base + suffix)

        # ⚡ ADAUGĂ VARIANTE cu cuvinte comune care lipsesc
        # Pentru cazuri ca "trad", "ed", "edition" etc.
        common_middle_words = ['trad', 'trad.', 'ed', 'edition', 'vol', 'tome']

        # Încearcă să insereze cuvinte în mijloc (după numele autorului)
        parts = identifier_base.split('-')
        if len(parts) >= 3:  # autor-nume-titlu...
            base_author = '-'.join(parts[:2])  # "chelaru-marius"
            rest_title = '-'.join(parts[2:])   # "poarta-catre-poezia-araba"

            for word in common_middle_words:
                # Varianta cu cuvântul în mijloc
                middle_variant = f"{base_author}-{word}-{rest_title}"
                variants_to_test.append(middle_variant)

                # Și cu sufixe
                for suffix in common_suffixes:
                    variants_to_test.append(middle_variant + suffix)

        # ⚡ ADAUGĂ VARIANTE cu COMMON_DUPLICATE_SUFFIXES
        for date_suffix in COMMON_DUPLICATE_SUFFIXES[:6]:  # Primele 6 sufixe
            variants_to_test.append(identifier_base + date_suffix)

        # ⚡ ELIMINĂ DUPLICATELE
        variants_to_test = list(dict.fromkeys(variants_to_test))

        logger.info(f"   🔍 Testez {len(variants_to_test)} variante")

        # ⚡ TESTEAZĂ TOATE VARIANTELE
        for i, variant in enumerate(variants_to_test):
            if i % 10 == 0:  # Log la fiecare 10 variante
                logger.info(f"   📊 Progres teste URL: {i+1}/{len(variants_to_test)}")

            test_url = f"{DETAILS_BASE_URL}/{variant}"
            if self.test_url_exists(test_url, variant):
                logger.info(f"   🎯 DUPLICAT GĂSIT: {variant}")
                return True, f"url_variant_{i}"

        logger.info(f"   ✅ Niciun duplicat găsit în {len(variants_to_test)} variante")
        return False, "no_duplicates"

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
            # ⚡ NU MAI FOLOSI SEARCH HTML - e blocat de Archive.org

            # PRIMUL: Test direct URL cu variante inteligente
            is_duplicate, method = self.method_3_direct_url_test_enhanced(folder_info)
            if is_duplicate:
                logger.info(f"🎯 DUPLICAT DETECTAT prin test direct URL!")
                self.url_test_hits += 1
                self.delete_folder(folder_info, f"Duplicat găsit prin {method}")
                return True

            # AL DOILEA: API search
            is_duplicate, method = self.method_2_api_identifier_search(folder_info)
            if is_duplicate and method == "api_duplicate":
                logger.info("🎯 DUPLICAT DETECTAT prin API identifier!")
                self.api_hits += 1
                self.delete_folder(folder_info, "Duplicat găsit prin API identifier")
                return True

            # Niciun duplicat găsit
            logger.info("✅ NU sunt duplicate detectate - păstrez folderul")
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

    def test_specific_chatterji(self):
        """Test specific pentru cartea Chatterji"""
        print("🔍 TESTEZ DIRECT URL-ul cunoscut:")

        known_identifier = "chatterji-j.-c.-filozofia-ezoterica-a-indiei-ctrl"
        test_url = f"https://archive.org/details/{known_identifier}"

        try:
            response = self.session.head(test_url, timeout=15)
            if response.status_code == 200:
                print(f"   ✅ URL-ul există: {known_identifier}")
                print(f"   🌐 {test_url}")
            else:
                print(f"   ❌ Status {response.status_code} pentru {known_identifier}")
        except Exception as e:
            print(f"   ❌ Eroare la testarea URL: {e}")

        print("\n🔍 TESTEZ API DIRECT (funcționează):")
        try:
            api_url = "https://archive.org/advancedsearch.php"
            params = {
                "q": "chatterji",
                "fl[]": ["identifier", "title"],
                "rows": 5,
                "output": "json"
            }

            response = self.session.get(api_url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                docs = data.get("response", {}).get("docs", [])
                print(f"   ✅ API găsit {len(docs)} rezultate pentru 'chatterji'")

                for doc in docs[:3]:
                    print(f"      📚 {doc.get('identifier', 'N/A')}: {doc.get('title', 'N/A')}")
            else:
                print(f"   ❌ API Status: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Eroare API: {e}")

        print(f"\n⚠️ NOTĂ: Search-ul HTML prin requests este blocat de Archive.org")
        print(f"   Dar API-ul și testul direct URL funcționează perfect!")

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

        # Test specific pentru Chatterji
        print("🧪 TESTEZ CAZUL CHATTERJI:")
        checker.test_specific_chatterji()
        print("\n" + "="*60 + "\n")

        # ⚠️ ADAUGĂ ASTA pentru a reprocessa folderul Chatterji
        if "g:\\ARHIVA\\C\\Chatterji, J.C" in checker.state["processed_folders"]:
            print("🔄 Elimin Chatterji din folderele procesate pentru retestare...")
            checker.state["processed_folders"].remove("g:\\ARHIVA\\C\\Chatterji, J.C")
            checker.save_state()

        success = checker.run()

        if success:
            print("\nâœ… Proces finalizat cu succes!")
        else:
            print("\nâŒ Proces finalizat cu erori!")

    except Exception as e:
        print(f"âŒ Eroare fatalÄƒ: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()