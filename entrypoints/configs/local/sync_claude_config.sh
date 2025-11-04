#!/bin/bash
# Sync Claude Desktop config to Windows
# Automatically copies the config file to Claude Desktop folder

set -e

# Source and destination paths
SOURCE="/home/kimghw/MailQueryWithMCP/entrypoints/configs/local/claude_desktop_config.json"
DEST="/mnt/c/Users/GEOHWA KIM/AppData/Roaming/Claude/claude_desktop_config.json"

echo "🔄 Syncing Claude Desktop config..."
echo "From: $SOURCE"
echo "To: $DEST"
echo ""

# Check if source file exists
if [ ! -f "$SOURCE" ]; then
    echo "❌ Error: Source file not found: $SOURCE"
    exit 1
fi

# Copy the file
cp "$SOURCE" "$DEST"

if [ $? -eq 0 ]; then
    echo "✅ Config synced successfully!"
    echo ""
    echo "📝 Current config:"
    cat "$SOURCE"
    echo ""
    echo "⚠️  Please restart Claude Desktop to apply changes"
else
    echo "❌ Failed to sync config"
    exit 1
fi
