-- Migration 034: Add FK constraint on event_relationships.case_id
-- The column was created with a comment "FK added when cases table exists"
-- The cases table now exists (migration 013), so add the constraint.

ALTER TABLE event_relationships
    ADD CONSTRAINT fk_event_relationships_case_id
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL;
