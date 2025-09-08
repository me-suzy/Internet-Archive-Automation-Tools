import re
import requests
import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote_plus
from datetime import datetime

def process_filename(filepath):
    """Procesează numele fișierului pentru a genera query de căutare."""
    filename = os.path.splitext(os.path.basename(filepath))[0]

    words_to_remove = [
        'retail', 'scan', 'ctrl', 'ocr', 'vp', 'istor',
        'trad', 'trad.', 'ed', 'edition', 'vol', 'tome'
    ]

    filename = re.sub(r'\([^)]*\)', '', filename)
    filename = re.sub(r'\d+', '', filename)
    words = re.findall(r'\w+', filename.lower())
    filtered_words = [word for word in words if word not in words_to_remove]

    return ' '.join(filtered_words), filtered_words

def calculate_relevance_score(query_words, result_title, result_creator=""):
    """Calculează scorul de relevanță între query și rezultat."""
    query_text = ' '.join(query_words).lower()
    title_text = (result_title + " " + result_creator).lower()

    query_text = re.sub(r'[^\w\s]', ' ', query_text)
    title_text = re.sub(r'[^\w\s]', ' ', title_text)

    query_words_set = set(query_text.split())
    title_words_set = set(title_text.split())

    common_words = query_words_set.intersection(title_words_set)

    if not query_words_set:
        return 0, common_words

    base_score = len(common_words) / len(query_words_set)
    important_words = list(query_words_set)[:3]
    important_matches = sum(1 for word in important_words if word in title_words_set)
    importance_bonus = important_matches / len(important_words) * 0.3

    return min(base_score + importance_bonus, 1.0), common_words

def search_archive_org(query, min_relevance_score=0.5):
    """Caută pe archive.org cu verificare de relevanță."""
    url = f"https://archive.org/advancedsearch.php?q={quote_plus(query)}&output=json&rows=5"

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        docs = data.get('response', {}).get('docs', [])

        query_words = query.lower().split()
        relevant_results = []

        for doc in docs:
            title = doc.get('title', [''])
            if isinstance(title, list):
                title = title[0] if title else ''

            creator = doc.get('creator', [''])
            if isinstance(creator, list):
                creator = ', '.join(creator) if creator else ''

            relevance_score, common_words = calculate_relevance_score(query_words, title, creator)

            if relevance_score >= min_relevance_score:
                relevant_results.append({
                    'title': title,
                    'creator': creator,
                    'relevance_score': relevance_score,
                    'identifier': doc.get('identifier', ''),
                    'url': f"https://archive.org/details/{doc.get('identifier', '')}"
                })

        return len(relevant_results) > 0, relevant_results

    except Exception:
        return False, []

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

def format_size(size_bytes):
    """Formatează dimensiunea în unități citibile."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def scan_and_delete_found_folders(base_directory, use_backup=True):
    """
    Scanează arhiva și șterge automat SUBFOLDERELE găsite pe Archive.org.
    VERSIUNE CORECTATĂ - testează fiecare subfolder individual.
    """
    base_path = Path(base_directory)
    if not base_path.exists():
        print(f"❌ Directorul {base_directory} nu există!")
        return

    backup_directory = None
    if use_backup:
        backup_directory = str(base_path.parent / "ARCHIVE_BACKUP")
        os.makedirs(backup_directory, exist_ok=True)
        print(f"🔒 Backup folder: {backup_directory}")
    else:
        print("⚠️  Modul ȘTERGERE DEFINITIVĂ activat!")

    print("🔍 Scanez arhiva și caut pe Archive.org...")
    print("="*60)

    # Găsește toate fișierele
    print("📄 Caut fișiere în arhivă...")
    file_extensions = ['.pdf', '.djvu', '.epub', '.rtf', '.doc', '.docx', '.txt']
    all_files = []
    for ext in file_extensions:
        files_found = list(base_path.rglob(f"*{ext}"))
        all_files.extend(files_found)
        print(f"   Găsite {len(files_found)} fișiere {ext}")

    print(f"📊 Total fișiere găsite: {len(all_files)}")

    # MODIFICARE CRITICĂ: Grupează pe SUBFOLDERE, nu pe autor
    print("📂 Grupez pe subfoldere individuale...")
    subfolders_to_process = {}

    for filepath in all_files:
        try:
            relative_path = Path(filepath).relative_to(base_path)

            # Pentru fiecare fișier, identifică subfolderul direct
            if len(relative_path.parts) >= 2:
                # Format: author/book_folder/file.pdf
                author_name = relative_path.parts[0]
                book_folder = relative_path.parts[1]
                subfolder_key = f"{author_name}/{book_folder}"
                subfolder_path = base_path / author_name / book_folder

                if subfolder_key not in subfolders_to_process:
                    subfolders_to_process[subfolder_key] = {
                        'path': str(subfolder_path),
                        'files': [],
                        'author': author_name,
                        'book': book_folder
                    }

                subfolders_to_process[subfolder_key]['files'].append(str(filepath))
            elif len(relative_path.parts) == 2:
                # Format direct: author/file.pdf
                author_name = relative_path.parts[0]
                author_folder_path = base_path / author_name

                if author_name not in subfolders_to_process:
                    subfolders_to_process[author_name] = {
                        'path': str(author_folder_path),
                        'files': [],
                        'author': author_name,
                        'book': 'direct_files'
                    }

                subfolders_to_process[author_name]['files'].append(str(filepath))

        except ValueError:
            continue

    total_subfolders = len(subfolders_to_process)
    print(f"📂 Găsite {total_subfolders} subfoldere de procesat")
    print("\n🔍 Încep căutarea pe Archive.org...")
    print("="*60)

    subfolders_to_delete = []
    processed = 0
    found_count = 0
    start_time = time.time()

    # TESTEAZĂ FIECARE SUBFOLDER INDIVIDUAL
    for subfolder_key, subfolder_info in subfolders_to_process.items():
        processed += 1

        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        eta_seconds = (total_subfolders - processed) / rate if rate > 0 else 0
        eta_minutes = int(eta_seconds / 60)

        display_name = f"{subfolder_info['author']} - {subfolder_info['book']}"
        print(f"[{processed:3}/{total_subfolders}] {display_name[:50]:<50}", end=" ")

        if subfolder_info['files']:
            test_file = subfolder_info['files'][0]
            search_query, _ = process_filename(test_file)

            print(f"🔍 Caut...", end=" ")

            found, results = search_archive_org(search_query, min_relevance_score=0.5)

            if found and results:
                subfolder_size = calculate_folder_size(subfolder_info['path'])
                subfolders_to_delete.append({
                    'name': display_name,
                    'path': subfolder_info['path'],
                    'size': subfolder_size,
                    'files_count': len(subfolder_info['files']),
                    'query': search_query,
                    'best_match': results[0]['title'],
                    'relevance_score': results[0]['relevance_score'],
                    'author': subfolder_info['author'],
                    'book': subfolder_info['book']
                })
                found_count += 1
                print(f"✅ GĂSIT ({format_size(subfolder_size)}) ETA: {eta_minutes}min")
            else:
                print(f"❌ Nu există    ETA: {eta_minutes}min")
        else:
            print("❌ Fără fișiere")

        time.sleep(0.3)

    # =================== PARTEA CARE LIPSEA ===================

    if not subfolders_to_delete:
        print("\n✅ Nu s-au găsit subfoldere de șters. Toate cărțile din arhivă sunt unice!")
        return

    # Calculează statistici
    total_size = sum(subfolder['size'] for subfolder in subfolders_to_delete)

    print(f"\n{'='*60}")
    print(f"📊 RAPORT FINAL")
    print(f"{'='*60}")
    print(f"Subfoldere procesate: {total_subfolders}")
    print(f"Subfoldere găsite pe Archive.org: {found_count}")
    print(f"Spațiu de eliberat: {format_size(total_size)}")
    print(f"Rata de succes: {found_count/total_subfolders*100:.1f}%")

    print(f"\n📋 Primele 10 subfoldere de șters:")
    for i, subfolder in enumerate(subfolders_to_delete[:10], 1):
        print(f"   {i:2}. {subfolder['name'][:50]:<50} - {format_size(subfolder['size']):>8}")
        print(f"       Găsit ca: {subfolder['best_match'][:60]}")

    if len(subfolders_to_delete) > 10:
        print(f"   ... și încă {len(subfolders_to_delete) - 10} subfoldere")

    if use_backup:
        print(f"\n⚠️  ATENȚIE!")
        print(f"   • Se vor muta {found_count} subfoldere în backup")
        print(f"   • Se vor elibera {format_size(total_size)} de spațiu")
        print(f"   • Backup folder: {backup_directory}")
    else:
        print(f"\n⚠️  ATENȚIE - ȘTERGERE DEFINITIVĂ!")
        print(f"   • Se vor ȘTERGE DEFINITIV {found_count} subfoldere")
        print(f"   • Se vor elibera {format_size(total_size)} de spațiu")
        print(f"   • NU VA EXISTA BACKUP!")

    # Confirmarea finală
    action_word = "muta în backup" if use_backup else "șterge definitiv"
    confirmation = input(f"\n🗑️  Dorești să {action_word} toate subfolderele găsite? (scrie 'DA' pentru confirmare): ")

    if confirmation.upper() == 'DA':
        action_msg = f"backup-ul {found_count} subfoldere..." if use_backup else f"ștergerea DEFINITIVĂ a {found_count} subfoldere..."
        print(f"\n🚀 Încep {action_msg}")
        print("="*60)

        deleted_count = 0
        deleted_size = 0

        for i, subfolder in enumerate(subfolders_to_delete, 1):
            try:
                action_verb = "Backup" if use_backup else "Șterg"
                print(f"[{i:3}/{found_count}] {action_verb} {subfolder['name'][:40]:<40}", end=" ")

                if use_backup:
                    # Mută în backup cu timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = subfolder['name'].replace('/', '_').replace('\\', '_')
                    backup_path = os.path.join(backup_directory, f"{safe_name}_{timestamp}")
                    shutil.move(subfolder['path'], backup_path)
                    print(f"✅ Mutat ({format_size(subfolder['size'])})")
                else:
                    # Șterge definitiv
                    shutil.rmtree(subfolder['path'])
                    print(f"✅ Șters definitiv ({format_size(subfolder['size'])})")

                deleted_count += 1
                deleted_size += subfolder['size']

            except Exception as e:
                print(f"❌ Eroare: {e}")

        print(f"\n🎉 OPERAȚIUNE COMPLETĂ!")
        print(f"{'='*60}")
        print(f"   ✅ Subfoldere procesate: {deleted_count}/{found_count}")
        print(f"   💾 Spațiu eliberat: {format_size(deleted_size)}")

        if use_backup:
            print(f"   🔒 Backup salvat în: {backup_directory}")
        else:
            print(f"   ⚠️  Subfoldere ȘTERSE DEFINITIV - nu există backup!")

        # Salvează log-ul
        log_file = f"deleted_subfolders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(subfolders_to_delete, f, ensure_ascii=False, indent=2)
        print(f"   📄 Log salvat în: {log_file}")

    else:
        print("❌ Operațiune anulată.")



def main():
    base_directory = r"g:\ARHIVA\C"

    print("🗄️  CURĂȚARE AUTOMATĂ ARHIVĂ")
    print("="*50)
    print("Acest program va:")
    print("• Scana toate folderele din arhivă")
    print("• Căuta fiecare carte pe Archive.org")
    print("• Șterge/Muta folderele găsite online")
    print("="*50)

    # Întreabă utilizatorul ce vrea
    backup_choice = input("\nCe vrei să fac cu folderele găsite?\n1. Mută în backup (sigur)\n2. Șterge definitiv (risky)\nAlege (1 sau 2): ")

    use_backup = backup_choice != "2"

    if use_backup:
        print("✅ Folderele vor fi mutate în backup")
    else:
        print("⚠️  ATENȚIE: Folderele vor fi ȘTERSE DEFINITIV!")
        confirm = input("Ești sigur? (scrie 'DA' pentru confirmare): ")
        if confirm != "DA":
            print("❌ Operațiune anulată")
            return

    input("\nApasă ENTER pentru a începe scanarea...")

    scan_and_delete_found_folders(base_directory, use_backup=use_backup)

if __name__ == "__main__":
    main()