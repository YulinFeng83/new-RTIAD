locals {
	event_model_eventhouse_name   = "kql_${var.client_name}_event_model"
	event_model_database_name     = "kql_${var.client_name}_event_model"
	event_model_eventstream_name  = "es_${var.client_name}_event_model"
	revenue_eventhouse_name       = "kql_${var.client_name}_revenue"
	revenue_database_name         = "kql_${var.client_name}_revenue"
	revenue_eventstream_name      = "es_${var.client_name}_revenue"
	shared_pos_schema_set_name    = "pos_schema_set_${var.client_name}"
	queryset_name                 = "kqs_${var.client_name}"
	storemonitor_dashboard_name   = "StoreMonitor"
	officecam_dashboard_name      = "Office-Cam"
	pos_traffic_dashboard_name    = "POS & Traffic RT Dash"

	scripts_dir = "${path.module}/../scripts"
	fabric_dir  = "${path.module}/../fabric"
	kql_dir     = "${path.module}/../fabric/kql"
	eventstream_dir = "${path.module}/../fabric/eventstream"
	dashboards_dir  = "${path.module}/../fabric/dashboards"

	event_model_table_script       = "${local.kql_dir}/01_create_store_events_raw.kql"
	event_model_enriched_script    = "${local.kql_dir}/02_create_traffic_session_enriched_rt.kql"
	event_model_dashboards_script  = "${local.kql_dir}/03_create_dashboard_functions.kql"
	event_model_policies_script    = "${local.kql_dir}/05_policies.kql"
	revenue_table_script           = "${local.kql_dir}/06_create_pos_events_rt.kql"
	revenue_functions_script       = "${local.kql_dir}/07_create_revenue_functions.kql"
	revenue_policies_script        = "${local.kql_dir}/08_revenue_policies.kql"
	revenue_mv_script              = "${local.kql_dir}/09_create_store_revenue_5m_mv.kql"

	event_model_template_path      = "${local.eventstream_dir}/es_event_model.definition.json"
	revenue_template_path          = "${local.eventstream_dir}/es_revenue.definition.json"
	pos_schema_set_template_path   = "${local.eventstream_dir}/pos_schema_set.definition.json"
	queryset_template_path         = "${local.kql_dir}/kqs_event_model.definition.json"
	storemonitor_template_path     = "${local.dashboards_dir}/StoreMonitor.definition.json"
	officecam_template_path        = "${local.dashboards_dir}/Office-Cam.definition.json"
	pos_traffic_template_path      = "${local.dashboards_dir}/POS & Traffic RT Dash.definition.json"
}

resource "fabric_workspace" "client" {
	display_name = "${var.client_display_name} - Analytics"
	description  = "Fabric analytics workspace for ${var.client_display_name}"
	capacity_id  = var.capacity_id
}

resource "fabric_eventhouse" "event_model" {
	workspace_id              = fabric_workspace.client.id
	display_name              = local.event_model_eventhouse_name
	description               = "${var.client_display_name} Event Model (${var.environment})"
	definition_update_enabled = true
}

resource "fabric_kql_database" "event_model" {
	workspace_id = fabric_workspace.client.id
	display_name = local.event_model_database_name
	description  = "${var.client_display_name} Event Model (${var.environment})"

	configuration = {
		database_type = "ReadWrite"
		eventhouse_id = fabric_eventhouse.event_model.id
	}
}

resource "fabric_eventstream" "event_model" {
	workspace_id              = fabric_workspace.client.id
	display_name              = local.event_model_eventstream_name
	description               = "${var.client_display_name} Event Model Stream (${var.environment})"
	definition_update_enabled = true
}

resource "fabric_eventhouse" "revenue" {
	workspace_id              = fabric_workspace.client.id
	display_name              = local.revenue_eventhouse_name
	description               = "${var.client_display_name} Revenue Model (${var.environment})"
	definition_update_enabled = true
}

resource "fabric_kql_database" "revenue" {
	workspace_id = fabric_workspace.client.id
	display_name = local.revenue_database_name
	description  = "${var.client_display_name} Revenue Model (${var.environment})"

	configuration = {
		database_type = "ReadWrite"
		eventhouse_id = fabric_eventhouse.revenue.id
	}
}

resource "fabric_eventstream" "revenue" {
	workspace_id              = fabric_workspace.client.id
	display_name              = local.revenue_eventstream_name
	description               = "${var.client_display_name} Revenue Model Stream (${var.environment})"
	definition_update_enabled = true
}

resource "null_resource" "event_model_table" {
	depends_on = [fabric_kql_database.event_model]

	triggers = {
		script_hash = filesha256(local.event_model_table_script)
		kusto_uri   = tostring(try(fabric_eventhouse.event_model.properties["query_service_uri"], ""))
		database    = local.event_model_database_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/run_kql.ps1' `
			  -KustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -Database '${local.event_model_database_name}' `
			  -ScriptPath '${local.event_model_table_script}'
		EOT
	}
}

resource "null_resource" "event_model_enriched" {
	depends_on = [null_resource.event_model_table]

	triggers = {
		script_hash = filesha256(local.event_model_enriched_script)
		kusto_uri   = tostring(try(fabric_eventhouse.event_model.properties["query_service_uri"], ""))
		database    = local.event_model_database_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/run_kql.ps1' `
			  -KustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -Database '${local.event_model_database_name}' `
			  -ScriptPath '${local.event_model_enriched_script}'
		EOT
	}
}

resource "null_resource" "event_model_dashboard_functions" {
	depends_on = [null_resource.event_model_enriched]

	triggers = {
		script_hash = filesha256(local.event_model_dashboards_script)
		kusto_uri   = tostring(try(fabric_eventhouse.event_model.properties["query_service_uri"], ""))
		database    = local.event_model_database_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/run_kql.ps1' `
			  -KustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -Database '${local.event_model_database_name}' `
			  -ScriptPath '${local.event_model_dashboards_script}'
		EOT
	}
}

resource "null_resource" "event_model_policies" {
	depends_on = [null_resource.event_model_dashboard_functions]

	triggers = {
		script_hash = filesha256(local.event_model_policies_script)
		kusto_uri   = tostring(try(fabric_eventhouse.event_model.properties["query_service_uri"], ""))
		database    = local.event_model_database_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/run_kql.ps1' `
			  -KustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -Database '${local.event_model_database_name}' `
			  -ScriptPath '${local.event_model_policies_script}'
		EOT
	}
}

resource "null_resource" "revenue_table" {
	depends_on = [fabric_kql_database.revenue]

	triggers = {
		script_hash = filesha256(local.revenue_table_script)
		kusto_uri   = tostring(try(fabric_eventhouse.revenue.properties["query_service_uri"], ""))
		database    = local.revenue_database_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/run_kql.ps1' `
			  -KustoUri '${fabric_eventhouse.revenue.properties["query_service_uri"]}' `
			  -Database '${local.revenue_database_name}' `
			  -ScriptPath '${local.revenue_table_script}'
		EOT
	}
}

resource "null_resource" "revenue_materialized_view" {
	depends_on = [null_resource.revenue_table]

	triggers = {
		script_hash = filesha256(local.revenue_mv_script)
		kusto_uri   = tostring(try(fabric_eventhouse.revenue.properties["query_service_uri"], ""))
		database    = local.revenue_database_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/run_kql.ps1' `
			  -KustoUri '${fabric_eventhouse.revenue.properties["query_service_uri"]}' `
			  -Database '${local.revenue_database_name}' `
			  -ScriptPath '${local.revenue_mv_script}'
		EOT
	}
}

resource "null_resource" "revenue_functions" {
	depends_on = [null_resource.revenue_materialized_view]

	triggers = {
		script_hash = filesha256(local.revenue_functions_script)
		kusto_uri   = tostring(try(fabric_eventhouse.revenue.properties["query_service_uri"], ""))
		database    = local.revenue_database_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/run_kql.ps1' `
			  -KustoUri '${fabric_eventhouse.revenue.properties["query_service_uri"]}' `
			  -Database '${local.revenue_database_name}' `
			  -ScriptPath '${local.revenue_functions_script}'
		EOT
	}
}

resource "null_resource" "revenue_policies" {
	depends_on = [null_resource.revenue_functions]

	triggers = {
		script_hash = filesha256(local.revenue_policies_script)
		kusto_uri   = tostring(try(fabric_eventhouse.revenue.properties["query_service_uri"], ""))
		database    = local.revenue_database_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/run_kql.ps1' `
			  -KustoUri '${fabric_eventhouse.revenue.properties["query_service_uri"]}' `
			  -Database '${local.revenue_database_name}' `
			  -ScriptPath '${local.revenue_policies_script}'
		EOT
	}
}

resource "null_resource" "shared_pos_schema_set" {
	triggers = {
		template_hash = filesha256(local.pos_schema_set_template_path)
		workspace_id  = fabric_workspace.client.id
		display_name  = local.shared_pos_schema_set_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/push_definition.ps1' `
			  -WorkspaceId '${fabric_workspace.client.id}' `
			  -ItemType 'EventSchemaSet' `
			  -DisplayName '${local.shared_pos_schema_set_name}' `
			  -TemplatePath '${local.pos_schema_set_template_path}' `
			  -ClientName '${var.client_name}' `
			  -ClientDisplayName '${var.client_display_name}' `
			  -Environment '${var.environment}'
		EOT
	}
}

resource "null_resource" "event_model_definition" {
	depends_on = [fabric_eventstream.event_model, null_resource.event_model_policies]

	triggers = {
		template_hash    = filesha256(local.event_model_template_path)
		workspace_id     = fabric_workspace.client.id
		eventstream_id   = fabric_eventstream.event_model.id
		kql_database_id  = fabric_kql_database.event_model.id
		database_name    = local.event_model_database_name
		display_name     = local.event_model_eventstream_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/push_eventstream.ps1' `
			  -WorkspaceId '${fabric_workspace.client.id}' `
			  -ItemId '${fabric_eventstream.event_model.id}' `
			  -TemplatePath '${local.event_model_template_path}' `
			  -DisplayName '${local.event_model_eventstream_name}' `
			  -KqlDatabaseId '${fabric_kql_database.event_model.id}' `
			  -KqlDatabaseName '${local.event_model_database_name}' `
			  -ClientName '${var.client_name}' `
			  -ClientDisplayName '${var.client_display_name}' `
			  -Environment '${var.environment}'
		EOT
	}
}

resource "null_resource" "revenue_definition" {
	depends_on = [fabric_eventstream.revenue, null_resource.revenue_policies, null_resource.shared_pos_schema_set]

	triggers = {
		template_hash      = filesha256(local.revenue_template_path)
		workspace_id       = fabric_workspace.client.id
		eventstream_id     = fabric_eventstream.revenue.id
		kql_database_id    = fabric_kql_database.revenue.id
		database_name      = local.revenue_database_name
		display_name       = local.revenue_eventstream_name
		schema_set_name    = local.shared_pos_schema_set_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/push_eventstream.ps1' `
			  -WorkspaceId '${fabric_workspace.client.id}' `
			  -ItemId '${fabric_eventstream.revenue.id}' `
			  -TemplatePath '${local.revenue_template_path}' `
			  -DisplayName '${local.revenue_eventstream_name}' `
			  -KqlDatabaseId '${fabric_kql_database.revenue.id}' `
			  -KqlDatabaseName '${local.revenue_database_name}' `
			  -SharedSchemaSetDisplayName '${local.shared_pos_schema_set_name}' `
			  -ClientName '${var.client_name}' `
			  -ClientDisplayName '${var.client_display_name}' `
			  -Environment '${var.environment}'
		EOT
	}
}

resource "null_resource" "queryset" {
	depends_on = [null_resource.event_model_policies]

	triggers = {
		template_hash   = filesha256(local.queryset_template_path)
		workspace_id    = fabric_workspace.client.id
		display_name    = local.queryset_name
		kusto_uri       = tostring(try(fabric_eventhouse.event_model.properties["query_service_uri"], ""))
		kql_database_id = fabric_kql_database.event_model.id
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/push_definition.ps1' `
			  -WorkspaceId '${fabric_workspace.client.id}' `
			  -ItemType 'KQLQueryset' `
			  -DisplayName '${local.queryset_name}' `
			  -TemplatePath '${local.queryset_template_path}' `
			  -EventModelKustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -EventModelDatabaseId '${fabric_kql_database.event_model.id}' `
			  -EventModelDatabaseName '${local.event_model_database_name}' `
			  -ClientName '${var.client_name}' `
			  -ClientDisplayName '${var.client_display_name}' `
			  -Environment '${var.environment}'
		EOT
	}
}

resource "null_resource" "storemonitor_dashboard" {
	depends_on = [null_resource.event_model_policies, null_resource.revenue_policies]

	triggers = {
		template_hash = filesha256(local.storemonitor_template_path)
		workspace_id  = fabric_workspace.client.id
		display_name  = local.storemonitor_dashboard_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/push_definition.ps1' `
			  -WorkspaceId '${fabric_workspace.client.id}' `
			  -ItemType 'KQLDashboard' `
			  -DisplayName '${local.storemonitor_dashboard_name}' `
			  -TemplatePath '${local.storemonitor_template_path}' `
			  -DashboardPrimaryKustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -DashboardPrimaryDatabaseId '${fabric_kql_database.event_model.id}' `
			  -DashboardPrimaryDatabaseName '${local.event_model_database_name}' `
			  -EventModelKustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -EventModelDatabaseId '${fabric_kql_database.event_model.id}' `
			  -EventModelDatabaseName '${local.event_model_database_name}' `
			  -RevenueKustoUri '${fabric_eventhouse.revenue.properties["query_service_uri"]}' `
			  -RevenueDatabaseId '${fabric_kql_database.revenue.id}' `
			  -RevenueDatabaseName '${local.revenue_database_name}' `
			  -ClientName '${var.client_name}' `
			  -ClientDisplayName '${var.client_display_name}' `
			  -Environment '${var.environment}'
		EOT
	}
}

resource "null_resource" "officecam_dashboard" {
	depends_on = [null_resource.event_model_policies]

	triggers = {
		template_hash = filesha256(local.officecam_template_path)
		workspace_id  = fabric_workspace.client.id
		display_name  = local.officecam_dashboard_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/push_definition.ps1' `
			  -WorkspaceId '${fabric_workspace.client.id}' `
			  -ItemType 'KQLDashboard' `
			  -DisplayName '${local.officecam_dashboard_name}' `
			  -TemplatePath '${local.officecam_template_path}' `
			  -DashboardPrimaryKustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -DashboardPrimaryDatabaseId '${fabric_kql_database.event_model.id}' `
			  -DashboardPrimaryDatabaseName '${local.event_model_database_name}' `
			  -EventModelKustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -EventModelDatabaseId '${fabric_kql_database.event_model.id}' `
			  -EventModelDatabaseName '${local.event_model_database_name}' `
			  -ClientName '${var.client_name}' `
			  -ClientDisplayName '${var.client_display_name}' `
			  -Environment '${var.environment}'
		EOT
	}
}

resource "null_resource" "pos_traffic_dashboard" {
	depends_on = [null_resource.event_model_policies, null_resource.revenue_policies]

	triggers = {
		template_hash = filesha256(local.pos_traffic_template_path)
		workspace_id  = fabric_workspace.client.id
		display_name  = local.pos_traffic_dashboard_name
	}

	provisioner "local-exec" {
		interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
		command     = <<-EOT
			& '${local.scripts_dir}/push_definition.ps1' `
			  -WorkspaceId '${fabric_workspace.client.id}' `
			  -ItemType 'KQLDashboard' `
			  -DisplayName '${local.pos_traffic_dashboard_name}' `
			  -TemplatePath '${local.pos_traffic_template_path}' `
			  -DashboardPrimaryKustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -DashboardPrimaryDatabaseId '${fabric_kql_database.event_model.id}' `
			  -DashboardPrimaryDatabaseName '${local.event_model_database_name}' `
			  -EventModelKustoUri '${fabric_eventhouse.event_model.properties["query_service_uri"]}' `
			  -EventModelDatabaseId '${fabric_kql_database.event_model.id}' `
			  -EventModelDatabaseName '${local.event_model_database_name}' `
			  -RevenueKustoUri '${fabric_eventhouse.revenue.properties["query_service_uri"]}' `
			  -RevenueDatabaseId '${fabric_kql_database.revenue.id}' `
			  -RevenueDatabaseName '${local.revenue_database_name}' `
			  -ClientName '${var.client_name}' `
			  -ClientDisplayName '${var.client_display_name}' `
			  -Environment '${var.environment}'
		EOT
	}
}
