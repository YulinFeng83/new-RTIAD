Eventstream inventory

Workspace ID:
846cf29f-843c-4f77-b85c-3e10b32d4b59

Eventstream:
- name: es_event_model
- id: e44f79f1-1cad-4e5d-86e4-379914bdfabb
- state: live/published
- transforms: none visible

Source:
- name: CustomEndpoint-Source
- type: Custom endpoint
- status: Active
- protocols: Event Hub, AMQP, Kafka
- auth modes visible: Entra ID Authentication, SAS Key Authentication

Destination:
- display name: eventmodel-eventhouse
- type: Eventhouse
- status: Active
- related Kusto item: kql_event_model
- destination table: store_events_raw
