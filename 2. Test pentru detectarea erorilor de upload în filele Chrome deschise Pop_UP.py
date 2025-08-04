#!/usr/bin/env python3
"""
Script corect pentru detectarea erorilor de upload în filele Chrome deschise
Gestionează toate cele 4 tipuri de pop-up-uri (desfăcute/închise, SlowDown/BadContent/404)
"""

import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException

class ErrorChecker:
    def __init__(self, timeout=25):
        self.timeout = timeout
        self.driver = None
        self.wait = None
        self.setup_chrome_driver()

    def setup_chrome_driver(self):
        """Conectează la instanța Chrome existentă"""
        try:
            print("🔧 Conectez la instanța Chrome existentă...")
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

            self.driver = webdriver.Chrome(options=chrome_options)
            self.wait = WebDriverWait(self.driver, self.timeout)
            print("✅ Conectat la Chrome cu succes!")
            return True
        except WebDriverException as e:
            print(f"❌ Eroare la conectarea la Chrome: {e}")
            return False

    def clean_filename(self, filename):
        """Curăță și standardizează numele fișierului (elimină extensii, calea, și sufixele automate cu numere)"""
        # Elimină calea completă (ex. C:\fakepath\) și extensia
        filename = re.sub(r'^C:\\fakepath\\', '', filename)
        filename = re.sub(r'\.[a-zA-Z0-9]+$', '', filename)

        # Înlătură liniile și capitalizează corect
        filename = re.sub(r'-', ' ', filename)
        filename = ' '.join(word.capitalize() for word in filename.split())

        # Elimină sufixele automate cu numere (ex. _202508, _20250804)
        filename = re.sub(r'_(\d+)$', '', filename)

        # Ajustări specifice bazate pe cererea ta
        if filename.lower() == 'bartos m. j. compozitia in pictura scan':
            filename = 'Bartos M. J. - Compozitia in pictura scan'

        print(f"   📁 Nume fișier curățat: '{filename}'")
        return filename

    def extract_filename_from_xml(self, xml_content):
        """Extrage numele fișierului din conținutul XML sau din alte surse"""
        try:
            # Caută pattern-ul: "Your upload of FILENAME from username"
            resource_match = re.search(r"Your upload of ([^\s]+) from username", xml_content)
            if resource_match:
                filename = resource_match.group(1)
                filename = self.clean_filename(filename)
                print(f"   📁 Nume fișier extras din XML: '{filename}'")
                return filename
            else:
                print("   ⚠️ Nu s-a putut extrage numele fișierului din XML")
                # Fallback: Caută în DOM elemente care ar putea conține numele fișierului
                try:
                    file_elements = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file'], .upload-filename, .file-name")
                    for element in file_elements:
                        filename = element.get_attribute("value") or element.text.strip() or "fisier-necunoscut"
                        if filename and filename != "fisier-necunoscut":
                            filename = self.clean_filename(filename)
                            print(f"   📁 Nume fișier extras din DOM: '{filename}'")
                            return filename
                    print("   ⚠️ Nu am găsit numele fișierului în DOM (input sau clasa file-name)")
                except NoSuchElementException:
                    print("   ⚠️ Nu am găsit elementele de fișier în DOM")
                # Fallback final: Titlul paginii (dacă conține informații utile)
                page_title = self.driver.title
                if page_title and page_title != "Upload to Internet Archive":
                    filename = self.clean_filename(page_title)
                    print(f"   📁 Nume fișier extras din titlu: '{filename}'")
                    return filename
                print("   ⚠️ Nu am găsit numele fișierului în niciun fallback")
                return "fisier-necunoscut"
        except Exception as e:
            print(f"   ❌ Eroare la extragerea numelui fișierului: {e}")
            return "fisier-necunoscut"

    def get_error_details_from_popup(self):
        """Extrage detaliile erorii din pop-up-ul deschis sau nedesfăcut"""
        try:
            print("   🔍 Verific starea pop-up-ului de eroare...")

            # Așteaptă prezența elementului cu detaliile erorii
            error_details_div = self.wait.until(
                EC.presence_of_element_located((By.ID, "upload_error_details"))
            )

            # Verifică dacă detaliile sunt deja vizibile
            display_style = error_details_div.get_attribute("style")
            is_visible = "display: block" in display_style or "display:block" in display_style

            print(f"   📊 Stare detalii eroare: {display_style}")

            if not is_visible:
                print("   🔒 Detaliile sunt ascunse, încerc să le desfac...")

                # Așteaptă până când linkul pentru detalii este clicabil
                try:
                    details_link = self.wait.until(
                        EC.element_to_be_clickable((By.ID, "upload_error_show_details"))
                    )
                    print("   ✅ Link pentru detalii găsit!")
                    print(f"   📎 Link text: '{details_link.text}'")

                    # Încearcă să faci click pe link de maxim 3 ori
                    for attempt in range(3):
                        try:
                            self.driver.execute_script("arguments[0].click();", details_link)
                            print(f"   👆 Am dat click pe link pentru detalii (încercarea {attempt + 1})")

                            # Așteaptă până când detaliile devin vizibile
                            error_details_div = self.wait.until(
                                EC.visibility_of_element_located((By.ID, "upload_error_details"))
                            )
                            display_style = error_details_div.get_attribute("style")
                            print(f"   ✅ Detaliile sunt acum vizibile după click: {display_style}")
                            break
                        except TimeoutException:
                            print(f"   ⚠️ Detaliile nu sunt vizibile după click (încercarea {attempt + 1})")
                            if attempt == 2:
                                print("   ⚠️ Nu am putut face detaliile vizibile după 3 încercări, forțez afișarea prin JavaScript...")
                                self.driver.execute_script("document.getElementById('upload_error_details').style.display = 'block';")
                                error_details_div = self.wait.until(
                                    EC.visibility_of_element_located((By.ID, "upload_error_details"))
                                )
                                display_style = error_details_div.get_attribute("style")
                                print(f"   ✅ Detaliile forțate vizibile prin JavaScript: {display_style}")
                                break
                            time.sleep(1)
                except TimeoutException:
                    print("   ⚠️ Timeout: Nu am găsit linkul pentru detalii (#upload_error_show_details)")
                    return None
                except NoSuchElementException:
                    print("   ⚠️ Nu am găsit linkul pentru detalii (#upload_error_show_details)")
                    return None
            else:
                print("   ✅ Detaliile sunt deja vizibile!")

            # Extrage conținutul XML din elementul <pre>
            try:
                pre_element = error_details_div.find_element(By.TAG_NAME, "pre")
                xml_content = pre_element.text.strip()

                # Decodează entitățile HTML dacă e necesar
                xml_content = xml_content.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

                print("   ✅ CONȚINUT XML GĂSIT!")
                print("   📋 Conținut XML complet:")
                print("   " + "="*50)
                print("   " + xml_content)
                print("   " + "="*50)

                return xml_content

            except NoSuchElementException:
                print("   ⚠️ Nu am găsit elementul <pre> în #upload_error_details")
                return None
            except Exception as e:
                print(f"   ❌ Eroare la extragerea detaliilor XML: {e}")
                return None

        except TimeoutException:
            print("   ⚠️ Timeout: Nu am găsit elementul #upload_error_details")
            return None
        except NoSuchElementException:
            print("   ⚠️ Nu am găsit elementul #upload_error_details")
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
                print(f"   🔍 Text găsit în #upload_error_text: {error_text}")
                match = re.search(r'(\d{3})\s*([^<]+)', error_text)
                if match:
                    error_code, error_status = match.groups()
                    print(f"   📊 Cod eroare detectat din text: {error_code}")
                    print(f"   📊 Status eroare detectat din text: {error_status}")
                    return error_code, error_status
            except NoSuchElementException:
                print("   ⚠️ Nu am găsit nici #upload_error_text")
            return "unknown", "unknown"

    def check_single_tab_for_errors(self, window_handle, tab_index):
        """Verifică o singură filă pentru erori de upload"""
        print(f"\n📋 === VERIFIC FILA #{tab_index}: {window_handle} ===")

        try:
            self.driver.switch_to.window(window_handle)

            # Puțin timp pentru stabilizarea paginii
            time.sleep(1)

            # Afișează URL-ul curent
            current_url = self.driver.current_url
            print(f"   🌐 URL: {current_url}")

            # Afișează titlul paginii
            page_title = self.driver.title
            print(f"   📄 Titlu pagină: '{page_title}'")

            # Verifică dacă există mesajul de eroare
            print("   🔍 Caut mesajul de eroare...")
            try:
                error_div = self.driver.find_element(By.ID, "progress_msg")
                error_text = error_div.text.strip()
                print(f"   📝 Text găsit în #progress_msg: '{error_text}'")

                if "There is a network problem" in error_text or "network problem" in error_text.lower():
                    print("   🚨 EROARE DE NETWORK DETECTATĂ!")
                else:
                    print("   ⚠️ Mesaj neașteptat în #progress_msg, verific codul erorii...")
                    # Verifică direct codul erorii
                    error_code, error_status = self.get_error_code_and_status()
                    if error_code in ["400", "503", "404"]:
                        print(f"   🚨 EROARE DETECTATĂ CU COD: {error_code} {error_status}")

                        # Extrage detaliile erorii din pop-up
                        xml_content = self.get_error_details_from_popup()

                        if xml_content:
                            # Extrage numele fișierului din XML
                            filename = self.extract_filename_from_xml(xml_content)

                            return {
                                "filename": filename,
                                "page_title": page_title,
                                "window_handle": window_handle,
                                "error_code": error_code,
                                "error_status": error_status,
                                "error_details": xml_content,
                                "timestamp": datetime.now().isoformat()
                            }
                        else:
                            print("   ⚠️ Nu am putut obține detaliile XML")
                            self.driver.save_screenshot(f"error_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                            print("   📸 Captură de ecran salvată pentru depanare")
                            return {
                                "filename": "fisier-necunoscut",
                                "page_title": page_title,
                                "window_handle": window_handle,
                                "error_code": error_code,
                                "error_status": error_status,
                                "error_details": "Nu s-au putut obține detalii XML",
                                "timestamp": datetime.now().isoformat()
                            }
                    else:
                        print("   ✅ Nu este eroare relevantă")
                        return None

                # Dacă s-a detectat o eroare de network, procesează-o
                error_code, error_status = self.get_error_code_and_status()

                # Extrage detaliile erorii din pop-up
                xml_content = self.get_error_details_from_popup()

                if xml_content:
                    # Extrage numele fișierului din XML
                    filename = self.extract_filename_from_xml(xml_content)

                    return {
                        "filename": filename,
                        "page_title": page_title,
                        "window_handle": window_handle,
                        "error_code": error_code,
                        "error_status": error_status,
                        "error_details": xml_content,
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    print("   ⚠️ Nu am putut obține detaliile XML")
                    self.driver.save_screenshot(f"error_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                    print("   📸 Captură de ecran salvată pentru depanare")
                    return {
                        "filename": "fisier-necunoscut",
                        "page_title": page_title,
                        "window_handle": window_handle,
                        "error_code": error_code,
                        "error_status": error_status,
                        "error_details": "Nu s-au putut obține detalii XML",
                        "timestamp": datetime.now().isoformat()
                    }

            except NoSuchElementException:
                print("   ✅ Nu există elementul #progress_msg - nu sunt erori")
                return None
            except Exception as e:
                print(f"   ❌ Eroare la căutarea mesajului de eroare: {e}")
                return None

        except Exception as e:
            print(f"   ❌ Eroare generală la verificarea filei: {e}")
            return None

    def check_all_upload_errors(self):
        """Verifică toate filele deschise pentru erori de upload"""
        print("\n🔍 === ÎNCEPUT VERIFICARE ERORI ===")

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

                if error_info:
                    failed_uploads.append(error_info)
                    print(f"   🚨 EROARE CONFIRMATĂ în fila #{i}")
                else:
                    print(f"   ✅ Fila #{i} - OK, nu există erori")

                # Pauză între verificări
                time.sleep(2)

            # Revine la fereastra originală
            try:
                if current_window in self.driver.window_handles:
                    self.driver.switch_to.window(current_window)
                    print(f"\n🏠 M-am întors la fereastra originală: {current_window}")
                elif self.driver.window_handles:
                    self.driver.switch_to.window(self.driver.window_handles[0])
                    print(f"\n🏠 M-am întors la prima fereastră disponibilă")
            except Exception as switch_error:
                print(f"⚠️ Nu am putut reveni la fereastra originală: {switch_error}")

            # Afișează rezultatul final cu erori detaliate
            print(f"\n📊 === REZULTAT FINAL ===")
            print(f"🔍 File verificate: {len(all_windows)}")
            print(f"🚨 Erori găsite: {len(failed_uploads)}")

            if failed_uploads:
                print(f"\n📋 LISTA FIȘIERELOR CU ERORI:")
                for i, error in enumerate(failed_uploads, 1):
                    print(f"   {i}. 📖 {error['filename']}")
                    print(f"      📄 Titlu: {error['page_title']}")
                    print(f"      🚨 Eroare: {error['error_code']} {error['error_status']}")
                    print(f"      🕒 Timp: {error['timestamp']}")
                    if len(error['error_details']) > 100:
                        print(f"      📝 Detalii: {error['error_details'][:100]}...")
                    else:
                        print(f"      📝 Detalii: {error['error_details']}")
                    print()

                # Afișează lista finală doar cu titluri
                print(f"\n📋 LISTA FINALA FIȘIERELOR CU ERORI:")
                for i, error in enumerate(failed_uploads, 1):
                    print(f"   {i}. 📖 {error['filename']}")

                # Salvează rezultatele în fișier doar cu lista finală
                self.save_results_to_file([error['filename'] for error in failed_uploads])
            else:
                print("✅ Nu au fost găsite erori de upload în nicio filă!")

            return failed_uploads

        except Exception as e:
            print(f"❌ Eroare generală la verificarea erorilor: {e}")
            return []

    def save_results_to_file(self, filenames):
        """Salvează doar lista finală a titlurilor într-un fișier"""
        try:
            filename = f"upload_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"LISTA FINALA FIȘIERELOR CU ERORI - {datetime.now().isoformat()}\n")
                f.write("=" * 60 + "\n\n")
                for i, file_name in enumerate(filenames, 1):
                    f.write(f"{i}. 📖 {file_name}\n")
            print(f"📄 Rezultatele au fost salvate în: {filename}")
        except Exception as e:
            print(f"⚠️ Nu am putut salva rezultatele în fișier: {e}")

    def run_test(self):
        """Rulează testul de detectare erori"""
        print("🚀 Încep testul CORECT de detectare erori...")
        print("🎯 Gestionez toate cele 4 tipuri de pop-up-uri!")
        print("=" * 60)

        if not self.driver:
            print("❌ Nu s-a putut conecta la Chrome")
            return False

        results = self.check_all_upload_errors()

        print("\n✅ Test finalizat!")
        return len(results) > 0

def main():
    """Funcția principală pentru test"""
    checker = ErrorChecker(timeout=25)  # Timeout mai mare
    has_errors = checker.run_test()

    if has_errors:
        print("\n🚨 Au fost găsite erori de upload!")
    else:
        print("\n✅ Nu au fost găsite erori!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Test întrerupt de utilizator")
    except Exception as e:
        print(f"❌ Eroare fatală: {e}")
        import traceback
        traceback.print_exc()