#!/bin/bash
# DCR Database Foreign Key Fix Script

DB_PATH="/home/kimghw/KR365/data/auth_mail_query.db"
BACKUP_PATH="/home/kimghw/KR365/data/auth_mail_query.db.backup.$(date +%Y%m%d_%H%M%S)"

echo "🔧 Fixing DCR database foreign key constraints..."

# Backup existing database
echo "📦 Backing up database to: $BACKUP_PATH"
cp "$DB_PATH" "$BACKUP_PATH"

# Export existing data
echo "📤 Exporting existing data..."
sqlite3 "$DB_PATH" <<EOF
.mode insert
.output /tmp/dcr_azure_app.sql
SELECT * FROM dcr_azure_app;
.output /tmp/dcr_clients.sql
SELECT * FROM dcr_clients_mail_query;
.output stdout
EOF

# Delete database
echo "🗑️  Removing old database..."
rm -f "$DB_PATH" "${DB_PATH}-wal" "${DB_PATH}-shm"

echo "✅ Database will be recreated on next server start with proper foreign keys."
echo "📦 Backup saved to: $BACKUP_PATH"
echo ""
echo "Next steps:"
echo "1. Restart the server: ./start-dashboard-mail-query.sh"
echo "2. The database will be recreated with proper foreign keys"
echo "3. You'll need to re-authenticate users"
