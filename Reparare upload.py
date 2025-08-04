#!/usr/bin/env python3
"""
Script pentru repararea upload-urilor Brut Mihaela
Șterge unitățile din stare și le reprocessează
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

def fix_brut_uploads():
    """Repară upload-urile pentru Brut Mihaela"""

    state_file = "state_archive.json"
    backup_file = f"state_archive_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    print("🔧 REPARARE UPLOAD-URI BRUT MIHAELA")
    print("=" * 40)

    if not os.path.exists(state_file):
        print("❌ Fișierul state_archive.json nu există!")
        return False

    # 1. Backup
    try:
        shutil.copy2(state_file, backup_file)
        print(f"✅ Backup creat: {backup_file}")
    except Exception as e:
        print(f"⚠️ Nu am putut crea backup: {e}")

    # 2. Încarcă starea
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
    except Exception as e:
        print(f"❌ Eroare la citirea stării: {e}")
        return False

    # 3. Identifică unitățile Brut
    processed_units = state.get('processed_units', [])
    processed_folders = state.get('processed_folders', [])

    brut_units_to_remove = [
        "g:\\ARHIVA\\B\\Brut, Mihaela",
        "g:\\ARHIVA\\B\\Brut, Mihaela\\Sustinerea Unui Discurs Public"
    ]

    brut_folders_to_remove = [
        "g:\\ARHIVA\\B\\Brut, Mihaela"
    ]

    # 4. Șterge unitățile Brut
    units_removed = 0
    folders_removed = 0

    print("\n🗑️ Șterg unitățile Brut din stare...")

    # Șterge din processed_units
    original_units_count = len(processed_units)
    processed_units = [unit for unit in processed_units if not any(brut in unit for brut in ["Brut, Mihaela"])]
    units_removed = original_units_count - len(processed_units)

    # Șterge din processed_folders
    original_folders_count = len(processed_folders)
    processed_folders = [folder for folder in processed_folders if not any(brut in folder for brut in ["Brut, Mihaela"])]
    folders_removed = original_folders_count - len(processed_folders)

    print(f"   📊 Unități șterse: {units_removed}")
    print(f"   📊 Foldere șterse: {folders_removed}")

    # 5. Actualizează starea
    state['processed_units'] = processed_units
    state['processed_folders'] = processed_folders

    # Ajustează contoarele
    if units_removed > 0:
        # Scade din uploads_today numărul de fișiere care vor fi re-uploadate
        files_to_reupload = 2  # Cele 2 PDF-uri Brut
        state['uploads_today'] = max(0, state.get('uploads_today', 0) - files_to_reupload)
        state['total_files_uploaded'] = max(0, state.get('total_files_uploaded', 0) - files_to_reupload)

        print(f"   📊 Upload-uri ajustate: -{files_to_reupload}")
        print(f"   📊 Noi upload-uri astăzi: {state['uploads_today']}")

    # 6. Salvează starea
    try:
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        print(f"✅ Starea a fost actualizată!")
    except Exception as e:
        print(f"❌ Eroare la salvarea stării: {e}")
        return False

    # 7. Instrucțiuni finale
    print(f"\n🎯 URMĂTORII PAȘI:")
    print("1. ✅ Starea a fost curățată - unitățile Brut au fost șterse")
    print("2. 🚀 Rulează scriptul principal - va reprocessa unitățile Brut")
    print("3. 📊 Vor fi re-uploadate 2 fișiere PDF")
    print("4. ⏱️ Estimat: ~2-3 minute pentru re-procesare")

    print(f"\n📋 UNITĂȚILE CARE VOR FI REPROCESSATE:")
    for unit in brut_units_to_remove:
        print(f"   📂 {unit}")

    return True

if __name__ == "__main__":
    fix_brut_uploads()