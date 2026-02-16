-- Migration script to update assignment_submissions table for append-only mode
-- Run this in your Supabase SQL editor if the table already exists

-- Step 1: Check what constraints exist (run this first to see constraint names)
-- SELECT constraint_name, constraint_type 
-- FROM information_schema.table_constraints 
-- WHERE table_name = 'assignment_submissions';

-- Step 2: Drop ALL existing primary key and unique constraints
-- This will remove any constraint that prevents duplicate (name, sid) or (assignment_name, name) combinations
DO $$ 
DECLARE
    r RECORD;
BEGIN
    -- Drop primary key constraint
    FOR r IN (SELECT constraint_name 
              FROM information_schema.table_constraints 
              WHERE table_name = 'assignment_submissions' 
              AND constraint_type = 'PRIMARY KEY') 
    LOOP
        EXECUTE 'ALTER TABLE assignment_submissions DROP CONSTRAINT IF EXISTS ' || quote_ident(r.constraint_name);
    END LOOP;
    
    -- Drop unique constraints
    FOR r IN (SELECT constraint_name 
              FROM information_schema.table_constraints 
              WHERE table_name = 'assignment_submissions' 
              AND constraint_type = 'UNIQUE') 
    LOOP
        EXECUTE 'ALTER TABLE assignment_submissions DROP CONSTRAINT IF EXISTS ' || quote_ident(r.constraint_name);
    END LOOP;
END $$;

-- Step 3: Add the new auto-incrementing ID column if it doesn't exist
ALTER TABLE assignment_submissions 
ADD COLUMN IF NOT EXISTS id BIGSERIAL;

-- Step 4: Populate id for existing rows if they're NULL
DO $$
DECLARE
    max_id BIGINT;
BEGIN
    SELECT COALESCE(MAX(id), 0) INTO max_id FROM assignment_submissions;
    IF max_id = 0 THEN
        -- Create sequence if it doesn't exist and set it to start after existing rows
        PERFORM setval('assignment_submissions_id_seq', (SELECT COUNT(*) FROM assignment_submissions));
    END IF;
    UPDATE assignment_submissions SET id = nextval('assignment_submissions_id_seq') WHERE id IS NULL;
END $$;

-- Step 5: Make id NOT NULL and set as primary key
ALTER TABLE assignment_submissions 
ALTER COLUMN id SET NOT NULL;

-- Drop old primary key if it exists, then add new one
ALTER TABLE assignment_submissions 
DROP CONSTRAINT IF EXISTS assignment_submissions_pkey;

ALTER TABLE assignment_submissions 
ADD CONSTRAINT assignment_submissions_pkey PRIMARY KEY (id);

-- Step 6: Create indexes for faster lookups (if they don't exist)
CREATE INDEX IF NOT EXISTS idx_assignment_submissions_email ON assignment_submissions(email);
CREATE INDEX IF NOT EXISTS idx_assignment_submissions_sid ON assignment_submissions(sid);
CREATE INDEX IF NOT EXISTS idx_assignment_submissions_assignment ON assignment_submissions(assignment_name);
CREATE INDEX IF NOT EXISTS idx_assignment_submissions_name ON assignment_submissions(name);

