#!/usr/bin/env python3
"""
Automatizare incarcare fisiere pe Archive.org - Versiunea cu Subfoldere Recursiv:
- Scaneaza RECURSIV toate subfolderele din g:\\ARHIVA\\B\\ (fara limita de nivel)
- Verifica in prealabil pe Internet Archive daca fisierele exista; daca da, sterge folderul local si sare la urmatorul
- Daca nu exista, incarca TOATE fisierele (exceptand .jpg/.png) pe archive.org
- Pentru foldere fara PDF: muta un fisier specific in d:\\3\\ cu OVERWRITE
- Prioritate fisiere: .mobi, .epub, .djvu, .docx, .doc, .lit, rtf
- Completeaza automat campurile pe archive.org
- Limita: maxim 200 upload-uri pe zi
- Pastreaza evidenta progresului in state_archive.json
- Verifica erori 404/505 dupa 5 minute de la ultimul upload si salveaza titlurile intr-un txt
- Copiază automat fișierele cu erori în g:\\TEMP\\ pentru verificare ușoară
"""

import time
import os
import sys
import re
import json
import shutil
import difflib
import requests
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException

# Configurații
ARCHIVE_PATH = Path(r"g:\ARHIVA\B")
MOVE_PATH = Path(r"d:\3")
TEMP_PATH = Path(r"g:\TEMP")
ARCHIVE_URL = "https://archive.org/upload"
ARCHIVE_SEARCH_URL = "https://archive.org/search.php"
MAX_UPLOADS_PER_DAY = 200
STATE_FILENAME = "state_archive.json"

# Extensii prioritare și de ignorat
PRIORITY_EXTENSIONS = ['.mobi', '.epub', '.djvu', '.docx', '.doc', '.lit', '.rtf']
IGNORE_EXTENSIONS = ['.jpg', '.png']

class ArchiveUploader:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.driver = None
        self.wait = None
        self.attached_existing = False
        self.state_path = STATE_FILENAME
        self._load_state()

    def _load_state(self):
        """Încarcă starea din fișierul JSON"""
        today = datetime.now().strftime("%Y-%m-%d")
        default_state = {
            "date": today,
            "processed_folders": [],
            "processed_units": [],
            "uploads_today": 0,
            "folders_moved": 0,
            "last_processed_folder": "",
            "total_files_uploaded": 0,
            "deleted_folders": []
        }

        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r", encoding="utf-8") as f:
                    loaded_state = json.load(f)

                if loaded_state.get("date") == today:
                    self.state = loaded_state
                    for key in default_state:
                        if key not in self.state:
                            self.state[key] = default_state[key]
                    print(f"📋 Stare încărcată: {self.state.get('uploads_today', 0)} upload-uri astăzi")
                else:
                    print("🆕 Zi nouă detectată. Resetez starea.")
                    self.state = default_state
            else:
                self.state = default_state
        except Exception as e:
            print(f"⚠ Eroare la citirea stării: {e}")
            self.state = default_state

        self._save_state()

    def _save_state(self):
        """Salvează starea curentă în fișierul JSON"""
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠ Eroare la salvarea stării: {e}")

    def setup_chrome_driver(self):
        """Configurează și inițializează driver-ul Chrome"""
        try:
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

            prefs = {
                "download.default_directory": str(Path.cwd()),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True
            }
            chrome_options.add_experimental_option("prefs", prefs)

            try:
                self.driver = webdriver.Chrome(options=chrome_options)
                self.wait = WebDriverWait(self.driver, self.timeout)
                self.attached_existing = True
                print("✅ Conectat la sesiunea Chrome existentă")
                return True
            except WebDriverException:
                chrome_options = Options()
                chrome_options.add_experimental_option("prefs", prefs)
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--window-size=1920,1080")

                self.driver = webdriver.Chrome(options=chrome_options)
                self.wait = WebDriverWait(self.driver, self.timeout)
                self.attached_existing = False
                print("✅ Pornit Chrome nou cu succes")
                return True

        except Exception as e:
            print(f"❌ Eroare la inițializarea WebDriver: {e}")
            return False

    def alphabetical_sort_key(self, folder_name):
        """Generează o cheie de sortare alfabetică, ignorând caractere speciale"""
        clean_name = re.sub(r'[^a-zA-ZăâîșțĂÂÎȘȚ\s]', '', folder_name.lower())
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()
        return clean_name

    def scan_folder_structure(self, folder_path):
        """Scanează recursiv structura folderului și returnează unitățile de procesat"""
        processing_units = []

        try:
            for root, dirs, files in os.walk(folder_path):
                current_path = Path(root)
                if files:  # Doar folderele cu fișiere
                    unit_files = [f for f in map(lambda x: current_path / x, files)
                                 if f.suffix.lower() not in IGNORE_EXTENSIONS]
                    pdf_files = [f for f in unit_files if f.suffix.lower() == '.pdf']

                    unit_name = str(current_path.relative_to(ARCHIVE_PATH))

                    processing_units.append({
                        "path": current_path,
                        "name": unit_name,
                        "has_pdf": len(pdf_files) > 0,
                        "pdf_files": pdf_files,
                        "all_files": unit_files,
                        "is_root": current_path == folder_path
                    })

                    if self.is_unit_processed(current_path):
                        print(f"⏭️ {unit_name}: DEJA PROCESAT (se reevaluează)")
                    else:
                        print(f"📂 {unit_name}: {len(pdf_files)} PDF-uri, {len(unit_files)} fișiere")

            print(f"📊 Găsite {len(processing_units)} unități în {folder_path.name}")
            return processing_units

        except Exception as e:
            print(f"❌ Eroare la scanarea {folder_path}: {e}")
            return []

    def get_folders_to_process(self):
        """Returnează folderele de procesat, sortate alfabetic"""
        try:
            all_folders = [f for f in ARCHIVE_PATH.iterdir() if f.is_dir()]
            all_folders.sort(key=lambda x: self.alphabetical_sort_key(x.name))

            print("📋 Primele 10 foldere în ordine alfabetică:")
            for i, folder in enumerate(all_folders[:10], 1):
                print(f"   {i}. {folder.name}")

            remaining_folders = all_folders

            print(f"\n📁 Total foldere: {len(all_folders)}")
            print(f"🎯 Foldere de procesat: {len(remaining_folders)}")

            return remaining_folders

        except Exception as e:
            print(f"❌ Eroare la obținerea folderelor: {e}")
            return []

    def clean_title_for_search(self, filename):
        """Curăță titlul pentru căutare pe archive.org"""
        name = Path(filename).stem
        patterns_to_remove = [
            r'[_-]\d{6,8}$',
            r'\s*\([^)]*\)$',
            r'\s*\[[^\]]*\]$',
            r'\b[vV]\.?\s*\d+([\.\-]\d+)*\b',
            r'\b(scan|ctrl|retail|cop\d+|Vp|draft|final|ocr|edit|proof|beta|alpha|test|demo|sample|preview|full|complete|fix|corrected)\b',
            r'[\-_]\d+$'
        ]

        for pattern in patterns_to_remove:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)

        name = re.sub(r'\s+[-–]\s*', ' - ', name)
        name = re.sub(r'\s+', ' ', name).strip()

        print(f"🔍 Titlu curățat pentru căutare: '{name}'")
        return name

    def exists_on_archive(self, title):
        """Verifică dacă un titlu există pe archive.org folosind API-ul"""
        url = "https://archive.org/advancedsearch.php"
        params = {
            "q": f"title:({title}*) OR mediatype:texts",
            "fl[]": "identifier,title",
            "rows": 5,
            "output": "json",
            "sort[]": "downloads desc"
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ArchiveUploader/1.0"
        }

        for attempt in range(1, 4):
            try:
                print(f"🔍 Verific pe archive.org: '{title}' (încercarea {attempt})")
                response = requests.get(url, params=params, headers=headers, timeout=15)
                response.raise_for_status()

                data = response.json()
                num_results = data.get("response", {}).get("numFound", 0)

                if num_results > 0:
                    print(f"✅ Găsit {num_results} rezultate pentru '{title}'")
                    return True

                print(f"❌ Nu există rezultate pentru '{title}'")
                return False

            except requests.RequestException as e:
                print(f"⚠ Eroare API (încercarea {attempt}): {e}")
                if attempt < 3:
                    time.sleep(2 ** attempt)

        print("❌ Eșuat după 3 încercări")
        return False

    def is_unit_processed(self, unit_path):
        """Verifică dacă o unitate a fost procesată"""
        return str(unit_path) in self.state.get("processed_units", [])

    def delete_folder(self, folder_path):
        """Șterge un folder și tot conținutul său"""
        try:
            print(f"🗑️ Încep ștergerea {folder_path}")
            shutil.rmtree(folder_path)

            if str(folder_path) in self.state.get("processed_units", []):
                self.state["processed_units"].remove(str(folder_path))

            if str(folder_path) not in self.state.get("deleted_folders", []):
                self.state.setdefault("deleted_folders", []).append(str(folder_path))

            self._save_state()

            print(f"✅ Șters cu succes: {folder_path}")
            return True

        except Exception as e:
            print(f"❌ Eroare la ștergerea {folder_path}: {e}")
            return False

    def mark_unit_processed(self, unit_path, unit_name, status):
        """Marchează o unitate ca procesată în stare"""
        if str(unit_path) not in self.state.get("processed_units", []):
            self.state.setdefault("processed_units", []).append(str(unit_path))
            self.state["last_processed_folder"] = unit_name
            self._save_state()
        print(f"✅ Unitate marcată ca procesată: {unit_name} ({status})")

    def process_single_unit(self, unit):
        """Procesează o unitate (folder cu fișiere)"""
        print(f"\n📂 Procesez unitatea: {unit['name']}")

        if not unit["all_files"]:
            print("⚠ Unitate goală - ignorată")
            self.mark_unit_processed(unit["path"], unit["name"], "GOL")
            return True

        all_exist = True
        representative_title = self.clean_title_for_search(unit["all_files"][0].name)

        # Verifică dacă toate fișierele pot fi reprezentate de un titlu comun
        for file in unit["pdf_files"]:
            title = self.clean_title_for_search(file.name)
            if not self.exists_on_archive(title):
                all_exist = False
                break

        if all_exist:
            print(f"📌 Toate fișierele din '{unit['name']}' există pe archive.org - șterg folderul local")
            if self.delete_folder(unit["path"]):
                self.mark_unit_processed(unit["path"], unit["name"], "ȘTERS")
                return "deleted"
            return False

        if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
            print(f"⚠ Limita de {MAX_UPLOADS_PER_DAY} upload-uri atinsă!")
            return "limit_reached"

        if unit["has_pdf"]:
            print(f"📄 PDF detectat - încărcare pe archive.org cu titlul: {representative_title}")
            success = self.upload_files_to_archive(unit["all_files"], unit["name"], representative_title)

            if success:
                self.state["uploads_today"] += len(unit["all_files"])
                self.state["total_files_uploaded"] += len(unit["all_files"])
                self.mark_unit_processed(unit["path"], unit["name"], "UPLOAD")
                print(f"✅ Încărcat cu succes (#{self.state['uploads_today']})")
                return True
            return False
        else:
            print(f"🔍 Nu există PDF - caut fișier prioritar")
            priority_file = self.find_priority_file(unit["all_files"])

            if priority_file:
                if self.move_file_to_d3(priority_file):
                    self.state["folders_moved"] += 1
                    self.mark_unit_processed(unit["path"], unit["name"], "MUTAT")
                    print(f"✅ Mutat {priority_file.name} în d:\\3\\")
                    return True
                return False
            else:
                print("⚠ Nu s-a găsit niciun fișier prioritar")
                self.mark_unit_processed(unit["path"], unit["name"], "GOL")
                return True

    def find_priority_file(self, files):
        """Găsește primul fișier din lista de priorități"""
        for ext in PRIORITY_EXTENSIONS:
            for file in files:
                if file.suffix.lower() == ext:
                    return file
        return None

    def move_file_to_d3(self, file_path):
        """Mută fișierul în d:\3, suprascriind dacă există"""
        try:
            MOVE_PATH.mkdir(exist_ok=True, parents=True)
            dest = MOVE_PATH / file_path.name
            shutil.copy2(file_path, dest)
            return True
        except Exception as e:
            print(f"❌ Eroare la mutare: {e}")
            return False

    def sanitize_title(self, text):
        """Curăță textul pentru a fi folosit ca titlu"""
        title = re.sub(r'[^\w\s-]', ' ', text)
        title = re.sub(r'\s+', ' ', title).strip()
        return title

    def navigate_to_upload_page(self):
        """Navighează la pagina de upload"""
        try:
            print(f"🌐 Navighez către {ARCHIVE_URL}")
            self.driver.get(ARCHIVE_URL)
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            print("✅ Pagina de upload încărcată")
            return True
        except Exception as e:
            print(f"❌ Eroare la navigare: {e}")
            return False

    def upload_files_to_archive(self, files, folder_name, title):
        """Încarcă fișierele pe archive.org cu retry pentru erori de timeout"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"⚠️ ATENȚIE: Nu modifica tab-ul Chrome în timpul upload-ului! (Încercarea {attempt + 1}/{max_retries})")

                self.driver.execute_script("window.open('');")
                self.driver.switch_to.window(self.driver.window_handles[-1])

                if not self.navigate_to_upload_page():
                    return False

                print(f"📤 Încep încărcarea pentru {folder_name} ({len(files)} fișiere)")

                try:
                    file_input = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
                    )
                except TimeoutException:
                    print("❌ Nu am găsit input-ul pentru fișiere")
                    return False

                file_paths = "\n".join(str(f.absolute()) for f in files)
                file_input.send_keys(file_paths)

                print(f"📁 Fișiere trimise: {len(files)}")
                time.sleep(3)

                if self.fill_form_fields(folder_name, title):
                    print("✅ Upload inițiat cu succes")
                    return True

            except TimeoutException as e:
                print(f"❌ Eroare de timeout: {e} (Încercarea {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
            except Exception as e:
                print(f"❌ Eroare la încărcare: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue

        return False

    def fill_form_fields(self, folder_name, title):
        """Completează câmpurile formularului de upload cu titlul specificat"""
        try:
            try:
                title_element = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#page_title, span.x-archive-meta-title"))
                )
                if not title_element.get_attribute("value"):
                    title_element.send_keys(title)
                print(f"📝 Titlul: {title}")
            except Exception as e:
                print(f"⚠ Nu am putut completa titlul: {e}")

            try:
                desc_wrapper = self.wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#description, span#description"))
                )
                desc_wrapper.click()

                try:
                    iframe = self.driver.find_elements(By.TAG_NAME, "iframe")
                    for i in iframe:
                        self.driver.switch_to.frame(i)
                        try:
                            editor = self.driver.find_element(By.TAG_NAME, "body")
                            self.driver.execute_script("arguments[0].innerText = arguments[1];", editor, title)
                            self.driver.switch_to.default_content()
                            break
                        except:
                            self.driver.switch_to.default_content()
                    else:
                        editor = self.driver.find_element(By.CSS_SELECTOR, "body.wysiwyg")
                        self.driver.execute_script("arguments[0].innerText = arguments[1];", editor, title)
                except Exception as e:
                    print(f"⚠ Nu am putut completa descrierea: {e}")
                    pass

                print("📝 Descriere completată")
            except Exception as e:
                print(f"⚠ Nu am putut accesa descrierea: {e}")

            try:
                subj_wrapper = self.wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#subjects, span#subjects"))
                )
                subj_wrapper.click()

                subj_input = self.driver.find_element(
                    By.CSS_SELECTOR, "input[placeholder*='Add keywords'], input.input_field"
                )
                subj_input.clear()
                subj_input.send_keys(title)
                print("📝 Tag-uri completate")
            except Exception as e:
                print(f"⚠ Nu am putut completa tag-urile: {e}")

            try:
                date_span = self.wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#date_text, span#date_text"))
                )
                date_span.click()

                year = self.wait.until(EC.presence_of_element_located((By.ID, "date_year")))
                month = self.driver.find_element(By.ID, "date_month")
                day = self.driver.find_element(By.ID, "date_day")

                self.driver.execute_script("""
                    arguments[0].removeAttribute('readonly');
                    arguments[0].removeAttribute('disabled');
                """, month)
                self.driver.execute_script("""
                    arguments[0].removeAttribute('readonly');
                    arguments[0].removeAttribute('disabled');
                """, day)

                year.clear()
                year.send_keys("1983")
                month.clear()
                month.send_keys("12")
                day.clear()
                day.send_keys("13")

                print("📅 Data completată: 1983-12-13")
            except Exception as e:
                print(f"⚠ Nu am putut completa data: {e}")

            try:
                collection_select = self.driver.find_element(
                    By.CSS_SELECTOR, "select.mediatypecollection, select[name='mediatypecollection']"
                )
                self.driver.execute_script("""
                    arguments[0].value = 'texts:opensource';
                    arguments[0].dispatchEvent(new Event('change'));
                """, collection_select)
                print("📚 Colecție selectată: texts:opensource")
            except Exception as e:
                print(f"⚠ Nu am putut selecta colecția: {e}")

            try:
                upload_btn = self.wait.until(
                    EC.element_to_be_clickable((By.ID, "upload_button"))
                )
                upload_btn.click()
                print("⏫ Început upload...")
                time.sleep(3)
                return True
            except Exception as e:
                print(f"❌ Nu am putut apăsa butonul de upload: {e}")
                return False

        except Exception as e:
            print(f"❌ Eroare la completarea formularului: {e}")
            return False

    def process_folder(self, folder_path):
        """Procesează un folder și toate subfolderele sale"""
        print(f"\n📁 Procesez folderul: {folder_path.name}")

        units = self.scan_folder_structure(folder_path)
        if not units:
            print(f"✅ Toate unitățile din {folder_path.name} sunt procesate sau reevaluate")
            self._cleanup_empty_parent(folder_path)
            if str(folder_path) not in self.state["processed_folders"]:
                self.state["processed_folders"].append(str(folder_path))
                self.state["last_processed_folder"] = folder_path.name
                self._save_state()
            return True

        all_deleted = True
        for i, unit in enumerate(units, 1):
            print(f"\n📦 Unitate {i}/{len(units)}: {unit['name']}")

            try:
                result = self.process_single_unit(unit)

                if result == "limit_reached":
                    print(f"⏹️ Limita de upload-uri atinsă")
                    return "limit_reached"
                elif result == "deleted":
                    continue
                elif not result:
                    print(f"⚠ Eșec la procesarea unității")
                    all_deleted = False
                else:
                    all_deleted = False  # Dacă un upload sau mutare reușește, nu șterge folderul părinte

            except Exception as e:
                print(f"❌ Eroare neașteptată: {e}")
                all_deleted = False
                continue

        if all_deleted:
            if self.delete_folder(folder_path):
                self.mark_unit_processed(folder_path, folder_path.name, "ȘTERS")
            else:
                if str(folder_path) not in self.state["processed_folders"]:
                    self.state["processed_folders"].append(str(folder_path))
                    self.state["last_processed_folder"] = folder_path.name
                    self._save_state()
                    print(f"✅ Folderul {folder_path.name} procesat complet")
        self._cleanup_empty_parent(folder_path)
        return not all_deleted  # Returnează True dacă există unități procesate, False dacă toate sunt șterse

    def _cleanup_empty_parent(self, folder_path):
        """Șterge folderul părinte dacă este gol, ignorând fișierele de sistem"""
        try:
            has_non_system_content = False
            for item in folder_path.iterdir():
                if not item.name.startswith('.') and item.name not in ['Thumbs.db', 'desktop.ini']:
                    has_non_system_content = True
                    break
            if not has_non_system_content:
                if self.delete_folder(folder_path):
                    print(f"✅ Folderul părinte {folder_path.name} șters pentru că este gol")
        except Exception as e:
            print(f"⚠ Eroare la verificarea/ștergerea folderului părinte: {e}")

    def check_for_errors_after_upload(self):
        """Verifică erorile după upload"""
        print("\n⏳ Aștept 5 minute pentru verificarea erorilor...")
        time.sleep(300)

        print("\n🔍 Verific erori în filele deschise...")
        if not self.driver:
            print("❌ Driver-ul nu este disponibil")
            return []

        failed_uploads = []
        original_window = self.driver.current_window_handle

        for i, window in enumerate(self.driver.window_handles, 1):
            try:
                self.driver.switch_to.window(window)
                print(f"\n📋 Fila {i}: {self.driver.current_url}")

                try:
                    error_div = self.driver.find_element(By.ID, "progress_msg")
                    error_text = error_div.text.lower()

                    if "error" in error_text or "failed" in error_text:
                        print(f"🚨 Eroare detectată: {error_text}")
                        error_code = "unknown"
                        error_status = "unknown"
                        error_details = ""

                        try:
                            error_code = self.driver.find_element(By.ID, "upload_error_code").text
                            error_status = self.driver.find_element(By.ID, "upload_error_status").text
                        except:
                            pass

                        try:
                            details_div = self.driver.find_element(By.ID, "upload_error_details")
                            if "display: none" in details_div.get_attribute("style"):
                                self.driver.find_element(By.ID, "upload_error_show_details").click()
                            pre_element = details_div.find_element(By.TAG_NAME, "pre")
                            error_details = pre_element.text
                        except:
                            pass

                        filename = "unknown"
                        try:
                            if "upload of" in error_text:
                                filename = re.search(r"upload of (.+?) from", error_text).group(1)
                            else:
                                filename = self.driver.find_element(
                                    By.CSS_SELECTOR, ".upload-filename, .file-name"
                                ).text
                        except:
                            pass

                        failed_uploads.append({
                            "filename": filename,
                            "error_code": error_code,
                            "error_status": error_status,
                            "error_details": error_details,
                            "timestamp": datetime.now().isoformat()
                        })

                        print(f"📝 Eroare înregistrată: {filename} ({error_code})")
                except NoSuchElementException:
                    print("✅ Nu sunt erori în această filă")

            except Exception as e:
                print(f"⚠ Eroare la verificarea filei: {e}")

        try:
            self.driver.switch_to.window(original_window)
        except:
            if self.driver.window_handles:
                self.driver.switch_to.window(self.driver.window_handles[0])

        if failed_uploads:
            error_file = f"upload_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(error_file, "w", encoding="utf-8") as f:
                f.write(f"Erori upload - {datetime.now()}\n")
                f.write("=" * 50 + "\n\n")
                for i, error in enumerate(failed_uploads, 1):
                    f.write(f"{i}. {error['filename']} ({error['error_code']})\n")
                    f.write(f"   Status: {error['error_status']}\n")
                    f.write(f"   Detalii: {error['error_details'][:200]}...\n\n")

            print(f"📄 Erorile au fost salvate în {error_file}")
            self.copy_error_files_to_temp(failed_uploads)

        return failed_uploads

    def copy_error_files_to_temp(self, failed_uploads):
        """Copiază fișierele cu erori în folderul TEMP"""
        if not failed_uploads:
            print("✅ Nu sunt fișiere cu erori de copiat")
            return []

        print(f"\n📁 Copiez fișierele cu erori în {TEMP_PATH}")
        TEMP_PATH.mkdir(exist_ok=True, parents=True)

        copied_files = []
        search_folders = [Path(f) for f in self.state.get("processed_folders", []) if Path(f).exists()]
        search_folders.append(ARCHIVE_PATH)

        for error in failed_uploads:
            filename = error["filename"]
            print(f"\n🔍 Caut fișierul original pentru: {filename}")

            best_match = None
            best_score = 0

            for folder in search_folders:
                for root, _, files in os.walk(folder):
                    for file in files:
                        file_path = Path(root) / file
                        similarity = difflib.SequenceMatcher(None, filename.lower(), file.lower()).ratio()
                        if similarity > 0.7 and similarity > best_score:
                            best_match = file_path
                            best_score = similarity

            if best_match:
                print(f"   ✅ Potrivire găsită: {best_match} (similaritate: {best_score:.2f})")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest_name = f"{best_match.stem}_ERROR_{timestamp}{best_match.suffix}"
                dest_path = TEMP_PATH / dest_name

                try:
                    shutil.copy2(best_match, dest_path)
                    info_path = dest_path.with_suffix(".txt")
                    with open(info_path, "w", encoding="utf-8") as f:
                        f.write(f"Fișier original: {best_match}\n")
                        f.write(f"Eroare upload: {error['error_code']} - {error['error_status']}\n")
                        f.write(f"Detalii:\n{error['error_details']}\n")
                    copied_files.append({"original": str(best_match), "copy": str(dest_path), "info_file": str(info_path)})
                    print(f"   📁 Copiat în: {dest_path}")
                except Exception as e:
                    print(f"   ❌ Eroare la copiere: {e}")
            else:
                print(f"   ⚠ Nu am găsit fișierul original")

        print(f"\n📊 Rezumat copiere:")
        print(f"✅ Fișiere copiate: {len(copied_files)}")
        print(f"❌ Erori: {len(failed_uploads) - len(copied_files)}")

        return copied_files

    def run(self):
        """Rulează procesul principal"""
        print("\n" + "=" * 60)
        print("🚀 ARCHIVE.ORG UPLOADER")
        print("=" * 60)
        print(f"📁 Sursa: {ARCHIVE_PATH}")
        print(f"📁 Destinație: {MOVE_PATH}")
        print(f"🗂️ TEMP: {TEMP_PATH}")
        print(f"🎯 Upload-uri maxime/zi: {MAX_UPLOADS_PER_DAY}")
        print("\n⚠️ ATENȚIE: Nu atinge Chrome în timpul upload-urilor!")
        print("=" * 60)

        try:
            if not self.setup_chrome_driver():
                return False

            MOVE_PATH.mkdir(exist_ok=True, parents=True)
            TEMP_PATH.mkdir(exist_ok=True, parents=True)

            folders = self.get_folders_to_process()
            if not folders:
                print("✅ Nu mai sunt foldere de procesat")
                return True

            for i, folder in enumerate(folders, 1):
                print(f"\n📊 Progres: {i}/{len(folders)} - {folder.name}")

                try:
                    result = self.process_folder(folder)

                    if result == "limit_reached":
                        print("⏹️ Oprire din cauza limitei de upload-uri")
                        break
                    elif not result:
                        print("⚠ Folderul nu a fost procesat complet")

                    if i < len(folders):
                        time.sleep(3)

                except KeyboardInterrupt:
                    print("\n⏹️ Oprire manuală")
                    break
                except Exception as e:
                    print(f"❌ Eroare neașteptată: {e}")
                    continue

            self.check_for_errors_after_upload()

            print("\n" + "=" * 60)
            print("📊 RAPORT FINAL")
            print("=" * 60)
            print(f"📤 Upload-uri astăzi: {self.state['uploads_today']}/{MAX_UPLOADS_PER_DAY}")
            print(f"📁 Foldere procesate: {len(self.state['processed_folders'])}")
            print(f"📄 Fișiere încărcate: {self.state['total_files_uploaded']}")
            print(f"📂 Fișiere mutate: {self.state['folders_moved']}")
            print(f"🗑️ Foldere șterse: {len(self.state.get('deleted_folders', []))}")

            if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
                print("\n🎯 LIMITA DE UPLOAD-URI ATINSĂ!")

            return True

        except KeyboardInterrupt:
            print("\n⏹️ Execuție întreruptă manual")
            return False
        except Exception as e:
            print(f"\n❌ Eroare neașteptată: {e}")
            return False
        finally:
            if not self.attached_existing and self.driver:
                try:
                    self.driver.quit()
                except:
                    pass

def main():
    """Funcția principală"""
    if not ARCHIVE_PATH.exists():
        print(f"❌ Folderul sursă {ARCHIVE_PATH} nu există")
        return False

    uploader = ArchiveUploader()
    success = uploader.run()

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()