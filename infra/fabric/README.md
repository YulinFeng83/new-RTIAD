# Fabric Client Onboarding

This directory contains the reusable onboarding assets for provisioning a new Fabric client deployment with two stacks:

- Event Model
- Revenue Model

Terraform creates the core Fabric resources. PowerShell helpers then push the exported KQL, Eventstream, Queryset, schema-set, and dashboard definitions that are not modeled as first-class Terraform resources.

## Required Inputs

Set these in `infra/terraform/terraform.tfvars` or pass them with `-var`:

- `client_name`: short slug used in generated item names.
- `client_display_name`: human-readable client name.
- `environment`: environment suffix, default `prod`.
- `capacity_id`: Fabric capacity ID for the new client workspace.

Generated names follow this pattern:

- `kql_<client_name>_event_model`
- `es_<client_name>_event_model`
- `kql_<client_name>_revenue`
- `es_<client_name>_revenue`
- `pos_schema_set_<client_name>`
- `kqs_<client_name>`

## Prerequisites

- Terraform 1.6+
- Azure CLI
- PowerShell
- Access to the target Fabric workspace

Authenticate first:

```powershell
az login --tenant <tenant-id>
```

The helper scripts obtain tokens for:

- `https://api.fabric.microsoft.com`
- `https://kusto.kusto.windows.net`

## What Terraform Creates

Terraform in `infra/terraform` creates:

- client Fabric workspace
- Event Model Eventhouse
- Event Model KQL database
- Event Model Eventstream shell
- Revenue Eventhouse
- Revenue KQL database
- Revenue Eventstream shell

Terraform then runs post-create automation with `null_resource` and `local-exec` for:

- Event Model KQL scripts
- Revenue Model KQL scripts
- shared POS schema set
- Eventstream definition updates
- Queryset definition
- dashboard definitions

## Artifact Layout

- `eventstream/es_event_model.definition.json`: templated Event Model Eventstream
- `eventstream/es_revenue.definition.json`: templated Revenue Eventstream
- `eventstream/pos_schema_set.definition.json`: templated shared schema set
- `kql/01_create_store_events_raw.kql`: Event Model raw table
- `kql/02_create_traffic_session_enriched_rt.kql`: Event Model enrichment objects
- `kql/03_create_dashboard_functions.kql`: Event Model dashboard functions
- `kql/05_policies.kql`: Event Model policies
- `kql/06_create_pos_events_rt.kql`: Revenue raw table
- `kql/07_create_revenue_functions.kql`: Revenue functions
- `kql/08_revenue_policies.kql`: Revenue policies
- `kql/09_create_store_revenue_5m_mv.kql`: Revenue materialized view
- `kql/kqs_event_model.definition.json`: templated Queryset
- `dashboards/*.definition.json`: templated dashboards
- `../scripts/run_kql.ps1`: executes KQL scripts
- `../scripts/push_eventstream.ps1`: updates Eventstream definitions
- `../scripts/push_definition.ps1`: creates or updates schema sets, dashboards, and queryset items
- `../scripts/deploy.ps1`: optional end-to-end deploy wrapper

## Standard Deployment

Review and apply Terraform first:

```powershell
cd infra/terraform
terraform init
terraform workspace new client_acme
terraform plan -var="client_name=acme" -var="client_display_name=Acme Corp" -var="environment=prod" -var="capacity_id=<cap-id>"
terraform apply -var="client_name=acme" -var="client_display_name=Acme Corp" -var="environment=prod" -var="capacity_id=<cap-id>"
```

Then push the non-Terraformable artifacts:

```powershell
cd ..\scripts
.\deploy.ps1 -ClientName "acme"
```

If you want the wrapper to run Terraform apply as well:

```powershell
cd ..\scripts
.\deploy.ps1 -ClientName "acme" -ClientDisplayName "Acme Corp" -CapacityId <cap-id> -RunTerraformApply
```

## Validation

Use these commands before applying changes:

```powershell
cd infra/terraform
terraform init
terraform validate
terraform plan
```

## Manual Follow-Up

The onboarding template preserves the exported dashboard and KQL logic, but a few areas still need explicit validation per client:

- Dashboard queries are rebound to the new Kusto URIs and database IDs, but the query text itself is preserved from the source workspace. Confirm the target client has the same expected tables and functions.
- `EventSchemaSetDedicatedToEventstream__ea2b690e-780f-42b9-b3e6-ba01721bc3aa.definition.json` is retained as an archival export only. The reusable flow uses `pos_schema_set_<client_name>` instead.
- Dashboards, querysets, and schema sets are pushed through REST calls and are not tracked as native Terraform resources, so teardown is not fully automated at item granularity.
- The workspace is now created by Terraform. Capacity assignment is handled directly through `fabric_workspace.capacity_id`.

## Teardown Caveat

`terraform destroy` removes the Terraform-managed Eventhouse, KQL database, and Eventstream resources. Script-created or script-updated items may require separate cleanup if the workspace lifecycle does not remove them implicitly.

## Source Control Hygiene

Ignore local Terraform state and plan artifacts:

- `.terraform/`
- `*.tfstate`
- `*.tfstate.*`
- `*.tfplan`

Do not commit tokens, secrets, or tenant-specific sensitive values.
