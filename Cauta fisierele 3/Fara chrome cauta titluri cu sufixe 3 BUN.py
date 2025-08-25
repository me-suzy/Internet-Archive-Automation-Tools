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
    """
    Procesează numele fișierului eliminând cuvintele specifice,
    parantezele și cifrele pentru a genera un query de căutare.
    """
    filename = os.path.splitext(os.path.basename(filepath))[0]

    words_to_remove = [
        'retail', 'scan', 'ctrl', 'ocr', 'vp', 'istor',
        'trad', 'trad.', 'ed', 'edition', 'vol', 'tome'
    ]

    # Elimină conținutul din paranteză
    filename = re.sub(r'\([^)]*\)', '', filename)

    # Elimină cifrele
    filename = re.sub(r'\d+', '', filename)

    # Împarte în cuvinte
    words = re.findall(r'\w+', filename.lower())

    # Elimină cuvintele specifice
    filtered_words = [word for word in words if word not in words_to_remove]

    search_query = ' '.join(filtered_words)

    return search_query, filtered_words

def calculate_relevance_score(query_words, result_title, result_creator=""):
    """
    Calculează un scor de relevanță între query și rezultat.
    Returnează un scor între 0-1 (0 = irelevant, 1 = perfect match).
    """
    # Normalizează textele pentru comparație
    query_text = ' '.join(query_words).lower()
    title_text = (result_title + " " + result_creator).lower()

    # Eliminăm diacriticele și caracterele speciale
    query_text = re.sub(r'[^\w\s]', ' ', query_text)
    title_text = re.sub(r'[^\w\s]', ' ', title_text)

    query_words_set = set(query_text.split())
    title_words_set = set(title_text.split())

    # Numărul de cuvinte comune
    common_words = query_words_set.intersection(title_words_set)

    if not query_words_set:
        return 0

    # Scor bazat pe procentul de cuvinte comune
    base_score = len(common_words) / len(query_words_set)

    # Bonus pentru cuvinte cheie importante (primele 2-3 cuvinte din query)
    important_words = list(query_words_set)[:3]
    important_matches = sum(1 for word in important_words if word in title_words_set)
    importance_bonus = important_matches / len(important_words) * 0.5

    final_score = min(base_score + importance_bonus, 1.0)

    return final_score, common_words

def search_archive_org_api_with_relevance(query, min_relevance_score=0.4, max_results=5, debug=False):
    """
    Caută pe archive.org și filtrează rezultatele pe baza relevanței.
    """
    url = f"https://archive.org/advancedsearch.php?q={quote_plus(query)}&output=json&rows={max_results * 2}"

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        num_found = data.get('response', {}).get('numFound', 0)
        docs = data.get('response', {}).get('docs', [])

        if debug:
            print(f"   🔍 API returnează {num_found} rezultate totale")
            print(f"   📄 Primele {len(docs)} documente returnate:")

        query_words = query.lower().split()
        relevant_results = []

        for i, doc in enumerate(docs):
            title = doc.get('title', ['Fără titlu'])
            if isinstance(title, list):
                title = title[0] if title else 'Fără titlu'

            identifier = doc.get('identifier', '')
            creator = doc.get('creator', [''])
            if isinstance(creator, list):
                creator = ', '.join(creator) if creator else ''

            # Calculează scorul de relevanță
            relevance_score, common_words = calculate_relevance_score(query_words, title, creator)

            if debug:
                print(f"      {i+1}. {title}")
                print(f"         Creator: {creator}")
                print(f"         Scor relevanță: {relevance_score:.2f}")
                print(f"         Cuvinte comune: {common_words}")

            # Filtrează doar rezultatele cu scor suficient de mare
            if relevance_score >= min_relevance_score:
                result = {
                    'title': title,
                    'identifier': identifier,
                    'creator': creator,
                    'url': f"https://archive.org/details/{identifier}",
                    'relevance_score': relevance_score,
                    'common_words': list(common_words)
                }
                relevant_results.append(result)

        if debug:
            print(f"   ✅ Rezultate relevante (scor ≥ {min_relevance_score}): {len(relevant_results)}")

        # Sortează după scorul de relevanță
        relevant_results.sort(key=lambda x: x['relevance_score'], reverse=True)

        return len(relevant_results) > 0, len(relevant_results), relevant_results[:max_results]

    except Exception as e:
        if debug:
            print(f"   ❌ Eroare API: {e}")
        return False, -1, [f"Eroare: {e}"]

def test_specific_query():
    """
    Testează cu query-ul specific care a dat probleme.
    """
    query = "childe gordon de la preistorie la istorie"

    print("="*80)
    print(f"🧪 TEST DEBUG PENTRU: '{query}'")
    print("="*80)

    print("\n1. Test cu relevanță minimă 0.4:")
    found, count, results = search_archive_org_api_with_relevance(query, min_relevance_score=0.4, debug=True)

    print(f"\nRezultat final: {'GĂSIT' if found else 'NU S-A GĂSIT'} - {count} rezultate relevante")

    if results:
        print("\nRezultate finale filtrate:")
        for i, result in enumerate(results, 1):
            print(f"   {i}. {result['title']} (scor: {result['relevance_score']:.2f})")
            print(f"      Creator: {result['creator']}")
            print(f"      Cuvinte comune: {result['common_words']}")

    print("\n" + "-"*60)
    print("\n2. Test cu relevanță minimă 0.6 (mai strictă):")
    found2, count2, results2 = search_archive_org_api_with_relevance(query, min_relevance_score=0.6, debug=False)
    print(f"Rezultat cu scor mai strict: {'GĂSIT' if found2 else 'NU S-A GĂSIT'} - {count2} rezultate")

def scan_and_process_archive_fixed(base_directory, quarantine_directory=None, dry_run=True,
                                 min_relevance_score=0.5, file_extensions=None, max_folders=None):
    """
    Versiunea corectată care verifică relevanța rezultatelor.
    """
    if file_extensions is None:
        file_extensions = ['.pdf', '.djvu', '.epub', '.rtf', '.doc', '.docx', '.txt']

    base_path = Path(base_directory)
    if not base_path.exists():
        print(f"❌ Directorul {base_directory} nu există!")
        return []

    if quarantine_directory is None:
        quarantine_directory = str(base_path.parent / "QUARANTINE_ARCHIVE")

    if not dry_run:
        os.makedirs(quarantine_directory, exist_ok=True)
        print(f"📁 Director carantină: {quarantine_directory}")

    print(f"🔍 Scanez directorul: {base_directory}")
    print(f"📊 Scor minim de relevanță: {min_relevance_score}")
    print(f"🎭 Mod {'DRY RUN (simulare)' if dry_run else 'EXECUȚIE REALĂ'}")
    print("="*80)

    # Găsește toate fișierele din subdirectoare
    all_files = []
    for ext in file_extensions:
        all_files.extend(base_path.rglob(f"*{ext}"))

    # Grupează fișierele pe foldere de autor
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
                        'files': [],
                        'size': 0
                    }

                folders_to_process[author_folder_name]['files'].append(str(filepath))
        except ValueError:
            continue

    if max_folders:
        folders_list = list(folders_to_process.items())[:max_folders]
        folders_to_process = dict(folders_list)

    print(f"📊 Găsite {len(folders_to_process)} foldere de autor pentru procesare")

    results = []
    folders_to_delete = []

    for i, (folder_name, folder_info) in enumerate(folders_to_process.items(), 1):
        print(f"\n[{i}/{len(folders_to_process)}] 📂 {folder_name}")
        print(f"   Fișiere: {len(folder_info['files'])}")

        # Testează primul fișier din folder
        if folder_info['files']:
            test_file = folder_info['files'][0]
            search_query, filtered_words = process_filename(test_file)

            print(f"   Query test: '{search_query}'")

            # Testează cu verificarea de relevanță
            found, count, archive_results = search_archive_org_api_with_relevance(
                search_query,
                min_relevance_score=min_relevance_score,
                debug=False
            )

            if found and archive_results:
                print(f"   ✅ GĂSIT pe Archive.org: {count} rezultate relevante")
                for j, result in enumerate(archive_results[:2], 1):
                    print(f"      {j}. {result['title']} (scor: {result['relevance_score']:.2f})")
                    print(f"         Cuvinte comune: {result['common_words']}")

                folders_to_delete.append({
                    'name': folder_name,
                    'path': folder_info['path'],
                    'files_count': len(folder_info['files']),
                    'archive_results': archive_results,
                    'query': search_query,
                    'relevance_score': archive_results[0]['relevance_score']
                })
                print(f"   🗑️  MARCAT PENTRU ȘTERGERE")
            else:
                print(f"   ❌ Nu s-a găsit rezultat relevant pe Archive.org")

        time.sleep(1)

    print(f"\n📋 REZULTATE: {len(folders_to_delete)} foldere marcate pentru ștergere")

    return results

def main():
    """
    Funcția principală îmbunătățită.
    """
    print("🧪 TESTARE FUNCȚIE DE CĂUTARE ÎMBUNĂTĂȚITĂ")
    print("="*80)

    # Mai întâi testez query-ul problematic
    test_specific_query()

    # Întreabă utilizatorul dacă vrea să continue cu scanarea
    continue_scan = input("\n🤔 Continui cu scanarea arhivei? (y/n): ")

    if continue_scan.lower() in ['y', 'yes', 'da']:
        base_directory = r"g:\ARHIVA\C"

        min_relevance = input("\nScor minim de relevanță (0.3-0.8, recomandat 0.5): ")
        try:
            min_relevance_score = float(min_relevance) if min_relevance.strip() else 0.5
        except ValueError:
            min_relevance_score = 0.5

        max_folders = input("Număr maxim de foldere de testat (Enter pentru toate): ")
        max_folders = int(max_folders) if max_folders.strip() else None

        results = scan_and_process_archive_fixed(
            base_directory=base_directory,
            dry_run=True,  # Întotdeauna dry run pentru siguranță
            min_relevance_score=min_relevance_score,
            max_folders=max_folders
        )

if __name__ == "__main__":
    main()