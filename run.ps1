# .env에서 DISCORD_KOR_FIN 로드
$envFile = "C:\pjkgs_projects\vengeance_studio\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*DISCORD_KOR_FIN\s*=\s*(.+)$') {
            $env:DISCORD_WEBHOOK = $matches[1].Trim()
        }
    }
}

Set-Location "C:\pjkgs_projects\kor_fin_news"
& "C:\AI\miniconda\python.exe" main.py --now
