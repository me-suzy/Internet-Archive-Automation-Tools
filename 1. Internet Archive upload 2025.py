#!/usr/bin/env python3
"""
Automatizare incarcare fisiere pe Archive.org - Versiunea cu Subfoldere:
- Scaneaza RECURSIV folderele din g:\\ARHIVA\\B\\ (inclusiv subfoldere)
- Pentru foldere cu PDF: incarca toate fisierele (exceptand .jpg/.png) pe archive.org
- Pentru foldere fara PDF: muta un fisier specific in d:\\3\\ cu OVERWRITE
- Prioritate fisiere: .mobi, .epub, .djvu, .docx, .doc, .lit, rtf
- Completeaza automat campurile pe archive.org
- Limita: maxim 200 upload-uri pe zi
- Pastreaza evidenta progresului in state_archive.json

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
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException

# Configurari
ARCHIVE_PATH = Path(r"g:\ARHIVA\B")
MOVE_PATH = Path(r"d:\3")
ARCHIVE_URL = "https://archive.org/upload"
MAX_UPLOADS_PER_DAY = 200
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
                "processed_units": [],  # ADĂUGAT: salvează toate unitățile procesate
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
                        # Aceeasi zi - pastreaza totul
                        self.state = loaded
                        # Asigură compatibilitatea cu versiunea veche
                        if "processed_units" not in self.state:
                            self.state["processed_units"] = []
                        print(f"📋 Încărcat starea pentru {today}: {self.state.get('uploads_today', 0)} upload-uri, {len(self.state.get('processed_units', []))} unități procesate")
                    else:
                        # Zi noua - reseteaza
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

        # Adaugă în lista de unități procesate dacă nu există
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

            # Permite descarcari automate
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
            import re
            # Elimină toate caracterele care nu sunt litere sau spații
            clean_name = re.sub(r'[^a-zA-Z\s]', '', folder_name.lower())
            # Înlocuiește spațiile multiple cu unul singur
            clean_name = re.sub(r'\s+', ' ', clean_name).strip()
            return clean_name

    def scan_folder_structure(self, folder_path):
        """Scanează structura folderului și returnează o listă de unități de procesat"""
        processing_units = []

        try:
            # 1. Procesează fișierele din ROOT-ul folderului principal
            root_files = []
            root_pdf_files = []

            for item in folder_path.iterdir():
                if item.is_file() and item.suffix.lower() not in IGNORE_EXTENSIONS:
                    root_files.append(item)
                    if item.suffix.lower() == '.pdf':
                        root_pdf_files.append(item)

            # Dacă sunt fișiere în root, adaugă ca unitate de procesat (doar dacă nu e procesată)
            if root_files:
                root_unit_path = folder_path / "__ROOT__"  # Identificator unic pentru ROOT
                if not self.is_unit_processed(root_unit_path):
                    processing_units.append({
                        "path": root_unit_path,
                        "actual_path": folder_path,
                        "name": f"{folder_path.name} (ROOT)",
                        "has_pdf": len(root_pdf_files) > 0,
                        "pdf_files": root_pdf_files,
                        "all_files": root_files,
                        "is_root": True
                    })
                    print(f"📂 ROOT {folder_path.name}: {len(root_pdf_files)} PDF-uri, {len(root_files)} fișiere - NEPROCESATĂ")
                else:
                    print(f"⏭️ ROOT {folder_path.name}: DEJA PROCESATĂ")

            # 2. Procesează fiecare SUBFOLDER individual
            for item in folder_path.iterdir():
                if item.is_dir():
                    # Verifică dacă subfolderul a fost deja procesat
                    if self.is_unit_processed(item):
                        print(f"⏭️ SUBFOLDER {item.name}: DEJA PROCESAT")
                        continue

                    subfolder_files = []
                    subfolder_pdf_files = []

                    # Scanează DOAR acest subfolder (nu recursiv)
                    for subitem in item.iterdir():
                        if subitem.is_file() and subitem.suffix.lower() not in IGNORE_EXTENSIONS:
                            subfolder_files.append(subitem)
                            if subitem.suffix.lower() == '.pdf':
                                subfolder_pdf_files.append(subitem)

                    # Dacă subfolderul conține fișiere, adaugă ca unitate de procesat
                    if subfolder_files:
                        processing_units.append({
                            "path": item,
                            "actual_path": item,
                            "name": f"{folder_path.name}/{item.name}",
                            "has_pdf": len(subfolder_pdf_files) > 0,
                            "pdf_files": subfolder_pdf_files,
                            "all_files": subfolder_files,
                            "is_root": False
                        })
                        print(f"📂 SUBFOLDER {item.name}: {len(subfolder_pdf_files)} PDF-uri, {len(subfolder_files)} fișiere - NEPROCESATĂ")

            print(f"📊 Unități NOI de procesat pentru {folder_path.name}: {len(processing_units)}")
            return processing_units

        except Exception as e:
            print(f"❌ Eroare la scanarea structurii folderului {folder_path}: {e}")
            return []

    def process_single_unit(self, unit):
        """Procesează o singură unitate (ROOT sau subfolder)"""
        print(f"\n📂 Procesez unitatea: {unit['name']}")

        if unit["has_pdf"]:
            # VERIFICĂ LIMITA ÎNAINTE DE UPLOAD
            if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
                print(f"⚠ Limita de {MAX_UPLOADS_PER_DAY} upload-uri pe zi atinsă! Opresc.")
                return "limit_reached"

            # Unitate cu PDF - încarcă pe archive.org
            print(f"📄 PDF găsit în {unit['name']}! Upload IMEDIAT pe archive.org...")
            success = self.upload_files_to_archive(unit["all_files"], unit["name"])
            if success:
                self.state["uploads_today"] += 1
                self.state["total_files_uploaded"] += len(unit["all_files"])
                print(f"✅ Upload #{self.state['uploads_today']} reușit pentru {unit['name']}")
                print(f"📊 Rămân {MAX_UPLOADS_PER_DAY - self.state['uploads_today']} upload-uri pentru astăzi")

                # MARCHEAZĂ UNITATEA CA PROCESATĂ
                self.mark_unit_processed(unit["path"], unit["name"], "UPLOAD")
                return True
            else:
                return False
        else:
            # Unitate fără PDF - mută fișier în d:\3\
            print(f"❌ Niciun PDF în {unit['name']} - caut fișier de mutat în d:\\3\\")
            priority_file = self.find_priority_file(unit["all_files"])

            if priority_file:
                success = self.move_file_to_d3(priority_file)
                if success:
                    self.state["folders_moved"] += 1
                    print(f"✅ Fișier mutat din {unit['name']}: {priority_file.name}")

                    # MARCHEAZĂ UNITATEA CA PROCESATĂ
                    self.mark_unit_processed(unit["path"], unit["name"], "MUTAT")
                    return True
                else:
                    return False
            else:
                print(f"⚠ Niciun fișier cu extensiile prioritare găsit în {unit['name']}")

                # MARCHEAZĂ CA PROCESATĂ CHIAR DACĂ NU A FĂCUT NIMIC
                self.mark_unit_processed(unit["path"], unit["name"], "GOLA")
                return True  # Nu e o eroare, marcăm ca procesat



    def get_folders_to_process(self):
        """Obtine lista folderelor de procesat, sortate STRICT alfabetic"""
        try:
            # Obtine toate folderele
            all_folders = [f for f in ARCHIVE_PATH.iterdir() if f.is_dir()]

            # Sortează STRICT alfabetic, ignorând caracterele speciale
            all_folders.sort(key=lambda x: self.alphabetical_sort_key(x.name))

            # DEBUG: Afișează primele 10 foldere pentru verificare
            print("📋 Primele 10 foldere în ordine alfabetică:")
            for i, folder in enumerate(all_folders[:10]):
                clean_key = self.alphabetical_sort_key(folder.name)
                print(f"   {i+1}. {folder.name} (sortare: '{clean_key}')")

            processed = set(self.state.get("processed_folders", []))

            # Filtrează folderele deja procesate, păstrând ordinea alfabetică
            remaining = [f for f in all_folders if str(f) not in processed]

            print(f"📁 Găsite {len(all_folders)} foldere total")
            print(f"📋 Procesate deja: {len(processed)}")
            print(f"🎯 Rămân de procesat: {len(remaining)}")

            if remaining:
                print(f"📂 Primul folder de procesat: {remaining[0].name}")
                clean_key_first = self.alphabetical_sort_key(remaining[0].name)
                print(f"   (cheie sortare: '{clean_key_first}')")

            return remaining
        except Exception as e:
            print(f"❌ Eroare la scanarea folderelor: {e}")
            return []

    def scan_folder_recursive(self, folder_path):
        """Scaneaza recursiv un folder pentru toate fisierele"""
        all_files = []
        pdf_files = []

        try:
            # Scanare recursiva prin toate subfolderele
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = Path(root) / file

                    # Ignora fisierele cu extensii nedorite
                    if file_path.suffix.lower() not in IGNORE_EXTENSIONS:
                        all_files.append(file_path)

                        # Marcheaza fisierele PDF
                        if file_path.suffix.lower() == '.pdf':
                            pdf_files.append(file_path)

            print(f"📂 {folder_path.name}: Gasit {len(pdf_files)} PDF-uri, {len(all_files)} fisiere total")

            return {
                "has_pdf": len(pdf_files) > 0,
                "pdf_files": pdf_files,
                "all_files": all_files,
                "folder_name": folder_path.name
            }

        except Exception as e:
            print(f"❌ Eroare la scanarea recursiva a folderului {folder_path}: {e}")
            return None

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

            # OVERWRITE - nu mai verifica daca exista
            shutil.copy2(file_path, dest_path)
            print(f"📁 Mutat cu overwrite: {file_path.name} → {dest_path}")
            return True

        except Exception as e:
            print(f"❌ Eroare la mutarea fisierului {file_path}: {e}")
            return False

    def sanitize_title(self, folder_name):
        """Curata numele folderului pentru titlu"""
        # Elimina caractere speciale si inlocuieste cu spatii
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
            """Incarca fisierele pe archive.org - FARA inchiderea paginii"""
            try:
                # Deschide o fila noua pentru upload
                self.driver.execute_script("window.open('');")
                new_window = self.driver.window_handles[-1]
                self.driver.switch_to.window(new_window)

                if not self.navigate_to_upload_page():
                    return False

                print(f"📤 Incep incarcarea pentru folderul: {folder_name} ({len(files)} fisiere)")

                # Asteapta sa se incarce pagina complet - redus la 2 secunde
                time.sleep(2)

                # Gaseste input-ul pentru fisiere
                try:
                    file_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
                except:
                    print("❌ Nu am gasit input-ul pentru fisiere")
                    return False

                # Pregateste calea fisierelor pentru upload
                file_paths = "\n".join([str(f.absolute()) for f in files])

                # Trimite fisierele
                file_input.send_keys(file_paths)

                print(f"📁 Fisiere trimise: {len(files)}")

                # Timpul redus la 3 secunde pentru ca fisierele sa se incarce
                print("⏳ Aștept 3 secunde pentru încărcarea fișierelor...")
                time.sleep(3)

                # Completeaza campurile automat
                result = self.fill_form_fields(folder_name)

                if result:
                    print("✅ Upload completat cu succes! Pagina rămâne deschisă pentru monitorizare.")
                    # NU închide pagina - o lăsăm deschisă pentru că upload-ul continuă

                return result

            except Exception as e:
                print(f"❌ Eroare la incarcarea fisierelor: {e}")
                return False
            # ELIMINAT finally: - nu mai închide pagina deloc!

    def fill_form_fields(self, folder_name):
        """Completează TOATE campurile - Description, Subjects, Date, Collection"""
        try:
            auto_title = self.sanitize_title(folder_name)

            # === TITLE ===
            try:
                title_element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#page_title, span.mdata_value.edit_text.required.x-archive-meta-title")))
                title_text = title_element.text.strip() or title_element.get_attribute("title") or auto_title
                print(f"📝 Title detectat: '{title_text}'")
                auto_title = title_text
            except Exception as e:
                print(f"⚠ Nu am putut citi title-ul: {e}")

            # === DESCRIPTION ===
            description_completed = False
            try:
                desc_wrapper = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#description, span#description")))
                desc_wrapper.click()
                time.sleep(0.5)

                # Încearcă iframe mai întâi
                try:
                    iframe = self.driver.find_element(By.TAG_NAME, "iframe")
                    self.driver.switch_to.frame(iframe)
                    editor_body = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body.wysiwyg")))
                    self.driver.execute_script("arguments[0].innerText = arguments[1];", editor_body, auto_title)
                    self.driver.switch_to.default_content()
                    description_completed = True
                    print("📝 Description completată în iframe")
                except Exception:
                    # Fallback: editorul direct
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

            # === SUBJECT TAGS ===
            subjects_completed = False
            try:
                subj_wrapper = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#subjects, span#subjects")))
                subj_wrapper.click()
                time.sleep(0.5)

                # Caută input-ul pentru subject tags
                try:
                    subj_input = self.driver.find_element(By.CSS_SELECTOR, "input[placeholder*='Add keywords'], input.input_field")
                    subj_input.clear()
                    subj_input.send_keys(auto_title)
                    subjects_completed = True
                    print("📝 Subject tags completate")
                except Exception:
                    # Fallback: caută prin toate input-urile
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

            # === DATE - ACTIVARE PRIN CLICK PE SPAN ===
            date_completed = False
            print("📝 Activez câmpurile de dată prin click pe span...")

            try:
                # CLICK pe span-ul principal pentru a activa câmpurile
                date_span = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#date_text, span#date_text")))
                date_span.click()
                print("   ✅ Click pe span#date_text efectuat")

                # Așteptă să apară câmpurile
                time.sleep(0.8)

                # Completează câmpurile activate
                try:
                    # Găsește câmpurile după activare
                    year_element = self.wait.until(EC.presence_of_element_located((By.ID, "date_year")))
                    month_element = self.driver.find_element(By.ID, "date_month")
                    day_element = self.driver.find_element(By.ID, "date_day")

                    # Completează anul
                    year_element.click()
                    year_element.clear()
                    year_element.send_keys("1983")

                    # Completează luna - elimină disabled
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

                    # Completează ziua - elimină disabled
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

                    # Verifică imediat valorile setate
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

            # === COLLECTION - OPTIMIZAT ===
            collection_completed = False
            print("📝 Completez câmpul Collection rapid...")

            try:
                # Metoda 1: JavaScript direct pentru viteză
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
                    # Fallback: metoda tradițională
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

            # === VERIFICARE FINALĂ OBLIGATORIE - 10 SECUNDE ===
            print("🔍 VERIFICARE FINALĂ - 10 secunde pentru toate câmpurile...")

            all_fields_completed = False

            for check in range(10):  # 10 secunde de verificare
                print(f"   Verificare #{check + 1}/10...")

                # Verifică toate câmpurile în timp real
                try:
                    desc_ok = description_completed
                    subj_ok = subjects_completed

                    # Date
                    year_val = self.driver.execute_script("return document.getElementById('date_year') ? document.getElementById('date_year').value : '';") or ""
                    month_val = self.driver.execute_script("return document.getElementById('date_month') ? document.getElementById('date_month').value : '';") or ""
                    day_val = self.driver.execute_script("return document.getElementById('date_day') ? document.getElementById('date_day').value : '';") or ""
                    date_ok = (year_val == '1983' and month_val == '12' and day_val == '13')

                    # Collection
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

            # === CONDIȚIE OBLIGATORIE - NU UPLOAD FĂRĂ TOATE CÂMPURILE ===
            if not all_fields_completed:
                print("❌ OPRESC UPLOAD-UL - NU toate câmpurile sunt completate!")

                # Debug final
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

            # === UPLOAD FINAL - DOAR DACĂ TOTUL E COMPLETAT ===
            print("✅ TOATE câmpurile verificate și completate - ÎNCEPE UPLOAD-UL!")

            try:
                upload_final_button = self.wait.until(EC.element_to_be_clickable((By.ID, "upload_button")))
                upload_final_button.click()
                print("✅ Upload inițiat - pagina rămâne deschisă pentru monitorizare!")

                # Scurt timeout pentru confirmare upload
                time.sleep(3)
                return True

            except Exception as e:
                print(f"❌ Nu am putut apăsa butonul de upload: {e}")
                return False

        except Exception as e:
            print(f"❌ Eroare generală la completarea formularului: {e}")
            return False

    def process_folder(self, folder_path):
        """Procesează un folder împărțindu-l în unități (ROOT + subfoldere)"""
        print(f"\n📂 Procesez folderul: {folder_path.name}")

        # Scanează structura folderului în unități de procesat (doar cele neprocesate)
        processing_units = self.scan_folder_structure(folder_path)
        if not processing_units:
            print(f"✅ Toate unitățile din {folder_path.name} au fost deja procesate!")
            # MARCHEAZĂ FOLDERUL PRINCIPAL CA PROCESAT
            if str(folder_path) not in self.state.get("processed_folders", []):
                self.state.setdefault("processed_folders", []).append(str(folder_path))
                self.state["last_processed_folder"] = folder_path.name
                self._save_state()
            return True

        # Procesează fiecare unitate individual
        all_success = True

        for i, unit in enumerate(processing_units, 1):
            print(f"\n📊 Unitatea {i}/{len(processing_units)} din {folder_path.name}")

            try:
                result = self.process_single_unit(unit)

                if result == "limit_reached":
                    print(f"🎯 Limita de {MAX_UPLOADS_PER_DAY} upload-uri atinsă!")
                    return "limit_reached"
                elif not result:
                    print(f"⚠ Eșec la procesarea unității {unit['name']}")
                    all_success = False

                # Pauză scurtă între unități din același folder
                if i < len(processing_units):
                    print("⏳ Pauză 2 secunde între unități...")
                    time.sleep(2)

            except Exception as e:
                print(f"❌ Eroare la procesarea unității {unit['name']}: {e}")
                all_success = False
                continue

        # Doar dacă TOATE unitățile au fost procesate cu succes, marchează folderul ca procesat
        if all_success:
            if str(folder_path) not in self.state.get("processed_folders", []):
                self.state.setdefault("processed_folders", []).append(str(folder_path))
                self.state["last_processed_folder"] = folder_path.name
                self._save_state()
                print(f"✅ Folderul {folder_path.name} complet procesat!")

        return all_success

    def run(self):
        """Executa procesul principal"""
        print("🚀 Incep executarea Archive.org Uploader")
        print("=" * 60)

        try:
            if not self.setup_chrome_driver():
                return False

            # Asigura-te ca directorul de destinatie exista
            MOVE_PATH.mkdir(exist_ok=True)

            # Obtine folderele de procesat
            folders_to_process = self.get_folders_to_process()

            if not folders_to_process:
                print("✅ Nu mai sunt foldere de procesat pentru astazi!")
                return True

            print(f"🎯 Procesez foldere până la limita de {MAX_UPLOADS_PER_DAY} upload-uri...")
            print(f"📊 Upload-uri deja făcute astăzi: {self.state['uploads_today']}")

            # VERIFICĂ DACĂ LIMITA E DEJA ATINSĂ
            if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
                print(f"✅ Limita de {MAX_UPLOADS_PER_DAY} upload-uri deja atinsa pentru astazi!")
                return True

            # Proceseaza fiecare folder
            for i, folder in enumerate(folders_to_process, 1):
                print(f"\n📊 Progres: {i}/{len(folders_to_process)}")

                try:
                    result = self.process_folder(folder)

                    if result == "limit_reached":
                        print(f"🎯 Limita de {MAX_UPLOADS_PER_DAY} upload-uri atinsa! Opresc procesarea.")
                        break
                    elif not result:
                        print(f"⚠ Esec la procesarea folderului {folder.name}")

                    # Pauza intre foldere
                    print("⏳ Pauza 3 secunde...")
                    time.sleep(3)

                except KeyboardInterrupt:
                    print("\n⚠ Intrerupt de utilizator")
                    break
                except Exception as e:
                    print(f"❌ Eroare la procesarea folderului {folder}: {e}")
                    continue

            # Raport final
            print(f"\n📊 RAPORT FINAL:")
            print(f"📤 Upload-uri pe archive.org astazi: {self.state['uploads_today']}/{MAX_UPLOADS_PER_DAY}")
            print(f"📁 Foldere cu fisiere mutate in d:\\3\\: {self.state['folders_moved']}")
            print(f"📄 Total fisiere incarcate: {self.state['total_files_uploaded']}")
            print(f"📋 Total foldere procesate: {len(self.state['processed_folders'])}")

            if self.state['uploads_today'] >= MAX_UPLOADS_PER_DAY:
                print(f"🎯 LIMITA ZILNICA ATINSA! Nu mai pot face upload-uri astazi.")

            return True

        except KeyboardInterrupt:
            print("\n⚠ Executie intrerupta manual")
            return False
        except Exception as e:
            print(f"\n❌ Eroare neasteptata: {e}")
            return False
        finally:
            if not self.attached_existing and self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass


def main():
    """Functia principala"""
    # Verifica daca directoarele exista
    if not ARCHIVE_PATH.exists():
        print(f"❌ Directorul sursa nu exista: {ARCHIVE_PATH}")
        return False

    print(f"📁 Director sursa: {ARCHIVE_PATH}")
    print(f"📁 Director destinatie: {MOVE_PATH}")
    print(f"🎯 Upload-uri maxime pe zi: {MAX_UPLOADS_PER_DAY}")

    uploader = ArchiveUploader()
    success = uploader.run()

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Eroare fatala: {e}")
        sys.exit(1)