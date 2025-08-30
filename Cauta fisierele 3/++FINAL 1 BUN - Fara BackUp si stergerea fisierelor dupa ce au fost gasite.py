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
    Scanează arhiva și șterge automat folderele găsite pe Archive.org.
    """
    base_path = Path(base_directory)
    if not base_path.exists():
        print(f"❌ Directorul {base_directory} nu există!")
        return

    backup_directory = None
    if use_backup:
        # Creează directorul de backup
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

    # Grupează pe foldere de autor
    print("📂 Grupez pe foldere de autor...")
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
    print(f"📂 Găsite {total_folders} foldere de procesat")
    print("\n🔍 Încep căutarea pe Archive.org...")
    print("="*60)

    folders_to_delete = []
    processed = 0
    found_count = 0

    start_time = time.time()

    for folder_name, folder_info in folders_to_process.items():
        processed += 1

        # Afișează progresul pentru FIECARE folder
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        eta_seconds = (total_folders - processed) / rate if rate > 0 else 0
        eta_minutes = int(eta_seconds / 60)

        print(f"[{processed:3}/{total_folders}] {folder_name[:40]:<40}", end=" ")

        if folder_info['files']:
            test_file = folder_info['files'][0]
            search_query, _ = process_filename(test_file)

            print(f"🔍 Caut...", end=" ")

            found, results = search_archive_org(search_query, min_relevance_score=0.5)

            if found and results:
                folder_size = calculate_folder_size(folder_info['path'])
                folders_to_delete.append({
                    'name': folder_name,
                    'path': folder_info['path'],
                    'size': folder_size,
                    'files_count': len(folder_info['files']),
                    'query': search_query,
                    'best_match': results[0]['title'],
                    'relevance_score': results[0]['relevance_score']
                })
                found_count += 1
                print(f"✅ GĂSIT ({format_size(folder_size)}) ETA: {eta_minutes}min")
            else:
                print(f"❌ Nu există    ETA: {eta_minutes}min")
        else:
            print("❌ Fără fișiere")

        time.sleep(0.3)  # Pauză pentru a nu suprasolicita API-ul

    if not folders_to_delete:
        print("\n✅ Nu s-au găsit foldere de șters. Toate cărțile din arhivă sunt unice!")
        return

    # Calculează statistici
    total_size = sum(folder['size'] for folder in folders_to_delete)

    print(f"\n{'='*60}")
    print(f"📊 RAPORT FINAL")
    print(f"{'='*60}")
    print(f"Foldere procesate: {total_folders}")
    print(f"Foldere găsite pe Archive.org: {found_count}")
    print(f"Spațiu de eliberat: {format_size(total_size)}")
    print(f"Rata de succes: {found_count/total_folders*100:.1f}%")

    print(f"\n📋 Primele 10 foldere de șters:")
    for i, folder in enumerate(folders_to_delete[:10], 1):
        print(f"   {i:2}. {folder['name'][:35]:<35} - {format_size(folder['size']):>8}")
        print(f"       Găsit ca: {folder['best_match'][:50]}")

    if len(folders_to_delete) > 10:
        print(f"   ... și încă {len(folders_to_delete) - 10} foldere")

    if use_backup:
        print(f"\n⚠️  ATENȚIE!")
        print(f"   • Se vor muta {found_count} foldere în backup")
        print(f"   • Se vor elibera {format_size(total_size)} de spațiu")
        print(f"   • Backup folder: {backup_directory}")
    else:
        print(f"\n⚠️  ATENȚIE - ȘTERGERE DEFINITIVĂ!")
        print(f"   • Se vor ȘTERGE DEFINITIV {found_count} foldere")
        print(f"   • Se vor elibera {format_size(total_size)} de spațiu")
        print(f"   • NU VA EXISTA BACKUP!")

    # Confirmarea finală
    action_word = "muta în backup" if use_backup else "șterge definitiv"
    confirmation = input(f"\n🗑️  Dorești să {action_word} toate folderele găsite? (scrie 'DA' pentru confirmare): ")

    if confirmation.upper() == 'DA':
        action_msg = f"backup-ul {found_count} foldere..." if use_backup else f"ștergerea DEFINITIVĂ a {found_count} foldere..."
        print(f"\n🚀 Încep {action_msg}")
        print("="*60)

        deleted_count = 0
        deleted_size = 0

        for i, folder in enumerate(folders_to_delete, 1):
            try:
                action_verb = "Backup" if use_backup else "Șterg"
                print(f"[{i:3}/{found_count}] {action_verb} {folder['name'][:40]:<40}", end=" ")

                if use_backup:
                    # Mută în backup cu timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_path = os.path.join(backup_directory, f"{folder['name']}_{timestamp}")
                    shutil.move(folder['path'], backup_path)
                    print(f"✅ Mutat ({format_size(folder['size'])})")
                else:
                    # Șterge definitiv
                    shutil.rmtree(folder['path'])
                    print(f"✅ Șters definitiv ({format_size(folder['size'])})")

                deleted_count += 1
                deleted_size += folder['size']

            except Exception as e:
                print(f"❌ Eroare: {e}")

        print(f"\n🎉 OPERAȚIUNE COMPLETĂ!")
        print(f"{'='*60}")
        print(f"   ✅ Foldere procesate: {deleted_count}/{found_count}")
        print(f"   💾 Spațiu eliberat: {format_size(deleted_size)}")

        if use_backup:
            print(f"   🔒 Backup salvat în: {backup_directory}")
        else:
            print(f"   ⚠️  Foldere ȘTERSE DEFINITIV - nu există backup!")

        # Salvează log-ul
        log_file = f"deleted_folders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(folders_to_delete, f, ensure_ascii=False, indent=2)
        print(f"   📄 Log salvat în: {log_file}")

    else:
        print("❌ Operațiune anulată.")

def main():
    base_directory = r"g:\ARHIVA\A"

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