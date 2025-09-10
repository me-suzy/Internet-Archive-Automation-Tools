import re
import requests
import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote_plus
from datetime import datetime

# Instalează mai întâi: pip install rapidfuzz
try:
    from rapidfuzz import fuzz, process
    FUZZY_AVAILABLE = True
except ImportError:
    print("⚠️ Pentru rezultate optime, instalează: pip install rapidfuzz")
    FUZZY_AVAILABLE = False

def normalize_clan_names(text):
    """Normalizează numele de clanuri pentru variații comune."""
    # Înlocuiește variații comune de clanuri scoțiene
    clan_variations = {
        'mcgregor': ['mc gregor', 'mcgregor', 'mac gregor', 'macgregor'],
        'macdonald': ['mac donald', 'macdonald', 'mc donald', 'mcdonald'],
        'macleod': ['mac leod', 'macleod', 'mc leod', 'mcleod'],
        'mackenzie': ['mac kenzie', 'mackenzie', 'mc kenzie', 'mckenzie'],
        'campbell': ['campbell', 'cambel'],
        'stuart': ['stuart', 'stewart'],
    }

    text_lower = text.lower()
    variations = []

    # Adaugă textul original
    variations.append(text)

    # Generează variații pentru fiecare clan găsit
    for base_clan, variants in clan_variations.items():
        for variant in variants:
            if variant in text_lower:
                for other_variant in variants:
                    if other_variant != variant:
                        new_text = re.sub(re.escape(variant), other_variant, text, flags=re.IGNORECASE)
                        if new_text != text:
                            variations.append(new_text)

    return list(set(variations))  # Elimină duplicatele

def extract_title_from_filename_improved(filepath):
    """Extrage titlul cărții din numele fișierului PDF cu normalizare îmbunătățită."""
    filename = os.path.splitext(os.path.basename(filepath))[0]

    # Încearcă să identifice pattern-ul "Autor - Serie - Număr. Titlu"
    if ' - ' in filename:
        parts = filename.split(' - ')
        if len(parts) >= 2:
            author_part = parts[0].strip()
            title_part = ' - '.join(parts[1:]).strip()
            return author_part, title_part

    # Curăță numele fișierului
    cleanup_words = [
        'scan', 'ctrl', 'ocr', 'retail', 'foto', 'conv', 'convert',
        'epub', 'pdf', 'djvu', 'mobi', 'mmxii', 'mmxi', 'mmxx'
    ]

    clean_name = filename
    for word in cleanup_words:
        clean_name = re.sub(rf'\b{word}\b', '', clean_name, flags=re.IGNORECASE)

    # Elimină numere izolate și caractere speciale
    clean_name = re.sub(r'\b\d+\b', '', clean_name)
    clean_name = re.sub(r'[._\-]+', ' ', clean_name)
    clean_name = ' '.join(clean_name.split())

    return "", clean_name

def generate_search_strategies_enhanced(author, title, filepath):
    """Generează strategii de căutare îmbunătățite cu variații de clanuri."""
    strategies = []

    # Curăță titlul pentru căutare
    title_clean = title.strip()
    if not title_clean:
        return strategies

    # Elimină cuvinte de zgomot
    noise_words = ['scan', 'ctrl', 'ocr', 'retail', 'foto', 'conv', 'convert', 'epub', 'pdf', 'djvu', 'mobi']
    title_words = [word for word in title_clean.split() if word.lower() not in noise_words and len(word) > 1]

    # Generează variații pentru nume de clanuri
    title_variations = normalize_clan_names(title_clean)

    # Pentru fiecare variație de titlu, generează strategii
    for title_var in title_variations:
        title_var_words = [word for word in title_var.split() if word.lower() not in noise_words and len(word) > 1]
        title_keywords = ' '.join(title_var_words[:8])  # Mai multe cuvinte pentru cărți cu titluri lungi

        if not title_keywords:
            continue

        # Strategia 1: Doar titlul (cea mai eficientă)
        strategies.append({
            'name': 'doar_titlu',
            'query': title_keywords,
            'description': f"Doar titlu: {title_keywords}",
            'priority': 1
        })

        # Strategia 2: Titlu cu fuzzy search (folosind ~)
        if len(title_var_words) >= 2:
            fuzzy_title = ' '.join([f"{word}~" for word in title_var_words[:4]])
            strategies.append({
                'name': 'titlu_fuzzy',
                'query': fuzzy_title,
                'description': f"Titlu fuzzy: {fuzzy_title}",
                'priority': 2
            })

        # Strategia 3: Căutare părți din titlu (pentru titluri lungi)
        if len(title_var_words) >= 3:
            key_words = title_var_words[:3]  # Primele 3 cuvinte cele mai importante
            partial_title = ' '.join(key_words)
            strategies.append({
                'name': 'titlu_partial',
                'query': partial_title,
                'description': f"Titlu partial: {partial_title}",
                'priority': 3
            })

    # Strategii cu autor (doar pentru variația originală)
    if author.strip():
        author_clean = author.strip()
        author_variations = normalize_clan_names(author_clean)

        for author_var in author_variations:
            for title_var in title_variations[:2]:  # Doar primele 2 variații de titlu
                title_var_words = [word for word in title_var.split() if word.lower() not in noise_words and len(word) > 1]
                title_keywords = ' '.join(title_var_words[:6])

                if title_keywords:
                    combined_query = f"{author_var} {title_keywords}"
                    strategies.append({
                        'name': f'autor_titlu',
                        'query': combined_query,
                        'description': f"Autor + titlu: {combined_query}",
                        'priority': 4
                    })

    # Sortează strategiile după prioritate
    strategies.sort(key=lambda x: x['priority'])

    # Returnează doar primele 6 strategii pentru a evita spam-ul
    return strategies[:6]

def search_archive_org_aggressive(strategies, min_relevance_score=0.2):
    """Căutare agresivă cu threshold mai mic și fuzzy matching îmbunătățit."""
    all_results = []

    for strategy in strategies:
        query = strategy['query']
        if not query.strip():
            continue

        try:
            url = f"https://archive.org/advancedsearch.php?q={quote_plus(query)}&output=json&rows=12"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=12)
            response.raise_for_status()

            data = response.json()
            docs = data.get('response', {}).get('docs', [])

            for doc in docs:
                title = doc.get('title', [''])
                if isinstance(title, list):
                    title = title[0] if title else ''

                creator = doc.get('creator', [''])
                if isinstance(creator, list):
                    creator = ', '.join(creator) if creator else ''

                # Calculează scorul de relevanță cu fuzzy matching agresiv
                query_words = re.sub(r'[~"]', '', query).replace('title:', '').replace('creator:', '').replace('AND', '').split()
                query_words = [w for w in query_words if len(w) > 1 and w not in ['(', ')']]

                if FUZZY_AVAILABLE:
                    relevance_score, score_details = calculate_aggressive_fuzzy_relevance(query_words, title, creator)
                else:
                    relevance_score, common_words = calculate_relevance_score_aggressive(query_words, title, creator)
                    score_details = {'common_words': common_words}

                if relevance_score >= min_relevance_score:
                    result = {
                        'title': title,
                        'creator': creator,
                        'relevance_score': relevance_score,
                        'identifier': doc.get('identifier', ''),
                        'url': f"https://archive.org/details/{doc.get('identifier', '')}",
                        'strategy': strategy['name'],
                        'strategy_description': strategy['description'],
                        'score_details': score_details
                    }
                    all_results.append(result)

        except Exception as e:
            print(f"Eroare căutare pentru strategia '{strategy['name']}': {e}")
            continue

    # Elimină duplicatele și sortează
    unique_results = {}
    for result in all_results:
        identifier = result['identifier']
        if identifier not in unique_results or result['relevance_score'] > unique_results[identifier]['relevance_score']:
            unique_results[identifier] = result

    final_results = list(unique_results.values())
    final_results.sort(key=lambda x: x['relevance_score'], reverse=True)

    return len(final_results) > 0, final_results[:3]

def calculate_aggressive_fuzzy_relevance(query_words, result_title, result_creator=""):
    """Calculează scorul de relevanță cu fuzzy matching foarte agresiv."""
    if not FUZZY_AVAILABLE:
        return calculate_relevance_score_aggressive(query_words, result_title, result_creator)

    query_text = ' '.join(query_words).lower()
    title_text = (result_title + " " + result_creator).lower()

    # Normalizează și curăță textele
    query_clean = re.sub(r'[^\w\s]', ' ', query_text)
    title_clean = re.sub(r'[^\w\s]', ' ', title_text)

    # Calculează multiple scoruri fuzzy
    ratio_score = fuzz.ratio(query_clean, title_clean) / 100
    partial_score = fuzz.partial_ratio(query_clean, title_clean) / 100
    token_sort_score = fuzz.token_sort_ratio(query_clean, title_clean) / 100
    token_set_score = fuzz.token_set_ratio(query_clean, title_clean) / 100

    # Calculează matching individual de cuvinte cu tolerance mare
    query_words_list = query_clean.split()
    title_words_list = title_clean.split()

    word_matches = 0
    for q_word in query_words_list:
        if len(q_word) > 2:
            # Caută cel mai bun match cu threshold scăzut
            best_match = process.extractOne(q_word, title_words_list,
                                          scorer=fuzz.ratio, score_cutoff=60)  # Threshold mai mic
            if best_match:
                word_matches += 1

    word_match_ratio = word_matches / len(query_words_list) if query_words_list else 0

    # Calculează scorul final cu ponderire agresivă
    final_score = (
        ratio_score * 0.15 +
        partial_score * 0.35 +        # Crește ponderea partial match
        token_sort_score * 0.25 +
        token_set_score * 0.15 +
        word_match_ratio * 0.1
    )

    # Bonus pentru matches parțiale foarte bune
    if partial_score > 0.8:
        final_score += 0.1
    if token_set_score > 0.7:
        final_score += 0.05

    return min(final_score, 1.0), {
        'ratio': ratio_score,
        'partial': partial_score,
        'token_sort': token_sort_score,
        'token_set': token_set_score,
        'word_match': word_match_ratio
    }

def calculate_relevance_score_aggressive(query_words, result_title, result_creator=""):
    """Fallback agresiv pentru calculul relevanței."""
    query_text = ' '.join(query_words).lower()
    title_text = (result_title + " " + result_creator).lower()

    query_text = re.sub(r'[^\w\s]', ' ', query_text)
    title_text = re.sub(r'[^\w\s]', ' ', title_text)

    query_words_set = set(query_text.split())
    title_words_set = set(title_text.split())

    # Calculează matches exacte
    exact_matches = query_words_set.intersection(title_words_set)

    # Calculează matches parțiale (substring)
    partial_matches = 0
    for q_word in query_words_set:
        if len(q_word) > 3:
            for t_word in title_words_set:
                if q_word in t_word or t_word in q_word:
                    partial_matches += 1
                    break

    if not query_words_set:
        return 0, exact_matches

    exact_score = len(exact_matches) / len(query_words_set)
    partial_score = partial_matches / len(query_words_set)

    # Combină scorurile
    final_score = exact_score * 0.7 + partial_score * 0.3

    # Bonus pentru matches importante
    important_words = list(query_words_set)[:3]
    important_matches = sum(1 for word in important_words if word in title_words_set)
    importance_bonus = important_matches / len(important_words) * 0.2

    return min(final_score + importance_bonus, 1.0), exact_matches

def scan_and_delete_found_folders_final(base_directory, use_backup=True):
    """
    Versiunea finală cu matching agresiv pentru variații de clanuri.
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

    print("🔍 Scanez arhiva cu matching agresiv pentru variații de clanuri...")
    print("="*60)

    # Găsește toate fișierele
    file_extensions = ['.pdf', '.djvu', '.epub', '.rtf', '.doc', '.docx', '.txt']
    all_files = []
    for ext in file_extensions:
        files_found = list(base_path.rglob(f"*{ext}"))
        all_files.extend(files_found)

    print(f"📊 Total fișiere găsite: {len(all_files)}")

    # Grupează pe subfoldere
    subfolders_to_process = {}
    for filepath in all_files:
        try:
            relative_path = Path(filepath).relative_to(base_path)

            if len(relative_path.parts) >= 2:
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

        except ValueError:
            continue

    total_subfolders = len(subfolders_to_process)
    print(f"📂 Găsite {total_subfolders} subfoldere de procesat")
    print("\n🔍 Încep căutarea agresivă cu variații de clanuri...")
    print("="*60)

    subfolders_to_delete = []
    processed = 0
    found_count = 0
    start_time = time.time()

    for subfolder_key, subfolder_info in subfolders_to_process.items():
        processed += 1

        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        eta_seconds = (total_subfolders - processed) / rate if rate > 0 else 0
        eta_minutes = int(eta_seconds / 60)

        # Afișează numele fișierului PDF
        if subfolder_info['files']:
            main_file = subfolder_info['files'][0]
            display_name = os.path.basename(main_file)[:45]
        else:
            display_name = f"{subfolder_info['author']} - {subfolder_info['book']}"

        print(f"[{processed:3}/{total_subfolders}] {display_name:<45}", end=" ")

        if subfolder_info['files']:
            test_file = subfolder_info['files'][0]

            # Extrage autorul și titlul
            author, title = extract_title_from_filename_improved(test_file)

            if not author and subfolder_info['author']:
                author = subfolder_info['author']

            # Generează strategii cu variații de clanuri
            strategies = generate_search_strategies_enhanced(author, title, test_file)

            print(f"🔍 Agresiv...", end=" ")

            found, results = search_archive_org_aggressive(strategies, min_relevance_score=0.2)

            if found and results:
                subfolder_size = calculate_folder_size(subfolder_info['path'])
                best_result = results[0]

                subfolders_to_delete.append({
                    'name': display_name,
                    'path': subfolder_info['path'],
                    'size': subfolder_size,
                    'files_count': len(subfolder_info['files']),
                    'extracted_author': author,
                    'extracted_title': title,
                    'best_match': best_result['title'],
                    'relevance_score': best_result['relevance_score'],
                    'archive_url': best_result['url'],
                    'winning_strategy': best_result['strategy_description'],
                    'author': subfolder_info['author'],
                    'book': subfolder_info['book'],
                    'score_details': best_result.get('score_details', {})
                })
                found_count += 1
                print(f"✅ GĂSIT {best_result['relevance_score']:.2f} ({format_size(subfolder_size)}) [{best_result['strategy']}] ETA: {eta_minutes}min")
            else:
                print(f"❌ Nu există    ETA: {eta_minutes}min")
        else:
            print("❌ Fără fișiere")

        time.sleep(0.05)  # Pauză foarte mică

    # Verifică dacă s-au găsit subfoldere de șters
    if not subfolders_to_delete:
        print("\n✅ Nu s-au găsit subfoldere de șters. Toate cărțile din arhivă sunt unice!")
        return

    # Calculează statistici
    total_size = sum(subfolder['size'] for subfolder in subfolders_to_delete)

    print(f"\n{'='*60}")
    print(f"📊 RAPORT FINAL AGRESIV")
    print(f"{'='*60}")
    print(f"Subfoldere procesate: {total_subfolders}")
    print(f"Subfoldere găsite pe Archive.org: {found_count}")
    print(f"Spațiu de eliberat: {format_size(total_size)}")
    print(f"Rata de succes: {found_count/total_subfolders*100:.1f}%")

    print(f"\n📋 Top 15 subfoldere găsite cu scoruri:")
    for i, subfolder in enumerate(subfolders_to_delete[:15], 1):
        score = subfolder['relevance_score']
        print(f"   {i:2}. {subfolder['name'][:40]:<40} - Score: {score:.2f} - {format_size(subfolder['size']):>8}")
        print(f"       Găsit ca: {subfolder['best_match'][:55]}")
        print(f"       Strategie: {subfolder['winning_strategy']}")

    if len(subfolders_to_delete) > 15:
        print(f"   ... și încă {len(subfolders_to_delete) - 15} subfoldere")

    # Analiză strategii
    strategy_stats = {}
    for subfolder in subfolders_to_delete:
        strategy = subfolder['winning_strategy'].split(':')[0]
        strategy_stats[strategy] = strategy_stats.get(strategy, 0) + 1

    print(f"\n📈 Analiza strategiilor de căutare:")
    for strategy, count in sorted(strategy_stats.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / found_count) * 100
        print(f"   {strategy}: {count} găsiri ({percentage:.1f}%)")

    if use_backup:
        print(f"\n⚠️  CONFIRMARE BACKUP")
        print(f"   • Se vor muta {found_count} subfoldere în backup")
        print(f"   • Se vor elibera {format_size(total_size)} de spațiu")
        print(f"   • Backup folder: {backup_directory}")
        print(f"   • Folderele goale vor fi șterse automat")
    else:
        print(f"\n⚠️  ATENȚIE - ȘTERGERE DEFINITIVĂ!")
        print(f"   • Se vor ȘTERGE DEFINITIV {found_count} subfoldere")
        print(f"   • Se vor elibera {format_size(total_size)} de spațiu")
        print(f"   • NU VA EXISTA BACKUP!")
        print(f"   • Folderele goale vor fi șterse automat")

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
                print(f"[{i:3}/{found_count}] {action_verb} {subfolder['name'][:35]:<35}", end=" ")

                if use_backup:
                    # Mută în backup cu timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = subfolder['name'].replace('/', '_').replace('\\', '_').replace(':', '_')
                    safe_name = safe_name[:50]  # Limitează lungimea
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

        print(f"\n🎉 OPERAȚIUNE PRINCIPALĂ COMPLETĂ!")
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

        # Curățare foldere goale
        print(f"\n🧹 CURĂȚARE FOLDERE GOALE")
        print("="*60)
        empty_folders_deleted = clean_empty_folders(base_directory)

        # Raport final complet
        print(f"\n🏁 RAPORT FINAL COMPLET")
        print("="*60)
        print(f"   📁 Subfoldere șterse: {deleted_count}")
        print(f"   🗂️  Foldere goale șterse: {len(empty_folders_deleted)}")
        print(f"   💾 Spațiu total eliberat: {format_size(deleted_size)}")

    else:
        print("❌ Operațiune anulată.")


def clean_empty_folders(base_directory):
    """Șterge toate folderele goale din directorul de bază."""
    print(f"📂 Caut foldere goale...")

    base_path = Path(base_directory)
    empty_folders_deleted = []

    # Fă 3 treceri pentru foldere imbricate
    for pass_num in range(1, 4):
        deleted_this_pass = []

        try:
            for author_folder in base_path.iterdir():
                if author_folder.is_dir():
                    try:
                        if len(os.listdir(str(author_folder))) == 0:
                            print(f"   🗑️  Șterg folderul gol: {author_folder.name}")
                            shutil.rmtree(str(author_folder))
                            deleted_this_pass.append(author_folder.name)
                            empty_folders_deleted.append(author_folder.name)
                    except Exception:
                        pass
        except Exception:
            pass

        if not deleted_this_pass:
            break

    print(f"   📊 Total foldere goale șterse: {len(empty_folders_deleted)}")
    return empty_folders_deleted

# Funcțiile auxiliare rămân la fel
def calculate_folder_size(folder_path):
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
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def main():
    base_directory = r"g:\ARHIVA\C"

    print("🗄️  CURĂȚARE AUTOMATĂ ARHIVĂ - VERSIUNE AGRESIVĂ")
    print("="*60)

    if FUZZY_AVAILABLE:
        print("✅ Algoritmi fuzzy agresivi activați")
    else:
        print("⚠️  Instalează 'rapidfuzz' pentru rezultate mai bune")

    print("Acest program va:")
    print("• Detecta variații de clanuri (McGregor/Mc Gregor)")
    print("• Folosi fuzzy search (~) pentru toleranță la erori")
    print("• Threshold foarte mic (0.2) pentru mai multe găsiri")
    print("• Testa strategii multiple cu prioritizare")
    print("="*60)

    backup_choice = input("\nCe vrei să fac cu folderele găsite?\n1. Mută în backup (sigur)\n2. Șterge definitiv (risky)\nAlege (1 sau 2): ")
    use_backup = backup_choice != "2"

    input("\nApasă ENTER pentru a începe scanarea agresivă...")
    scan_and_delete_found_folders_final(base_directory, use_backup=use_backup)

if __name__ == "__main__":
    main()