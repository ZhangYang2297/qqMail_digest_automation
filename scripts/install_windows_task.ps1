param(
  [Parameter(Mandatory=$true)] [string] $TaskName,
  [Parameter(Mandatory=$true)] [string] $PythonExe,
  [Parameter(Mandatory=$true)] [string] $ScriptPath,
  [Parameter(Mandatory=$true)] [string] $ConfigPath,
  [string] $WorkingDirectory = (Split-Path -Parent $ConfigPath)
)

$python = (Resolve-Path -LiteralPath $PythonExe).Path
$script = (Resolve-Path -LiteralPath $ScriptPath).Path
$config = (Resolve-Path -LiteralPath $ConfigPath).Path
$workdir = (Resolve-Path -LiteralPath $WorkingDirectory).Path

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`" --config `"$config`"" -WorkingDirectory $workdir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "QQ Mail digest watcher" -Force | Out-Null
Write-Output "Installed scheduled task: $TaskName"
Write-Output "Test with: Start-ScheduledTask -TaskName '$TaskName'"
