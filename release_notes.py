"""Select unseen, published releases from the host-editable changelog."""
import re


def version_key(value):
    if not isinstance(value,str) or len(value)>32:return None
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value or '')
    return tuple(map(int, match.groups())) if match else None


def unseen_notes(text, seen, current):
    published = version_key(current)
    sections = []
    headings = list(re.finditer(r'^#{1,6}\s+v?(\d+\.\d+\.\d+)\b[^\n]*', text, re.M))
    for index, match in enumerate(headings):
        version = match.group(1)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        if version_key(version) <= published:
            sections.append((version, text[match.start():end].strip()))
    previous = version_key(seen)
    if previous and previous >= published:
        return [], ''
    # New players get this release, rather than years of historical notes.
    chosen = [(v, s) for v, s in sections if version_key(v) > previous] if previous else [(v, s) for v, s in sections if v == current]
    chosen.sort(key=lambda item: version_key(item[0]), reverse=True)
    if not chosen and (not previous or previous < published):
        return [current], 'Welcome to version ' + current
    return [v for v, _ in chosen], '\n\n'.join(s for _, s in chosen)
