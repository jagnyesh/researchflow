#!/usr/bin/env python3
"""
Remove emojis from documentation files for professional GitHub presentation.
"""
import re
from pathlib import Path

# Common emoji mappings to text equivalents
EMOJI_REPLACEMENTS = {
    "✅": "[x]",
    "✓": "[x]",
    "❌": "[ ]",
    "⚠️": "WARNING:",
    "📊": "",
    "🚀": "",
    "💡": "NOTE:",
    "🔧": "",
    "🎯": "",
    "📝": "",
    "🔥": "",
    "⭐": "",
    "🎉": "",
    "👍": "",
    "📌": "NOTE:",
    "🔍": "",
    "💻": "",
    "🤖": "",
    "🟢": "",
    "🟡": "",
    "🔴": "",
}


# Inclusive (start, end) code-point ranges treated as emoji. Checked in Python
# rather than in a regex character class: CodeQL reads class ranges above
# U+FFFF as UTF-16 surrogate pairs and flags them as overlapping (#470).
EMOJI_RANGES = (
    (0x1F600, 0x1F64F),  # emoticons
    (0x1F300, 0x1F5FF),  # symbols & pictographs
    (0x1F680, 0x1F6FF),  # transport & map symbols
    (0x2702, 0x27B0),  # dingbats
    (0x24C2, 0x24C2),  # circled M
    (0x2600, 0x26FF),  # miscellaneous symbols
    (0x2B00, 0x2BFF),  # miscellaneous symbols and arrows
    (0x25AA, 0x25AA),  # emoji-presented geometric shapes
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FB),
    (0x2934, 0x2935),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0x1F004, 0x1F004),
    (0x1F0CF, 0x1F0CF),
    (0xFE0F, 0xFE0F),  # emoji variation selector
    (0x1F170, 0x1F251),  # enclosed alphanumerics/ideographs; includes flags
)


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


def remove_emojis_from_file(file_path: Path, dry_run: bool = False):
    """Remove emojis from a markdown file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        original_content = content

        # Replace known emojis with text equivalents
        for emoji, replacement in EMOJI_REPLACEMENTS.items():
            content = content.replace(emoji, replacement)

        content = "".join(ch for ch in content if not _is_emoji(ch))

        # Clean up any double spaces created by emoji removal
        content = re.sub(r"  +", " ", content)

        # Clean up lines that now start with just a space
        content = re.sub(r"^\s+$", "", content, flags=re.MULTILINE)

        if content != original_content:
            if not dry_run:
                file_path.write_text(content, encoding="utf-8")
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
    docs_dir = Path(__file__).parent.parent / "docs"

    if not docs_dir.exists():
        print(f"ERROR: Documentation directory not found: {docs_dir}")
        return

    print("=" * 80)
    print("Removing emojis from documentation files")
    print("=" * 80)

    # Find all markdown files
    md_files = list(docs_dir.rglob("*.md"))

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


if __name__ == "__main__":
    main()
