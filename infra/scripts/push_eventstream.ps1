param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceId,

    [Parameter(Mandatory = $true)]
    [string]$ItemId,

    [Parameter(Mandatory = $true)]
    [string]$TemplatePath,

    [Parameter(Mandatory = $true)]
    [string]$DisplayName,

    [Parameter(Mandatory = $true)]
    [string]$KqlDatabaseId,

    [Parameter(Mandatory = $true)]
    [string]$KqlDatabaseName,

    [string]$SharedSchemaSetDisplayName,
    [string]$ClientName,
    [string]$ClientDisplayName,
    [string]$Environment = "prod"
)

$ErrorActionPreference = "Stop"

function Get-FabricToken {
    $token = az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv
    if (-not $token) {
        throw "Unable to acquire Fabric access token. Run az login first."
    }
    return $token
}

function Get-WorkspaceItems {
    param(
        [string]$WorkspaceId,
        [string]$Token
    )

    $headers = @{ Authorization = "Bearer $Token" }
    return (Invoke-RestMethod -Method Get -Uri "https://api.fabric.microsoft.com/v1/workspaces/$WorkspaceId/items" -Headers $headers).value
}

function Resolve-SchemaSetId {
    param(
        [string]$WorkspaceId,
        [string]$Token,
        [string]$DisplayName
    )

    if (-not $DisplayName) {
        return $null
    }

    $match = Get-WorkspaceItems -WorkspaceId $WorkspaceId -Token $Token | Where-Object {
        $_.type -eq "EventSchemaSet" -and $_.displayName -eq $DisplayName
    } | Select-Object -First 1

    if (-not $match) {
        throw "Unable to resolve EventSchemaSet '$DisplayName' in workspace '$WorkspaceId'."
    }

    return $match.id
}

function Convert-TemplateToDefinition {
    param(
        [string]$TemplateText,
        [hashtable]$Placeholders
    )

    $resolved = $TemplateText
    foreach ($key in $Placeholders.Keys) {
        $resolved = $resolved.Replace("{{$key}}", [string]$Placeholders[$key])
    }

    $template = $resolved | ConvertFrom-Json
    $parts = @()

    foreach ($property in $template.PSObject.Properties) {
        $key = $property.Name
        $path = if ($key -eq "platform") { ".platform" } else { "$key.json" }
        $payload = $property.Value | ConvertTo-Json -Depth 100
        $parts += @{
            path        = $path
            payload     = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))
            payloadType = "InlineBase64"
        }
    }

    return @{ definition = @{ parts = $parts } } | ConvertTo-Json -Depth 100
}

if (-not (Test-Path $TemplatePath)) {
    throw "Template not found: $TemplatePath"
}

$token = Get-FabricToken
$schemaSetId = Resolve-SchemaSetId -WorkspaceId $WorkspaceId -Token $token -DisplayName $SharedSchemaSetDisplayName
$templateText = Get-Content $TemplatePath -Raw

$placeholders = @{
    workspace_id                    = $WorkspaceId
    item_display_name               = $DisplayName
    item_stream_name                = "$DisplayName-stream"
    client_name                     = $ClientName
    client_display_name             = $ClientDisplayName
    environment                     = $Environment
    kql_database_id                 = $KqlDatabaseId
    kql_database_name               = $KqlDatabaseName
    shared_schema_set_id            = $schemaSetId
    shared_schema_set_display_name  = $SharedSchemaSetDisplayName
}

$body = Convert-TemplateToDefinition -TemplateText $templateText -Placeholders $placeholders
$headers = @{ Authorization = "Bearer $token" }

Invoke-RestMethod -Method Post -Uri "https://api.fabric.microsoft.com/v1/workspaces/$WorkspaceId/items/$ItemId/updateDefinition" -Headers $headers -ContentType "application/json; charset=utf-8" -Body $body | Out-Null

Write-Host "Updated Eventstream '$DisplayName' ($ItemId)."
