Current Architecture Analysis
Pattern: Hub-and-Spoke Multi-Agent Orchestration with Request/Response Key Characteristics:
Synchronous workflow - Agents process sequentially through 15 states
In-memory orchestration - State held in active_requests dict
Direct SQL execution - Query FHIR data on-demand during extraction
Tight coupling - Orchestrator knows all agents and routing rules
No event sourcing - State transitions not permanently logged as events
Critical Architectural Questions
1. Should you implement Lambda/Kappa Architecture for FHIR persistence?
YES - This is a fundamental gap. Here's why: Current Problem:
# extraction_agent.py line 56 - Queries CDW directly each time
cohort = await self._execute_phenotype_query(phenotype_sql)
Issues:
[ ] FHIR server queried repeatedly for same data
[ ] No caching layer for frequently accessed resources
[ ] Cannot handle FHIR server downtime
[ ] Poor performance for large cohorts (N+1 query problem)
[ ] No historical versioning (can't re-run old queries)
[ ] Violates eventual consistency principles
2. Recommended Architecture: Event-Sourced Lambda with FHIR Materialized Views
Here's a better architecture:

 STREAM INGESTION LAYER 
 (Kappa/Lambda - Real-time + Batch FHIR ingestion) 

 EVENT STORE (Immutable Log) 
 - All FHIR resource changes (create/update/delete) 
 - Agent state transitions 
 - Request lifecycle events 
 Tech: Kafka, EventStore, Postgres event table 

 BATCH VIEW REAL-TIME VIEW 
 (Lambda Layer) (Speed Layer) 

 - SQL-on-FHIR v2 - In-memory cache 
 - Materialized - Recent updates 
 ViewDefinitions 
 - Optimized for - Optimized for 
 analytics latency 

 QUERY LAYER 
 (Serving Layer) 

 - Merge batch + 
 real-time views 
 - Agent queries 
 execute here 

 AGENT LAYER 
 (Reactive/Async) 

 - Event-driven 
 - Parallel exec 
 - Saga pattern 

Alternative Architectural Patterns
Option 1: Event-Sourced CQRS with Saga Orchestration RECOMMENDED
Pattern:
Commands (Write) → Event Store → Projections (Read Models) ← Queries
 ↓
 Event Handlers → Agent Tasks (Sagas)
Benefits:
[x] Complete audit trail (event sourcing)
[x] Replay workflows for debugging
[x] Parallel agent execution (event-driven)
[x] Temporal consistency (event timestamps)
[x] Easy to add new agents (subscribe to events)
[x] Resilience (events persist, can retry)
Implementation:
# Events
class RequirementsGathered(Event):
 request_id: str
 requirements: dict
 timestamp: datetime

class FeasibilityValidated(Event):
 request_id: str
 feasible: bool
 cohort_size: int
 phenotype_sql: str

# Saga Coordinator (replaces Orchestrator)
class ResearchRequestSaga:
 async def on_requirements_gathered(self, event: RequirementsGathered):
 # Trigger phenotype validation
 await self.event_bus.publish(
 ValidateFeasibilityCommand(
 request_id=event.request_id,
 requirements=event.requirements
 )
 )

 async def on_feasibility_validated(self, event: FeasibilityValidated):
 if event.feasible:
 # Trigger parallel agents
 await asyncio.gather(
 self.event_bus.publish(ScheduleKickoffCommand(...)),
 self.event_bus.publish(PrepareExtractionCommand(...))
 )
File Changes:
Replace orchestrator.py with event-driven saga coordinator
Add event store (append-only log)
Convert agents to event handlers
Add projections for read models
Option 2: Lambda Architecture with FHIR Data Lake RECOMMENDED FOR DATA
Pattern:
FHIR Server → Ingestion Pipeline → Data Lake (Parquet/Delta Lake)
 ↓
 SQL-on-FHIR Views
 ↓
 Agent Queries
Implementation:
# Batch Layer: Nightly FHIR ingestion
class FHIRBatchIngestion:
 async def ingest_all_resources(self):
 """Full snapshot of FHIR data"""
 for resource_type in ['Patient', 'Condition', 'Observation']:
 resources = await fhir_client.search(resource_type, max_results=100000)
 # Write to Parquet with partitioning
 df = pd.DataFrame(resources)
 df.to_parquet(
 f's3://fhir-lake/{resource_type}/date={date.today()}.parquet',
 partition_cols=['lastUpdated']
 )

# Speed Layer: Real-time updates via FHIR subscription
class FHIRSpeedLayer:
 async def on_fhir_notification(self, resource: dict):
 """Handle real-time FHIR resource updates"""
 # Update in-memory cache
 self.cache.set(f"{resource['resourceType']}/{resource['id']}", resource)
 # Publish event for dependent views
 await self.event_bus.publish(ResourceUpdated(resource))

# Serving Layer: Merge batch + speed
class FHIRServingLayer:
 async def query_patients(self, criteria: dict):
 # Query batch view (Parquet files)
 batch_results = duckdb.query("""
 SELECT * FROM read_parquet('s3://fhir-lake/Patient/*.parquet')
 WHERE birthDate > '1980-01-01'
 """)

 # Merge with speed layer (recent updates)
 recent_updates = self.speed_layer.get_recent('Patient', since=yesterday)

 return merge_deduplicate(batch_results, recent_updates)
Benefits:
[x] Massive performance improvement - Pre-computed views
[x] Cost reduction - Query S3/Delta Lake instead of FHIR server
[x] Historical analysis - Time-travel queries
[x] Scalability - Handle millions of patients
[x] Fault tolerance - FHIR server downtime doesn't block queries
Option 3: Microservice Event Mesh (Kafka/RabbitMQ)
Pattern:
Agent Services ←→ Message Broker ←→ Event Store
 ↕
 FHIR Data Service
Benefits:
[x] True decoupling - Agents don't know about each other
[x] Scalability - Run multiple agent instances
[x] Resilience - Messages persist in broker
WARNING: Complexity - Requires Kafka/RabbitMQ infrastructure
Option 4: Workflow as Code (Temporal/Airflow)
Pattern:
# Using Temporal.io
@workflow.defn
class ResearchRequestWorkflow:
 @workflow.run
 async def run(self, request: ResearchRequest):
 # Step 1: Requirements
 requirements = await workflow.execute_activity(
 gather_requirements,
 request,
 start_to_close_timeout=timedelta(hours=24)
 )

 # Step 2: Feasibility
 feasibility = await workflow.execute_activity(
 validate_feasibility,
 requirements
 )

 if not feasibility.feasible:
 return "Not feasible"

 # Step 3: Parallel execution
 extraction, kickoff = await asyncio.gather(
 workflow.execute_activity(extract_data, ...),
 workflow.execute_activity(schedule_kickoff, ...)
 )
Benefits:
[x] Built-in retry/compensation
[x] Workflow versioning
[x] Distributed execution
[x] UI for monitoring
WARNING: Requires Temporal/Airflow infrastructure
Concrete Recommendations
Phase 1: Add Lambda Architecture for FHIR Data (4-6 weeks)
Why: Current architecture queries FHIR server on every request. This is slow, expensive, and fragile. Implementation:
Batch Layer: Nightly FHIR ingestion to Parquet/Delta Lake
Use DuckDB or Spark for SQL-on-FHIR view materialization
Store in S3/Azure Blob/local file system
Speed Layer: Cache recent FHIR updates
Redis/Memcached for hot data
Update on FHIR Subscription notifications
Serving Layer: Merge batch + speed
Update SQLonFHIRAdapter to query merged view
Add cache-aside pattern
Files to modify:
app/adapters/sql_on_fhir.py - Add data lake querying
Create app/ingestion/fhir_batch_ingestion.py
Create app/ingestion/fhir_speed_layer.py
Phase 2: Add Event Sourcing for Workflow State (3-4 weeks)
Why: Current in-memory state (active_requests dict) is lost on restart. No audit trail. Implementation:
Event Store: Append-only log of all state transitions
CREATE TABLE events (
 event_id SERIAL PRIMARY KEY,
 aggregate_id VARCHAR(255), -- request_id
 event_type VARCHAR(100), -- RequirementsGathered, FeasibilityValidated
 event_data JSONB,
 timestamp TIMESTAMPTZ,
 version INT
);
Projections: Rebuild current state from events
ResearchRequest table = projection of event stream
Can replay events for debugging
Update Orchestrator:
Publish events instead of direct state mutation
Agents subscribe to events
Files to modify:
app/orchestrator/orchestrator.py - Publish events
Create app/events/event_store.py
Create app/events/projections.py
Phase 3: Migrate to Reactive Agents (6-8 weeks)
Why: Current synchronous workflow blocks on each agent. Parallel execution needed. Implementation:
Event Bus: Kafka/RabbitMQ or in-process event dispatcher
Reactive Agents: Subscribe to events, publish results
Saga Coordinator: Orchestrates multi-agent workflows
Files to modify:
app/agents/base_agent.py - Add event handlers
Replace orchestrator.py with saga coordinator
Add event bus infrastructure
Immediate Action Items
Add FHIR data caching (1 week) - Low-hanging fruit
# In sql_on_fhir.py
@lru_cache(maxsize=1000)
async def execute_sql(self, sql: str):
 # Cache query results
Implement event logging (1 week) - Foundation for event sourcing
# Log all state transitions to database
await self.event_log.append(
 RequestStateChanged(request_id, old_state, new_state)
)
Prototype Lambda architecture (2 weeks) - Test feasibility
Ingest 1000 FHIR patients to Parquet
Create ViewDefinition over Parquet
Benchmark query performance vs. direct FHIR
Add async agent execution (2 weeks) - Improve performance
# Allow parallel agent execution where possible
await asyncio.gather(
 calendar_agent.schedule_kickoff(...),
 extraction_agent.prepare_extraction(...)
)
Would you like me to create a detailed implementation plan for any of these options? I can also create a proof-of-concept for the Lambda architecture with FHIR data materialization.