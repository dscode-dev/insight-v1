# Insight — expose the WSL stack to the local network. RUN AS ADMIN.
#
# WHY THIS IS NEEDED. WSL2 does not sit on the LAN: it lives behind a
# NAT'd virtual switch, so 172.23.207.224 is meaningless to any other
# machine. Binding the console to 0.0.0.0 made it reachable from THIS
# Windows host and no further. Reaching it from another device needs
# Windows to forward its own LAN-facing port into WSL, which is what
# `netsh interface portproxy` does.
#
# WHY IT MUST BE RE-RUN. The WSL IP is assigned per boot and changes.
# A portproxy rule pointing at a stale IP fails silently — the port
# accepts the connection and then nothing answers. So the rule is
# rebuilt from the CURRENT IP every time, rather than assumed.
#
# Register it to run at logon (once, as admin):
#   schtasks /create /tn "Insight LAN access" /sc onlogon /rl highest ^
#     /tr "powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\to\insight-lan-access.ps1"

#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'

# Only what the reverse proxy serves. 3001/9000/5000 are deliberately
# NOT forwarded: they are reached through nginx on 80, so exposing them
# too would create a second door that bypasses its default-deny.
$Ports = @(80)

function Get-WslIp {
    # `hostname -I` returns the WSL address first, then the Docker bridge
    # addresses. Only the first is the one Windows can route to.
    $raw = (wsl -d Ubuntu -e hostname -I) -join ' '
    $ip = ($raw -split '\s+' | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' })[0]
    if (-not $ip) { throw "could not determine the WSL IP (is the distro running?)" }
    return $ip
}

$wslIp = Get-WslIp
Write-Host "WSL IP: $wslIp"

foreach ($port in $Ports) {
    # Delete first: a rule for this port may already exist pointing at a
    # previous, now-dead WSL address. `add` would not replace it.
    netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
    netsh interface portproxy add v4tov4 `
        listenport=$port listenaddress=0.0.0.0 `
        connectport=$port connectaddress=$wslIp | Out-Null
    Write-Host "  forwarding 0.0.0.0:$port -> ${wslIp}:$port"

    $ruleName = "Insight WSL $port"
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        # Scoped to private/domain profiles: this opens a port to the
        # local network, and it should not follow the machine onto a
        # coffee-shop Wi-Fi marked Public.
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound `
            -Action Allow -Protocol TCP -LocalPort $port `
            -Profile Private,Domain | Out-Null
        Write-Host "  firewall rule created: $ruleName (Private,Domain)"
    }
}

Write-Host ""
Write-Host "Active forwards:"
netsh interface portproxy show v4tov4

$lan = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|172\.(1[6-9]|2[0-9]|3[01])\.)' } |
        Select-Object -First 1).IPAddress
if ($lan) {
    Write-Host ""
    Write-Host "Reachable from the LAN at:"
    Write-Host "  http://${lan}/console/"
    Write-Host "  http://${lan}/portainer/"
}
