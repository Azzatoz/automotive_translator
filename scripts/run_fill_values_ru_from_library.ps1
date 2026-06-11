# fill_values_ru_from_library.py — библиотека, затем Google; отчёт в reports/
$ErrorActionPreference = 'Stop'

$ScriptsDir = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $ScriptsDir '..')).Path
$Req = Join-Path $RepoRoot 'requirements\fill-values-ru.txt'
$ProjectRoot = (Resolve-Path (Join-Path $RepoRoot '..')).Path

function Get-PythonCommand {
    if ($env:PYTHON) {
        return @{ Executable = $env:PYTHON; Prefix = @() }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Executable = $python.Source; Prefix = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3 -c "import sys" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return @{ Executable = $py.Source; Prefix = @('-3') }
        }
    }

    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3) {
        return @{ Executable = $python3.Source; Prefix = @() }
    }

    throw "Python не найден. Установите Python или задайте переменную окружения PYTHON."
}

function Resolve-ExistingDirectory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $null
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Expand-UserPath([string]$Path) {
    if ($Path -match '^~([\\/]|$)') {
        return Join-Path $HOME $Path.Substring(1).TrimStart('\', '/')
    }
    return $Path
}

$RootPresetLabels = New-Object System.Collections.Generic.List[string]
$RootPresetPaths = New-Object System.Collections.Generic.List[string]

function Add-RootPreset([string]$Label, [string]$Path) {
    $resolved = Resolve-ExistingDirectory $Path
    if (-not $resolved) {
        return
    }
    if ($RootPresetPaths -contains $resolved) {
        return
    }
    [void]$RootPresetLabels.Add($Label)
    [void]$RootPresetPaths.Add($resolved)
}

Add-RootPreset 'Текущий проект (On translate)' $ProjectRoot
Add-RootPreset 'Dorest translate/Translated' (Join-Path $ProjectRoot '..\Translated')

$candidatePaths = @(
    (Join-Path $ProjectRoot '..\..\Rest 4.1.1\Translated'),
    (Join-Path $ProjectRoot '..\..\Dorest 3.2.0\dorest 320'),
    'D:\Voyah\Dorest translate\Translated'
)

foreach ($candidate in $candidatePaths) {
    $resolved = Resolve-ExistingDirectory $candidate
    if (-not $resolved) {
        continue
    }
    if ($RootPresetPaths -contains $resolved) {
        continue
    }

    switch -Regex ($candidate) {
        'Rest 4\.1\.1' { Add-RootPreset 'Rest 4.1.1/Translated' $resolved; continue }
        'dorest 320' { Add-RootPreset 'Dorest 3.2.0/dorest 320' $resolved; continue }
        default {
            $parent = Split-Path (Split-Path $resolved -Parent) -Leaf
            $leaf = Split-Path $resolved -Leaf
            Add-RootPreset "$parent/$leaf" $resolved
        }
    }
}

function Read-MenuChoice {
    param(
        [string]$Prompt,
        [int]$Min,
        [int]$Max
    )

    while ($true) {
        $input = Read-Host $Prompt
        $choice = 0
        if ([int]::TryParse($input, [ref]$choice)) {
            if ($choice -ge $Min -and $choice -le $Max) {
                return $choice
            }
        }
        Write-Host "Введите число от $Min до $Max."
    }
}

function Invoke-InteractiveFill {
    Write-Host ''
    Write-Host '=== Перевод APK -> values-ru ==='
    Write-Host ''
    Write-Host 'С какого языка переводить (оригинал в res/values)?'
    Write-Host '  1) Китайский (zh-CN)'
    Write-Host '  2) Английский (en)'

    $langChoice = Read-MenuChoice -Prompt 'Выберите язык [1-2]' -Min 1 -Max 2
    $sourceLang = if ($langChoice -eq 1) { 'zh-CN' } else { 'en' }
    Write-Host "--source-lang $sourceLang"
    Write-Host ''

    $defaultRoot = if ($RootPresetPaths.Count -gt 0) { $RootPresetPaths[0] } else { $ProjectRoot }
    Write-Host 'Путь: один модуль (com.qinggan.app.setting_src) или папка со всеми *_src.'
    Write-Host '  setting_src - только этот APK; On translate - все модули.'
    Write-Host ''

    for ($i = 0; $i -lt $RootPresetLabels.Count; $i++) {
        Write-Host ("  {0}) {1}" -f ($i + 1), $RootPresetLabels[$i])
    }
    $manualIndex = $RootPresetLabels.Count + 1
    Write-Host "  $manualIndex) Ввести путь вручную"

    $rootChoice = Read-MenuChoice -Prompt "Выберите каталог [1-$manualIndex]" -Min 1 -Max $manualIndex
    $rootIndex = $rootChoice - 1

    if ($rootIndex -lt $RootPresetPaths.Count) {
        $rootPath = $RootPresetPaths[$rootIndex]
    }
    else {
        $input = Read-Host "Путь к модулю или папке проекта [$defaultRoot]"
        if ([string]::IsNullOrWhiteSpace($input)) {
            $rootPath = $defaultRoot
        }
        else {
            $rootPath = Expand-UserPath $input.Trim()
        }
    }

    if (-not (Test-Path -LiteralPath $rootPath -PathType Container)) {
        Write-Error "Ошибка: каталог не найден: $rootPath"
    }

    $rootPath = (Resolve-Path -LiteralPath $rootPath).Path
    Write-Host "--root $rootPath"
    Write-Host ''

    return @{
        RootPath = $rootPath
        SourceLang = $sourceLang
    }
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [switch]$AllowFailure,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    $params = @()
    if ($Python.Prefix.Count -gt 0) {
        $params += $Python.Prefix
    }
    $params += $Arguments
    & $Python.Executable @params
    if (-not $AllowFailure -and $LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    return $LASTEXITCODE
}

$scriptArgs = @($args)
if ($scriptArgs.Count -eq 0) {
    $interactive = Invoke-InteractiveFill
    $scriptArgs = @('--root', $interactive.RootPath, '--source-lang', $interactive.SourceLang)
}

$python = Get-PythonCommand
$hasDeepTranslator = Invoke-Python $python -AllowFailure -c 'from deep_translator import GoogleTranslator'
if ($hasDeepTranslator -ne 0) {
    $exeInfo = Invoke-Python $python -c 'import sys; print(sys.executable)'
    Write-Host ('[run_fill_values_ru_from_library] pip install deep-translator: ' + $exeInfo)

    if (Test-Path -LiteralPath $Req) {
        Invoke-Python $python -m pip install --user -r $Req
    }
    else {
        Invoke-Python $python -m pip install --user deep-translator
    }
}

$env:PYTHONUNBUFFERED = '1'
$pyScript = Join-Path $ScriptsDir 'fill_values_ru_from_library.py'
Invoke-Python $python $pyScript @scriptArgs
exit $LASTEXITCODE