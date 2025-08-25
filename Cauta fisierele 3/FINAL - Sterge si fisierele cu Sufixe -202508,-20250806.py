import re
import requests
import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote_plus
from datetime import datetime

# Sufixe comune de duplicate de testat
COMMON_DUPLICATE_SUFFIXES = [
    '_202508', '_20250806', '_202507', '_20250705', '_202506', '_20250604',
    '_202505', '_20250503', '_202504', '_20250402', '_202503', '_20250301',
    '_202502', '_20250201', '_202501', '_20250101', '_202412', '_20241201',
    '_202411', '_20241101', '_202410', '_20241001', '_202409', '_20240901',
    '_202408', '_20240801', '_202407', '_20240701', '_202406', '_20240601'
]

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

def create_archive_identifier(words):
    """Creează un identificator Archive.org din cuvinte."""
    # Archive.org folosește lowercase și înlocuiește spații cu cratimă
    identifier_base = '-'.join(words)
    # Elimină caractere speciale și consecutive dashes
    identifier_base = re.sub(r'[^\w\-]', '', identifier_base)
    identifier_base = re.sub(r'-+', '-', identifier_base).strip('-')
    return identifier_base

def check_direct_url_exists(url, timeout=5):
    """Verifică dacă un URL există prin HTTP request direct."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)

        # 200 = există, 404 = nu există, alte coduri = poate exista dar e restricționat
        if response.status_code == 200:
            return True, "exists_public"
        elif response.status_code == 403:
            return True, "exists_restricted"  # Există dar e restricționat
        elif response.status_code in [301, 302]:
            return True, "exists_redirected"  # Există dar e redirectat
        else:
            return False, f"status_{response.status_code}"

    except requests.RequestException:
        return False, "connection_error"

def search_with_suffix_detection(query_words, min_relevance_score=0.5, debug=False):
    """
    Caută pe Archive.org cu verificare normală + verificare de sufixe.
    """
    query = ' '.join(query_words)

    # 1. Încearcă căutarea normală prin API
    found_normal, results_normal = search_archive_org_normal(query, min_relevance_score)

    if found_normal and results_normal:
        if debug:
            print(f"\n      ✅ Găsit prin API normal: {results_normal[0]['title'][:50]}")
        return True, results_normal, "normal_search"

    # 2. Dacă nu găsește normal, testează URL-uri cu sufixe
    if debug:
        print(f"\n      🔍 Nu găsit prin API, testez sufixe pentru: {query}")

    identifier_base = create_archive_identifier(query_words)

    # Testează URL-ul de bază
    base_url = f"https://archive.org/details/{identifier_base}"
    exists, status = check_direct_url_exists(base_url)
    if exists:
        if debug:
            print(f"      ✅ Găsit URL de bază: {base_url}")
        return True, [{'title': f"{query.title()}", 'url': base_url, 'relevance_score': 1.0}], "direct_base"

    # Testează sufixe
    if debug:
        print(f"      🔗 Testez sufixe pentru: {identifier_base}")

    for i, suffix in enumerate(COMMON_DUPLICATE_SUFFIXES[:15]):
        test_url = f"https://archive.org/details/{identifier_base}{suffix}"
        exists, status = check_direct_url_exists(test_url)
        if exists:
            if debug:
                print(f"      ✅ Găsit cu sufix {suffix}: {status}")
            return True, [{'title': f"{query.title()}{suffix}", 'url': test_url, 'relevance_score': 0.95}], "suffix_detection"

        # La fiecare 5 sufixe, afișează progres
        if debug and (i + 1) % 5 == 0:
            print(f"      🔍 Testat {i + 1}/15 sufixe...")

        time.sleep(0.1)

    if debug:
        print(f"      ❌ Nu găsit nici cu sufixe")

    return False, [], "not_found"

def search_archive_org_normal(query, min_relevance_score=0.5):
    """Căutarea normală prin API (codul existent)."""
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

def scan_and_delete_found_folders(base_directory, use_backup=True, debug_mode=False):
    """
    Scanează arhiva și șterge automat folderele găsite pe Archive.org.
    Include căutarea cu sufixe pentru fișierele ascunse.
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

    print("🔍 Scanez arhiva și caut pe Archive.org (inclusiv cu sufixe)...")
    print("="*70)

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
    print("\n🔍 Încep căutarea pe Archive.org (normală + sufixe)...")
    print("="*70)

    folders_to_delete = []
    processed = 0
    found_count = 0
    found_by_suffix = 0

    start_time = time.time()

    for folder_name, folder_info in folders_to_process.items():
        processed += 1

        # Afișează progresul pentru FIECARE folder
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        eta_seconds = (total_folders - processed) / rate if rate > 0 else 0
        eta_minutes = int(eta_seconds / 60)

        print(f"[{processed:3}/{total_folders}] {folder_name[:35]:<35}", end=" ")

        if folder_info['files']:
            test_file = folder_info['files'][0]
            search_query, filtered_words = process_filename(test_file)

            print(f"🔍 Caut...", end=" ")

            # Folosim noua funcție cu detectare de sufixe
            found, results, detection_method = search_with_suffix_detection(
                filtered_words,
                min_relevance_score=0.5,
                debug=debug_mode
            )

            if found and results:
                folder_size = calculate_folder_size(folder_info['path'])

                best_result = results[0]  # Primul rezultat (cel mai relevant)

                folders_to_delete.append({
                    'name': folder_name,
                    'path': folder_info['path'],
                    'size': folder_size,
                    'files_count': len(folder_info['files']),
                    'query': search_query,
                    'best_match': best_result['title'],
                    'archive_url': best_result['url'],
                    'detection_method': detection_method,
                    'relevance_score': best_result.get('relevance_score', 0.5)
                })

                found_count += 1
                if detection_method == "suffix_detection":
                    found_by_suffix += 1
                    method_symbol = "🔗"  # Link direct
                else:
                    method_symbol = "🔍"  # Căutare normală

                print(f"✅ {method_symbol} GĂSIT ({format_size(folder_size)}) ETA: {eta_minutes}min")

            else:
                print(f"❌ Nu există    ETA: {eta_minutes}min")
        else:
            print("❌ Fără fișiere")

        time.sleep(0.4)  # Pauză puțin mai mare pentru requests-urile suplimentare

    if not folders_to_delete:
        print("\n✅ Nu s-au găsit foldere de șters. Toate cărțile din arhivă sunt unice!")
        return

    # Calculează statistici
    total_size = sum(folder['size'] for folder in folders_to_delete)

    print(f"\n{'='*70}")
    print(f"📊 RAPORT FINAL")
    print(f"{'='*70}")
    print(f"Foldere procesate: {total_folders}")
    print(f"Foldere găsite pe Archive.org: {found_count}")
    print(f"   • Prin căutare normală: {found_count - found_by_suffix}")
    print(f"   • Prin detectare sufixe: {found_by_suffix}")
    print(f"Spațiu de eliberat: {format_size(total_size)}")
    print(f"Rata de succes: {found_count/total_folders*100:.1f}%")

    print(f"\n📋 Primele 10 foldere de șters:")
    for i, folder in enumerate(folders_to_delete[:10], 1):
        method_symbol = "🔗" if folder['detection_method'] == "suffix_detection" else "🔍"
        print(f"   {i:2}. {method_symbol} {folder['name'][:30]:<30} - {format_size(folder['size']):>8}")
        print(f"       URL: {folder['archive_url']}")

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
        print("="*70)

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
        print(f"{'='*70}")
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
    base_directory = r"g:\ARHIVA\C++"

    choice = input("🗑️  Vrei să ștergi toate folderele găsite pe Archive.org? (Y/N): ")

    if choice.upper() not in ['Y', 'YES', 'DA']:
        print("❌ Operațiune anulată")
        return

    print("🚀 Încep scanarea și ștergerea...")
    scan_and_delete_found_folders(base_directory)

if __name__ == "__main__":
    main()