-- Migration: Add Preview Extraction Fields to data_deliveries
-- Date: 2025-11-04
-- Description: Adds 4 fields to support preview extraction workflow
--   - preview_data: Stores 10-row preview for each data element
--   - preview_qa_report: Stores auto-QA validation results
--   - delivery_approved_by: Tracks who approved final dataset
--   - delivery_approved_at: Audit trail for delivery approval

-- Check if migration has already been applied
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_deliveries'
        AND column_name = 'preview_data'
    ) THEN
        -- Add preview_data column
        ALTER TABLE data_deliveries
        ADD COLUMN preview_data JSONB DEFAULT NULL;

        RAISE NOTICE 'Added column: preview_data';
    ELSE
        RAISE NOTICE 'Column preview_data already exists, skipping';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_deliveries'
        AND column_name = 'preview_qa_report'
    ) THEN
        -- Add preview_qa_report column
        ALTER TABLE data_deliveries
        ADD COLUMN preview_qa_report JSONB DEFAULT NULL;

        RAISE NOTICE 'Added column: preview_qa_report';
    ELSE
        RAISE NOTICE 'Column preview_qa_report already exists, skipping';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_deliveries'
        AND column_name = 'delivery_approved_by'
    ) THEN
        -- Add delivery_approved_by column
        ALTER TABLE data_deliveries
        ADD COLUMN delivery_approved_by VARCHAR DEFAULT NULL;

        RAISE NOTICE 'Added column: delivery_approved_by';
    ELSE
        RAISE NOTICE 'Column delivery_approved_by already exists, skipping';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_deliveries'
        AND column_name = 'delivery_approved_at'
    ) THEN
        -- Add delivery_approved_at column
        ALTER TABLE data_deliveries
        ADD COLUMN delivery_approved_at TIMESTAMP DEFAULT NULL;

        RAISE NOTICE 'Added column: delivery_approved_at';
    ELSE
        RAISE NOTICE 'Column delivery_approved_at already exists, skipping';
    END IF;
END $$;

-- Verify migration
DO $$
DECLARE
    column_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO column_count
    FROM information_schema.columns
    WHERE table_name = 'data_deliveries'
    AND column_name IN ('preview_data', 'preview_qa_report', 'delivery_approved_by', 'delivery_approved_at');

    IF column_count = 4 THEN
        RAISE NOTICE '✓ Migration successful: All 4 columns exist';
    ELSE
        RAISE WARNING '⚠ Migration incomplete: Only % of 4 columns exist', column_count;
    END IF;
END $$;
