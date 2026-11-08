$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Create .venv and install requirements + PyInstaller first (see README).' }
& $python make_demo.py
if ($LASTEXITCODE) { throw 'Demo generation failed' }
& $python -m unittest test_readers test_ui
if ($LASTEXITCODE) { throw 'Tests failed' }
& $python collect_licenses.py
if ($LASTEXITCODE) { throw 'License collection failed' }
& $python -m PyInstaller --noconfirm --clean --windowed --onedir --name SignalDesk --icon app.ico --add-data 'app.ico:.' --add-data 'examples/data:examples/data' --add-data 'examples/demo.png:examples' --add-data 'examples/README.md:examples' --add-data 'LICENSE:.' --add-data 'README.md:.' --add-data 'build/third-party:third-party' --exclude-module pytest --exclude-module IPython app.py
if ($LASTEXITCODE) { throw 'Packaging failed' }
New-Item -ItemType Directory -Force release | Out-Null
Compress-Archive -Path dist\SignalDesk -DestinationPath release\SignalDesk-v1.0.0-windows-x64.zip -Force
Get-FileHash release\SignalDesk-v1.0.0-windows-x64.zip -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLower())  SignalDesk-v1.0.0-windows-x64.zip" } | Set-Content release\SHA256SUMS.txt -Encoding ascii
