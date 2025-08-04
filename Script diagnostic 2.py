#!/usr/bin/env python3
"""
Investigație aprofundată pentru a înțelege ce s-a întâmplat cu upload-urile
"""

import json
import os
import glob
from pathlib import Path
from datetime import datetime

def investigate_upload_issues():
    """Investigație completă a problemelor de upload"""

    print("🕵️ INVESTIGAȚIE APROFUNDATĂ - UPLOAD-URI PROBLEMATICE")
    print("=" * 60)

    # 1. Verifică fișierele de erori generate de script
    print("\n📋 1. VERIFICARE FIȘIERE DE ERORI 404/505:")
    error_files = glob.glob("upload_errors_with_404_505*.txt")

    if error_files:
        print(f"📄 Găsite {len(error_files)} fișiere cu erori:")
        for error_file in sorted(error_files):
            print(f"   📄 {error_file}")
            try:
                with open(error_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if "Brut" in content:
                        print(f"   🚨 CONȚINE ERORI PENTRU BRUT:")
                        lines = content.split('\n')
                        for line in lines:
                            if "Brut" in line:
                                print(f"      ❌ {line.strip()}")
                    else:
                        print(f"   ✅ Nu conține erori pentru Brut")
            except Exception as e:
                print(f"   ❌ Eroare la citire: {e}")
    else:
        print("📄 Nu s-au găsit fișiere cu erori 404/505")

    # 2. Analizează starea detaliată
    print(f"\n📋 2. ANALIZĂ DETALIATĂ A STĂRII:")

    state_file = "state_archive.json"
    if not os.path.exists(state_file):
        print("❌ Fișierul de stare nu există!")
        return

    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)

        print(f"📊 Statistici generale:")
        print(f"   📤 Upload-uri astăzi: {state.get('uploads_today', 0)}")
        print(f"   📄 Total fișiere încărcate: {state.get('total_files_uploaded', 0)}")
        print(f"   📁 Foldere mutate: {state.get('folders_moved', 0)}")
        print(f"   📋 Data ultimei rulări: {state.get('date', 'N/A')}")

        # Verifică unitățile Brut specifice
        processed_units = state.get('processed_units', [])
        brut_units = [unit for unit in processed_units if 'Brut, Mihaela' in unit]

        print(f"\n🔍 Unități Brut procesate ({len(brut_units)}):")
        for i, unit in enumerate(brut_units, 1):
            print(f"   {i}. {unit}")

            # Încearcă să determine timpul procesării (aproximativ)
            unit_index = processed_units.index(unit)
            print(f"      📊 Poziția în listă: {unit_index + 1}/{len(processed_units)}")

    except Exception as e:
        print(f"❌ Eroare la citirea stării: {e}")

    # 3. Sugerează verificări manuale
    print(f"\n📋 3. VERIFICĂRI MANUALE RECOMANDATE:")
    print("=" * 40)

    titles_to_check = [
        "Brut Mihaela Instrumente pentru E learning",
        "Brut Mihaela Sustinerea Unui Discurs Public"
    ]

    print("🌐 Verifică pe Archive.org dacă aceste titluri există:")
    for i, title in enumerate(titles_to_check, 1):
        clean_title = title.replace(" ", "+")
        search_url = f"https://archive.org/search.php?query={clean_title}"
        print(f"\n   {i}. 📖 Titlu: {title}")
        print(f"      🔗 Caută: {search_url}")

    # 4. Analizează timing-ul
    print(f"\n📋 4. ANALIZĂ TIMING:")
    print("Dacă ambele unități au fost procesate consecutive:")
    print("   ⏱️  Prima unitate: upload + 10 secunde delay")
    print("   ⏱️  A doua unitate: upload + verificare erori după 5 minute")
    print("   🤔 S-ar putea ca a doua să fi avut probleme de timing")

    # 5. Recomandări
    print(f"\n💡 5. RECOMANDĂRI:")
    print("=" * 20)
    print("🔄 Opțiunea 1: RE-UPLOAD FORȚAT")
    print("   - Șterge ambele unități din processed_units")
    print("   - Rulează din nou scriptul pentru acest folder")

    print("\n🔍 Opțiunea 2: VERIFICARE MANUALĂ")
    print("   - Verifică pe archive.org ambele titluri")
    print("   - Caută în browser-ul Chrome filele deschise")

    print("\n📋 Opțiunea 3: ANALIZĂ LOG-URI")
    print("   - Verifică output-ul anterior al scriptului")
    print("   - Caută mesaje de eroare pentru 'Brut'")

    return brut_units

def generate_cleanup_commands(brut_units):
    """Generează comenzi pentru curățarea stării"""

    print(f"\n🧹 COMENZI PENTRU CURĂȚAREA STĂRII:")
    print("=" * 40)

    print("Pentru a reprocessa ambele unități Brut, șterge din state_archive.json:")
    print("\nDin 'processed_units' șterge:")
    for unit in brut_units:
        print(f'   "{unit}",')

    print("\nDin 'processed_folders' șterge (dacă există):")
    print('   "g:\\\\ARHIVA\\\\B\\\\Brut, Mihaela",')

    print(f"\n⚠️  ATENȚIE: După ștergere, scriptul va reprocessa ambele unități!")

if __name__ == "__main__":
    brut_units = investigate_upload_issues()
    if brut_units:
        generate_cleanup_commands(brut_units)