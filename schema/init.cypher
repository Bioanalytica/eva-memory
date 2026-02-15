// Eva Memory - Neo4j Schema Initialization
// Run against the default 'neo4j' database on Neo4j 5.x

// ============================================================================
// Uniqueness Constraints
// ============================================================================

CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE;
CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE;
CREATE CONSTRAINT session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT branch_name IF NOT EXISTS FOR (b:Branch) REQUIRE b.name IS UNIQUE;
CREATE CONSTRAINT project_name IF NOT EXISTS FOR (p:Project) REQUIRE p.name IS UNIQUE;

// ============================================================================
// Performance Indexes
// ============================================================================

CREATE INDEX memory_type IF NOT EXISTS FOR (m:Memory) ON (m.type);
CREATE INDEX memory_importance IF NOT EXISTS FOR (m:Memory) ON (m.importance);
CREATE INDEX memory_created IF NOT EXISTS FOR (m:Memory) ON (m.created);
CREATE INDEX memory_project IF NOT EXISTS FOR (m:Memory) ON (m.project);
CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type);

// ============================================================================
// Full-Text Indexes (for search)
// ============================================================================

CREATE FULLTEXT INDEX memory_fulltext IF NOT EXISTS
FOR (m:Memory) ON EACH [m.content, m.summary];

CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
FOR (e:Entity) ON EACH [e.name];

// ============================================================================
// v2 Indexes (confidence, decay, provenance)
// ============================================================================

CREATE INDEX memory_confidence IF NOT EXISTS FOR (m:Memory) ON (m.confidence);
CREATE INDEX memory_decayDays IF NOT EXISTS FOR (m:Memory) ON (m.decayDays);
CREATE INDEX memory_forgotten IF NOT EXISTS FOR (m:Memory) ON (m.forgotten);
CREATE INDEX memory_sourceChannel IF NOT EXISTS FOR (m:Memory) ON (m.sourceChannel);
CREATE INDEX memory_type_created IF NOT EXISTS FOR (m:Memory) ON (m.type, m.created);
