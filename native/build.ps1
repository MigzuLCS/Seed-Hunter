# Compila native/shbiomes.dll (cubiomes + fachada) com o MSVC do Visual Studio.
# Pre-requisito: git clone https://github.com/xpple/cubiomes tools/cubiomes
# O README do fork diz que o MSVC nao e suportado; os arquivos de bioma compilam, so o modulo de terreno nao
# (usa arrays de tamanho variavel), e ele nao e usado aqui.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$cub = Join-Path $root 'tools\cubiomes'
$out = Join-Path $PSScriptRoot 'build'
if (-not (Test-Path $cub)) { throw "Falta $cub (git clone https://github.com/xpple/cubiomes tools/cubiomes)" }
$vc = Get-ChildItem 'C:\Program Files\Microsoft Visual Studio', 'C:\Program Files (x86)\Microsoft Visual Studio' `
    -Recurse -Filter vcvars64.bat -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $vc) { throw 'vcvars64.bat nao encontrado: instale as Build Tools do Visual Studio (C++)' }
New-Item -ItemType Directory -Force $out | Out-Null
$srcs = 'biomes.c', 'layers.c', 'noise.c', 'biomenoise.c', 'generator.c', 'util.c' | ForEach-Object { "`"$cub\$_`"" }
$wrapper = "`"$PSScriptRoot\shbiomes.c`""
$cmd = "call `"$vc`" >nul 2>&1 && cd /d `"$out`" && cl /nologo /O2 /LD /I`"$cub`" $wrapper $($srcs -join ' ') /Fe:shbiomes.dll 2>&1"
$log = cmd /c $cmd
$log | Select-String 'error|fatal|warning C4(013|047)' | Select-Object -First 12 | ForEach-Object { $_.Line.Trim() }
if (-not (Test-Path "$out\shbiomes.dll")) { throw 'a compilacao falhou' }
Copy-Item "$out\shbiomes.dll" "$PSScriptRoot\shbiomes.dll" -Force
"OK: $PSScriptRoot\shbiomes.dll ($([int]((Get-Item "$PSScriptRoot\shbiomes.dll").Length/1KB)) KB)"
