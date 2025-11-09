-- Rollback Migration: Remove Preview Extraction Fields from data_deliveries
-- Date: 2025-11-04
-- Description: Removes the 4 fields added for preview extraction workflow
-- WARNING: This will delete data in these columns. Back up data first if needed.

-- Check if rollback is needed
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_deliveries'
        AND column_name = 'preview_data'
    ) THEN
        -- Remove preview_data column
        ALTER TABLE data_deliveries
        DROP COLUMN IF EXISTS preview_data;

        RAISE NOTICE 'Removed column: preview_data';
    ELSE
        RAISE NOTICE 'Column preview_data does not exist, skipping';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_deliveries'
        AND column_name = 'preview_qa_report'
    ) THEN
        -- Remove preview_qa_report column
        ALTER TABLE data_deliveries
        DROP COLUMN IF EXISTS preview_qa_report;

        RAISE NOTICE 'Removed column: preview_qa_report';
    ELSE
        RAISE NOTICE 'Column preview_qa_report does not exist, skipping';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_deliveries'
        AND column_name = 'delivery_approved_by'
    ) THEN
        -- Remove delivery_approved_by column
        ALTER TABLE data_deliveries
        DROP COLUMN IF EXISTS delivery_approved_by;

        RAISE NOTICE 'Removed column: delivery_approved_by';
    ELSE
        RAISE NOTICE 'Column delivery_approved_by does not exist, skipping';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_deliveries'
        AND column_name = 'delivery_approved_at'
    ) THEN
        -- Remove delivery_approved_at column
        ALTER TABLE data_deliveries
        DROP COLUMN IF EXISTS delivery_approved_at;

        RAISE NOTICE 'Removed column: delivery_approved_at';
    ELSE
        RAISE NOTICE 'Column delivery_approved_at does not exist, skipping';
    END IF;
END $$;

-- Verify rollback
DO $$
DECLARE
    column_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO column_count
    FROM information_schema.columns
    WHERE table_name = 'data_deliveries'
    AND column_name IN ('preview_data', 'preview_qa_report', 'delivery_approved_by', 'delivery_approved_at');

    IF column_count = 0 THEN
        RAISE NOTICE '✓ Rollback successful: All 4 columns removed';
    ELSE
        RAISE WARNING '⚠ Rollback incomplete: Still % columns remaining', column_count;
    END IF;
END $$;
