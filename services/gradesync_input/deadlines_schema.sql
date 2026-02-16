-- SQL Schema for deadlines table
-- Run this in your Supabase SQL editor to create the table

CREATE TABLE IF NOT EXISTS deadlines (
    id BIGSERIAL PRIMARY KEY,
    course_code TEXT NOT NULL,
    assignment_code TEXT,
    assignment_name TEXT NOT NULL,
    due TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(course_code, assignment_code, assignment_name)
);

-- Create indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_deadlines_course_code ON deadlines(course_code);
CREATE INDEX IF NOT EXISTS idx_deadlines_assignment_code ON deadlines(assignment_code);
CREATE INDEX IF NOT EXISTS idx_deadlines_assignment_name ON deadlines(assignment_name);
CREATE INDEX IF NOT EXISTS idx_deadlines_due ON deadlines(due);

-- Add comment to table
COMMENT ON TABLE deadlines IS 'Stores assignment deadlines with course and assignment identifiers';

