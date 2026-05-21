$date = Get-Date -Format "yyyy-MM-dd"
$src  = "C:\VisiPick\data\visipick.db"
$dest = "C:\VisiPick\backup\visipick-$date.db"

New-Item -ItemType Directory -Force -Path "C:\VisiPick\backup"
Copy-Item $src $dest
Write-Host "백업 완료: $dest"
