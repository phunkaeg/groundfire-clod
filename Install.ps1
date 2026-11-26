[CmdletBinding()]
param(
    [string]$Profile = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "1C SoftClub\il-2 sturmovik cliffs of dover"),
    [switch]$Night,
    [string]$GameDirectory,
    [string]$SmokeAtlas,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$target = [IO.Path]::GetFullPath($Profile)
$single = Join-Path $target "missions\Single"
$effects = Join-Path $target "GroundFireEffects"
$items = [Collections.Generic.List[object]]::new()

function Add-InstallFile([string]$Source, [string]$Destination) {
    if (!(Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Missing source file $Source"
    }
    if (Test-Path -LiteralPath $Destination) {
        $current = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        $incoming = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
        if ($current -ne $incoming) {
            throw "A different file already exists at $Destination. Back it up before installing."
        }
        return
    }
    $items.Add([pscustomobject]@{ Source = $Source; Destination = $Destination })
}

foreach ($file in Get-ChildItem -LiteralPath (Join-Path $repo "missions\day") -File) {
    Add-InstallFile $file.FullName (Join-Path $single $file.Name)
}

$scratch = $null
try {
    if ($Night) {
        foreach ($file in Get-ChildItem -LiteralPath (Join-Path $repo "missions\night") -File) {
            Add-InstallFile $file.FullName (Join-Path $single $file.Name)
        }
        foreach ($file in Get-ChildItem -LiteralPath (Join-Path $repo "effects") -File) {
            Add-InstallFile $file.FullName (Join-Path $effects $file.Name)
        }

        if (!$SmokeAtlas -and !$DryRun) {
            if (!$GameDirectory) {
                throw "Supply -GameDirectory for the installed beta or -SmokeAtlas for your local DDS."
            }
            $gamePath = (Resolve-Path -LiteralPath $GameDirectory).ProviderPath
            $compiler = Join-Path $env:windir "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
            $scratch = Join-Path ([IO.Path]::GetTempPath()) ("GroundFireAtlas-" + [Guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Path $scratch | Out-Null
            $exporter = Join-Path $scratch "ExportSmokeAtlas.exe"
            Push-Location -LiteralPath $repo
            try {
                & $compiler /nologo /platform:x64 "/out:$exporter" "tools\ExportSmokeAtlas.cs"
                if ($LASTEXITCODE -ne 0) { throw "Could not compile the local smoke atlas exporter." }
            } finally {
                Pop-Location
            }
            $SmokeAtlas = Join-Path $scratch "Smoke_Sprites_Air_W.dds"
            & $exporter $gamePath $SmokeAtlas
            if ($LASTEXITCODE -ne 0) { throw "The smoke atlas could not be exported from the installed game." }
        }
        if ($SmokeAtlas) {
            $SmokeAtlas = (Resolve-Path -LiteralPath $SmokeAtlas).ProviderPath
            $atlasStream = [IO.File]::OpenRead($SmokeAtlas)
            try {
                $signature = New-Object byte[] 4
                if ($atlasStream.Read($signature, 0, 4) -ne 4 -or [Text.Encoding]::ASCII.GetString($signature) -ne "DDS ") {
                    throw "Expected a DDS smoke atlas."
                }
            } finally {
                $atlasStream.Dispose()
            }
            Add-InstallFile $SmokeAtlas (Join-Path $effects "Smoke_Sprites_Air_W.dds")
        } elseif ($DryRun) {
            Write-Output "Night install also needs the local stock Smoke_Sprites_Air_W.dds."
        }
    }

    foreach ($item in $items) {
        Write-Output "$($item.Source) -> $($item.Destination)"
        if (!$DryRun) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $item.Destination) -Force | Out-Null
            Copy-Item -LiteralPath $item.Source -Destination $item.Destination
        }
    }
    if (!$DryRun) {
        Write-Output "Installed $($items.Count) files. Launch the matching bridge before flying."
    }
} finally {
    if ($scratch) {
        # These two files were generated inside this invocation's unique directory.
        foreach ($name in @("ExportSmokeAtlas.exe", "Smoke_Sprites_Air_W.dds")) {
            $file = Join-Path $scratch $name
            if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
        }
        Remove-Item -LiteralPath $scratch
    }
}
