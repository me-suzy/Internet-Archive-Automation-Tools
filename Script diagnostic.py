#!/usr/bin/env python3
"""
Script de diagnostic pentru a verifica de ce nu s-au încărcat toate fișierele PDF
"""

import json
import os
from pathlib import Path

def analyze_processing_issue():
    """Analizează problema cu procesarea incompletă"""

    # Configurări din scriptul original
    ARCHIVE_PATH = Path(r"g:\ARHIVA\B")
    STATE_FILENAME = "state_archive.json"

    # Calea problematică
    problem_folder = ARCHIVE_PATH / "Brut, Mihaela"

    print("🔍 DIAGNOSTICAREA PROBLEMEI DE UPLOAD")
    print("=" * 50)

    # 1. Verifică structura reală a folderului
    print(f"\n📁 Analizez structura folderului: {problem_folder}")

    if not problem_folder.exists():
        print("❌ Folderul nu există!")
        return

    pdf_files_found = []
    for root, dirs, files in os.walk(problem_folder):
        current_path = Path(root)
        pdf_files_in_dir = [f for f in files if f.lower().endswith('.pdf')]

        if pdf_files_in_dir:
            unit_name = str(current_path.relative_to(ARCHIVE_PATH))
            pdf_files_found.append({
                'path': str(current_path),
                'unit_name': unit_name,
                'pdf_files': pdf_files_in_dir,
                'file_count': len(files)
            })
            print(f"📂 Unitate găsită: {unit_name}")
            print(f"   📄 PDF-uri ({len(pdf_files_in_dir)}): {', '.join(pdf_files_in_dir)}")
            print(f"   📋 Total fișiere: {len(files)}")

    print(f"\n📊 Total unități cu PDF-uri găsite: {len(pdf_files_found)}")

    # 2. Verifică starea salvată
    print(f"\n📋 Verific starea salvată în {STATE_FILENAME}...")

    if os.path.exists(STATE_FILENAME):
        try:
            with open(STATE_FILENAME, 'r', encoding='utf-8') as f:
                state = json.load(f)

            processed_units = state.get('processed_units', [])
            processed_folders = state.get('processed_folders', [])
            uploads_today = state.get('uploads_today', 0)

            print(f"📤 Upload-uri făcute astăzi: {uploads_today}")
            print(f"📁 Foldere procesate: {len(processed_folders)}")
            print(f"🔧 Unități procesate: {len(processed_units)}")

            print(f"\n📋 Unități procesate din folderul problematic:")
            problem_units = []
            for unit_path in processed_units:
                if "Brut, Mihaela" in unit_path:
                    problem_units.append(unit_path)
                    print(f"   ✅ {unit_path}")

            print(f"\n🔍 ANALIZA PROBLEMEI:")
            print(f"   📂 Unități cu PDF găsite fizic: {len(pdf_files_found)}")
            print(f"   ✅ Unități marcate ca procesate: {len(problem_units)}")

            if len(pdf_files_found) > len(problem_units):
                print(f"   ⚠️  PROBLEMĂ: {len(pdf_files_found) - len(problem_units)} unități nu au fost procesate!")

                # Identifică unitățile neproce
                processed_paths = set(problem_units)
                unprocessed = []

                for unit in pdf_files_found:
                    if unit['path'] not in processed_paths:
                        unprocessed.append(unit)
                        print(f"   ❌ NEPROCESATĂ: {unit['unit_name']}")
                        print(f"      📄 Conține: {', '.join(unit['pdf_files'])}")

                return unprocessed
            else:
                print(f"   ✅ Toate unitățile par să fi fost procesate.")

        except Exception as e:
            print(f"❌ Eroare la citirea stării: {e}")
    else:
        print("❌ Fișierul de stare nu există!")

    return []

def suggest_solutions(unprocessed_units):
    """Sugerează soluții pentru unitățile neproce"""

    if not unprocessed_units:
        print("\n✅ Nu sunt unități neproce detectate.")
        return

    print(f"\n💡 SOLUȚII RECOMANDATE:")
    print("=" * 30)

    print("1. 🔄 REPORNIREA PROCESĂRII:")
    print("   - Rulează din nou scriptul - va relua de unde a rămas")
    print("   - Unitățile deja procesate vor fi omise automat")

    print("\n2. 🧹 ȘTERGEREA SELECTIVĂ DIN STARE:")
    print("   - Șterge unitățile neproce din 'processed_units'")
    print("   - Ține folderul principal în 'processed_folders' dacă alte unități au fost procesate")

    print("\n3. 📋 VERIFICAREA LOG-URILOR:")
    print("   - Caută în output-ul anterior mesaje de eroare pentru aceste unități:")
    for unit in unprocessed_units:
        print(f"     📂 {unit['unit_name']}")

    print("\n4. 🎯 PROCESAREA MANUALĂ:")
    print("   - Poți modifica temporar scriptul să proceseze doar aceste unități")

    # Generează JSON pentru ștergerea selectivă
    print(f"\n📝 PENTRU ȘTERGEREA SELECTIVĂ:")
    print("Șterge aceste căi din 'processed_units' în state_archive.json:")
    for unit in unprocessed_units:
        print(f'   "{unit["path"]}",')

if __name__ == "__main__":
    unprocessed = analyze_processing_issue()
    suggest_solutions(unprocessed)