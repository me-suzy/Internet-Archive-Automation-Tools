#!/usr/bin/env python3
"""
Automatizare incarcare PDF-uri individuale pe Archive.org din d:\\3\\Input\\:
- Scaneaza toate PDF-urile din d:\\3\\Input\\
- Incarca fiecare PDF individual pe archive.org
- Completeaza automat campurile pe archive.org
- Limita: maxim 200 upload-uri pe zi
- Pastreaza evidenta progresului in state_archive.json
- Verifica erori 404/505 dupa 5 minute de la ultimul upload si salveaza titlurile intr-un txt

Inainte de pornire ruleaza start_chrome_debug.bat pentru sesiunea Chrome cu remote debugging.

@echo off
REM Pornește Chrome pe profilul Default cu remote debugging activat
set CHROME_PATH="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
set PROFILE_DIR="C:/Users/necul/AppData/Local/Google/Chrome/User Data/Default"

REM Asigură-te că nu mai e deja un Chrome deschis pe acel profil
%CHROME_PATH% --remote-debugging-port=9222 --user-data-dir=%PROFILE_DIR%
"""

import time
import os
import sys
import re
import json
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
INPUT_PATH = Path(r"G:\3\Input")
ARCHIVE_URL = "https://archive.org/upload"
MAX_UPLOADS_PER_DAY = 9999
STATE_FILENAME = "state_archive.json"

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
            "processed_files": [],
            "uploads_today": 0,
            "last_processed_file": "",
            "total_files_uploaded": 0
        }
        self.state = default

        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if loaded.get("date") == today:
                    self.state = loaded
                    print(f"📋 Încărcat starea pentru {today}: {self.state.get('uploads_today', 0)} upload-uri")
                else:
                    print(f"🆕 Zi nouă detectată. Resetez starea.")
                    self.state = default
            except Exception as e:
                print(f"⚠ Eroare la citirea stării ({e}), resetez.")
                self.state = default
        self._save_state()

    def is_file_processed(self, file_path):
        """Verifică dacă un fișier a fost deja procesat"""
        file_key = str(file_path)
        return file_key in self.state.get("processed_files", [])

    def mark_file_processed(self, file_path):
        """Marchează un fișier ca procesat"""
        file_key = str(file_path)
        if file_key not in self.state.get("processed_files", []):
            self.state.setdefault("processed_files", []).append(file_key)
            self.state["last_processed_file"] = file_path.name
            print(f"✅ Fișier marcat ca procesat: {file_path.name}")
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

    def get_pdf_files_to_process(self):
        """Obtine lista fisierelor PDF de procesat din d:\\3\\Input\\"""
        try:
            if not INPUT_PATH.exists():
                print(f"❌ Folderul {INPUT_PATH} nu există!")
                return []

            all_pdfs = list(INPUT_PATH.glob("*.pdf"))
            print(f"📁 Găsite {len(all_pdfs)} fișiere PDF în {INPUT_PATH}")

            processed = set(self.state.get("processed_files", []))
            remaining = [f for f in all_pdfs if str(f) not in processed]

            print(f"📋 Procesate deja: {len(processed)}")
            print(f"🎯 Rămân de procesat: {len(remaining)}")

            if remaining:
                print(f"📄 Primul PDF de procesat: {remaining[0].name}")

            return remaining
        except Exception as e:
            print(f"❌ Eroare la scanarea PDF-urilor: {e}")
            return []

    def sanitize_title(self, filename):
        """Curata numele fisierului pentru titlu"""
        title = filename.stem  # Fără extensie
        title = re.sub(r'[^\w\s-]', ' ', title)
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

    def upload_pdf_to_archive(self, pdf_file):
        """Incarca un singur PDF pe archive.org"""
        try:
            self.driver.execute_script("window.open('');")
            new_window = self.driver.window_handles[-1]
            self.driver.switch_to.window(new_window)

            if not self.navigate_to_upload_page():
                return False

            print(f"📤 Incep incarcarea pentru: {pdf_file.name}")

            time.sleep(2)
            try:
                file_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
            except:
                print("❌ Nu am gasit input-ul pentru fisiere")
                return False

            file_input.send_keys(str(pdf_file.absolute()))
            print(f"📁 Fisier trimis: {pdf_file.name}")
            print("⏳ Aștept 3 secunde pentru încărcarea fișierului...")
            time.sleep(3)

            result = self.fill_form_fields(pdf_file.name)
            if result:
                print("✅ Upload completat cu succes! Pagina rămâne deschisă pentru monitorizare.")
            return result

        except Exception as e:
            print(f"❌ Eroare la incarcarea fisierului: {e}")
            return False

    def fill_form_fields(self, filename):
        """Completează TOATE campurile - Description, Subjects, Date, Collection"""
        try:
            auto_title = self.sanitize_title(Path(filename))

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

    def check_for_errors_after_upload(self):
        """Verifică toate filele deschise pentru erori 404, 505 sau 503 după 5 minute de la ultimul upload"""
        print("\n⏳ Aștept 5 minute după ultimul upload pentru a verifica erorile...")
        time.sleep(300)  # Așteaptă 5 minute
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
                print(f"📄 Rezultatele erorilor au fost salvate în: {filename}")

            return failed_uploads
        except Exception as e:
            print(f"❌ Eroare generală la verificarea erorilor: {e}")
            return []

    def run(self):
        """Executa procesul principal"""
        print("🚀 Încep executarea PDF Archive.org Uploader")
        print("=" * 60)

        try:
            if not self.setup_chrome_driver():
                return False

            pdf_files = self.get_pdf_files_to_process()

            if not pdf_files:
                print("✅ Nu mai sunt PDF-uri de procesat pentru astăzi!")
                return True

            print(f"🎯 Procesez PDF-uri până la limita de {MAX_UPLOADS_PER_DAY} upload-uri...")
            print(f"📊 Upload-uri deja făcute astăzi: {self.state['uploads_today']}")

            if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
                print(f"✅ Limita de {MAX_UPLOADS_PER_DAY} upload-uri deja atinsă pentru astăzi!")
                return True

            for i, pdf_file in enumerate(pdf_files, 1):
                if self.state["uploads_today"] >= MAX_UPLOADS_PER_DAY:
                    print(f"🎯 Limita de {MAX_UPLOADS_PER_DAY} upload-uri atinsă! Opresc.")
                    break

                print(f"\n📊 Progres PDF: {i}/{len(pdf_files)}")
                print(f"📄 Procesez: {pdf_file.name}")

                try:
                    success = self.upload_pdf_to_archive(pdf_file)
                    if success:
                        self.state["uploads_today"] += 1
                        self.state["total_files_uploaded"] += 1
                        self.mark_file_processed(pdf_file)
                        print(f"✅ Upload #{self.state['uploads_today']} reușit pentru {pdf_file.name}")
                        print(f"📊 Rămân {MAX_UPLOADS_PER_DAY - self.state['uploads_today']} upload-uri pentru astăzi")
                        # Pauză de 10 secunde după fiecare upload reușit
                        time.sleep(10)
                    else:
                        print(f"❌ Eșec la upload-ul pentru {pdf_file.name}")

                    # Pauză între fișiere
                    if i < len(pdf_files):
                        print("⏳ Pauză 3 secunde...")
                        time.sleep(3)

                except KeyboardInterrupt:
                    print("\n⚠ Încetat de utilizator")
                    break
                except Exception as e:
                    print(f"❌ Eroare la procesarea PDF-ului {pdf_file}: {e}")
                    continue

            # Verifică erorile după finalizarea upload-urilor
            if self.state["uploads_today"] > 0:
                self.check_for_errors_after_upload()

            print(f"\n📊 RAPORT FINAL:")
            print(f"📤 Upload-uri pe archive.org astăzi: {self.state['uploads_today']}/{MAX_UPLOADS_PER_DAY}")
            print(f"📄 Total fișiere încărcate: {self.state['total_files_uploaded']}")
            print(f"📋 Total PDF-uri procesate: {len(self.state['processed_files'])}")

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
    if not INPUT_PATH.exists():
        print(f"❌ Directorul sursa nu exista: {INPUT_PATH}")
        return False

    print(f"📁 Director sursa: {INPUT_PATH}")
    print(f"🎯 Upload-uri maxime pe zi: {MAX_UPLOADS_PER_DAY}")

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