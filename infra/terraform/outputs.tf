output "workspace_id" {
	description = "Created Fabric workspace ID for this client"
	value       = fabric_workspace.client.id
}

output "event_model_eventhouse_id" {
	description = "Event Model Eventhouse ID"
	value       = fabric_eventhouse.event_model.id
}

output "event_model_kql_database_id" {
	description = "Event Model KQL database ID"
	value       = fabric_kql_database.event_model.id
}

output "event_model_eventstream_id" {
	description = "Event Model Eventstream ID"
	value       = fabric_eventstream.event_model.id
}

output "event_model_kusto_uri" {
	description = "Event Model Kusto query service URI"
	value       = try(fabric_eventhouse.event_model.properties["query_service_uri"], null)
}

output "revenue_eventhouse_id" {
	description = "Revenue Eventhouse ID"
	value       = fabric_eventhouse.revenue.id
}

output "revenue_kql_database_id" {
	description = "Revenue KQL database ID"
	value       = fabric_kql_database.revenue.id
}

output "revenue_eventstream_id" {
	description = "Revenue Eventstream ID"
	value       = fabric_eventstream.revenue.id
}

output "revenue_kusto_uri" {
	description = "Revenue Kusto query service URI"
	value       = try(fabric_eventhouse.revenue.properties["query_service_uri"], null)
}
