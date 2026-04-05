param(
    [Parameter(Mandatory = $true)]
    [string]$ClientName,

    [string]$ClientDisplayName = $ClientName,
    [string]$Environment = "prod",
    [string]$CapacityId,
    [string]$WorkspaceId,
    [switch]$RunTerraformApply
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$terraformDir = Join-Path $repoRoot "infra\terraform"
$scriptsDir = Join-Path $repoRoot "infra\scripts"
$kqlDir = Join-Path $repoRoot "infra\fabric\kql"
$eventstreamDir = Join-Path $repoRoot "infra\fabric\eventstream"
$dashboardsDir = Join-Path $repoRoot "infra\fabric\dashboards"

function Invoke-Terraform {
    param([string[]]$Arguments)

    Push-Location $terraformDir
    try {
        & terraform @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Terraform command failed: terraform $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

if ($RunTerraformApply) {
    if (-not $CapacityId) {
        throw "CapacityId is required when -RunTerraformApply is used."
    }

    Invoke-Terraform -Arguments @(
        "apply",
        "-auto-approve",
        "-var=client_name=$ClientName",
        "-var=client_display_name=$ClientDisplayName",
        "-var=environment=$Environment",
        "-var=capacity_id=$CapacityId"
    )
}

$outputs = $null
Push-Location $terraformDir
try {
    $outputs = terraform output -json | Out-String | ConvertFrom-Json
}
finally {
    Pop-Location
}

$eventModelDatabaseName = "kql_${ClientName}_event_model"
$revenueDatabaseName = "kql_${ClientName}_revenue"
$schemaSetName = "pos_schema_set_${ClientName}"
$querysetName = "kqs_${ClientName}"

$eventModelKustoUri = $outputs.event_model_kusto_uri.value
$eventModelKqlDatabaseId = $outputs.event_model_kql_database_id.value
$eventModelEventstreamId = $outputs.event_model_eventstream_id.value
$revenueKustoUri = $outputs.revenue_kusto_uri.value
$revenueKqlDatabaseId = $outputs.revenue_kql_database_id.value
$revenueEventstreamId = $outputs.revenue_eventstream_id.value

if (-not $WorkspaceId) {
    $WorkspaceId = $outputs.workspace_id.value
}

if (-not $WorkspaceId) {
    throw "Unable to resolve workspace ID from Terraform output."
}

& (Join-Path $scriptsDir "run_kql.ps1") -KustoUri $eventModelKustoUri -Database $eventModelDatabaseName -ScriptPath (Join-Path $kqlDir "01_create_store_events_raw.kql")
& (Join-Path $scriptsDir "run_kql.ps1") -KustoUri $eventModelKustoUri -Database $eventModelDatabaseName -ScriptPath (Join-Path $kqlDir "02_create_traffic_session_enriched_rt.kql")
& (Join-Path $scriptsDir "run_kql.ps1") -KustoUri $eventModelKustoUri -Database $eventModelDatabaseName -ScriptPath (Join-Path $kqlDir "03_create_dashboard_functions.kql")
& (Join-Path $scriptsDir "run_kql.ps1") -KustoUri $eventModelKustoUri -Database $eventModelDatabaseName -ScriptPath (Join-Path $kqlDir "05_policies.kql")

& (Join-Path $scriptsDir "run_kql.ps1") -KustoUri $revenueKustoUri -Database $revenueDatabaseName -ScriptPath (Join-Path $kqlDir "06_create_pos_events_rt.kql")
& (Join-Path $scriptsDir "run_kql.ps1") -KustoUri $revenueKustoUri -Database $revenueDatabaseName -ScriptPath (Join-Path $kqlDir "09_create_store_revenue_5m_mv.kql")
& (Join-Path $scriptsDir "run_kql.ps1") -KustoUri $revenueKustoUri -Database $revenueDatabaseName -ScriptPath (Join-Path $kqlDir "07_create_revenue_functions.kql")
& (Join-Path $scriptsDir "run_kql.ps1") -KustoUri $revenueKustoUri -Database $revenueDatabaseName -ScriptPath (Join-Path $kqlDir "08_revenue_policies.kql")

& (Join-Path $scriptsDir "push_definition.ps1") -WorkspaceId $WorkspaceId -ItemType "EventSchemaSet" -DisplayName $schemaSetName -TemplatePath (Join-Path $eventstreamDir "pos_schema_set.definition.json") -ClientName $ClientName -ClientDisplayName $ClientDisplayName -Environment $Environment | Out-Null

& (Join-Path $scriptsDir "push_eventstream.ps1") -WorkspaceId $WorkspaceId -ItemId $eventModelEventstreamId -DisplayName "es_${ClientName}_event_model" -TemplatePath (Join-Path $eventstreamDir "es_event_model.definition.json") -KqlDatabaseId $eventModelKqlDatabaseId -KqlDatabaseName $eventModelDatabaseName -ClientName $ClientName -ClientDisplayName $ClientDisplayName -Environment $Environment

& (Join-Path $scriptsDir "push_eventstream.ps1") -WorkspaceId $WorkspaceId -ItemId $revenueEventstreamId -DisplayName "es_${ClientName}_revenue" -TemplatePath (Join-Path $eventstreamDir "es_revenue.definition.json") -KqlDatabaseId $revenueKqlDatabaseId -KqlDatabaseName $revenueDatabaseName -SharedSchemaSetDisplayName $schemaSetName -ClientName $ClientName -ClientDisplayName $ClientDisplayName -Environment $Environment

& (Join-Path $scriptsDir "push_definition.ps1") -WorkspaceId $WorkspaceId -ItemType "KQLDashboard" -DisplayName "StoreMonitor" -TemplatePath (Join-Path $dashboardsDir "StoreMonitor.definition.json") -DashboardPrimaryKustoUri $eventModelKustoUri -DashboardPrimaryDatabaseId $eventModelKqlDatabaseId -DashboardPrimaryDatabaseName $eventModelDatabaseName -EventModelKustoUri $eventModelKustoUri -EventModelDatabaseId $eventModelKqlDatabaseId -EventModelDatabaseName $eventModelDatabaseName -RevenueKustoUri $revenueKustoUri -RevenueDatabaseId $revenueKqlDatabaseId -RevenueDatabaseName $revenueDatabaseName -ClientName $ClientName -ClientDisplayName $ClientDisplayName -Environment $Environment | Out-Null

& (Join-Path $scriptsDir "push_definition.ps1") -WorkspaceId $WorkspaceId -ItemType "KQLDashboard" -DisplayName "Office-Cam" -TemplatePath (Join-Path $dashboardsDir "Office-Cam.definition.json") -DashboardPrimaryKustoUri $eventModelKustoUri -DashboardPrimaryDatabaseId $eventModelKqlDatabaseId -DashboardPrimaryDatabaseName $eventModelDatabaseName -EventModelKustoUri $eventModelKustoUri -EventModelDatabaseId $eventModelKqlDatabaseId -EventModelDatabaseName $eventModelDatabaseName -ClientName $ClientName -ClientDisplayName $ClientDisplayName -Environment $Environment | Out-Null

& (Join-Path $scriptsDir "push_definition.ps1") -WorkspaceId $WorkspaceId -ItemType "KQLDashboard" -DisplayName "POS & Traffic RT Dash" -TemplatePath (Join-Path $dashboardsDir "POS & Traffic RT Dash.definition.json") -DashboardPrimaryKustoUri $eventModelKustoUri -DashboardPrimaryDatabaseId $eventModelKqlDatabaseId -DashboardPrimaryDatabaseName $eventModelDatabaseName -EventModelKustoUri $eventModelKustoUri -EventModelDatabaseId $eventModelKqlDatabaseId -EventModelDatabaseName $eventModelDatabaseName -RevenueKustoUri $revenueKustoUri -RevenueDatabaseId $revenueKqlDatabaseId -RevenueDatabaseName $revenueDatabaseName -ClientName $ClientName -ClientDisplayName $ClientDisplayName -Environment $Environment | Out-Null

& (Join-Path $scriptsDir "push_definition.ps1") -WorkspaceId $WorkspaceId -ItemType "KQLQueryset" -DisplayName $querysetName -TemplatePath (Join-Path $kqlDir "kqs_event_model.definition.json") -EventModelKustoUri $eventModelKustoUri -EventModelDatabaseId $eventModelKqlDatabaseId -EventModelDatabaseName $eventModelDatabaseName -ClientName $ClientName -ClientDisplayName $ClientDisplayName -Environment $Environment | Out-Null

Write-Host "Client onboarding deployment completed for '$ClientName'."
