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
- NOUĂ FUNCȚIONALITATE: Copiază automat fișierele cu erori în g:\\TEMP\\ pentru verificare ușoară

Inainte de pornire ruleaza start_chrome_debug.bat pentru sesiunea Chrome cu remote debugging.

@echo off
REM Pornește Chrome pe profilul Default cu remote debugging activat
set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
set PROFILE_DIR="C:/Users/necul/AppData/Local/Google/Chrome/User Data/Default"

REM Asigură-te că nu mai e deja un Chrome deschis pe acel profil
%CHROME_PATH% --remote-debugging-port=9222 --user-data-dir=%PROFILE_DIR%
"""

import time
import os
import sys
import re
import json
import shutil
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

# Configurari
ARCHIVE_PATH = Path(r"g:\ARHIVA\B")
MOVE_PATH = Path(r"d:\3")
TEMP_PATH = Path(r"g:\TEMP")  # NOUĂ: Pentru fișierele cu erori
ARCHIVE_URL = "https://archive.org/upload"
MAX_UPLOADS_PER_DAY = 9999
STATE_FILENAME = "state_archive.json"

# Extensii in ordinea prioritatii pentru foldere fara PDF
PRIORITY_EXTENSIONS = ['.mobi', '.epub', '.djvu', '.docx', '.doc', '.lit', '.rtf']

# Extensii de ignorat
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
        """Incarca starea din fisierul JSON"""
        today = datetime.now().strftime("%Y-%m-%d")
        default = {
            "date": today,
            "processed_folders": [],
            "processed_units": [],
            "uploads_today": 0,
            "folders_moved": 0,
            "last_processed_folder": "",
            "total_files_uploaded": 0
        }
        self.state = default

        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if loaded.get("date") == today:
                    self.state = loaded
                    if "processed_units" not in self.state:
                        self.state["processed_units"] = []
                    print(f"📋 Încărcat starea pentru {today}: {self.state.get('uploads_today', 0)} upload-uri, {len(self.state.get('processed_units', []))} unități procesate")
                else:
                    print(f"🆕 Zi nouă detectată. Resetez starea.")
                    self.state = default
            except Exception as e:
                print(f"⚠ Eroare la citirea stării ({e}), resetez.")
                self.state = default
        self._save_state()

    def is_unit_processed(self, unit_path):
        """Verifică dacă o unitate a fost deja procesată"""
        unit_key = str(unit_path)
        return unit_key in self.state.get("processed_units", [])

    def mark_unit_processed(self, unit_path, unit_name, action_type):
        """Marchează o unitate ca procesată"""
        unit_key = str(unit_path)
        if unit_key not in self.state.get("processed_units", []):
            self.state.setdefault("processed_units", []).append(unit_key)
            print(f"✅ Unitatea marcată ca procesată: {unit_name} ({action_type})")
        self._save_state()

    def _save_state(self):
        """Salveaza starea in fisierul JSON"""
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠ Nu am putut salva starea: {e}")

    def setup_chrome_driver(self):
        """Configureaza driver-ul Chrome"""
        try:
            print("🔧 Initializare WebDriver – incerc conectare la instanta Chrome existenta...")
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
            prefs = {
                "download.default_directory": os.path.abspath(os.getcwd()),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
            }
            chrome_options.add_experimental_option("prefs", prefs)
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
                self.wait = WebDriverWait(self.driver, self.timeout)
                self.attached_existing = True
                print("✅ Conectat la instanta Chrome existenta cu succes.")
                return True
            except WebDriverException as e:
                print(f"⚠ Conexiune la Chrome existent esuat ({e}); pornesc o instanta noua.")
                chrome_options = Options()
                chrome_options.add_experimental_option("prefs", prefs)
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--window-size=1920,1080")
                self.driver = webdriver.Chrome(options=chrome_options)
                self.wait = WebDriverWait(self.driver, self.timeout)
                self.attached_existing = False
                print("✅ Chrome nou pornit cu succes.")
                return True
        except WebDriverException as e:
            print(f"❌ Eroare la initializarea WebDriver-ului: {e}")
            return False

    def alphabetical_sort_key(self, folder_name):
        """Creează o cheie de sortare pur alfabetică, ignorând caracterele speciale"""
        clean_name = re.sub(r'[^a-zA-Z\s]', '', folder_name.lower())
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()
        return clean_name

    def scan_folder_structure(self, folder_path):
        """Scanează recursiv structura folderului și returnează o listă de unități de procesat, forțând reevaluarea tuturor"""
        processing_units = []

        try:
            for root, dirs, files in os.walk(folder_path):
                current_path = Path(root)
                if files:  # Procesăm doar dacă există fișiere
                    unit_files = [current_path / f for f in files if (current_path / f).suffix.lower() not in IGNORE_EXTENSIONS]
                    pdf_files = [f for f in unit_files if f.suffix.lower() == '.pdf']
                    unit_name = str(current_path.relative_to(ARCHIVE_PATH))
                    processing_units.append({
                        "path": current_path,
                        "actual_path": current_path,
                        "name": unit_name,
                        "has_pdf": len(pdf_files) > 0,
                        "pdf_files": pdf_files,
                        "all_files": unit_files,
                        "is_root": current_path == folder_path
                    })
                    if self.is_unit_processed(current_path):
                        print(f"⏭️ {unit_name}: DEJA PROCESATĂ, dar forțez reevaluarea")
                    else:
                        print(f"📂 {unit_name}: {len(pdf_files)} PDF-uri, {len(unit_files)} fișiere - NEPROCESATĂ")

            print(f"📊 Unități de procesat pentru {folder_path.name}: {len(processing_units)}")
            return processing_units

        except Exception as e:
            print(f"❌ Eroare la scanarea structurii folderului {folder_path}: {e}")
            return []

    def get_folders_to_process(self):
        """Obtine lista folderelor de procesat, sortate strict alfabetic, reevaluați toate folderele"""
        try:
            all_folders = [f for f in ARCHIVE_PATH.iterdir() if f.is_dir()]
            all_folders.sort(key=lambda x: self.alphabetical_sort_key(x.name))

            print("📋 Primele 10 foldere în ordine alfabetică:")
            for i, folder in enumerate(all_folders[:10]):
                clean_key = self.alphabetical_sort_key(folder.name)
                print(f"   {i+1}. {folder.name} (sortare: '{clean_key}')")

            # Include toate folderele pentru reevaluare, indiferent de starea procesată
            remaining = all_folders

            print(f"📁 Găsite {len(all_folders)} foldere total")
            print(f"📋 Procesate deja: {len(set(self.state.get('processed_folders', [])))}")
            print(f"🎯 Rămân de procesat: {len(remaining)}")

            if remaining:
                print(f"📂 Primul folder de procesat: {remaining[0].name}")
                clean_key_first = self.alphabetical_sort_key(remaining[0].name)
                print(f"   (cheie sortare: '{clean_key_first}')")

            return remaining
        except Exception as e:
            print(f"❌ Eroare la scanarea folderelor: {e}")
            return []

    def clean_title_for_search(self, filename):
        """Curăță numele fișierului pentru căutare pe Internet Archive"""
        name = Path(filename).stem
        print(f"[CLEAN] original filename: {filename}")
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
        print(f"[CLEAN] cleaned title: {name}")
        return name

    def exists_on_archive(self, title):
        """Verifică dacă un titlu există pe Internet Archive folosind API-ul"""
        url = "https://archive.org/advancedsearch.php"
        headers = {"User-Agent": "ArchiveUploader/1.0 (contact@example.com)"}
        params = {
            "q": f'title:({title}*)',
            "fl[]": "identifier",
            "rows": 5,
            "output": "json"
        }
        print(f"[API] Cerere pentru titlu: '{title}' → {url} params={params}")
        for attempt in range(1, 4):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                num_found = data.get("response", {}).get("numFound", 0)
                print(f"[API] Răspuns: numFound={num_found}, raw={data}")
                if num_found > 0:
                    return True
                return False
            except requests.RequestException as e:
                print(f"[API] Eroare attempt {attempt}: {e}")
                time.sleep(2 ** attempt)
        print(f"[API] Eșuat după 3 încercări pentru '{title}'")
        return False

    def delete_folder(self, folder_path):
        """Șterge un folder și toate subfișierele sale"""
        try:
            print(f"🗑️ Șterg folderul: {folder_path}")
            shutil.rmtree(folder_path)
            print(f"✅ Folder șters cu succes: {folder_path}")
            return True
        except Exception as e:
            print(f"❌ Eroare la ștergerea folderului: {e}")
            return False

    def process_single_unit(self, unit):
        """Procesează o singură unitate (orice nivel de folder)"""
        print(f"\n📂 Procesez unitatea: {unit['name']}")

        # Verifică dacă titlul există pe Internet Archive
        search_title = self.clean_title_for_search(unit["all_files"][0].name) if unit["all_files"] else unit["name"]
        if self.exists_on_archive(search_title):
            print(f"📋 Titlul '{search_title}' există deja pe Internet Archive!")
            if self.delete_folder(unit["path"]):
                self.mark_unit_processed(unit["path"], unit["name"], "DELETED")
                return True
            return False

        if unit["has_pdf"]:
            if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
                print(f"⚠ Limita de {MAX_UPLOADS_PER_DAY} upload-uri pe zi atinsă! Opresc.")
                return "limit_reached"

            print(f"📄 PDF găsit în {unit['name']}! Upload IMEDIAT pe archive.org pentru toate fișierele...")
            success = self.upload_files_to_archive(unit["all_files"], unit["name"])
            if success:
                self.state["uploads_today"] += len(unit["all_files"])
                self.state["total_files_uploaded"] += len(unit["all_files"])
                print(f"✅ Upload #{self.state['uploads_today']} reușit pentru {unit['name']} (toate {len(unit['all_files'])} fișiere)")
                print(f"📊 Rămân {MAX_UPLOADS_PER_DAY - self.state['uploads_today']} upload-uri pentru astăzi")
                self.mark_unit_processed(unit["path"], unit["name"], "UPLOAD")
                return True
            else:
                return False
        else:
            print(f"❌ Niciun PDF în {unit['name']} - caut fișier de mutat în d:\\3\\")
            priority_file = self.find_priority_file(unit["all_files"])
            if priority_file:
                success = self.move_file_to_d3(priority_file)
                if success:
                    self.state["folders_moved"] += 1
                    print(f"✅ Fișier mutat din {unit['name']}: {priority_file.name}")
                    self.mark_unit_processed(unit["path"], unit["name"], "MUTAT")
                    return True
                else:
                    return False
            else:
                print(f"⚠ Niciun fișier cu extensiile prioritare găsit în {unit['name']}")
                self.mark_unit_processed(unit["path"], unit["name"], "GOLA")
                return True

    def find_priority_file(self, files):
        """Gaseste primul fisier conform prioritatii"""
        for ext in PRIORITY_EXTENSIONS:
            for file in files:
                if file.suffix.lower() == ext:
                    return file
        return None

    def move_file_to_d3(self, file_path):
        """Muta un fisier in d:\\3\\ cu OVERWRITE"""
        try:
            MOVE_PATH.mkdir(exist_ok=True)
            dest_path = MOVE_PATH / file_path.name
            shutil.copy2(file_path, dest_path)
            print(f"📁 Mutat cu overwrite: {file_path.name} → {dest_path}")
            return True
        except Exception as e:
            print(f"❌ Eroare la mutarea fisierului {file_path}: {e}")
            return False

    def sanitize_title(self, folder_name):
        """Curata numele folderului pentru titlu"""
        title = re.sub(r'[^\w\s-]', ' ', folder_name)
        title = re.sub(r'\s+', ' ', title).strip()
        return title

    def navigate_to_upload_page(self):
        """Navigheaza la pagina de upload"""
        try:
            print(f"🌐 Navighez catre: {ARCHIVE_URL}")
            self.driver.get(ARCHIVE_URL)
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'body')))
            print("✅ Pagina de upload incarcata.")
            return True
        except Exception as e:
            print(f"❌ Eroare la navigarea catre upload: {e}")
            return False

    def upload_files_to_archive(self, files, folder_name):
        """Incarca TOATE fisierele pe archive.org - FARA inchiderea paginii"""
        try:
            print("⚠️ ATENȚIE: NU schimba tab-ul în Chrome în timpul upload-ului!")
            print("🚫 Chrome = INTANGIBLE în următoarele minute!")

            self.driver.execute_script("window.open('');")
            new_window = self.driver.window_handles[-1]
            self.driver.switch_to.window(new_window)

            if not self.navigate_to_upload_page():
                return False

            print(f"📤 Incep incarcarea pentru folderul: {folder_name} ({len(files)} fisiere)")

            time.sleep(2)
            try:
                file_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
            except:
                print("❌ Nu am gasit input-ul pentru fisiere")
                return False

            file_paths = "\n".join([str(f.absolute()) for f in files])
            file_input.send_keys(file_paths)

            print(f"📁 Fisiere trimise: {len(files)}")
            print("⏳ Aștept 3 secunde pentru încărcarea fișierelor...")
            time.sleep(3)

            result = self.fill_form_fields(folder_name)
            if result:
                print("✅ Upload completat cu succes! Pagina rămâne deschisă pentru monitorizare.")
            return result

        except Exception as e:
            print(f"❌ Eroare la incarcarea fisierelor: {e}")
            return False

    def fill_form_fields(self, folder_name):
        """Completează TOATE campurile - Description, Subjects, Date, Collection"""
        try:
            auto_title = self.sanitize_title(folder_name)

            try:
                title_element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#page_title, span.mdata_value.edit_text.required.x-archive-meta-title")))
                title_text = title_element.text.strip() or title_element.get_attribute("title") or auto_title
                print(f"📝 Title detectat: '{title_text}'")
                auto_title = title_text
            except Exception as e:
                print(f"⚠ Nu am putut citi title-ul: {e}")

            description_completed = False
            try:
                desc_wrapper = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#description, span#description")))
                desc_wrapper.click()
                time.sleep(0.5)
                try:
                    iframe = self.driver.find_element(By.TAG_NAME, "iframe")
                    self.driver.switch_to.frame(iframe)
                    editor_body = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body.wysiwyg")))
                    self.driver.execute_script("arguments[0].innerText = arguments[1];", editor_body, auto_title)
                    self.driver.switch_to.default_content()
                    description_completed = True
                    print("📝 Description completată în iframe")
                except Exception:
                    try:
                        self.driver.switch_to.default_content()
                        editor_body = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body.wysiwyg")))
                        self.driver.execute_script("arguments[0].innerText = arguments[1];", editor_body, auto_title)
                        description_completed = True
                        print("📝 Description completată în editor direct")
                    except Exception:
                        print("⚠ Nu am putut completa Description în editor")
            except Exception as e:
                print(f"⚠ Eroare la Description: {e}")

            subjects_completed = False
            try:
                subj_wrapper = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#subjects, span#subjects")))
                subj_wrapper.click()
                time.sleep(0.5)
                try:
                    subj_input = self.driver.find_element(By.CSS_SELECTOR, "input[placeholder*='Add keywords'], input.input_field")
                    subj_input.clear()
                    subj_input.send_keys(auto_title)
                    subjects_completed = True
                    print("📝 Subject tags completate")
                except Exception:
                    inputs = self.driver.find_elements(By.TAG_NAME, "input")
                    for inp in inputs:
                        ph = inp.get_attribute("placeholder") or ""
                        if "keywords" in ph.lower() or "tags" in ph.lower():
                            inp.clear()
                            inp.send_keys(auto_title)
                            subjects_completed = True
                            print("📝 Subject tags completate (fallback)")
                            break
            except Exception as e:
                print(f"⚠ Eroare la Subject tags: {e}")

            date_completed = False
            print("📝 Activez câmpurile de dată prin click pe span...")
            try:
                date_span = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#date_text, span#date_text")))
                date_span.click()
                print("   ✅ Click pe span#date_text efectuat")
                time.sleep(0.8)
                try:
                    year_element = self.wait.until(EC.presence_of_element_located((By.ID, "date_year")))
                    month_element = self.driver.find_element(By.ID, "date_month")
                    day_element = self.driver.find_element(By.ID, "date_day")
                    year_element.click()
                    year_element.clear()
                    year_element.send_keys("1983")
                    self.driver.execute_script("""
                        var month = arguments[0];
                        month.disabled = false;
                        month.readOnly = false;
                        month.classList.remove('disabled');
                        month.removeAttribute('disabled');
                        month.removeAttribute('readonly');
                    """, month_element)
                    month_element.click()
                    month_element.clear()
                    month_element.send_keys("12")
                    self.driver.execute_script("""
                        var day = arguments[0];
                        day.disabled = false;
                        day.readOnly = false;
                        day.classList.remove('disabled');
                        day.removeAttribute('disabled');
                        day.removeAttribute('readonly');
                    """, day_element)
                    day_element.click()
                    day_element.clear()
                    day_element.send_keys("13")
                    current_year = year_element.get_attribute("value")
                    current_month = month_element.get_attribute("value")
                    current_day = day_element.get_attribute("value")
                    print(f"   📊 Valori setate: {current_year}-{current_month}-{current_day}")
                    if current_year == '1983' and current_month == '12' and current_day == '13':
                        date_completed = True
                        print("   ✅ Câmpurile de dată completate cu succes!")
                    else:
                        print(f"   ⚠ Valori incorecte în câmpurile de dată")
                except Exception as date_error:
                    print(f"   ❌ Eroare la completarea câmpurilor de dată: {date_error}")
            except Exception as e:
                print(f"❌ Eroare la activarea câmpurilor de dată: {e}")

            collection_completed = False
            print("📝 Completez câmpul Collection rapid...")
            try:
                result = self.driver.execute_script("""
                    var select = document.querySelector('select.mediatypecollection, select[name="mediatypecollection"]');
                    if (select) {
                        select.value = 'texts:opensource';
                        select.dispatchEvent(new Event('change', { bubbles: true }));
                        return select.value;
                    }
                    return null;
                """)
                if result == "texts:opensource":
                    collection_completed = True
                    print("   ✅ Collection selectată rapid: Community texts")
                else:
                    collection_select = self.driver.find_element(By.CSS_SELECTOR, "select.mediatypecollection, select[name='mediatypecollection']")
                    from selenium.webdriver.support.ui import Select
                    select_obj = Select(collection_select)
                    select_obj.select_by_value("texts:opensource")
                    selected_value = collection_select.get_attribute("value")
                    if selected_value == "texts:opensource":
                        collection_completed = True
                        print("   ✅ Collection selectată (fallback): Community texts")
            except Exception as e:
                print(f"❌ Eroare la selectarea Collection: {e}")

            print("🔍 VERIFICARE FINALĂ - 10 secunde pentru toate câmpurile...")
            all_fields_completed = False
            for check in range(10):
                print(f"   Verificare #{check + 1}/10...")
                try:
                    desc_ok = description_completed
                    subj_ok = subjects_completed
                    year_val = self.driver.execute_script("return document.getElementById('date_year') ? document.getElementById('date_year').value : '';") or ""
                    month_val = self.driver.execute_script("return document.getElementById('date_month') ? document.getElementById('date_month').value : '';") or ""
                    day_val = self.driver.execute_script("return document.getElementById('date_day') ? document.getElementById('date_day').value : '';") or ""
                    date_ok = (year_val == '1983' and month_val == '12' and day_val == '13')
                    coll_val = self.driver.execute_script("return document.querySelector('select.mediatypecollection') ? document.querySelector('select.mediatypecollection').value : '';") or ""
                    coll_ok = (coll_val == "texts:opensource")
                    print(f"   Status: Desc={desc_ok}, Subj={subj_ok}, Date={date_ok} [{year_val}-{month_val}-{day_val}], Coll={coll_ok}")
                    if desc_ok and subj_ok and date_ok and coll_ok:
                        print("   ✅ TOATE câmpurile sunt completate și verificate!")
                        all_fields_completed = True
                        break
                    else:
                        print("   ⚠ Unele câmpuri nu sunt completate, mai verific...")
                        time.sleep(1)
                except Exception as verify_error:
                    print(f"   ❌ Eroare la verificare: {verify_error}")
                    time.sleep(1)

            if not all_fields_completed:
                print("❌ OPRESC UPLOAD-UL - NU toate câmpurile sunt completate!")
                try:
                    final_status = self.driver.execute_script("""
                        return {
                            year: document.getElementById('date_year') ? document.getElementById('date_year').value : 'LIPSESTE',
                            month: document.getElementById('date_month') ? document.getElementById('date_month').value : 'LIPSESTE',
                            day: document.getElementById('date_day') ? document.getElementById('date_day').value : 'LIPSESTE',
                            collection: document.querySelector('select.mediatypecollection') ? document.querySelector('select.mediatypecollection').value : 'LIPSESTE'
                        };
                    """)
                    print(f"📊 Status final pentru debug: {final_status}")
                except:
                    pass
                return False

            print("✅ TOATE câmpurile verificate și completate - ÎNCEPE UPLOAD-UL!")
            try:
                upload_final_button = self.wait.until(EC.element_to_be_clickable((By.ID, "upload_button")))
                upload_final_button.click()
                print("✅ Upload inițiat - pagina rămâne deschisă pentru monitorizare!")
                time.sleep(3)
                return True
            except Exception as e:
                print(f"❌ Nu am putut apăsa butonul de upload: {e}")
                return False
        except Exception as e:
            print(f"❌ Eroare generală la completarea formularului: {e}")
            return False

    def process_folder(self, folder_path):
        """Procesează un folder împărțindu-l în unități (toate nivelurile) și șterge folderul părinte dacă devine gol"""
        print(f"\n📂 Procesez folderul: {folder_path.name}")
        processing_units = self.scan_folder_structure(folder_path)
        if not processing_units:
            print(f"✅ Toate unitățile din {folder_path.name} au fost procesate sau reevaluate!")
            self._cleanup_empty_parent(folder_path)
            if str(folder_path) not in self.state.get("processed_folders", []):
                self.state.setdefault("processed_folders", []).append(str(folder_path))
                self.state["last_processed_folder"] = folder_path.name
                self._save_state()
            return True

        all_success = True
        for i, unit in enumerate(processing_units, 1):
            print(f"\n📊 Unitatea {i}/{len(processing_units)} din {folder_path.name}")
            try:
                result = self.process_single_unit(unit)
                if result and unit["has_pdf"]:
                    time.sleep(2)  # Redus de la 10 la 2 secunde după upload
                if result == "limit_reached":
                    print(f"🎯 Limita de {MAX_UPLOADS_PER_DAY} upload-uri atinsă!")
                    return "limit_reached"
                elif not result:
                    print(f"⚠ Eșec la procesarea unității {unit['name']}")
                    all_success = False
            except Exception as e:
                print(f"❌ Eroare la procesarea unității {unit['name']}: {e}")
                all_success = False
                continue

        if all_success:
            if str(folder_path) not in self.state.get("processed_folders", []):
                self.state.setdefault("processed_folders", []).append(str(folder_path))
                self.state["last_processed_folder"] = folder_path.name
                self._save_state()
                print(f"✅ Folderul {folder_path.name} complet procesat!")
            self._cleanup_empty_parent(folder_path)
        return all_success

        if all_success:
            if str(folder_path) not in self.state.get("processed_folders", []):
                self.state.setdefault("processed_folders", []).append(str(folder_path))
                self.state["last_processed_folder"] = folder_path.name
                self._save_state()
                print(f"✅ Folderul {folder_path.name} complet procesat!")
            # Verifică și șterge folderul părinte dacă este gol după procesare
            self._cleanup_empty_parent(folder_path)
        return all_success

    def _cleanup_empty_parent(self, folder_path):
        """Șterge folderul părinte dacă este gol, ignorând fișierele de sistem"""
        try:
            # Verifică dacă folderul conține doar fișiere de sistem sau este gol
            has_non_system_content = False
            for item in folder_path.iterdir():
                if not item.name.startswith('.') and item.name not in ['Thumbs.db', 'desktop.ini']:
                    has_non_system_content = True
                    break
            if not has_non_system_content:
                if self.delete_folder(folder_path):
                    if str(folder_path) in self.state.get("processed_folders", []):
                        self.state["processed_folders"].remove(str(folder_path))
                        self._save_state()
                    print(f"✅ Folderul părinte {folder_path.name} șters pentru că este gol sau conține doar fișiere de sistem")
        except Exception as e:
            print(f"⚠ Eroare la verificarea/ștergerea folderului părinte {folder_path}: {e}")

    def clean_filename(self, filename):
        """Curăță și standardizează numele fișierului"""
        filename = re.sub(r'^C:\\fakepath\\', '', filename)
        filename = re.sub(r'\.[a-zA-Z0-9]+$', '', filename)
        filename = re.sub(r'-', ' ', filename)
        filename = ' '.join(word.capitalize() for word in filename.split())
        filename = re.sub(r'_(\d+)$', '', filename)
        print(f"   📁 Nume fișier curățat: '{filename}'")
        return filename

    def extract_filename_from_xml(self, xml_content):
        """Extrage numele fișierului din conținutul XML sau din alte surse"""
        try:
            resource_match = re.search(r"Your upload of ([^\s]+) from username", xml_content)
            if resource_match:
                filename = resource_match.group(1)
                return self.clean_filename(filename)
            try:
                file_elements = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file'], .upload-filename, .file-name")
                for element in file_elements:
                    filename = element.get_attribute("value") or element.text.strip() or "fisier-necunoscut"
                    if filename and filename != "fisier-necunoscut":
                        return self.clean_filename(filename)
            except NoSuchElementException:
                pass
            page_title = self.driver.title
            if page_title and page_title != "Upload to Internet Archive":
                return self.clean_filename(page_title)
            return "fisier-necunoscut"
        except Exception as e:
            print(f"   ❌ Eroare la extragerea numelui fișierului: {e}")
            return "fisier-necunoscut"

    def get_error_details_from_popup(self):
        """Extrage detaliile erorii din pop-up-ul deschis sau nedesfăcut"""
        try:
            print("   🔍 Verific starea pop-up-ului de eroare...")
            error_details_div = self.wait.until(EC.presence_of_element_located((By.ID, "upload_error_details")))
            display_style = error_details_div.get_attribute("style")
            is_visible = "display: block" in display_style or "display:block" in display_style

            if not is_visible:
                print("   🔒 Detaliile sunt ascunse, încerc să le desfac...")
                try:
                    details_link = self.wait.until(EC.element_to_be_clickable((By.ID, "upload_error_show_details")))
                    for attempt in range(3):
                        try:
                            self.driver.execute_script("arguments[0].click();", details_link)
                            error_details_div = self.wait.until(EC.visibility_of_element_located((By.ID, "upload_error_details")))
                            break
                        except TimeoutException:
                            if attempt == 2:
                                self.driver.execute_script("document.getElementById('upload_error_details').style.display = 'block';")
                                error_details_div = self.wait.until(EC.visibility_of_element_located((By.ID, "upload_error_details")))
                                break
                            time.sleep(1)
                except TimeoutException:
                    print("   ⚠️ Timeout: Nu am găsit linkul pentru detalii")
                    return None
            try:
                pre_element = error_details_div.find_element(By.TAG_NAME, "pre")
                xml_content = pre_element.text.strip()
                xml_content = xml_content.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                print("   ✅ CONȚINUT XML GĂSIT!")
                print("   " + "="*50)
                print("   " + xml_content)
                print("   " + "="*50)
                return xml_content
            except NoSuchElementException:
                print("   ⚠️ Nu am găsit elementul <pre> în #upload_error_details")
                return None
        except TimeoutException:
            print("   ⚠️ Timeout: Nu am găsit elementul #upload_error_details")
            return None
        except Exception as e:
            print(f"   ❌ Eroare la extragerea detaliilor: {e}")
            return None

    def get_error_code_and_status(self):
        """Extrage codul și statusul erorii din pop-up"""
        try:
            error_code_element = self.driver.find_element(By.ID, "upload_error_code")
            error_status_element = self.driver.find_element(By.ID, "upload_error_status")
            error_code = error_code_element.text.strip()
            error_status = error_status_element.text.strip()
            print(f"   📊 Cod eroare: {error_code}")
            print(f"   📊 Status eroare: {error_status}")
            return error_code, error_status
        except NoSuchElementException:
            print("   ⚠️ Nu am găsit elementele pentru codul/statusul erorii")
            try:
                error_text = self.driver.find_element(By.ID, "upload_error_text").text
                match = re.search(r'(\d{3})\s*([^<]+)', error_text)
                if match:
                    return match.groups()
            except NoSuchElementException:
                pass
            return "unknown", "unknown"

    def check_single_tab_for_errors(self, window_handle, tab_index):
        """Verifică o singură filă pentru erori 404 sau 505, inclusiv pop-up-uri"""
        print(f"\n📋 === VERIFIC FILA #{tab_index}: {window_handle} ===")
        try:
            self.driver.switch_to.window(window_handle)
            time.sleep(1)
            current_url = self.driver.current_url
            print(f"   🌐 URL: {current_url}")
            page_title = self.driver.title
            print(f"   📄 Titlu pagină: '{page_title}'")
            print("   🔍 Caut mesajul de eroare...")
            try:
                error_div = self.driver.find_element(By.ID, "progress_msg")
                error_text = error_div.text.strip()
                print(f"   📝 Text găsit în #progress_msg: '{error_text}'")
                if "There is a network problem" in error_text or "network problem" in error_text.lower():
                    print("   🚨 EROARE DE NETWORK DETECTATĂ!")
                error_code, error_status = self.get_error_code_and_status()
                if error_code in ["404", "505", "503"]:
                    print(f"   🚨 EROARE DETECTATĂ CU COD: {error_code} {error_status}")
                    xml_content = self.get_error_details_from_popup()
                    filename = self.extract_filename_from_xml(xml_content) if xml_content else "fisier-necunoscut"
                    return {
                        "filename": filename,
                        "page_title": page_title,
                        "window_handle": window_handle,
                        "error_code": error_code,
                        "error_status": error_status,
                        "error_details": xml_content or "Nu s-au putut obține detalii XML",
                        "timestamp": datetime.now().isoformat()
                    }
                print("   ✅ Nu este eroare 404 sau 505 relevantă")
                return None
            except NoSuchElementException:
                print("   ✅ Nu există elementul #progress_msg - nu sunt erori")
                return None
        except Exception as e:
            print(f"   ❌ Eroare la verificarea filei: {e}")
            return None

    def normalize_filename_for_matching(self, filename):
        """Normalizează numele fișierului pentru comparație"""
        name = Path(filename).stem if isinstance(filename, (str, Path)) else str(filename)
        name = name.lower()
        name = re.sub(r'[^\w\s]', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        name = name.replace(' ', '-')
        return name

    def find_original_file_for_error(self, error_filename, search_folders):
        """Găsește fișierul original pe baza numelui din eroare"""
        print(f"🔍 Caut fișierul original pentru: '{error_filename}'")
        normalized_error = self.normalize_filename_for_matching(error_filename)
        print(f"   📝 Nume normalizat din eroare: '{normalized_error}'")
        candidates = []
        for folder_path in search_folders:
            if not folder_path.exists():
                continue
            try:
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = Path(root) / file
                        if file_path.suffix.lower() in ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc']:
                            normalized_file = self.normalize_filename_for_matching(file)
                            similarity = difflib.SequenceMatcher(None, normalized_error, normalized_file).ratio()
                            if similarity > 0.6:
                                candidates.append({
                                    'path': file_path,
                                    'similarity': similarity,
                                    'normalized_name': normalized_file
                                })
                                print(f"   📋 Candidat găsit: {file} (similaritate: {similarity:.2f})")
            except Exception as e:
                print(f"   ⚠️ Eroare la scanarea folderului {folder_path}: {e}")
        candidates.sort(key=lambda x: x['similarity'], reverse=True)
        if candidates:
            best_match = candidates[0]
            print(f"   ✅ Cea mai bună potrivire: {best_match['path'].name} (similaritate: {best_match['similarity']:.2f})")
            return best_match['path']
        print(f"   ❌ Nu am găsit fișierul original pentru '{error_filename}'")
        return None

    def copy_error_files_to_temp(self, failed_uploads):
        """Copiază fișierele cu erori direct în folderul TEMP - versiune simplificată"""
        if not failed_uploads:
            print("✅ Nu sunt fișiere cu erori de copiat")
            return []

        print(f"\n📁 === COPIERE FIȘIERE CU ERORI ÎN {TEMP_PATH} ===")
        try:
            TEMP_PATH.mkdir(exist_ok=True)
            print(f"📂 Folderul TEMP pregătit: {TEMP_PATH}")
        except Exception as e:
            print(f"❌ Eroare la crearea folderului TEMP: {e}")
            return []

        processed_folders = []
        for folder_path_str in self.state.get("processed_folders", []):
            folder_path = Path(folder_path_str)
            if folder_path.exists():
                processed_folders.append(folder_path)
        if ARCHIVE_PATH.exists():
            processed_folders.append(ARCHIVE_PATH)

        print(f"🔍 Voi căuta în {len(processed_folders)} foldere pentru fișierele cu erori")
        copied_files = []
        failed_copies = []
        for i, error_info in enumerate(failed_uploads, 1):
            print(f"\n📋 Procesez eroarea {i}/{len(failed_uploads)}: {error_info['filename']}")
            original_file = self.find_original_file_for_error(error_info['filename'], processed_folders)
            if not original_file:
                failed_copies.append({
                    'error_info': error_info,
                    'reason': 'Fișierul original nu a fost găsit'
                })
                continue
            try:
                original_name = original_file.stem
                original_ext = original_file.suffix
                error_code = error_info.get('error_code', 'unknown')
                timestamp = datetime.now().strftime("%H%M%S")
                dest_filename = f"{original_name}_ERROR-{error_code}_{timestamp}{original_ext}"
                dest_path = TEMP_PATH / dest_filename
                info_filename = f"{original_name}_ERROR-{error_code}_{timestamp}_INFO.txt"
                info_path = TEMP_PATH / info_filename
                print(f"   📁 Copiez: {original_file.name}")
                print(f"   📁    → {dest_path}")
                shutil.copy2(original_file, dest_path)
                with open(info_path, 'w', encoding='utf-8') as f:
                    f.write(f"INFORMAȚII DESPRE EROAREA DE UPLOAD\n")
                    f.write("=" * 40 + "\n\n")
                    f.write(f"Fișier original: {original_file}\n")
                    f.write(f"Nume din eroare: {error_info['filename']}\n")
                    f.write(f"Cod eroare: {error_info['error_code']}\n")
                    f.write(f"Status eroare: {error_info['error_status']}\n")
                    f.write(f"Timestamp eroare: {error_info['timestamp']}\n")
                    f.write(f"Titlu pagină: {error_info['page_title']}\n\n")
                    f.write(f"DETALII XML EROARE:\n")
                    f.write("-" * 20 + "\n")
                    f.write(error_info.get('error_details', 'Nu sunt disponibile detalii XML'))
                copied_files.append({
                    'original_path': original_file,
                    'copied_path': dest_path,
                    'info_path': info_path,
                    'error_code': error_code,
                    'error_info': error_info
                })
                print(f"   ✅ Copiat cu succes în TEMP: {dest_filename}")
            except Exception as e:
                print(f"   ❌ Eroare la copierea fișierului {original_file}: {e}")
                failed_copies.append({
                    'error_info': error_info,
                    'original_file': original_file,
                    'reason': str(e)
                })
        print(f"\n📊 === RAPORT COPIERE FIȘIERE CU ERORI ===")
        print(f"✅ Fișiere copiate cu succes: {len(copied_files)}")
        print(f"❌ Eșecuri la copiere: {len(failed_copies)}")
        if copied_files:
            print(f"\n📁 FIȘIERE COPIATE ÎN {TEMP_PATH}:")
            for copied in copied_files:
                print(f"   📄 {copied['copied_path'].name}")
                print(f"   ℹ️  {copied['info_path'].name}")
        if failed_copies:
            print(f"\n❌ EȘECURI LA COPIERE:")
            for failed in failed_copies:
                print(f"   📄 {failed['error_info']['filename']}")
                print(f"      Motiv: {failed['reason']}")
        return copied_files

    def check_for_errors_after_upload(self):
        """Verifică toate filele deschise pentru erori 404, 505 sau 503 după 5 minute de la ultimul upload
        și copiază automat fișierele cu erori în g:\\TEMP\\"""
        print("\n⏳ Aștept 5 minute după ultimul upload pentru a verifica erorile...")
        time.sleep(90)  # Așteaptă 5 minute
        print("\n🔍 === ÎNCEPUT VERIFICARE ERORI 404/505/503 DUPĂ UPLOAD ===")
        if not self.driver:
            print("❌ Driver-ul Chrome nu este disponibil")
            return

        try:
            current_window = self.driver.current_window_handle
            all_windows = self.driver.window_handles
            print(f"📊 Găsite {len(all_windows)} file deschise în Chrome")
            print(f"🏠 Fereastra curentă: {current_window}")
            print("   📋 Lista tuturor filelor:")
            for i, window_handle in enumerate(all_windows, 1):
                self.driver.switch_to.window(window_handle)
                print(f"   {i}. {window_handle} - URL: {self.driver.current_url} - Titlu: {self.driver.title}")

            failed_uploads = []
            for i, window_handle in enumerate(all_windows, 1):
                error_info = self.check_single_tab_for_errors(window_handle, i)
                if error_info and error_info["error_code"] in ["404", "505", "503"]:
                    failed_uploads.append(error_info)
                    print(f"   🚨 EROARE {error_info['error_code']}/{error_info['error_status']} CONFIRMATĂ în fila #{i}")
                else:
                    print(f"   ✅ Fila #{i} - OK, nu există erori 404/505/503")
                time.sleep(2)

            try:
                if current_window in self.driver.window_handles:
                    self.driver.switch_to.window(current_window)
                    print(f"\n🏠 M-am întors la fereastra originală: {current_window}")
                elif self.driver.window_handles:
                    self.driver.switch_to.window(self.driver.window_handles[0])
                    print(f"\n🏠 M-am întors la prima fereastră disponibilă")
            except Exception as switch_error:
                print(f"⚠️ Nu am putut reveni la fereastra originală: {switch_error}")

            print(f"\n📊 === REZULTAT FINAL VERIFICARE ERORI ===")
            print(f"🔍 File verificate: {len(all_windows)}")
            print(f"🚨 Erori 404/505/503 găsite: {len(failed_uploads)}")

            # NOUĂ FUNCȚIONALITATE: Copiază fișierele cu erori în TEMP
            copied_files = []
            if failed_uploads:
                print(f"\n📁 === ÎNCEPE COPIEREA FIȘIERELOR CU ERORI ===")
                copied_files = self.copy_error_files_to_temp(failed_uploads)

            failed_uploads_list = []
            if failed_uploads:
                print(f"\n📋 LISTA FIȘIERELOR CU ERORI (404/505/503):")
                for i, error in enumerate(failed_uploads, 1):
                    print(f"   {i}. 📖 {error['filename']}")
                    print(f"      📄 Titlu: {error['page_title']}")
                    print(f"      🚨 Eroare: {error['error_code']} {error['error_status']}")
                    print(f"      🕒 Timp: {error['timestamp']}")
                    if len(error['error_details']) > 100:
                        print(f"      📝 Detalii: {error['error_details'][:100]}...")
                    else:
                        print(f"      📝 Detalii: {error['error_details']}")
                    failed_uploads_list.append(error['filename'])
            else:
                print("✅ Nu au fost găsite erori 404/505/503 în nicio filă!")

            # Salvează rezultatele în fișierul text original
            filename = f"upload_errors_with_404_505_503_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            if failed_uploads_list or not failed_uploads:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"LISTA FIȘIERELOR CU ERORI (404/505/503) - {datetime.now().isoformat()}\n")
                    f.write("=" * 60 + "\n\n")
                    if failed_uploads:
                        for i, error in enumerate(failed_uploads, 1):
                            f.write(f"{i}. 📖 {error['filename']} (Cod: {error['error_code']}, Status: {error['error_status']})\n")
                    else:
                        f.write("✅ Nu au fost detectate erori 404/505/503 în nicio filă.\n")

                    # Adaugă informații despre fișierele copiate
                    if copied_files:
                        f.write(f"\n" + "=" * 60 + "\n")
                        f.write(f"FIȘIERE COPIATE ÎN {TEMP_PATH}:\n")
                        f.write("=" * 60 + "\n\n")
                        for copied in copied_files:
                            f.write(f"📁 {copied['original_path'].name}\n")
                            f.write(f"   → Copiat în: {copied['copied_path']}\n")
                            f.write(f"   → Info file: {copied['info_path']}\n")
                            f.write(f"   → Cod eroare: {copied['error_code']}\n\n")

                print(f"📄 Rezultatele erorilor au fost salvate în: {filename}")

            return failed_uploads
        except Exception as e:
            print(f"❌ Eroare generală la verificarea erorilor: {e}")
            return []

    def save_error_results_to_file(self, filenames):
        """Salvează lista finală a titlurilor cu erori 404/505 într-un fișier"""
        try:
            filename = f"upload_errors_with_404_505_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"LISTA FIȘIERELOR CU ERORI 404/505 - {datetime.now().isoformat()}\n")
                f.write("=" * 60 + "\n\n")
                if filenames:
                    for i, file_name in enumerate(filenames, 1):
                        f.write(f"{i}. 📖 {file_name}\n")
                else:
                    f.write("✅ Nu au fost detectate erori 404/505 în nicio filă.\n")
            print(f"📄 Rezultatele erorilor au fost salvate în: {filename}")
        except Exception as e:
            print(f"⚠️ Nu am putut salva rezultatele erorilor în fișier: {e}")

    def run(self):
        """Executa procesul principal"""
        print("🚀 Încep executarea Archive.org Uploader")
        print("=" * 60)
        print("⚠️ IMPORTANT: NU schimba tab-ul în Chrome în timpul upload-urilor!")
        print("🚫 Hands off Chrome during uploads - lasă să lucreze singur!")
        print("=" * 60)

        try:
            if not self.setup_chrome_driver():
                return False

            MOVE_PATH.mkdir(exist_ok=True)
            TEMP_PATH.mkdir(exist_ok=True)  # Creează și folderul TEMP
            folders_to_process = self.get_folders_to_process()

            if not folders_to_process:
                print("✅ Nu mai sunt foldere de procesat pentru astăzi!")
                return True

            print(f"🎯 Procesez foldere până la limita de {MAX_UPLOADS_PER_DAY} upload-uri...")
            print(f"📊 Upload-uri deja făcute astăzi: {self.state['uploads_today']}")

            if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
                print(f"✅ Limita de {MAX_UPLOADS_PER_DAY} upload-uri deja atinsă pentru astăzi!")
                return True

            for i, folder in enumerate(folders_to_process, 1):
                print(f"\n📊 Progres: {i}/{len(folders_to_process)}")
                try:
                    result = self.process_folder(folder)
                    if result == "limit_reached":
                        print(f"🎯 Limita de {MAX_UPLOADS_PER_DAY} upload-uri atinsă! Opresc procesarea.")
                        break
                    elif not result:
                        print(f"⚠ Eșec la procesarea folderului {folder.name}")
                    print("⏳ Pauză 3 secunde...")
                    time.sleep(3)
                except KeyboardInterrupt:
                    print("\n⚠ Încetat de utilizator")
                    break
                except Exception as e:
                    print(f"❌ Eroare la procesarea folderului {folder}: {e}")
                    continue

            self.check_for_errors_after_upload()

            print(f"\n📊 RAPORT FINAL:")
            print(f"📤 Upload-uri pe archive.org astăzi: {self.state['uploads_today']}/{MAX_UPLOADS_PER_DAY}")
            print(f"📁 Foldere cu fișiere mutate în d:\\3\\: {self.state['folders_moved']}")
            print(f"📄 Total fișiere încărcate: {self.state['total_files_uploaded']}")
            print(f"📋 Total foldere procesate: {len(self.state['processed_folders'])}")
            print(f"🗂️ Fișiere cu erori copiate în: {TEMP_PATH}")

            if self.state['uploads_today'] >= MAX_UPLOADS_PER_DAY:
                print(f"🎯 LIMITA ZILNICĂ ATINSĂ! Nu mai pot face upload-uri astăzi.")

            return True
        except KeyboardInterrupt:
            print("\n⚠ Executie întreruptă manual")
            return False
        except Exception as e:
            print(f"\n❌ Eroare neașteptată: {e}")
            return False
        finally:
            if not self.attached_existing and self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass

def main():
    """Functia principala"""
    if not ARCHIVE_PATH.exists():
        print(f"❌ Directorul sursa nu exista: {ARCHIVE_PATH}")
        return False

    print(f"📁 Director sursa: {ARCHIVE_PATH}")
    print(f"📁 Director destinatie: {MOVE_PATH}")
    print(f"🗂️ Director pentru erori: {TEMP_PATH}")
    print(f"🎯 Upload-uri maxime pe zi: {MAX_UPLOADS_PER_DAY}")
    print(f"\n🚨 REGULA DE AUR: NU atinge Chrome în timpul upload-urilor!")

    uploader = ArchiveUploader()
    success = uploader.run()

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Eroare fatală: {e}")
        sys.exit(1)