#!/bin/bash
# Script to check if CLAUDE.md needs updating

echo "🔍 Checking if CLAUDE.md is in sync with project..."

# Check for new directories not mentioned in CLAUDE.md
NEW_DIRS=$(find app -maxdepth 2 -type d | grep -v __pycache__ | while read dir; do
  if ! grep -q "$dir" CLAUDE.md; then
    echo "  ⚠️  Directory not in CLAUDE.md: $dir"
  fi
done)

if [ ! -z "$NEW_DIRS" ]; then
  echo "$NEW_DIRS"
fi

# Check for new docs not mentioned in CLAUDE.md
echo ""
echo "📄 Checking new documentation files..."
NEW_DOCS=$(find docs -maxdepth 2 -name "*.md" | while read doc; do
  doc_basename=$(basename "$doc")
  if ! grep -q "$doc_basename" CLAUDE.md; then
    echo "  ⚠️  Doc not in CLAUDE.md: $doc_basename"
  fi
done)

if [ ! -z "$NEW_DOCS" ]; then
  echo "$NEW_DOCS"
else
  echo "  ✅ All docs referenced"
fi

# Check for new env vars not mentioned in CLAUDE.md
echo ""
echo "🔧 Checking environment variables..."
NEW_VARS=$(grep "^[A-Z_]*=" config/.env.example | cut -d= -f1 | while read var; do
  if ! grep -q "$var" CLAUDE.md; then
    echo "  ⚠️  Env var not in CLAUDE.md: $var"
  fi
done)

if [ ! -z "$NEW_VARS" ]; then
  echo "$NEW_VARS"
else
  echo "  ✅ All env vars referenced"
fi

echo ""
echo "📊 Summary:"
echo "  - See CLAUDE_UPDATE_CHECKLIST.md for detailed update instructions"
echo "  - Run 'code CLAUDE.md' to edit"
echo ""
