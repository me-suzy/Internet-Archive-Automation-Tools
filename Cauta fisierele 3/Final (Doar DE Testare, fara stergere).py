import re
import requests
import json
import os
from urllib.parse import quote_plus
import time
from pathlib import Path

def process_filename(filepath):
    """
    Procesează numele fișierului eliminând cuvintele specifice,
    parantezele și cifrele pentru a genera un query de căutare.
    """
    # Extrage numele fișierului fără extensie și cale
    filename = os.path.splitext(os.path.basename(filepath))[0]

    # Lista cu cuvinte de eliminat
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

    # Reconstrește termenul de căutare
    search_query = ' '.join(filtered_words)

    return search_query, filtered_words

def search_archive_org_api(query, max_results=5):
    """
    Caută pe archive.org folosind API-ul oficial.
    """
    url = f"https://archive.org/advancedsearch.php?q={quote_plus(query)}&output=json&rows={max_results}"

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        num_found = data.get('response', {}).get('numFound', 0)
        docs = data.get('response', {}).get('docs', [])

        if num_found > 0:
            results = []
            for doc in docs:
                title = doc.get('title', ['Fără titlu'])
                if isinstance(title, list):
                    title = title[0] if title else 'Fără titlu'

                identifier = doc.get('identifier', '')
                creator = doc.get('creator', ['Necunoscut'])
                if isinstance(creator, list):
                    creator = ', '.join(creator) if creator else 'Necunoscut'

                results.append({
                    'title': title,
                    'identifier': identifier,
                    'creator': creator,
                    'url': f"https://archive.org/details/{identifier}"
                })

            return True, num_found, results
        else:
            return False, 0, []

    except Exception as e:
        return False, -1, [f"Eroare: {e}"]

def process_single_file(filepath, verbose=True):
    """
    Procesează un singur fișier și returnează rezultatul.
    """
    search_query, filtered_words = process_filename(filepath)

    if verbose:
        print(f"\n📁 {os.path.basename(filepath)}")
        print(f"   Query: '{search_query}'")

    # Încearcă mai multe variante de căutare
    search_variants = [
        search_query,
        ' '.join(filtered_words[:4]),  # primele 4 cuvinte
        ' '.join(filtered_words[:3]),  # primele 3 cuvinte
        f'creator:"{filtered_words[0]} {filtered_words[1]}"' if len(filtered_words) >= 2 else search_query
    ]

    best_result = None

    for i, variant in enumerate(search_variants):
        found, count, results = search_archive_org_api(variant, max_results=3)

        if found and results:
            if verbose:
                print(f"   ✅ GĂSIT cu varianta {i+1}: {count} rezultate")
                for j, result in enumerate(results[:2], 1):
                    print(f"      {j}. {result['title']}")
                    print(f"         {result['url']}")

            best_result = {
                'filepath': filepath,
                'query': variant,
                'found': True,
                'count': count,
                'results': results,
                'status': 'GĂSIT'
            }
            break

        # Pauză între căutări pentru a nu suprasolicita API-ul
        time.sleep(0.5)

    if not best_result:
        if verbose:
            print(f"   ❌ NU S-A GĂSIT")

        best_result = {
            'filepath': filepath,
            'query': search_query,
            'found': False,
            'count': 0,
            'results': [],
            'status': 'NU S-A GĂSIT'
        }

    return best_result

def process_directory(directory_path, file_extensions=None, max_files=None):
    """
    Procesează toate fișierele dintr-un director.
    """
    if file_extensions is None:
        file_extensions = ['.pdf', '.djvu', '.epub', '.txt']

    directory = Path(directory_path)
    if not directory.exists():
        print(f"❌ Directorul {directory_path} nu există!")
        return []

    # Găsește toate fișierele cu extensiile specificate
    all_files = []
    for ext in file_extensions:
        all_files.extend(directory.rglob(f"*{ext}"))

    if max_files:
        all_files = all_files[:max_files]

    print(f"🔍 Găsite {len(all_files)} fișiere pentru procesare")
    print("="*80)

    results = []
    found_count = 0

    for i, filepath in enumerate(all_files, 1):
        print(f"\n[{i}/{len(all_files)}]", end="")

        result = process_single_file(str(filepath), verbose=True)
        results.append(result)

        if result['found']:
            found_count += 1

        # Pauză între fișiere
        time.sleep(1)

    return results, found_count

def generate_report(results, output_file=None):
    """
    Generează un raport cu rezultatele.
    """
    found_results = [r for r in results if r['found']]
    not_found_results = [r for r in results if not r['found']]

    report = []
    report.append("="*80)
    report.append("RAPORT CĂUTARE ARCHIVE.ORG")
    report.append("="*80)
    report.append(f"Total fișiere procesate: {len(results)}")
    report.append(f"Fișiere găsite: {len(found_results)}")
    report.append(f"Fișiere negăsite: {len(not_found_results)}")
    report.append(f"Rata de succes: {len(found_results)/len(results)*100:.1f}%")

    if found_results:
        report.append("\n" + "="*50)
        report.append("FIȘIERE GĂSITE:")
        report.append("="*50)

        for result in found_results:
            filename = os.path.basename(result['filepath'])
            report.append(f"\n📚 {filename}")
            report.append(f"   Query folosit: {result['query']}")
            report.append(f"   Rezultate găsite: {result['count']}")

            for i, item in enumerate(result['results'][:2], 1):
                report.append(f"   {i}. {item['title']}")
                report.append(f"      URL: {item['url']}")

    if not_found_results:
        report.append(f"\n{'='*50}")
        report.append("FIȘIERE NEGĂSITE:")
        report.append("="*50)

        for result in not_found_results:
            filename = os.path.basename(result['filepath'])
            report.append(f"\n❌ {filename}")
            report.append(f"   Query încercat: {result['query']}")

    report_text = '\n'.join(report)
    print(report_text)

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"\n💾 Raportul a fost salvat în: {output_file}")

def main():
    """
    Funcția principală - testează cu exemplul dat și permite procesare în lot.
    """
    # Test cu exemplul dat
    filepath = r"g:\ARHIVA\C\Chelaru, Marius\Chelaru, Marius - Poarta catre poezia araba - (trad) - retail.pdf"

    print("="*80)
    print("TEST CU EXEMPLUL SPECIFICAT")
    print("="*80)

    result = process_single_file(filepath, verbose=True)

    # Exemplu procesare director (decomentează pentru a folosi)
    """
    print("\n" + "="*80)
    print("PROCESARE DIRECTOR")
    print("="*80)

    # Înlocuiește cu calea către directorul tău
    directory_path = r"g:\ARHIVA\C"

    results, found_count = process_directory(
        directory_path,
        file_extensions=['.pdf'],
        max_files=10  # limitează la primele 10 fișiere pentru test
    )

    generate_report(results, output_file="archive_org_report.txt")
    """

if __name__ == "__main__":
    main()