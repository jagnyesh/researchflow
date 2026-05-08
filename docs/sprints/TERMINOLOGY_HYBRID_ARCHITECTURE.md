# Terminology Service: Hybrid Architecture Plan

**Date**: October 31, 2025
**Status**: Planning
**Priority**: High
**Estimated Effort**: 2-4 weeks
**Sprint**: Sprint 7 (Future)

---

## Executive Summary

This document outlines a hybrid architecture for medical terminology management in ResearchFlow, transitioning from hardcoded condition mappings to an industry-standard, scalable terminology service.

**Problem**: Current system uses hardcoded `CONDITION_MAPPINGS` dictionary with only 6 conditions. Queries for unmapped conditions (e.g., "stress") fail to generate correct SQL WHERE clauses.

**Solution**: Implement hybrid terminology service combining:
- **Local cache** (Redis) - 10ms response
- **Database tables** (PostgreSQL) - 50ms response
- **FHIR Terminology Server** (NLM/external API) - 500ms response

**Benefits**: 400,000+ conditions supported, always up-to-date codes, FHIR-compliant, graceful degradation

---

## Current State Analysis

### What We Have Today

**File**: `app/services/query_interpreter.py`
**Lines**: 81-88

```python
CONDITION_MAPPINGS = {
    "type 2 diabetes": {"snomed": "44054006", "icd10": "E11.9", "icd10_pattern": "E11%"},
    "diabetes": {"snomed": "73211009", "icd10": "E11.9", "icd10_pattern": "E1%"},
    "hypertension": {"snomed": "38341003", "icd10": "I10", "icd10_pattern": "I10%"},
    "high blood pressure": {"snomed": "38341003", "icd10": "I10", "icd10_pattern": "I10%"},
    "hyperlipidemia": {"snomed": "13645005", "icd10": "E78.5", "icd10_pattern": "E78%"},
    "asthma": {"snomed": "195967001", "icd10": "J45.909", "icd10_pattern": "J45%"},
}
```

### Issues with Current Approach

1. **Limited Coverage**: Only 6 conditions mapped
   - Fails for: stress, anxiety, depression, COPD, heart failure, cancer, etc.
   - Researchers will encounter failures frequently

2. **Maintenance Burden**: Manual updates required
   - New ICD-10 codes released annually
   - SNOMED CT updates twice per year
   - No automated update pipeline

3. **Not Industry Standard**: Production clinical systems don't use hardcoded mappings
   - Epic, Cerner, Athena all use terminology servers
   - Fails FHIR interoperability standards

4. **No Cross-Mapping**: Can't translate between coding systems
   - No ICD-10 → SNOMED lookup
   - No synonym resolution ("Type 2 diabetes" vs "NIDDM")

### Temporary Fix (Implemented October 31, 2025)

**Files Modified**:
- `app/services/query_interpreter.py` (lines 215-244)
- `app/sql_on_fhir/join_query_builder.py` (lines 207-236)

**What It Does**:
- Detects when condition is NOT in `CONDITION_MAPPINGS`
- Falls back to text search: `WHERE code_text ILIKE '%stress%'`
- Logs warning for tracking unmapped conditions

**Pros**:
- ✅ Fixes "stress" query immediately
- ✅ No breaking changes to existing queries
- ✅ Minimal code change (30 lines)

**Cons**:
- ❌ Less accurate (false positives possible)
- ❌ Not scalable (text search is slow on large datasets)
- ❌ Still not industry standard

**Conclusion**: Temporary fix is acceptable for MVP, but hybrid architecture needed for production.

---

## Industry Standards Research

### 1. FHIR Terminology Server

**What It Is**:
- HL7 FHIR specification for terminology services
- RESTful API for code lookups, validation, expansion, translation
- Supports SNOMED CT, ICD-10, LOINC, RxNorm, and 100+ vocabularies

**Standard Operations** (FHIR R4):
```
GET [base]/CodeSystem/$lookup?system=http://snomed.info/sct&code=44054006
→ Returns: {"display": "Type 2 diabetes mellitus", ...}

GET [base]/ValueSet/$expand?url=http://hl7.org/fhir/ValueSet/condition-code
→ Returns: All condition codes in the value set

POST [base]/ConceptMap/$translate
→ Translates code from one system to another (e.g., ICD-10 → SNOMED)

GET [base]/ValueSet/$validate-code?system=...&code=...
→ Checks if code is valid in a value set
```

**Public FHIR Terminology Servers**:
- **NLM** (Free): `https://tx.fhir.org/r4` - U.S. National Library of Medicine
- **Ontoserver** (Open source): `https://r4.ontoserver.csiro.au`
- **TerminologyHub** (Commercial): `https://www.terminologyhub.com/`

**Production Examples**:
- **Epic**: Uses internal FHIR Terminology Server for all code lookups
- **Cerner**: Millennium Terminology Server (HL7 compliant)
- **Athena**: Standardized Vocabularies API

**Benefits**:
- ✅ Always current (automatic updates from upstream sources)
- ✅ FHIR-compliant (interoperability)
- ✅ Handles 400,000+ SNOMED CT concepts
- ✅ Cross-mapping built-in (ICD-10 ↔ SNOMED ↔ LOINC)
- ✅ Versioning support (audit trail)

**Challenges**:
- ❌ 200-500ms latency (external API call)
- ❌ Licensing (SNOMED CT requires membership, ~$5k/year)
- ❌ Rate limits (free tiers limit requests)

---

### 2. UMLS (Unified Medical Language System)

**What It Is**:
- Metathesaurus from U.S. National Library of Medicine
- Integrates 200+ vocabularies into unified system
- Provides REST API for lookups

**Key Features**:
- **Cross-Mapping**: Automatically links SNOMED ↔ ICD-10 ↔ LOINC ↔ RxNorm
- **Synonym Resolution**: "Type 2 diabetes" = "diabetes mellitus type 2" = "NIDDM"
- **Semantic Network**: Understands relationships (e.g., "metformin" IS-A "hypoglycemic agent")

**API Example**:
```bash
# Search for concept
GET https://uts-ws.nlm.nih.gov/rest/search/current?string=stress

# Get concept details
GET https://uts-ws.nlm.nih.gov/rest/content/current/CUI/C0038435

# Get atoms (all synonyms)
GET https://uts-ws.nlm.nih.gov/rest/content/current/CUI/C0038435/atoms
```

**Licensing**:
- Free for research use with UMLS account
- Requires annual license renewal
- SNOMED CT requires separate membership

**When to Use**:
- ✅ Need cross-mapping between vocabularies
- ✅ Need synonym resolution
- ✅ Need semantic relationships

**When NOT to Use**:
- ❌ Need real-time lookups (500ms+ latency)
- ❌ Need latest codes (UMLS releases quarterly)
- ❌ High-volume production (rate limits)

---

### 3. Database-Backed Terminology Tables

**What Production Systems Do**:

**Architecture** (Columbia-Presbyterian Medical Center, 1995 - still relevant today):
- Medical Entities Dictionary (MED) - centralized terminology database
- Optimized for high-volume production use (10,000+ lookups/sec)
- Supports local extensions and institution-specific codes

**Modern Schema Example**:
```sql
CREATE TABLE terminology.snomed_ct (
    concept_id BIGINT PRIMARY KEY,
    term TEXT NOT NULL,
    fsn TEXT,  -- Fully Specified Name
    semantic_tag TEXT,
    is_active BOOLEAN,
    effective_date DATE
);

CREATE INDEX idx_snomed_term_trgm
ON terminology.snomed_ct
USING gin (term gin_trgm_ops);  -- Fuzzy text search

CREATE TABLE terminology.snomed_icd10_map (
    snomed_code BIGINT REFERENCES terminology.snomed_ct(concept_id),
    icd10_code TEXT,
    map_priority INT,
    map_rule TEXT
);

-- Example query
SELECT s.concept_id, s.term, m.icd10_code
FROM terminology.snomed_ct s
LEFT JOIN terminology.snomed_icd10_map m ON s.concept_id = m.snomed_code
WHERE s.term ILIKE '%diabetes%'
LIMIT 10;
```

**Data Sources**:
- **SNOMED CT**: Download RF2 release files (requires NLM membership)
- **ICD-10-CM**: Free from CDC
- **LOINC**: Free from Regenstrief Institute
- **RxNorm**: Free from NLM

**Loading Process**:
```bash
# 1. Download SNOMED CT RF2 release (annual)
wget https://download.nlm.nih.gov/umls/snomed/snomedct-xxx.zip

# 2. Parse RF2 files and load into PostgreSQL
python scripts/load_snomed_ct.py

# 3. Create indexes
psql -f scripts/create_indexes.sql

# 4. Load ICD-10 mapping
python scripts/load_icd10_mapping.py
```

**Benefits**:
- ✅ Fast (50ms lookup with indexes)
- ✅ No external dependencies
- ✅ Full control over data
- ✅ Supports local extensions

**Challenges**:
- ❌ Initial setup effort (loading SNOMED CT: ~4 hours)
- ❌ Quarterly updates needed (manual pipeline)
- ❌ Storage requirements (~2 GB for SNOMED CT)
- ❌ Licensing (SNOMED CT membership)

**When to Use**:
- ✅ Need sub-100ms response times
- ✅ High query volume (>1000/sec)
- ✅ Need offline capability

---

## Hybrid Architecture (Recommended)

### Overview

**Three-Tier Lookup**:
```
User Query ("stress")
    ↓
┌─────────────────────────────────────────┐
│ 1. Redis Cache (10ms)                  │ ← Hot path (95% of queries)
│    - Top 1000 conditions                │
│    - TTL: 24 hours                      │
└─────────────────────────────────────────┘
    ↓ (cache miss)
┌─────────────────────────────────────────┐
│ 2. PostgreSQL Tables (50ms)             │ ← Warm path (4% of queries)
│    - 400,000+ SNOMED CT concepts        │
│    - Fuzzy text search                  │
└─────────────────────────────────────────┘
    ↓ (not found or ambiguous)
┌─────────────────────────────────────────┐
│ 3. FHIR Terminology Server (500ms)      │ ← Cold path (1% of queries)
│    - NLM tx.fhir.org                    │
│    - Latest codes + cross-mapping       │
└─────────────────────────────────────────┘
    ↓
Cache result (24 hours)
```

### Performance Characteristics

| Scenario | Cache Hit | DB Hit | API Hit | Response Time |
|----------|-----------|--------|---------|---------------|
| **Common Conditions** (diabetes, hypertension) | ✅ | - | - | 10ms |
| **Moderate Conditions** (heart failure, COPD) | ❌ | ✅ | - | 50ms |
| **Rare Conditions** (Takayasu arteritis) | ❌ | ❌ | ✅ | 500ms |
| **First Query** (any condition) | ❌ | ✅/❌ | Maybe | 50-500ms |
| **Repeat Query** (same condition) | ✅ | - | - | 10ms |

**Expected Distribution**:
- 95% queries hit cache → avg 10ms
- 4% queries hit database → avg 50ms
- 1% queries hit API → avg 500ms
- **Overall average**: 15ms

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1) - 2 days

**Goal**: Create `TerminologyService` class with unified interface

**Tasks**:
1. Create `app/services/terminology_service.py`:
   ```python
   class TerminologyService:
       def __init__(self):
           self.cache = Redis()  # Optional for now
           self.db = None  # Placeholder
           self.fhir_client = None  # Placeholder

       async def resolve_condition(self, term: str) -> Dict:
           """Unified lookup interface"""
           pass

       async def search_conditions(self, term: str, limit: int = 10) -> List[Dict]:
           """Fuzzy search for conditions"""
           pass

       async def get_icd10_for_snomed(self, snomed_code: str) -> Optional[str]:
           """Cross-mapping"""
           pass
   ```

2. Add configuration to `.env`:
   ```bash
   # Terminology Service Configuration
   TERMINOLOGY_DB_ENABLED=false  # Enable when DB is loaded
   TERMINOLOGY_FHIR_ENABLED=false  # Enable when ready
   TERMINOLOGY_CACHE_TTL=86400  # 24 hours
   ```

3. Update `query_interpreter.py` to use `TerminologyService`:
   ```python
   # Replace:
   CONDITION_MAPPINGS = {...}

   # With:
   self.terminology_service = TerminologyService()
   ```

**Deliverables**:
- ✅ `TerminologyService` interface defined
- ✅ Configuration options in `.env`
- ✅ Query interpreter refactored to use service
- ✅ Unit tests for interface

---

### Phase 2: Database-Backed Terminology (Week 2) - 5 days

**Goal**: Load SNOMED CT into PostgreSQL and implement database lookups

**Tasks**:

1. **Obtain SNOMED CT License** (1 day):
   - Register at https://www.nlm.nih.gov/research/umls/Snomed/snomed_main.html
   - Request SNOMED CT US Edition (free for U.S. users)
   - Download RF2 release files (~2 GB)

2. **Create Database Schema** (1 hour):
   ```sql
   -- Create terminology schema
   CREATE SCHEMA IF NOT EXISTS terminology;

   -- SNOMED CT concepts
   CREATE TABLE terminology.snomed_ct (
       concept_id BIGINT PRIMARY KEY,
       term TEXT NOT NULL,
       fsn TEXT,
       semantic_tag TEXT,
       is_active BOOLEAN DEFAULT TRUE,
       effective_date DATE,
       created_at TIMESTAMP DEFAULT NOW()
   );

   -- SNOMED CT descriptions (synonyms)
   CREATE TABLE terminology.snomed_descriptions (
       description_id BIGINT PRIMARY KEY,
       concept_id BIGINT REFERENCES terminology.snomed_ct(concept_id),
       term TEXT NOT NULL,
       type_id BIGINT,  -- 900000000000003001 = FSN, 900000000000013009 = Synonym
       is_active BOOLEAN DEFAULT TRUE
   );

   -- ICD-10-CM mapping
   CREATE TABLE terminology.snomed_icd10_map (
       id SERIAL PRIMARY KEY,
       snomed_code BIGINT REFERENCES terminology.snomed_ct(concept_id),
       icd10_code TEXT NOT NULL,
       icd10_display TEXT,
       map_priority INT DEFAULT 1,
       map_rule TEXT
   );

   -- Indexes for performance
   CREATE INDEX idx_snomed_term_trgm ON terminology.snomed_ct
   USING gin (term gin_trgm_ops);

   CREATE INDEX idx_snomed_descriptions_term ON terminology.snomed_descriptions (term);
   CREATE INDEX idx_snomed_descriptions_concept ON terminology.snomed_descriptions (concept_id);
   CREATE INDEX idx_icd10_snomed ON terminology.snomed_icd10_map (snomed_code);
   ```

3. **Create Loading Scripts** (2 days):
   ```python
   # scripts/terminology/load_snomed_ct.py
   import csv
   from pathlib import Path
   from app.database import engine

   def load_snomed_concepts(rf2_dir: Path):
       """Load SNOMED CT concepts from RF2 files"""
       concepts_file = rf2_dir / "Snapshot" / "Terminology" / "sct2_Concept_Snapshot_US_xxx.txt"

       with open(concepts_file, 'r', encoding='utf-8') as f:
           reader = csv.DictReader(f, delimiter='\t')
           batch = []
           for row in reader:
               if row['active'] == '1':
                   batch.append({
                       'concept_id': int(row['id']),
                       'is_active': True,
                       'effective_date': row['effectiveTime']
                   })

                   if len(batch) >= 10000:
                       # Bulk insert
                       insert_batch(batch)
                       batch = []

   def load_snomed_descriptions(rf2_dir: Path):
       """Load SNOMED CT descriptions (synonyms)"""
       descriptions_file = rf2_dir / "Snapshot" / "Terminology" / "sct2_Description_Snapshot_US_xxx.txt"
       # Similar batch loading

   def load_icd10_mapping(mapping_file: Path):
       """Load SNOMED → ICD-10 mapping"""
       # Load from SNOMED CT ICD-10 map file
   ```

4. **Implement Database Lookups** (1 day):
   ```python
   # app/services/terminology_service.py
   class TerminologyService:
       async def search_conditions(self, term: str, limit: int = 10) -> List[Dict]:
           """Search SNOMED CT conditions by term"""
           query = """
               SELECT
                   s.concept_id,
                   s.term,
                   s.fsn,
                   m.icd10_code,
                   similarity(s.term, $1) as score
               FROM terminology.snomed_ct s
               LEFT JOIN terminology.snomed_icd10_map m ON s.concept_id = m.snomed_code
               WHERE s.semantic_tag = 'disorder'
                 AND s.is_active = true
                 AND s.term ILIKE $2
               ORDER BY score DESC, s.term
               LIMIT $3
           """

           results = await self.db.fetch_all(
               query,
               term,
               f"%{term}%",
               limit
           )

           return [
               {
                   "snomed": str(row['concept_id']),
                   "name": row['term'],
                   "fsn": row['fsn'],
                   "icd10": row['icd10_code'],
                   "confidence": row['score']
               }
               for row in results
           ]
   ```

5. **Testing** (1 day):
   - Test with top 100 conditions from medical literature
   - Verify cross-mapping accuracy
   - Benchmark query performance

**Deliverables**:
- ✅ SNOMED CT loaded into PostgreSQL (~400,000 concepts)
- ✅ ICD-10 cross-mapping functional
- ✅ Database lookups < 50ms (P95)
- ✅ Test coverage >80%

---

### Phase 3: FHIR Terminology Server Integration (Week 3) - 3 days

**Goal**: Integrate with NLM FHIR Terminology Server for long-tail queries

**Tasks**:

1. **Create FHIR Client** (1 day):
   ```python
   # app/services/fhir_terminology_client.py
   import httpx
   from typing import Optional, Dict, List

   class FHIRTerminologyClient:
       def __init__(self, base_url: str = "https://tx.fhir.org/r4"):
           self.base_url = base_url
           self.client = httpx.AsyncClient(timeout=10.0)

       async def lookup_code(
           self,
           system: str,
           code: str
       ) -> Optional[Dict]:
           """
           Lookup a specific code

           Example:
               system="http://snomed.info/sct"
               code="44054006"
           """
           url = f"{self.base_url}/CodeSystem/$lookup"
           params = {
               "system": system,
               "code": code
           }

           response = await self.client.get(url, params=params)
           response.raise_for_status()

           return response.json()

       async def search_code(
           self,
           system: str,
           text: str
       ) -> List[Dict]:
           """
           Search for codes by text

           Example:
               system="http://snomed.info/sct"
               text="diabetes"
           """
           url = f"{self.base_url}/CodeSystem/$search"
           params = {
               "system": system,
               "text": text
           }

           response = await self.client.get(url, params=params)
           response.raise_for_status()

           return response.json().get("expansion", {}).get("contains", [])

       async def validate_code(
           self,
           system: str,
           code: str
       ) -> bool:
           """Check if code is valid"""
           url = f"{self.base_url}/CodeSystem/$validate-code"
           params = {
               "system": system,
               "code": code
           }

           response = await self.client.get(url, params=params)
           return response.json().get("result", False)
   ```

2. **Integrate with TerminologyService** (1 day):
   ```python
   # app/services/terminology_service.py
   class TerminologyService:
       def __init__(self):
           self.cache = Redis() if CACHE_ENABLED else None
           self.db = Database()
           self.fhir_client = FHIRTerminologyClient() if FHIR_ENABLED else None

       async def resolve_condition(self, term: str) -> Dict:
           # 1. Check cache
           if self.cache:
               cached = await self.cache.get(f"condition:{term}")
               if cached:
                   logger.info(f"Cache hit for '{term}'")
                   return json.loads(cached)

           # 2. Check local database
           db_results = await self.search_conditions(term, limit=5)
           if db_results and db_results[0]['confidence'] > 0.8:
               best_match = db_results[0]
               await self._cache_result(term, best_match)
               logger.info(f"Database hit for '{term}'")
               return best_match

           # 3. Call FHIR Terminology Server
           if self.fhir_client:
               try:
                   fhir_results = await self.fhir_client.search_code(
                       system="http://snomed.info/sct",
                       text=term
                   )
                   if fhir_results:
                       best_match = self._parse_fhir_result(fhir_results[0])
                       await self._cache_result(term, best_match)
                       logger.info(f"FHIR API hit for '{term}'")
                       return best_match
               except Exception as e:
                   logger.error(f"FHIR API failed for '{term}': {e}")

           # 4. Fall back to database result (even if low confidence)
           if db_results:
               logger.warning(f"Low-confidence match for '{term}': {db_results[0]}")
               return db_results[0]

           # 5. No results - return None
           logger.error(f"No terminology match found for '{term}'")
           return {"name": term, "snomed": None, "icd10": None}
   ```

3. **Configuration & Testing** (1 day):
   - Add FHIR server URL to `.env`
   - Test with rare conditions (e.g., "Takayasu arteritis")
   - Test fallback behavior when API is down
   - Benchmark end-to-end performance

**Deliverables**:
- ✅ FHIR client functional
- ✅ Three-tier lookup working
- ✅ Graceful degradation on API failure
- ✅ Performance: <20ms average (95% cache hits)

---

### Phase 4: Caching & Monitoring (Week 4) - 2 days

**Goal**: Add Redis caching and monitoring dashboard

**Tasks**:

1. **Redis Cache Setup** (1 day):
   ```python
   # config/docker-compose.yml
   redis:
     image: redis:7-alpine
     ports:
       - "6379:6379"
     volumes:
       - redis_data:/data
     command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru

   volumes:
     redis_data:
   ```

   ```python
   # app/services/cache_service.py
   from redis.asyncio import Redis
   import json

   class TerminologyCache:
       def __init__(self, redis_url: str = "redis://localhost:6379"):
           self.redis = Redis.from_url(redis_url, decode_responses=True)

       async def get(self, key: str) -> Optional[Dict]:
           value = await self.redis.get(key)
           return json.loads(value) if value else None

       async def set(self, key: str, value: Dict, ttl: int = 86400):
           await self.redis.setex(key, ttl, json.dumps(value))

       async def stats(self) -> Dict:
           """Get cache statistics"""
           info = await self.redis.info('stats')
           return {
               "hits": info['keyspace_hits'],
               "misses": info['keyspace_misses'],
               "hit_rate": info['keyspace_hits'] / (info['keyspace_hits'] + info['keyspace_misses']) if (info['keyspace_hits'] + info['keyspace_misses']) > 0 else 0
           }
   ```

2. **Monitoring Dashboard** (1 day):
   - Add terminology service metrics to Admin Dashboard
   - Track: cache hit rate, avg response time, API call volume
   - Alert on: API failures, slow queries, low cache hit rate

**Deliverables**:
- ✅ Redis cache operational
- ✅ Cache hit rate >90%
- ✅ Monitoring dashboard functional

---

## Cost Analysis

### Licensing Costs

| Component | Cost | Frequency | Notes |
|-----------|------|-----------|-------|
| **SNOMED CT (U.S.)** | Free | Annual | Via NLM (U.S. users only) |
| **SNOMED CT (International)** | $3,000-$5,000 | Annual | SNOMED International membership |
| **ICD-10-CM** | Free | - | Public domain (CDC) |
| **LOINC** | Free | - | Free with registration |
| **RxNorm** | Free | - | NLM public domain |
| **UMLS API** | Free | Annual | Requires license renewal |
| **NLM FHIR Server** | Free | - | Rate-limited (60 req/min) |

**Total Annual Cost (U.S. deployment)**: $0
**Total Annual Cost (International)**: $3,000-$5,000

### Infrastructure Costs

| Component | Size | Monthly Cost | Notes |
|-----------|------|--------------|-------|
| **PostgreSQL (terminology schema)** | 5 GB | $0 | Included in existing DB |
| **Redis (cache)** | 256 MB | $0 | Included in existing infrastructure |
| **FHIR API calls** | ~1000/day | $0 | Free tier (NLM) |

**Total Infrastructure Cost**: $0 (uses existing resources)

### Development Costs

| Phase | Effort | Cost (@ $150/hr) |
|-------|--------|------------------|
| Phase 1 (Foundation) | 16 hours | $2,400 |
| Phase 2 (Database) | 40 hours | $6,000 |
| Phase 3 (FHIR) | 24 hours | $3,600 |
| Phase 4 (Caching) | 16 hours | $2,400 |
| **Total** | **96 hours** | **$14,400** |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **SNOMED CT licensing delays** | Medium | High | Start licensing process early (Week 1) |
| **Database loading failures** | Low | Medium | Thorough testing with sample data |
| **FHIR API rate limits** | Medium | Low | Implement robust caching (95% hit rate) |
| **Performance degradation** | Low | High | Extensive load testing before production |
| **Code mapping errors** | Medium | High | Validate against gold standard datasets |
| **Maintenance burden** | Medium | Medium | Automate quarterly updates |

---

## Success Metrics

### Phase 1 (Foundation)

- ✅ `TerminologyService` interface defined and documented
- ✅ Query interpreter refactored (no hardcoded mappings)
- ✅ All existing tests passing
- ✅ No breaking changes to existing functionality

### Phase 2 (Database)

- ✅ SNOMED CT loaded (400,000+ concepts)
- ✅ ICD-10 cross-mapping functional
- ✅ Database lookups < 50ms (P95)
- ✅ Accuracy >95% on top 100 conditions
- ✅ Test coverage >80%

### Phase 3 (FHIR)

- ✅ FHIR client functional
- ✅ Three-tier lookup working
- ✅ Graceful degradation on API failure
- ✅ End-to-end response time <100ms (P95)

### Phase 4 (Caching & Monitoring)

- ✅ Cache hit rate >90%
- ✅ Average response time <20ms
- ✅ Monitoring dashboard showing real-time metrics
- ✅ Zero downtime during terminology updates

### Production Readiness

- ✅ Handles 10,000+ unique condition queries/day
- ✅ Zero SQL generation failures for common conditions
- ✅ <1% fallback to text search for rare conditions
- ✅ Complete audit trail for all terminology lookups
- ✅ Automated quarterly update pipeline

---

## Alternative: Keep Hardcoded (Not Recommended)

If hybrid architecture is too complex, we could **expand the hardcoded dictionary** instead:

### Minimal Approach

**Expand CONDITION_MAPPINGS to top 100 conditions** (covers ~90% of queries):

```python
# Add these to existing CONDITION_MAPPINGS:
ADDITIONAL_MAPPINGS = {
    "stress": {"snomed": "262188008", "icd10": "F43.9", "name": "Stress-related disorder"},
    "anxiety": {"snomed": "48694002", "icd10": "F41.9", "name": "Anxiety disorder"},
    "depression": {"snomed": "35489007", "icd10": "F32.9", "name": "Major depressive disorder"},
    "heart failure": {"snomed": "84114007", "icd10": "I50.9", "name": "Heart failure"},
    "copd": {"snomed": "13645005", "icd10": "J44.9", "name": "COPD"},
    "cancer": {"snomed": "363346000", "icd10": "C80.1", "name": "Malignant neoplasm"},
    # ... add 94 more
}
```

**Pros**:
- ✅ Simple implementation (1 hour)
- ✅ No infrastructure changes
- ✅ No licensing costs

**Cons**:
- ❌ Still limited to ~100 conditions
- ❌ Manual updates required
- ❌ NOT industry standard
- ❌ No cross-mapping
- ❌ No synonym resolution
- ❌ Not production-ready

**Recommendation**: Only acceptable for MVP/prototype phase. Must migrate to hybrid architecture for production.

---

## Appendix A: SQL-on-FHIR v2 Alignment

The official **SQL-on-FHIR v2** specification explicitly supports terminology service integration:

> "Integration with a FHIR Terminology Service is also supported, allowing users to incorporate knowledge from rich terminologies such as SNOMED CT within their queries."
>
> — SQL-on-FHIR v2 Implementation Guide

**Best Practice**: Use FHIR Terminology Server for code lookups, reference official ValueSets in ViewDefinitions.

**Example ViewDefinition with Terminology Service**:
```yaml
name: condition_diagnoses
resource: Condition
select:
  - column: patient_id
    path: subject.reference
  - column: code
    path: code.coding.code
    description: "ICD-10 or SNOMED code"
  - column: display
    path: code.coding.display
where:
  - path: code.memberOf('http://hl7.org/fhir/ValueSet/condition-code')
    # Uses FHIR Terminology Server to expand ValueSet
```

---

## Appendix B: References

### Standards & Specifications

1. **FHIR Terminology Services**: https://www.hl7.org/fhir/terminology-service.html
2. **SQL-on-FHIR v2**: https://build.fhir.org/ig/FHIR/sql-on-fhir-v2/
3. **SNOMED CT**: https://www.snomed.org/
4. **ICD-10-CM**: https://www.cdc.gov/nchs/icd/icd-10-cm.htm
5. **LOINC**: https://loinc.org/
6. **RxNorm**: https://www.nlm.nih.gov/research/umls/rxnorm/
7. **UMLS**: https://www.nlm.nih.gov/research/umls/

### Production Examples

8. **Epic Terminology Services**: https://fhir.epic.com/Documentation?docId=terminology
9. **Cerner Millennium**: https://docs.oracle.com/en/industries/health/millennium/
10. **Clinical Architecture Symedical**: https://clinicalarchitecture.com/symedical/

### Research Papers

11. **Recent Developments in Clinical Terminologies** (PMC6115234):
    https://pmc.ncbi.nlm.nih.gov/articles/PMC6115234/

12. **Coding Systems for Clinical Decision Support** (PMC7641774):
    https://pmc.ncbi.nlm.nih.gov/articles/PMC7641774/

13. **Why Terminology Standards Matter for AI in Healthcare** (PMC11375201):
    https://pmc.ncbi.nlm.nih.gov/articles/PMC11375201/

### Tools & Libraries

14. **NLM FHIR Terminology Server**: https://tx.fhir.org/r4
15. **Ontoserver** (open source): https://ontoserver.csiro.au/
16. **UMLS REST API**: https://documentation.uts.nlm.nih.gov/rest/

---

## Next Steps

1. **Review this document** with team and stakeholders
2. **Obtain SNOMED CT license** (start immediately - can take 2-4 weeks)
3. **Schedule Sprint 7** for hybrid architecture implementation
4. **Assign Phase 1** (Foundation) to engineering team
5. **Set up monitoring** for current text search fallback to track usage

**Questions? Contact**: [Engineering Lead]
**Last Updated**: October 31, 2025
**Status**: Planning / Ready for Sprint 7
