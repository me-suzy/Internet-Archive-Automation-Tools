import re
from pathlib import Path

def alphabetical_sort_key(folder_name):
    """Creează o cheie de sortare pur alfabetică, ignorând caracterele speciale"""
    clean_name = re.sub(r'[^a-zA-Z\s]', '', folder_name.lower())
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    return clean_name

# Test cu folderele menționate
folders = [
    "Cabuti, Horia Al",
    "C.O.C.C. S.A",
    "Cadell, Elizabeth",
    "Cacacostea, D",
    "Cace, Sorin",
    "Cadar, Ioan"
]

print("Ordinea folderelor după sortare alfabetică:")
print("=" * 50)

# Creează lista cu chei de sortare
folder_data = []
for folder in folders:
    sort_key = alphabetical_sort_key(folder)
    folder_data.append((folder, sort_key))

# Sortează
folder_data.sort(key=lambda x: x[1])

# Afișează rezultatul
for i, (folder, sort_key) in enumerate(folder_data, 1):
    print(f"{i:2d}. {folder:<25} → '{sort_key}'")

print("\n" + "=" * 50)
print("CONCLUZIE:")
if any("C.O.C.C" in folder for folder, _ in folder_data[:3]):
    index = next(i for i, (folder, _) in enumerate(folder_data, 1) if "C.O.C.C" in folder)
    print(f"'C.O.C.C. S.A' este pe poziția #{index}")
else:
    print("'C.O.C.C. S.A' nu este în primele 3 poziții")