$folderPath = "E:\Carte\BB\17 - Site Leadership\alte\Ionel Balauta\Aryeht\Task 1 - Traduce tot site-ul\Doar Google Web\Andreea\Meditatii\2023\++Internet Archive BUN 2025 + Chrome\Cauta pe internet archive daca exista fisierele 4"

# Obține fișierele din folderul rădăcină care au spații în jurul caracterelor `-` sau `_`
Get-ChildItem -Path $folderPath -File |
Where-Object { $_.Name -match '[-_]\s|\s[-_]' } |
ForEach-Object {
    $oldName = $_.Name
    $newName = $oldName -replace '\s+[-_]', '-' -replace '[-_]\s+', '-'
    $oldFullPath = Join-Path -Path $folderPath -ChildPath $oldName
    $newFullPath = Join-Path -Path $folderPath -ChildPath $newName

    # Redenumește fișierul
    Rename-Item -Path $oldFullPath -NewName $newName -Force
    Write-Host "Fișier redenumit: $oldName -> $newName"
}

Write-Host "Redenumirea fișierelor a fost finalizată."
