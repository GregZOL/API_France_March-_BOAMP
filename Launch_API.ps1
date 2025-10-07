# One-click launcher for Windows PowerShell
# - Crée un venv si nécessaire
# - Installe les dépendances si absentes / requirements.txt modifié
# - Démarre le serveur Flask
# - Ouvre le navigateur sur http://localhost:8000

$ErrorActionPreference = 'Stop'
$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path  # répertoire projet
Set-Location $PSScriptRoot

function Find-Python {
  if (Get-Command py -ErrorAction SilentlyContinue) { return 'py -3' }
  if (Get-Command python -ErrorAction SilentlyContinue) { return 'python' }
  throw 'Python non trouvé. Installez Python 3 depuis https://www.python.org/downloads/'
}

$py = Find-Python

if (-Not (Test-Path '.venv')) {
  iex "$py -m venv .venv"
}

& .\.venv\Scripts\Activate.ps1  # active le venv

# Install requirements only if needed (missing pkgs or changed lock)
$req = Join-Path $PSScriptRoot 'Back-end/requirements.txt'
$stamp = Join-Path $PSScriptRoot '.venv/.requirements.sha256'

function Get-FileSha256($path) {
  (Get-FileHash -Algorithm SHA256 -Path $path).Hash
}

$reqHash = Get-FileSha256 $req
$curHash = ''
if (Test-Path $stamp) { $curHash = Get-Content $stamp -ErrorAction SilentlyContinue }

$needInstall = $false
& python -m pip show flask *> $null; $ok1 = $LASTEXITCODE -eq 0
& python -m pip show certifi *> $null; $ok2 = $LASTEXITCODE -eq 0
if (-not ($ok1 -and $ok2)) { $needInstall = $true }
if ($reqHash -ne $curHash) { $needInstall = $true }

if ($needInstall) {
  python -m pip install --upgrade pip | Out-Null
  python -m pip install -r $req
  Set-Content -Path $stamp -Value $reqHash | Out-Null
}

if (Test-Path .\Back-end\local_ca.pem) {
  $env:LOCAL_CA_FILE = (Resolve-Path .\Back-end\local_ca.pem)
  $env:SSL_CERT_FILE = (Resolve-Path .\Back-end\local_ca.pem)
}

$env:PREFER_EXPLORE = if ($env:PREFER_EXPLORE) { $env:PREFER_EXPLORE } else { '1' }

Start-Process 'http://localhost:8000'  # ouvre le navigateur

python .\Back-end\app.py  # démarre le serveur

Write-Host "Serveur arrêté. Fermez cette fenêtre."
Read-Host "Appuyez sur Entrée pour quitter"
