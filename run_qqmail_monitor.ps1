param(
  [string] $PythonExe = "python",
  [string] $WatcherScript = "C:\Users\admin\.codex\skills\qqmail-digest-automation\scripts\qqmail_digest_watcher.py",
  [string] $ConfigPath = "C:\Users\admin\Documents\QQmail\config.json",
  [string] $LogPath = "C:\Users\admin\Documents\QQmail\qqmail_monitor.log",
  [int] $PollSeconds = 60
)

function Write-LogLine([string] $Message) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Show-QQMailNotification([int] $Count) {
  $todayFile = Join-Path "C:\Users\admin\Documents\QQmail\txt" ((Get-Date -Format "yyyyMMdd") + ".txt")
  $message = "收到 $Count 封新邮件，摘要已写入 $todayFile"
  try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    Add-Type -AssemblyName System.Drawing -ErrorAction Stop
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
    $notify.BalloonTipTitle = "QQ邮箱新邮件摘要"
    $notify.BalloonTipText = $message
    $notify.Visible = $true
    $notify.ShowBalloonTip(10000)
    Start-Sleep -Seconds 12
    $notify.Dispose()
    Write-LogLine "notification_sent count=$Count"
  } catch {
    Write-LogLine "notification_failed $($_.Exception.Message)"
  }
}

Write-LogLine "monitor_started poll_seconds=$PollSeconds"
while ($true) {
  try {
    $output = & $PythonExe $WatcherScript --config $ConfigPath --once 2>&1
    $joined = ($output | Out-String).Trim()
    Write-LogLine "watcher_output $joined"
    $processed = 0
    if ($joined -match 'processed=(\d+)') {
      $processed = [int] $Matches[1]
    }
    if ($processed -gt 0) {
      Show-QQMailNotification -Count $processed
    }
  } catch {
    Write-LogLine "monitor_error $($_.Exception.Message)"
  }
  Start-Sleep -Seconds $PollSeconds
}
