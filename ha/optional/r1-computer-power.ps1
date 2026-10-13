# Only these fixed commands are available to the Home Assistant SSH key.
$ErrorActionPreference = 'Stop'
$r1RequestedCommand = $env:SSH_ORIGINAL_COMMAND
switch -Exact ($r1RequestedCommand) {
    'r1-ha-status' {
        [Console]::WriteLine('ready')
        exit 0
    }
    'r1-ha-shutdown-60' {
        & "$env:SystemRoot\System32\shutdown.exe" /s /t 60 /c 'Home Assistant: shutdown in 60 seconds'
        $r1ShutdownCode = $LASTEXITCODE
        if ($r1ShutdownCode -eq 0) { [Console]::WriteLine('shutdown_scheduled') }
        exit $r1ShutdownCode
    }
    'r1-ha-cancel-shutdown' {
        & "$env:SystemRoot\System32\cmd.exe" /d /c 'shutdown.exe /a >nul 2>&1'
        $r1CancelCode = $LASTEXITCODE
        if ($r1CancelCode -eq 0) {
            [Console]::WriteLine('shutdown_cancelled')
            exit 0
        }
        if ($r1CancelCode -eq 1116) {
            [Console]::WriteLine('no_shutdown_pending')
            exit 0
        }
        exit $r1CancelCode
    }
    default {
        [Console]::Error.WriteLine('Command denied')
        exit 64
    }
}
