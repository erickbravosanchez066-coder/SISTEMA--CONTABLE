SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'contable_db ' AND pid <> pg_backend_pid();
ALTER DATABASE "contable_db " RENAME TO contable_db;
