-- ============================================================================
-- V1__initial_schema.sql
-- Baseline Schema Migration for Azure SQL Database
-- ============================================================================

-- 1. Schema Version Tracking Table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'schema_version')
BEGIN
    CREATE TABLE dbo.schema_version (
        version_rank INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        installed_rank INT NOT NULL,
        version VARCHAR(50) NOT NULL,
        description VARCHAR(200) NOT NULL,
        type VARCHAR(20) NOT NULL,
        script VARCHAR(1000) NOT NULL,
        checksum INT NULL,
        installed_by VARCHAR(100) NOT NULL,
        installed_on DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        execution_time INT NOT NULL,
        success BIT NOT NULL
    );

    CREATE UNIQUE INDEX uq_schema_version ON dbo.schema_version (version);
END;

-- 2. Audit Event Log Table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'audit_events')
BEGIN
    CREATE TABLE dbo.audit_events (
        event_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        event_timestamp DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        source_component NVARCHAR(128) NOT NULL,
        action_name NVARCHAR(128) NOT NULL,
        principal_name NVARCHAR(256) NOT NULL,
        client_ip NVARCHAR(45) NULL,
        payload_json NVARCHAR(MAX) NULL
    );

    CREATE NONCLUSTERED INDEX ix_audit_events_timestamp 
        ON dbo.audit_events (event_timestamp DESC);
END;

-- 3. Application System Heartbeat / Health Check Table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'system_heartbeat')
BEGIN
    CREATE TABLE dbo.system_heartbeat (
        node_id NVARCHAR(128) NOT NULL PRIMARY KEY,
        last_heartbeat DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        region NVARCHAR(64) NOT NULL,
        status NVARCHAR(32) NOT NULL DEFAULT 'HEALTHY',
        details NVARCHAR(MAX) NULL
    );
END;

-- 4. Record Initial Schema Migration Execution
IF NOT EXISTS (SELECT * FROM dbo.schema_version WHERE version = '1.0.0')
BEGIN
    INSERT INTO dbo.schema_version (
        installed_rank, version, description, type, script, installed_by, execution_time, success
    )
    VALUES (
        1, '1.0.0', 'Initial baseline schema migration', 'SQL', 'V1__initial_schema.sql', SUSER_NAME(), 10, 1
    );
END;
