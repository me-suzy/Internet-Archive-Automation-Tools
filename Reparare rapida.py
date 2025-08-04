#!/usr/bin/env python3
"""
REPARARE RAPIDĂ pentru Brut Mihaela - Eșec de upload din cauza pierderii focus-ului
"""

import json
import shutil
from datetime import datetime

def fix_brut_focus_issue():
    """Repară rapid problema cu focus-ul pentru Brut Mihaela"""

    print("🔧 REPARARE RAPIDĂ - Brut Mihaela Upload Eșuat")
    print("=" * 50)
    print("📝 Cauza: Pierderea focus-ului Chrome în timpul upload-ului")

    state_file = "state_archive.json"

    # 1. Backup
    backup_file = f"backup_before_brut_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        shutil.copy2(state_file, backup_file)
        print(f"✅ Backup: {backup_file}")
    except Exception as e:
        print(f"⚠️ Nu pot face backup: {e}")
        return False

    # 2. Încarcă și modifică starea
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)

        print(f"📊 Stare curentă:")
        print(f"   📤 Upload-uri astăzi: {state.get('uploads_today', 0)}")
        print(f"   🔧 Unități procesate: {len(state.get('processed_units', []))}")

        # Identifică și șterge unitățile Brut
        original_units = state.get('processed_units', [])
        original_folders = state.get('processed_folders', [])

        # Șterge unitățile Brut
        filtered_units = [u for u in original_units if 'Brut, Mihaela' not in u]
        filtered_folders = [f for f in original_folders if 'Brut, Mihaela' not in f]

        units_removed = len(original_units) - len(filtered_units)
        folders_removed = len(original_folders) - len(filtered_folders)

        # Actualizează starea
        state['processed_units'] = filtered_units
        state['processed_folders'] = filtered_folders

        # Ajustează contoarele
        if units_removed > 0:
            # Scade 2 fișiere PDF care vor fi re-uploadate
            state['uploads_today'] = max(0, state.get('uploads_today', 0) - 2)
            state['total_files_uploaded'] = max(0, state.get('total_files_uploaded', 0) - 2)

        print(f"\n🧹 Curățare efectuată:")
        print(f"   🗑️ Unități șterse: {units_removed}")
        print(f"   🗑️ Foldere șterse: {folders_removed}")
        print(f"   📊 Noi upload-uri astăzi: {state['uploads_today']}")

        # Salvează
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        print(f"\n✅ REPARARE COMPLETĂ!")
        print(f"\n🚀 URMĂTORII PAȘI:")
        print(f"1. ✅ Unitățile Brut au fost șterse din stare")
        print(f"2. 🔄 Rulează scriptul principal")
        print(f"3. ⚠️  FOARTE IMPORTANT: NU schimba tab-ul în Chrome!")
        print(f"4. ☕ Ia-ți o cafea și lasă Chrome în pace")
        print(f"5. 📊 Vor fi re-uploadate 2 fișiere PDF")

        print(f"\n📋 UNITĂȚI CARE VOR FI REPROCESSATE:")
        brut_units = [
            "g:\\ARHIVA\\B\\Brut, Mihaela",
            "g:\\ARHIVA\\B\\Brut, Mihaela\\Sustinerea Unui Discurs Public"
        ]
        for unit in brut_units:
            print(f"   📂 {unit}")

        return True

    except Exception as e:
        print(f"❌ Eroare: {e}")
        return False

def show_focus_reminder():
    """Afișează reminder-ul pentru focus"""

    print(f"\n🚨 REMINDER CRITIC - FOCUS CHROME:")
    print("=" * 40)
    print("⚠️  În timpul rulării scriptului:")
    print("   ❌ NU schimba tab-ul în Chrome")
    print("   ❌ NU minimiza Chrome")
    print("   ❌ NU apăsa Alt+Tab")
    print("   ❌ NU deschide alte aplicații")
    print("")
    print("   ✅ Lasă Chrome să lucreze singur")
    print("   ✅ Urmărește progresul în consolă")
    print("   ✅ Ia-ți o pauză ☕")
    print("")
    print("🎯 REGULA DE AUR: Hands off Chrome!")

if __name__ == "__main__":
    success = fix_brut_focus_issue()
    if success:
        show_focus_reminder()
        input("\n🔄 Apasă ENTER pentru a continua cu rularea scriptului principal...")
    else:
        print("❌ Repararea a eșuat!")