import time
import os
import shutil
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import tempfile
import json  # <- Adaugă asta
from datetime import datetime  # <- Adaugă asta
import re  # <- Adaugă asta

def setup_browser():
    """Se conectează la Chrome-ul deschis cu debug pe portul 9222."""
    from selenium.webdriver.chrome.service import Service

    chrome_options = Options()
    # Se conectează la Chrome-ul existent cu debug
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    try:
        driver = webdriver.Chrome(options=chrome_options)
        print(f"      🌐 Conectat la Chrome debug pe port 9222")
        return driver
    except Exception as e:
        print(f"      ❌ Nu pot conecta la Chrome debug: {e}")
        print(f"      💡 Asigură-te că ai rulat start_chrome_debug.bat mai întâi!")
        raise e

def check_duplicate_with_browser(filepath, driver=None):
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
        # Navighează rapid la upload
        driver.get("https://archive.org/upload/")

        # Așteaptă doar elementul esențial
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
        )

        # SKIP setarea titlului - nu e necesară pentru detectarea duplicatelor
        # Archive.org detectează oricum duplicatele după conținutul fișierului

        # Upload direct fișierul real
        file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
        print(f"      ⬆️  Upload: {os.path.basename(filepath)}")
        file_input.send_keys(filepath)

        # Timp optimizat de așteptare
        print(f"      ⏳ Verific duplicatele...")
        time.sleep(8)  # Redus de la 15 la 8 secunde

        # Detectare rapidă a ID-ului
        detected_id = None

        try:
            # Caută direct elementul #item_id (cel mai rapid)
            item_id_element = driver.find_element(By.CSS_SELECTOR, "#item_id")
            detected_id = item_id_element.get_attribute('value') or item_id_element.text

            if detected_id:
                print(f"      🎯 ID: '{detected_id}'")

                # Verificare rapidă de sufix
                import re
                if re.search(r'_20\d{4,6}$', detected_id):
                    print(f"      ✅ DUPLICAT!")
                    return True, detected_id
                else:
                    print(f"      ❌ Unic")
                    return False, detected_id
            else:
                print(f"      ❓ Nu pot extrage ID")
                return False, None

        except Exception as e:
            print(f"      ❌ Eroare: {e}")
            return False, None

    except Exception as e:
        print(f"      ❌ Eroare browser: {e}")
        return False, None
    finally:
        if should_quit_driver and driver:
            driver.quit()

def scan_and_delete_found_folders(base_directory):
    """
    Versiunea completă pentru curățarea arhivei.
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
                time.sleep(1)
            else:
                print(f"❌ Fără fișiere")

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

    for i, folder in enumerate(folders_to_delete[:5], 1):  # Primele 5
        print(f"   {i}. {folder['name']} → {folder['detected_id']}")

    if len(folders_to_delete) > 5:
        print(f"   ... și încă {len(folders_to_delete) - 5} foldere")

    confirmation = input(f"\n🗑️  ȘTERGI {duplicates_found} foldere cu duplicate? (DA): ")

    if confirmation.upper() == 'DA':
        print(f"\n🚀 Șterg {duplicates_found} foldere...")

        deleted_count = 0
        deleted_size = 0

        for i, folder in enumerate(folders_to_delete, 1):
            try:
                print(f"[{i:3}/{duplicates_found}] {folder['name'][:35]:<35}", end=" ")
                shutil.rmtree(folder['path'])
                deleted_count += 1
                deleted_size += folder['size']
                print(f"✅ Șters")
            except Exception as e:
                print(f"❌ Eroare: {e}")

        print(f"\n🎉 COMPLET!")
        print(f"   ✅ Șterse: {deleted_count}/{duplicates_found} foldere")
        print(f"   💾 Eliberat: {format_size(deleted_size)}")

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

def scan_with_browser_automation(base_directory):
    """Scanează folosind automatizarea browserului."""
    base_path = Path(base_directory)

    print("🔍 Scanez cu automatizare browser real...")
    print("="*50)

    # Găsește toate fișierele
    all_files = []
    for ext in ['.pdf']:  # Testez doar PDF-uri pentru început
        all_files.extend(base_path.rglob(f"*{ext}"))

    # Grupează pe foldere
    folders_to_process = {}
    for filepath in all_files[:3]:  # Testez doar primele 3
        try:
            relative_path = Path(filepath).relative_to(base_path)
            if relative_path.parts:
                author_folder_name = relative_path.parts[0]
                if author_folder_name not in folders_to_process:
                    folders_to_process[author_folder_name] = {
                        'path': str(base_path / author_folder_name),
                        'files': [str(filepath)]
                    }
        except ValueError:
            continue

    duplicates_found = []

    for i, (folder_name, folder_info) in enumerate(folders_to_process.items(), 1):
        print(f"[{i}] {folder_name}")

        if folder_info['files']:
            test_file = folder_info['files'][0]
            is_duplicate, detected_id = check_duplicate_with_browser(test_file)

            if is_duplicate:
                duplicates_found.append({
                    'name': folder_name,
                    'path': folder_info['path'],
                    'detected_id': detected_id
                })
                print(f"   ✅ DUPLICAT: {detected_id}")
            else:
                print(f"   ❌ Unic")

    if duplicates_found:
        print(f"\n🎯 Găsite {len(duplicates_found)} duplicate!")
        for dup in duplicates_found:
            print(f"   - {dup['name']} → {dup['detected_id']}")
    else:
        print("\n✅ Niciun duplicat găsit")

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