-- SQL Schema for assignment_submissions table
-- Run this in your Supabase SQL editor to create the table

CREATE TABLE IF NOT EXISTS assignment_submissions (
    assignment_name TEXT NOT NULL,
    sid TEXT,
    name TEXT NOT NULL,
    email TEXT,
    status TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (assignment_name, name)
);

-- Create indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_assignment_submissions_email ON assignment_submissions(email);
CREATE INDEX IF NOT EXISTS idx_assignment_submissions_sid ON assignment_submissions(sid);
CREATE INDEX IF NOT EXISTS idx_assignment_submissions_assignment ON assignment_submissions(assignment_name);
CREATE INDEX IF NOT EXISTS idx_assignment_submissions_name ON assignment_submissions(name);

