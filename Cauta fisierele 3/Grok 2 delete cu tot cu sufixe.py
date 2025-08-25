import time
import os
import shutil
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import json
from datetime import datetime
import re

def setup_browser():
    """Se conectează la Chrome-ul deschis cu debug pe portul 9222."""
    from selenium.webdriver.chrome.service import Service

    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    try:
        driver = webdriver.Chrome(options=chrome_options)
        print(f"      🌐 Conectat la Chrome debug pe port 9222")
        return driver
    except Exception as e:
        print(f"      ❌ Nu pot conecta la Chrome debug: {e}")
        print(f"      💡 Asigură-te că ai rulat start_chrome_debug.bat mai întâi!")
        raise e

def check_duplicate_with_browser(filepath, driver=None, max_retries=2):
    """
    Verifică duplicatele folosind browserul real cu fișierul REAL (OPTIMIZAT).
    """
    filename = os.path.basename(filepath)
    print(f"      🌐 Testez: {filename}")

    if not os.path.exists(filepath):
        print(f"      ❌ Fișierul nu există: {filepath}")
        return False, None

    should_quit_driver = False
    if driver is None:
        driver = setup_browser()
        should_quit_driver = True

    try:
        for attempt in range(max_retries):
            try:
                # Navighează la upload
                driver.get("https://archive.org/upload/")

                # Așteaptă elementul esențial
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
                )

                # Upload fișierul real
                file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                print(f"      ⬆️  Upload: {filename}")
                file_input.send_keys(filepath)

                # Așteaptă procesarea
                print(f"      ⏳ Verific duplicatele (încercarea {attempt + 1}/{max_retries})...")
                time.sleep(8)  # Redus la 8 secunde

                # Verifică CAPTCHA
                captcha_detected = False
                try:
                    captcha = driver.find_element(By.CSS_SELECTOR, ".g-recaptcha, [id*='captcha'], [class*='captcha']")
                    captcha_detected = True
                    print(f"      ⚠️ CAPTCHA detectat! Rezolvă manual în browser și apasă Enter pentru a continua...")
                    input("      Aștept confirmare manuală (apasă Enter): ")
                except NoSuchElementException:
                    pass

                # Așteaptă redirecționarea
                try:
                    WebDriverWait(driver, 5).until(
                        EC.url_contains("archive.org/details/")
                    )
                except TimeoutException:
                    print(f"      🔍 Nu s-a detectat redirecționare")

                # Verifică URL-ul curent
                current_url = driver.current_url
                url_match = re.search(r'archive\.org/details/(.+?)(?:$|\?)', current_url)
                url_id = url_match.group(1) if url_match else None

                # Detectare ID din #item_id
                detected_id = None
                try:
                    item_id_element = driver.find_element(By.CSS_SELECTOR, "#item_id")
                    detected_id = item_id_element.get_attribute('value') or item_id_element.text
                    if detected_id and re.match(r'.+_(scan_)?20\d{4,6}$', detected_id):
                        print(f"      🎯 Duplicat găsit: '{detected_id}'")
                        return True, detected_id  # Ieșim imediat dacă ID-ul indică duplicat
                except NoSuchElementException:
                    print(f"      ❓ Nu pot extrage #item_id (încercarea {attempt + 1})")

                # Caută mesaj de duplicat
                duplicate_message = None
                try:
                    duplicate_message = driver.find_element(By.XPATH, "//*[contains(text(), 'already exists') or contains(text(), 'duplicate item') or contains(text(), 'already uploaded')]").text
                    print(f"      🔍 Mesaj duplicat găsit: {duplicate_message}")
                except NoSuchElementException:
                    pass

                # Caută link către duplicat
                duplicate_link = None
                try:
                    duplicate_link = driver.find_element(By.CSS_SELECTOR, "a[href*='archive.org/details/']").get_attribute('href')
                    link_match = re.search(r'archive\.org/details/(.+?)(?:$|\?)', duplicate_link)
                    if link_match:
                        duplicate_link_id = link_match.group(1)
                        print(f"      🔍 Link duplicat găsit: {duplicate_link}")
                        if not url_id:
                            url_id = duplicate_link_id
                except NoSuchElementException:
                    pass

                # Log pentru depanare
                print(f"      🔍 URL curent: {current_url}")
                print(f"      🔍 ID detectat: {detected_id or 'N/A'}")
                if duplicate_message:
                    print(f"      🔍 Mesaj duplicat: {duplicate_message}")
                if duplicate_link:
                    print(f"      🔍 Link duplicat: {duplicate_link}")

                # Verifică dacă ID-ul sau URL-ul indică un duplicat
                final_id = url_id or detected_id
                if final_id and re.match(r'.+_(scan_)?20\d{4,6}$', final_id):
                    print(f"      🎯 Duplicat găsit: '{final_id}'")
                    return True, final_id
                elif duplicate_message or duplicate_link or captcha_detected:
                    print(f"      🎯 Duplicat găsit bazat pe mesaj/link/captcha: '{final_id or 'N/A'}'")
                    return True, final_id or duplicate_link
                else:
                    print(f"      ❌ Unic (ID: {final_id or 'N/A'})")
                    if attempt == max_retries - 1:
                        # Captură HTML pentru depanare
                        html = driver.page_source
                        html_file = f"debug_upload_{filename}_{attempt + 1}.html"
                        with open(html_file, 'w', encoding='utf-8') as f:
                            f.write(html)
                        print(f"      📄 HTML salvat pentru depanare: {html_file}")
                        return False, final_id
                    time.sleep(1)  # Redus la 1 secundă

            except TimeoutException as e:
                print(f"      ❌ Timeout la upload: {e}")
                if attempt == max_retries - 1:
                    return False, None
                time.sleep(1)
            except Exception as e:
                print(f"      ❌ Eroare browser: {e}")
                if attempt == max_retries - 1:
                    return False, None
                time.sleep(1)
    finally:
        if should_quit_driver and driver:
            driver.quit()

def scan_and_delete_found_folders(base_directory, backup_dir=None):
    """
    Versiunea completă pentru curățarea arhivei cu backup opțional.
    """
    base_path = Path(base_directory)
    if not base_path.exists():
        print(f"❌ Directorul {base_directory} nu există!")
        return

    print("🔍 CURĂȚARE ARHIVĂ cu DETECȚIE DUPLICATE")
    print("="*50)

    # Găsește toate fișierele
    file_extensions = ['.pdf', '.djvu', '.epub', '.rtf', '.doc', '.docx']
    all_files = []
    for ext in file_extensions:
        files_found = list(base_path.rglob(f"*{ext}"))
        all_files.extend(files_found)
        print(f"   {ext}: {len(files_found)} fișiere")

    # Grupează pe foldere de autor
    folders_to_process = {}
    for filepath in all_files:
        try:
            relative_path = Path(filepath).relative_to(base_path)
            if relative_path.parts:
                author_folder_name = relative_path.parts[0]
                author_folder_path = base_path / author_folder_name

                if author_folder_name not in folders_to_process:
                    folders_to_process[author_folder_name] = {
                        'path': str(author_folder_path),
                        'files': []
                    }

                folders_to_process[author_folder_name]['files'].append(str(filepath))
        except ValueError:
            continue

    total_folders = len(folders_to_process)
    print(f"📂 Total foldere: {total_folders}")

    # Un singur driver pentru toate testele
    driver = setup_browser()

    folders_to_delete = []
    duplicates_found = 0

    try:
        for i, (folder_name, folder_info) in enumerate(folders_to_process.items(), 1):
            print(f"[{i:3}/{total_folders}] {folder_name[:40]:<40}", end=" ")

            if folder_info['files']:
                test_file = folder_info['files'][0]
                is_duplicate, detected_id = check_duplicate_with_browser(test_file, driver)

                if is_duplicate:
                    folder_size = calculate_folder_size(folder_info['path'])
                    folders_to_delete.append({
                        'name': folder_name,
                        'path': folder_info['path'],
                        'size': folder_size,
                        'detected_id': detected_id
                    })
                    duplicates_found += 1
                    print(f"✅ DUPLICAT")
                else:
                    print(f"❌ Unic")

                # Pauză minimă
                time.sleep(0.5)  # Redus la 0.5 secunde

    finally:
        driver.quit()

    if not folders_to_delete:
        print(f"\n✅ Niciun duplicat găsit din {total_folders} foldere!")
        return

    # Calculează statistici
    total_size = sum(folder['size'] for folder in folders_to_delete)

    print(f"\n{'='*60}")
    print(f"📊 DUPLICATE DETECTATE: {duplicates_found}/{total_folders}")
    print(f"💾 Spațiu de eliberat: {format_size(total_size)}")
    print(f"{'='*60}")

    for i, folder in enumerate(folders_to_delete[:5], 1):
        print(f"   {i}. {folder['name']} → {folder['detected_id']}")

    if len(folders_to_delete) > 5:
        print(f"   ... și încă {len(folders_to_delete) - 5} foldere")

    confirmation = input(f"\n🗑️  ȘTERGI {duplicates_found} foldere cu duplicate? (DA): ")

    if confirmation.upper() == 'DA':
        print(f"\n🚀 Șterg {duplicates_found} foldere...")
        backup_dir = backup_dir or f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        Path(backup_dir).mkdir(exist_ok=True)

        deleted_count = 0
        deleted_size = 0

        for i, folder in enumerate(folders_to_delete, 1):
            try:
                print(f"[{i:3}/{duplicates_found}] {folder['name'][:35]:<35}", end=" ")
                # Mută în backup înainte de ștergere
                backup_path = os.path.join(backup_dir, folder['name'])
                shutil.move(folder['path'], backup_path)
                deleted_count += 1
                deleted_size += folder['size']
                print(f"✅ Mutat în backup și șters")
            except Exception as e:
                print(f"❌ Eroare: {e}")

        print(f"\n🎉 COMPLET!")
        print(f"   ✅ Șterse: {deleted_count}/{duplicates_found} foldere")
        print(f"   💾 Eliberat: {format_size(deleted_size)}")
        print(f"   📂 Backup: {backup_dir}")

        # Log
        log_file = f"deleted_duplicates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(folders_to_delete, f, ensure_ascii=False, indent=2)
        print(f"   📄 Log: {log_file}")
    else:
        print("❌ Anulat")

def format_size(size_bytes):
    """Formatează dimensiunea în unități citibile."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def calculate_folder_size(folder_path):
    """Calculează dimensiunea unui folder."""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, FileNotFoundError):
                    pass
    except Exception:
        pass
    return total_size

def main():
    print("🤖 CURĂȚARE ARHIVĂ cu SELENIUM")
    print("🎯 Detectează duplicate prin upload real pe Archive.org")

    choice = input("Pornești curățarea completă? (Y/N): ")
    if choice.upper() not in ['Y', 'YES', 'DA']:
        return

    base_directory = r"g:\ARHIVA\C++"
    scan_and_delete_found_folders(base_directory)

if __name__ == "__main__":
    main()