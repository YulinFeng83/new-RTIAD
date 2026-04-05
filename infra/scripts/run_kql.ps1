param(
    [Parameter(Mandatory = $true)]
    [string]$KustoUri,

    [Parameter(Mandatory = $true)]
    [string]$Database,

    [Parameter(Mandatory = $true)]
    [string]$ScriptPath
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ScriptPath)) {
    throw "KQL script not found: $ScriptPath"
}

$token = az account get-access-token --resource https://kusto.kusto.windows.net --query accessToken -o tsv
if (-not $token) {
    throw "Unable to acquire Kusto access token. Run az login first."
}

$body = @{
    db  = $Database
    csl = (Get-Content $ScriptPath -Raw)
} | ConvertTo-Json -Depth 5

$uri = "$($KustoUri.TrimEnd('/'))/v1/rest/mgmt"

Invoke-RestMethod -Method Post -Uri $uri -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json; charset=utf-8" -Body $body | Out-Null

Write-Host "Applied KQL script '$ScriptPath' to database '$Database'."
