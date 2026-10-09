param(
    [string]$AdapterName = "以太网",
    [string]$PcIp = "169.254.32.100",
    [string]$SubnetMask = "255.255.0.0"
)

netsh interface ip set address name="$AdapterName" static $PcIp $SubnetMask none
netsh interface ip set dns name="$AdapterName" source=none
ipconfig
