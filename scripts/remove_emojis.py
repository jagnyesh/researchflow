#!/usr/bin/env python3
"""
Remove emojis from documentation files for professional GitHub presentation.
"""
import re
from pathlib import Path

# Common emoji mappings to text equivalents
EMOJI_REPLACEMENTS = {
    '✅': '[x]',
    '✓': '[x]',
    '❌': '[ ]',
    '⚠️': 'WARNING:',
    '📊': '',
    '🚀': '',
    '💡': 'NOTE:',
    '🔧': '',
    '🎯': '',
    '📝': '',
    '🔥': '',
    '⭐': '',
    '🎉': '',
    '👍': '',
    '📌': 'NOTE:',
    '🔍': '',
    '💻': '',
    '🤖': '',
    '🟢': '',
    '🟡': '',
    '🔴': '',
}

def remove_emojis_from_file(file_path: Path, dry_run: bool = False):
    """Remove emojis from a markdown file."""
    try:
        content = file_path.read_text(encoding='utf-8')
        original_content = content

        # Replace known emojis with text equivalents
        for emoji, replacement in EMOJI_REPLACEMENTS.items():
            content = content.replace(emoji, replacement)

        # Remove any remaining emojis (Unicode emoji range)
        # This regex matches most emojis
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags (iOS)
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE
        )
        content = emoji_pattern.sub('', content)

        # Clean up any double spaces created by emoji removal
        content = re.sub(r'  +', ' ', content)

        # Clean up lines that now start with just a space
        content = re.sub(r'^\s+$', '', content, flags=re.MULTILINE)

        if content != original_content:
            if not dry_run:
                file_path.write_text(content, encoding='utf-8')
                print(f"✓ Updated: {file_path.relative_to(Path.cwd())}")
            else:
                print(f"Would update: {file_path.relative_to(Path.cwd())}")
            return True
        else:
            print(f"  No changes: {file_path.relative_to(Path.cwd())}")
            return False
    except Exception as e:
        print(f"ERROR processing {file_path}: {e}")
        return False

def main():
    """Remove emojis from all documentation files."""
    docs_dir = Path(__file__).parent.parent / 'docs'

    if not docs_dir.exists():
        print(f"ERROR: Documentation directory not found: {docs_dir}")
        return

    print("=" * 80)
    print("Removing emojis from documentation files")
    print("=" * 80)

    # Find all markdown files
    md_files = list(docs_dir.rglob('*.md'))

    print(f"\nFound {len(md_files)} markdown files")
    print()

    updated_count = 0
    for md_file in sorted(md_files):
        if remove_emojis_from_file(md_file):
            updated_count += 1

    print()
    print("=" * 80)
    print(f"Summary: Updated {updated_count}/{len(md_files)} files")
    print("=" * 80)

if __name__ == '__main__':
    main()
