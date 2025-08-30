def find_priority_file(self, files):
        """Gaseste primul fisier conform prioritatii"""
        for ext in PRIORITY_EXTENSIONS:
            for file in files:
                if file.suffix.lower() == ext:
                    return file
        return None#!/usr/bin/env python3
"""
Automatizare incarcare fisiere pe Archive.org - Versiunea cu ZERO TAB CLOSURES:
- Scaneaza RECURSIV toate subfolderele din g:\\ARHIVA\\B\\ (fara limita de nivel)
- Pentru foldere cu PDF: incarca TOATE fisierele (exceptand .jpg/.png) pe archive.org
- Pentru foldere fara PDF: muta un fisier specific in d:\\3\\ cu OVERWRITE
- Prioritate fisiere: .mobi, .epub, .djvu, .docx, .doc, .lit, rtf
- Completeaza automat campurile pe archive.org
- Limita: maxim 200 upload-uri pe zi
- Pastreaza evidenta progresului in state_archive.json
- Verifica erori 404/505 dupa 5 minute de la ultimul upload si salveaza titlurile intr-un txt
- NOUĂ FUNCȚIONALITATE: Copiază automat fișierele cu erori în g:\\TEMP\\ pentru verificare ușoară
- ZERO TAB CLOSURES: NICIUN tab nu se închide NICIODATĂ - upload-uri de 200+ MB durează 30+ minute!

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
import difflib
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
ARCHIVE_PATH = Path(r"g:\ARHIVA\C") # - Aici e folderul cu fisiere
MOVE_PATH = Path(r"d:\3")  # Aici e folderul unde copiezi fisierele diferite de PDF
TEMP_PATH = Path(r"g:\TEMP")  # NOUĂ: Pentru fișierele cu erori
ARCHIVE_URL = "https://archive.org/upload"
MAX_UPLOADS_PER_DAY = 9999
STATE_FILENAME = "state_archive.json"

# Extensii in ordinea prioritatii pentru foldere fara PDF
PRIORITY_EXTENSIONS = ['.mobi', '.epub', '.djvu', '.docx', '.doc', '.lit', '.rtf']

# Extensii de ignorat
IGNORE_EXTENSIONS = ['.jpg', '.png']

class ArchiveUploader:
    def __init__(self, timeout=90):
        self.timeout = timeout
        self.driver = None
        self.wait = None
        self.attached_existing = False
        self.state_path = STATE_FILENAME
        self.upload_tabs = []  # FIXED: Track upload tabs instead of closing them
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
        is_processed = unit_key in self.state.get("processed_units", [])

        # DEBUG: Afișează toate căile procesate pentru investigare
        if "C.O.C.C" in unit_key:
            print(f"🔍 DEBUG - Verific calea: {unit_key}")
            print(f"🔍 DEBUG - Este procesată: {is_processed}")
            print(f"🔍 DEBUG - Căi procesate care conțin 'C.O.C.C':")
            for processed_path in self.state.get("processed_units", []):
                if "C.O.C.C" in processed_path:
                    print(f"    📋 {processed_path}")

        return is_processed

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

    def restart_chrome_if_needed(self):
        """NEVER RESTART - Only check for critical memory crashes that would stop everything"""
        try:
            all_windows = self.driver.window_handles
            print(f"🔍 Verificare stare Chrome: {len(all_windows)} tab-uri deschise - TOATE PĂSTRATE!")

            # NEVER restart just because of many tabs - uploads can take 30+ minutes!
            # Only restart if Chrome is completely broken (not just slow)

            critical_crash = False
            memory_errors = 0

            # Only check for actual crashes, not just "many tabs"
            print(f"📊 {len(all_windows)} tab-uri deschise - NORMAL pentru upload-uri lungi!")

            # Check for actual browser crashes only
            try:
                # Test if Chrome is still responsive by getting current URL
                current_url = self.driver.current_url
                print(f"✅ Chrome este responsiv: {current_url[:50]}...")
            except Exception as e:
                print(f"🚨 Chrome pare să fi crashed: {e}")
                critical_crash = True

            # Only check for critical memory crashes (not just warnings)
            try:
                page_source = self.driver.page_source
                if "chrome://crash" in page_source or "crashed" in self.driver.title.lower():
                    critical_crash = True
                    print("🚨 Chrome crash page detectată!")
            except:
                critical_crash = True
                print("🚨 Nu pot accesa page source - posibil crash!")

            if critical_crash:
                print("🚨 CHROME A CRASHED COMPLET - restart OBLIGATORIU...")

                # Salvează starea curentă
                old_driver = self.driver

                # Închide Chrome-ul crashed
                try:
                    old_driver.quit()
                    print("   ✅ Chrome crashed închis")
                except:
                    print("   ⚠️ Chrome era deja mort")

                # Așteaptă 10 secunde
                time.sleep(10)

                # Pornește Chrome nou
                success = self.setup_chrome_driver()
                if success:
                    print("   ✅ Chrome nou pornit după crash")
                    self.upload_tabs = []  # Reset upload tabs list
                    return True
                else:
                    print("   ❌ Eroare la pornirea Chrome nou")
                    return False
            else:
                print(f"✅ Chrome funcționează OK cu {len(all_windows)} tab-uri - CONTINUĂ NORMAL!")
                return True

        except Exception as e:
            print(f"❌ Eroare la verificarea stării Chrome: {e}")
            return False

    def alphabetical_sort_key(self, folder_name):
        """Creează o cheie de sortare pur alfabetică, ignorând caracterele speciale"""
        clean_name = re.sub(r'[^a-zA-Z\s]', '', folder_name.lower())
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()
        return clean_name

    def scan_folder_structure(self, folder_path):
        """Scanează recursiv structura folderului și returnează o listă de unități de procesat"""
        processing_units = []

        try:
            for root, dirs, files in os.walk(folder_path):
                current_path = Path(root)
                if files:  # Procesăm doar dacă există fișiere
                    unit_files = [current_path / f for f in files if (current_path / f).suffix.lower() not in IGNORE_EXTENSIONS]
                    pdf_files = [f for f in unit_files if f.suffix.lower() == '.pdf']
                    unit_name = str(current_path.relative_to(ARCHIVE_PATH))
                    if not self.is_unit_processed(current_path):
                        processing_units.append({
                            "path": current_path,
                            "actual_path": current_path,
                            "name": unit_name,
                            "has_pdf": len(pdf_files) > 0,
                            "pdf_files": pdf_files,
                            "all_files": unit_files,
                            "is_root": current_path == folder_path
                        })
                        print(f"📂 {unit_name}: {len(pdf_files)} PDF-uri, {len(unit_files)} fișiere - NEPROCESATĂ")
                    else:
                        print(f"⏭️ {unit_name}: DEJA PROCESATĂ")

            print(f"📊 Unități NOI de procesat pentru {folder_path.name}: {len(processing_units)}")
            return processing_units

        except Exception as e:
            print(f"❌ Eroare la scanarea structurii folderului {folder_path}: {e}")
            return []

    def get_folders_to_process(self):
        """Obtine lista folderelor de procesat, sortate strict alfabetic"""
        try:
            all_folders = [f for f in ARCHIVE_PATH.iterdir() if f.is_dir()]
            all_folders.sort(key=lambda x: self.alphabetical_sort_key(x.name))

            print("📋 Primele 10 foldere în ordine alfabetică:")
            for i, folder in enumerate(all_folders[:10]):
                clean_key = self.alphabetical_sort_key(folder.name)
                print(f"   {i+1}. {folder.name} (sortare: '{clean_key}')")

            processed = set(self.state.get("processed_folders", []))
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

    def process_single_unit(self, unit):
        """Procesează o singură unitate (orice nivel de folder)"""
        print(f"\n📂 Procesez unitatea: {unit['name']}")

        if unit["has_pdf"]:
            # NEVER RESTART - Let uploads run for as long as they need (30+ minutes for 200+ MB files)
            print(f"📊 Chrome tabs: {len(self.driver.window_handles)} - TOATE PĂSTRATE pentru upload-uri lungi!")
            # Only check Chrome health if there are signs of actual crashes

            if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
                print(f"⚠ Limita de {MAX_UPLOADS_PER_DAY} upload-uri pe zi atinsă! Opresc.")
                return "limit_reached"

            print(f"📄 PDF găsit în {unit['name']}! Upload pe archive.org pentru TOATE fișierele din folder...")

            # Show exactly what files will be uploaded
            pdf_files = [f for f in unit["all_files"] if f.suffix.lower() == '.pdf']
            other_files = [f for f in unit["all_files"] if f.suffix.lower() != '.pdf']

            print(f"   📑 PDF-uri de uplodat: {len(pdf_files)}")
            for pdf in pdf_files:
                size_mb = pdf.stat().st_size / (1024*1024) if pdf.exists() else 0
                print(f"      📄 {pdf.name} ({size_mb:.1f} MB)")

            if other_files:
                print(f"   📎 Alte fișiere de uplodat: {len(other_files)}")
                for other in other_files[:3]:  # Show first 3
                    print(f"      📎 {other.name}")
                if len(other_files) > 3:
                    print(f"      📎 ... și încă {len(other_files)-3} fișiere")

            print(f"   📊 TOTAL fișiere pentru upload: {len(unit['all_files'])}")

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
        """FIXED: Incarca TOATE fisierele pe archive.org - FĂRĂ închiderea automată a tab-urilor"""
        current_window = None
        new_window = None

        try:
            print("⚠️ ATENȚIE: NU schimba tab-ul în Chrome în timpul upload-ului!")
            print("🚫 Chrome = INTANGIBLE în următoarele minute!")

            # Salvează fereastra curentă
            current_window = self.driver.current_window_handle

            # NEVER close tabs - uploads can take 30+ minutes for large files (200+ MB)
            all_windows = self.driver.window_handles
            print(f"📊 Tab-uri deschise: {len(all_windows)} (TOATE PĂSTRATE - upload-uri pot dura 30+ minute!)")

            # Deschide tab nou pentru upload - ÎNTOTDEAUNA
            print("🆕 Deschid tab NOU pentru upload...")
            self.driver.execute_script("window.open('');")
            new_window = self.driver.window_handles[-1]
            self.driver.switch_to.window(new_window)

            # FIXED: Track this upload tab
            self.upload_tabs.append(new_window)
            print(f"📋 Tab upload #{len(self.upload_tabs)} creat: {new_window}")

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
                print("✅ Upload LANSAT cu succes!")
                # ZERO TAB CLOSURES - Tab remains open indefinitely for monitoring
                print("📋 TAB PĂSTRAT DESCHIS PERMANENT - NICIODATĂ NU SE ÎNCHIDE!")
                print(f"🏷️ Tab ID: {new_window}")
                print("⏳ Upload-uri mari (200+ MB) pot dura 30+ minute - TAB-ul rămâne activ!")

                # Switch back to original window but NEVER close upload tab
                if current_window in self.driver.window_handles:
                    self.driver.switch_to.window(current_window)
                    print(f"🔄 Revin la tab-ul principal: {current_window}")
                else:
                    remaining = self.driver.window_handles
                    if remaining and len(remaining) > 1:
                        # Switch to first non-upload tab
                        for tab in remaining:
                            if tab != new_window:
                                self.driver.switch_to.window(tab)
                                print(f"🔄 Revin la alt tab disponibil: {tab}")
                                break

            return result

        except Exception as e:
            print(f"❌ Eroare la incarcarea fisierelor: {e}")
            # NEVER close tabs even on error - let user investigate the upload status
            if new_window:
                print(f"⚠️ Eroare în upload, dar PĂSTREZ tab-ul {new_window} pentru investigare și posibila continuare!")
            # Try to switch back to a working tab but DON'T close anything
            try:
                if current_window and current_window in self.driver.window_handles:
                    self.driver.switch_to.window(current_window)
                elif self.driver.window_handles:
                    self.driver.switch_to.window(self.driver.window_handles[0])
            except:
                pass
            return False

    def is_timeout_error(self, exception):
        """Verifică dacă o excepție este cauzată de timeout HTTP"""
        error_str = str(exception).lower()
        return any(phrase in error_str for phrase in [
            "read timed out",
            "connection timeout",
            "httpconnectionpool",
            "timeout exception"
        ])

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
                    if self.is_timeout_error(date_error):
                        print(f"   ⚠ Timeout la câmpurile de dată: {date_error}")
                        print("   🔄 Încerc restart Chrome...")
                        if self.restart_chrome_if_needed():
                            return False  # Pentru reîncercare
                    print(f"   ❌ Eroare la completarea câmpurilor de dată: {date_error}")
            except Exception as e:
                if self.is_timeout_error(e):
                    print(f"⚠ Timeout la activarea câmpurilor de dată: {e}")
                    print("🔄 Încerc restart Chrome...")
                    if self.restart_chrome_if_needed():
                        return False  # Pentru reîncercare
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
                print("✅ Upload inițiat - TAB RĂMÂNE DESCHIS pentru monitorizare upload și detectare erori!")
                time.sleep(3)
                return True
            except Exception as e:
                print(f"❌ Nu am putut apăsa butonul de upload: {e}")
                return False
        except Exception as e:
            print(f"❌ Eroare generală la completarea formularului: {e}")
            return False

    def process_folder(self, folder_path):
        """Procesează un folder împărțindu-l în unități (toate nivelurile)"""
        print(f"\n📂 Procesez folderul: {folder_path.name}")
        processing_units = self.scan_folder_structure(folder_path)
        if not processing_units:
            print(f"✅ Toate unitățile din {folder_path.name} au fost deja procesate!")
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
                    time.sleep(10)  # Adaugă 10-secunde delay după fiecare upload
                if result == "limit_reached":
                    print(f"🎯 Limita de {MAX_UPLOADS_PER_DAY} upload-uri atinsă!")
                    return "limit_reached"
                elif not result:
                    print(f"⚠ Eșec la procesarea unității {unit['name']}")
                    all_success = False
                if i < len(processing_units):
                    print("⏳ Pauză 2 secunde între unități...")
                    time.sleep(2)
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
        return all_success

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
        """FIXED: Verifică o singură filă pentru erori 400/404/505/503, inclusiv pop-up-uri"""
        print(f"\n📋 === VERIFIC FILA #{tab_index}: {window_handle} ===")
        try:
            # FIXED: Check if tab still exists before switching
            if window_handle not in self.driver.window_handles:
                print(f"   ❌ Tab-ul {window_handle} nu mai există (a fost închis prematur)")
                return {
                    "filename": "tab-closed-prematurely",
                    "page_title": "Tab închis",
                    "window_handle": window_handle,
                    "error_code": "TAB_CLOSED",
                    "error_status": "Tab was closed before upload completion",
                    "error_details": "Tab was closed prematurely, cannot check for upload errors",
                    "timestamp": datetime.now().isoformat()
                }

            self.driver.switch_to.window(window_handle)
            time.sleep(1)
            current_url = self.driver.current_url
            print(f"   🌐 URL: {current_url}")
            page_title = self.driver.title
            print(f"   📄 Titlu pagină: '{page_title}'")

            # Get page source first for comprehensive error checking
            page_source = self.driver.page_source

            # Verifică erori de memorie Chrome
            if ("not enough memory" in page_title.lower() or
                "out of memory" in page_title.lower() or
                "error code: out of memory" in page_source.lower() or
                "aw, snap" in page_title.lower()):
                print(f"   🚨 EROARE DE MEMORIE DETECTATĂ!")
                return {
                    "filename": "memory-error-detected",
                    "page_title": page_title,
                    "window_handle": window_handle,
                    "error_code": "OUT_OF_MEMORY",
                    "error_status": "Chrome memory exhausted",
                    "error_details": "Browser ran out of memory, needs restart",
                    "timestamp": datetime.now().isoformat()
                }

            # FIXED: More comprehensive error detection in page source
            error_patterns = {
                "400": ["bad request", "400 bad request", "error 400"],
                "404": ["not found", "404 not found", "error 404", "page not found"],
                "500": ["internal server error", "500 internal server", "error 500"],
                "503": ["service unavailable", "503 service", "error 503"],
                "505": ["http version not supported", "505 http", "error 505"]
            }

            page_source_lower = page_source.lower()
            for error_code, patterns in error_patterns.items():
                for pattern in patterns:
                    if pattern in page_source_lower:
                        print(f"   🚨 EROARE {error_code} DETECTATĂ ÎN PAGE SOURCE!")
                        return {
                            "filename": self.extract_filename_from_xml(page_source),
                            "page_title": page_title,
                            "window_handle": window_handle,
                            "error_code": error_code,
                            "error_status": f"Error detected in page source: {pattern}",
                            "error_details": f"Pattern '{pattern}' found in page content",
                            "timestamp": datetime.now().isoformat()
                        }

            print("   🔍 Caut mesajul de eroare în elementele specifice...")

            # Verifică dacă pop-up-ul este vizibil
            try:
                overlay = self.driver.find_element(By.ID, "overlay_alert")
                is_visible = overlay.is_displayed()
                print(f"   📱 Overlay alert găsit, vizibil: {is_visible}")
                if not is_visible:
                    print("   ⚠️ Pop-up-ul este ascuns!")
            except NoSuchElementException:
                print("   ⚠️ Nu există overlay_alert!")

            # FIXED: Check multiple possible error message locations
            error_selectors = [
                "#progress_msg",
                "#upload_error_text",
                ".error-message",
                ".upload-error",
                "[class*='error']",
                "[id*='error']"
            ]

            found_error = False
            for selector in error_selectors:
                try:
                    error_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for error_div in error_elements:
                        if not error_div.is_displayed():
                            continue

                        error_text = error_div.text.strip()
                        if not error_text:
                            continue

                        print(f"   📝 Text găsit în {selector}: '{error_text}'")

                        # Check for network problems
                        if "There is a network problem" in error_text or "network problem" in error_text.lower():
                            print("   🚨 EROARE DE NETWORK DETECTATĂ!")
                            found_error = True

                        # Extract error codes from the text
                        error_code_match = re.search(r'\b(400|404|500|503|505)\b', error_text)
                        if error_code_match:
                            error_code = error_code_match.group(1)
                            print(f"   🚨 COD EROARE {error_code} GĂSIT ÎN TEXT!")
                            found_error = True

                            # Get additional error details
                            error_code_full, error_status = self.get_error_code_and_status()
                            xml_content = self.get_error_details_from_popup()
                            filename = self.extract_filename_from_xml(xml_content) if xml_content else "fisier-necunoscut"

                            return {
                                "filename": filename,
                                "page_title": page_title,
                                "window_handle": window_handle,
                                "error_code": error_code,
                                "error_status": error_status,
                                "error_details": xml_content or f"Error found in {selector}: {error_text}",
                                "timestamp": datetime.now().isoformat()
                            }
                except NoSuchElementException:
                    continue
                except Exception as e:
                    print(f"   ⚠️ Eroare la verificarea {selector}: {e}")
                    continue

            # FIXED: Also check overlay_alert separately
            try:
                overlay_alert = self.driver.find_element(By.ID, "overlay_alert")
                if overlay_alert.is_displayed():
                    print("   🚨 OVERLAY_ALERT DETECTAT ȘI VIZIBIL!")
                    # Extrage direct din overlay
                    try:
                        error_code_elem = overlay_alert.find_element(By.ID, "upload_error_code")
                        error_status_elem = overlay_alert.find_element(By.ID, "upload_error_status")
                        error_code = error_code_elem.text.strip()
                        error_status = error_status_elem.text.strip()
                        print(f"   📊 OVERLAY EROARE: {error_code} - {error_status}")

                        if error_code in ["400", "404", "500", "503", "505"]:
                            xml_content = self.get_error_details_from_popup()
                            filename = self.extract_filename_from_xml(xml_content) if xml_content else "overlay-detected-file"

                            return {
                                "filename": filename,
                                "page_title": page_title,
                                "window_handle": window_handle,
                                "error_code": error_code,
                                "error_status": error_status,
                                "error_details": xml_content or "Eroare detectată din overlay_alert",
                                "timestamp": datetime.now().isoformat()
                            }
                    except NoSuchElementException:
                        print("   ⚠️ Nu am găsit elementele de eroare în overlay")
            except NoSuchElementException:
                print("   ℹ️ Nu există overlay_alert")

            if not found_error:
                print("   ✅ Nu este eroare 400/404/505/503 relevantă")
            return None

        except Exception as e:
            print(f"   ❌ Eroare la verificarea filei: {e}")
            return None

    def normalize_filename_for_matching(self, filename):
        """Normalizează numele fișierului pentru comparație"""
        # Elimină extensia
        name = Path(filename).stem if isinstance(filename, (str, Path)) else str(filename)

        # Convertește la lowercase
        name = name.lower()

        # Înlocuiește caracterele speciale cu space sau elimină
        name = re.sub(r'[^\w\s]', ' ', name)

        # Elimină spațiile multiple și strip
        name = re.sub(r'\s+', ' ', name).strip()

        # Înlocuiește spațiile cu -
        name = name.replace(' ', '-')

        return name

    def find_original_file_for_error(self, error_filename, search_folders):
        """Găsește fișierul original pe baza numelui din eroare"""
        print(f"🔍 Caut fișierul original pentru: '{error_filename}'")

        # Normalizează numele din eroare
        normalized_error = self.normalize_filename_for_matching(error_filename)
        print(f"   📝 Nume normalizat din eroare: '{normalized_error}'")

        # Lista candidaților
        candidates = []

        # Scanează toate fișierele din folderele procesate recent
        for folder_path in search_folders:
            if not folder_path.exists():
                continue

            try:
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = Path(root) / file
                        if file_path.suffix.lower() in ['.pdf', '.epub', '.mobi', '.djvu', '.docx', '.doc']:
                            normalized_file = self.normalize_filename_for_matching(file)

                            # Calculează similaritatea
                            similarity = difflib.SequenceMatcher(None, normalized_error, normalized_file).ratio()

                            if similarity > 0.6:  # Threshold pentru potrivire
                                candidates.append({
                                    'path': file_path,
                                    'similarity': similarity,
                                    'normalized_name': normalized_file
                                })
                                print(f"   📋 Candidat găsit: {file} (similaritate: {similarity:.2f})")
            except Exception as e:
                print(f"   ⚠️ Eroare la scanarea folderului {folder_path}: {e}")

        # Sortează după similaritate
        candidates.sort(key=lambda x: x['similarity'], reverse=True)

        if candidates:
            best_match = candidates[0]
            print(f"   ✅ Cea mai bună potrivire: {best_match['path'].name} (similaritate: {best_match['similarity']:.2f})")
            return best_match['path']
        else:
            print(f"   ❌ Nu am găsit fișierul original pentru '{error_filename}'")
            return None

    def copy_error_files_to_temp(self, failed_uploads):
        """Copiază fișierele cu erori direct în folderul TEMP - versiune simplificată"""
        if not failed_uploads:
            print("✅ Nu sunt fișiere cu erori de copiat")
            return []

        print(f"\n📁 === COPIERE FIȘIERE CU ERORI ÎN {TEMP_PATH} ===")

        # Creează doar folderul TEMP principal
        try:
            TEMP_PATH.mkdir(exist_ok=True)
            print(f"📂 Folderul TEMP pregătit: {TEMP_PATH}")
        except Exception as e:
            print(f"❌ Eroare la crearea folderului TEMP: {e}")
            return []

        # Obține lista folderelor procesate recent pentru căutare
        processed_folders = []
        for folder_path_str in self.state.get("processed_folders", []):
            folder_path = Path(folder_path_str)
            if folder_path.exists():
                processed_folders.append(folder_path)

        # Adaugă și folderul ARHIVA\B pentru căutare completă
        if ARCHIVE_PATH.exists():
            processed_folders.append(ARCHIVE_PATH)

        print(f"🔍 Voi căuta în {len(processed_folders)} foldere pentru fișierele cu erori")

        copied_files = []
        failed_copies = []

        for i, error_info in enumerate(failed_uploads, 1):
            print(f"\n📋 Procesez eroarea {i}/{len(failed_uploads)}: {error_info['filename']}")

            # Skip tab closure errors - these are our fault, not archive.org errors
            if error_info.get('error_code') == 'TAB_CLOSED':
                print(f"   ⏭️ Skip - tab închis prematur (eroare de cod, nu de archive.org)")
                continue

            # Găsește fișierul original
            original_file = self.find_original_file_for_error(error_info['filename'], processed_folders)

            if not original_file:
                failed_copies.append({
                    'error_info': error_info,
                    'reason': 'Fișierul original nu a fost găsit'
                })
                continue

            try:
                # Creează numele simplu cu cod eroare și timestamp
                original_name = original_file.stem
                original_ext = original_file.suffix
                error_code = error_info.get('error_code', 'unknown')
                timestamp = datetime.now().strftime("%H%M%S")

                # Fișierul PDF direct în TEMP
                dest_filename = f"{original_name}_ERROR-{error_code}_{timestamp}{original_ext}"
                dest_path = TEMP_PATH / dest_filename

                # Fișierul INFO direct în TEMP
                info_filename = f"{original_name}_ERROR-{error_code}_{timestamp}_INFO.txt"
                info_path = TEMP_PATH / info_filename

                # Copiază fișierul PDF
                print(f"   📁 Copiez: {original_file.name}")
                print(f"   📁    → {dest_path}")

                shutil.copy2(original_file, dest_path)

                # Creează fișierul INFO
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

        # Raport final simplificat
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
        """FIXED: Verifică toate filele DESCHISE pentru erori după 5 minute de la ultimul upload"""
        print("\n⏳ Aștept 5 minute după ultimul upload pentru a verifica erorile...")
        time.sleep(300)  # Așteaptă 5 minute
        print("\n🔍 === ÎNCEPUT VERIFICARE ERORI 400/404/505/503 DUPĂ UPLOAD ===")

        if not self.driver:
            print("❌ Driver-ul Chrome nu este disponibil")
            return

        try:
            current_window = self.driver.current_window_handle
            all_windows = self.driver.window_handles
            print(f"📊 Găsite {len(all_windows)} file deschise în Chrome")
            print(f"🏠 Fereastra curentă: {current_window}")

            # FIXED: Check only upload tabs first, then all tabs
            print(f"📋 Tab-uri de upload create: {len(self.upload_tabs)}")

            print("   📋 Lista tuturor filelor:")
            for i, window_handle in enumerate(all_windows, 1):
                try:
                    self.driver.switch_to.window(window_handle)
                    url = self.driver.current_url
                    title = self.driver.title
                    is_upload_tab = window_handle in self.upload_tabs
                    tab_type = "UPLOAD" if is_upload_tab else "NORMAL"
                    print(f"   {i}. {window_handle} [{tab_type}] - URL: {url} - Titlu: {title}")
                except Exception as e:
                    print(f"   {i}. {window_handle} - EROARE: {e}")

            failed_uploads = []

            # FIXED: Check all tabs, but prioritize upload tabs
            tabs_to_check = []

            # First, add all upload tabs
            for tab in self.upload_tabs:
                if tab in all_windows:
                    tabs_to_check.append((tab, "UPLOAD"))

            # Then add other tabs that might be archive.org
            for tab in all_windows:
                if tab not in self.upload_tabs:
                    try:
                        self.driver.switch_to.window(tab)
                        if "archive.org" in self.driver.current_url:
                            tabs_to_check.append((tab, "ARCHIVE"))
                    except:
                        continue

            print(f"🎯 Verificând {len(tabs_to_check)} tab-uri relevante pentru erori...")

            for i, (window_handle, tab_type) in enumerate(tabs_to_check, 1):
                print(f"\n📋 Verificare {i}/{len(tabs_to_check)} - Tab {tab_type}: {window_handle}")
                error_info = self.check_single_tab_for_errors(window_handle, i)
                if error_info and error_info["error_code"] in ["400", "404", "500", "503", "505", "TAB_CLOSED", "OUT_OF_MEMORY"]:
                    failed_uploads.append(error_info)
                    print(f"   🚨 EROARE {error_info['error_code']}/{error_info['error_status']} CONFIRMATĂ în tab {tab_type} #{i}")
                else:
                    print(f"   ✅ Tab {tab_type} #{i} - OK, nu există erori")
                time.sleep(2)

            # FIXED: Return to a safe tab
            try:
                if current_window in self.driver.window_handles:
                    self.driver.switch_to.window(current_window)
                    print(f"\n🏠 M-am întors la fereastra originală: {current_window}")
                elif self.driver.window_handles:
                    # Find a non-upload tab to switch to
                    safe_tab = None
                    for tab in self.driver.window_handles:
                        if tab not in self.upload_tabs:
                            safe_tab = tab
                            break
                    if safe_tab:
                        self.driver.switch_to.window(safe_tab)
                        print(f"🏠 M-am întors la tab sigur: {safe_tab}")
                    else:
                        self.driver.switch_to.window(self.driver.window_handles[0])
                        print(f"🏠 M-am întors la primul tab disponibil")
            except Exception as switch_error:
                print(f"⚠️ Nu am putut reveni la fereastra originală: {switch_error}")

            print(f"\n📊 === REZULTAT FINAL VERIFICARE ERORI ===")
            print(f"🔍 Tab-uri verificate: {len(tabs_to_check)}")
            print(f"🚨 Erori găsite: {len(failed_uploads)}")

            # FIXED: Separate real errors from tab closure errors
            real_errors = [err for err in failed_uploads if err.get('error_code') not in ['TAB_CLOSED']]
            tab_closure_errors = [err for err in failed_uploads if err.get('error_code') == 'TAB_CLOSED']

            print(f"📊 Erori reale de server: {len(real_errors)}")
            print(f"⚠️ Tab-uri închise prematur: {len(tab_closure_errors)}")

            # NOUĂ FUNCȚIONALITATE: Copiază fișierele cu erori în TEMP
            copied_files = []
            if real_errors:  # Only copy real server errors, not tab closures
                print(f"\n📁 === ÎNCEPE COPIEREA FIȘIERELOR CU ERORI REALE ===")
                copied_files = self.copy_error_files_to_temp(real_errors)

            failed_uploads_list = []
            if failed_uploads:
                print(f"\n📋 LISTA COMPLETĂ A PROBLEMELOR DETECTATE:")
                for i, error in enumerate(failed_uploads, 1):
                    error_type = "🚨 EROARE SERVER" if error['error_code'] not in ['TAB_CLOSED'] else "⚠️ TAB ÎNCHIS"
                    print(f"   {i}. {error_type} - 📖 {error['filename']}")
                    print(f"      📄 Titlu: {error['page_title']}")
                    print(f"      🚨 Eroare: {error['error_code']} {error['error_status']}")
                    print(f"      🕒 Timp: {error['timestamp']}")
                    if len(error['error_details']) > 100:
                        print(f"      📝 Detalii: {error['error_details'][:100]}...")
                    else:
                        print(f"      📝 Detalii: {error['error_details']}")
                    failed_uploads_list.append(error['filename'])
            else:
                print("✅ Nu au fost găsite erori în niciun tab!")

            # FIXED: Save results with better categorization
            error_reports_path = Path(r"e:\Carte\BB\17 - Site Leadership\alte\Ionel Balauta\Aryeht\Task 1 - Traduce tot site-ul\Doar Google Web\Andreea\Meditatii\2023\++Internet Archive BUN 2025 + Chrome\RAPOARTE_ERORI")  # sau alt director de preferat
            error_reports_path.mkdir(exist_ok=True)
            filename = error_reports_path / f"upload_errors_detailed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"RAPORT DETALIAT VERIFICARE ERORI UPLOAD - {datetime.now().isoformat()}\n")
                f.write("=" * 70 + "\n\n")

                f.write(f"STATISTICI:\n")
                f.write(f"- Tab-uri verificate: {len(tabs_to_check)}\n")
                f.write(f"- Erori server reale: {len(real_errors)}\n")
                f.write(f"- Tab-uri închise prematur: {len(tab_closure_errors)}\n")
                f.write(f"- Total probleme: {len(failed_uploads)}\n\n")

                if real_errors:
                    f.write("🚨 ERORI SERVER REALE (400/404/500/503/505):\n")
                    f.write("=" * 50 + "\n")
                    for i, error in enumerate(real_errors, 1):
                        f.write(f"{i}. 📖 {error['filename']} (Cod: {error['error_code']}, Status: {error['error_status']})\n")
                        f.write(f"   Titlu: {error['page_title']}\n")
                        f.write(f"   Timp: {error['timestamp']}\n\n")

                if tab_closure_errors:
                    f.write("⚠️ TAB-URI ÎNCHISE PREMATUR:\n")
                    f.write("=" * 30 + "\n")
                    f.write("Aceste erori sunt cauzate de închiderea prematură a tab-urilor de către cod.\n")
                    f.write("Nu reprezintă erori de server și probabil upload-urile au reușit.\n\n")
                    for i, error in enumerate(tab_closure_errors, 1):
                        f.write(f"{i}. 📖 {error['filename']}\n")

                if not failed_uploads:
                    f.write("✅ Nu au fost detectate probleme în niciun tab.\n")

                # Adaugă informații despre fișierele copiate
                if copied_files:
                    f.write(f"\n" + "=" * 70 + "\n")
                    f.write(f"FIȘIERE CU ERORI COPIATE ÎN {TEMP_PATH}:\n")
                    f.write("=" * 70 + "\n\n")
                    for copied in copied_files:
                        f.write(f"📁 {copied['original_path'].name}\n")
                        f.write(f"   → Copiat în: {copied['copied_path']}\n")
                        f.write(f"   → Info file: {copied['info_path']}\n")
                        f.write(f"   → Cod eroare: {copied['error_code']}\n\n")

            print(f"📄 Raportul detaliat a fost salvat în: {filename}")

            return failed_uploads
        except Exception as e:
            print(f"❌ Eroare generală la verificarea erorilor: {e}")
            return []

    def save_error_results_to_file(self, filenames):
        """Salvează lista finală a titlurilor cu erori 404/505 într-un fișier"""
        try:
            filename = f"upload_errors_with_400_404_505_503_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"LISTA FIȘIERELOR CU ERORI 400/404/505/503 - {datetime.now().isoformat()}\n")
                f.write("=" * 60 + "\n\n")
                if filenames:
                    for i, file_name in enumerate(filenames, 1):
                        f.write(f"{i}. 📖 {file_name}\n")
                else:
                    f.write("✅ Nu au fost detectate erori 400/404/505/503 în nicio filă.\n")
            print(f"📄 Rezultatele erorilor au fost salvate în: {filename}")
        except Exception as e:
            print(f"⚠️ Nu am putut salva rezultatele erorilor în fișier: {e}")

    def run(self):
        """Executa procesul principal"""
        print("🚀 Încep executarea Archive.org Uploader - ZERO TAB CLOSURES")
        print("=" * 60)
        print("⚠️ IMPORTANT: NU schimba tab-ul în Chrome în timpul upload-urilor!")
        print("🚫 Hands off Chrome during uploads - lasă să lucreze singur!")
        print("✅ ZERO TAB CLOSURES: Toate tab-urile rămân deschise permanent!")
        print("⏳ Upload-uri mari (200+ MB) pot dura 30+ minute - TOTUL PĂSTRAT!")
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

            # FIXED: Check for errors only after all uploads are done
            print(f"\n🔍 TOATE UPLOAD-URILE FINALIZATE - VERIFIC ERORILE...")
            self.check_for_errors_after_upload()

            print(f"\n📊 RAPORT FINAL:")
            print(f"📤 Upload-uri pe archive.org astăzi: {self.state['uploads_today']}/{MAX_UPLOADS_PER_DAY}")
            print(f"📁 Foldere cu fișiere mutate în d:\\3\\: {self.state['folders_moved']}")
            print(f"📄 Total fișiere încărcate: {self.state['total_files_uploaded']}")
            print(f"📋 Total foldere procesate: {len(self.state['processed_folders'])}")
            print(f"🗂️ Fișiere cu erori copiate în: {TEMP_PATH}")
            print(f"📊 Tab-uri de upload create și PĂSTRATE: {len(self.upload_tabs)}")
            print(f"🕐 ZERO TAB CLOSURES - toate upload-urile pot continua 30+ minute fără întrerupere!")

            if self.state['uploads_today'] >= MAX_UPLOADS_PER_DAY:
                print(f"🎯 LIMITA ZILNICĂ ATINSĂ! Nu mai pot face upload-uri astăzi.")
                print(f"📋 Tab-urile existente rămân deschise pentru monitorizare și finalizare!")

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