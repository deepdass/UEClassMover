import os, shutil, re

# helpers
# ---------------------------------------------------------------------------

def build_index(source):
    index = {}
    for root, _, files in os.walk(source):
        for f in files:
            key = f.lower()
            if key not in index:
                index[key] = []
            index[key].append(os.path.join(root, f))
    return index


def find_file(index, filename):
    matches = index.get(filename.lower(), [])
    if not matches:
        return None
    if len(matches) > 1:
        print(f"  WARNING: multiple copies of '{filename}' found — using first:")
        for m in matches:
            print(f"    {m}")
    return matches[0]


def compute_include_path(source, dest_dir, filename):
    """
    Build.cs has:  PublicIncludePaths.AddRange(new string[] {"<ProjName>"})
    So UBT adds the module root (Source/Projectidk/) to include search paths.
    Include paths are therefore relative to the module root.

    Also, This is better than changing every include when you rename the project :)
    """
    source   = os.path.normpath(source)
    dest_dir = os.path.normpath(dest_dir)

    try:
        rel = os.path.relpath(dest_dir, source)
    except ValueError:
        raise ValueError(f"Destination '{dest_dir}' is not under source root '{source}'")

    if rel.startswith(".."):
        raise ValueError(
            f"Destination '{dest_dir}' is outside the module root '{source}'.\n"
            f"  All files must stay under the module root."
        )

    rel = rel.replace("\\", "/")
    if rel == ".":
        return filename

    parts = rel.split("/")
    if parts[0].lower() in ("public", "private"):
        parts = parts[1:]
    rel = "/".join(parts)

    if not rel:
        return filename
    return rel + "/" + filename


# Build.cs patcher
# ---------------------------------------------------------------------------

def patch_build_cs(source, proj_name):
    """
    Find <ProjName>.Build.cs and ensure it contains:
        PublicIncludePaths.AddRange(new string[] {"<ProjName>"});
    Inserts it right after the constructor's opening brace if missing.
    """
    build_cs = os.path.join(source, f"{proj_name}.Build.cs")
    if not os.path.exists(build_cs):
        print(f"  WARNING: {proj_name}.Build.cs not found — skipping patch.")
        return

    try:
        with open(build_cs, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError as e:
        print(f"  WARNING: Could not read {proj_name}.Build.cs — skipping patch: {e}")
        return

    insert_line = f'\t\tPublicIncludePaths.AddRange(new string[] {{"{proj_name}"}});\n'

    if f'"{proj_name}"' in content and "PublicIncludePaths" in content:
        print(f"  Build.cs already has PublicIncludePaths \"{proj_name}\" — skipping.")
        return

    patched, n = re.subn(
        r'(public\s+' + re.escape(proj_name) + r'\s*\([^)]*\)\s*'
        r'(?::\s*base\s*\([^)]*\)\s*)?\{)',
        r'\1\n' + insert_line.rstrip('\n'),
        content
    )

    if n == 0:
        lines     = content.splitlines(keepends=True)
        new_lines = []
        inserted  = False
        in_ctor   = False
        for line in lines:
            new_lines.append(line)
            if not inserted and re.search(
                r'public\s+' + re.escape(proj_name) + r'\s*\(', line
            ):
                in_ctor = True
            if in_ctor and not inserted and line.strip() == "{":
                new_lines.append(insert_line)
                inserted = True
                in_ctor  = False
        if not inserted:
            print("  WARNING: Could not locate constructor in Build.cs — patch skipped.")
            return
        patched = "".join(new_lines)

    try:
        with open(build_cs, "w", encoding="utf-8") as fh:
            fh.write(patched)
    except OSError as e:
        print(f"  WARNING: Could not write {proj_name}.Build.cs — patch skipped: {e}")
        return

    print(f"  Build.cs patched — added include path: {proj_name}")


# include rewriting
# ---------------------------------------------------------------------------

def find_include_in_line(line, basename_lower):
    """
    Match any  #include ".../<basename>"  line case-insensitively.
    Returns the exact string inside the quotes, or None.
    """
    m = re.match(r'\s*#include\s+"([^"]+)"', line)
    if not m:
        return None
    path_in_quotes = m.group(1)
    if path_in_quotes.replace("\\", "/").split("/")[-1].lower() == basename_lower:
        return path_in_quotes
    return None


def update_includes(source, name, new_include_path):
    h_basename_low = (name + ".h").lower()
    new_inc        = f'#include "{new_include_path}"'

    for root, _, files in os.walk(source):
        for f in files:
            if not f.endswith((".h", ".cpp")):
                continue

            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()

                changed   = False
                new_lines = []
                seen_incs = set()
                for line in lines:
                    found = find_include_in_line(line, h_basename_low)
                    if found is None:
                        new_lines.append(line)
                        continue

                    current_inc = f'#include "{found}"'
                    if current_inc == new_inc:
                        new_lines.append(line)
                        seen_incs.add(new_inc)
                        continue

                    if new_inc in seen_incs:
                        print(f"  Removed duplicate in {f}: {current_inc}")
                        changed = True
                    else:
                        new_lines.append(line.replace(current_inc, new_inc))
                        seen_incs.add(new_inc)
                        print(f"  Updated in {f}:")
                        print(f"    - {current_inc}")
                        print(f"    + {new_inc}")
                        changed = True

                if changed:
                    with open(path, "w", encoding="utf-8", errors="replace") as fh:
                        fh.writelines(new_lines)
            except Exception as e:
                print(f"  Could not update {f}: {e}")


def update_self_includes(source, dest_path, index):
    try:
        with open(dest_path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()

        changed   = False
        new_lines = []
        seen_incs = set()
        for line in lines:
            m = re.match(r'(\s*#include\s+")([^"]+)(")', line)
            if not m:
                new_lines.append(line)
                continue

            prefix, inc_path, suffix = m.group(1), m.group(2), m.group(3)
            basename = inc_path.replace("\\", "/").split("/")[-1]

            if basename.lower().endswith(".generated.h"):
                new_lines.append(line)
                continue

            found = find_file(index, basename)
            if not found:
                new_lines.append(line)
                continue

            correct_inc_path = compute_include_path(source, os.path.dirname(found), basename)

            old_quoted = inc_path
            new_line   = line.replace(old_quoted, correct_inc_path, 1)
            new_inc    = f'#include "{correct_inc_path}"'

            if new_inc in seen_incs:
                print(f"  Removed duplicate in {os.path.basename(dest_path)}: #include \"{inc_path}\"")
                changed = True
                continue

            seen_incs.add(new_inc)

            if new_line != line:
                print(f"  Updated in {os.path.basename(dest_path)}:")
                print(f"    - {line.strip()}")
                print(f"    + {new_line.strip()}")
                changed = True

            new_lines.append(new_line)

        if changed:
            with open(dest_path, "w", encoding="utf-8", errors="replace") as fh:
                fh.writelines(new_lines)
    except Exception as e:
        print(f"  Could not update self-includes in {os.path.basename(dest_path)}: {e}")


def preview_includes(source, proj_name, name, h_inc_path, entries, index):
    changes = []

    h_basename_low = (name + ".h").lower()
    new_inc        = f'#include "{h_inc_path}"'

    for root, _, files in os.walk(source):
        for f in files:
            if not f.endswith((".h", ".cpp")):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
                seen = set()
                for line in lines:
                    found = find_include_in_line(line, h_basename_low)
                    if not found:
                        continue
                    current_inc = f'#include "{found}"'
                    if current_inc == new_inc:
                        seen.add(new_inc)
                        continue
                    display = path.replace(os.path.normpath(source), os.path.join("Source", proj_name))
                    if new_inc in seen:
                        changes.append((display, current_inc, None))
                    else:
                        changes.append((display, current_inc, new_inc))
                        seen.add(new_inc)
            except Exception as e:
                print(f"  WARNING: Could not preview {f}: {e}")

    for (filename, dest_dir, _) in entries:
        src = find_file(index, filename)
        if not src:
            continue
        try:
            with open(src, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
            for line in lines:
                m = re.match(r'(\s*#include\s+")([^"]+)(")', line)
                if not m:
                    continue
                inc_path = m.group(2)
                basename = inc_path.replace("\\", "/").split("/")[-1]
                found = find_file(index, basename)
                if not found:
                    continue
                correct = compute_include_path(source, os.path.dirname(found), basename)
                if correct != inc_path:
                    display = src.replace(os.path.normpath(source), os.path.join("Source", proj_name))
                    changes.append((display, f'#include "{inc_path}"', f'#include "{correct}"'))
        except Exception as e:
            print(f"  WARNING: Could not preview self-includes in {filename}: {e}")

    if changes:
        print("  Include changes:")
        for (filepath, old, new) in changes:
            print(f"    {filepath}")
            print(f"      - {old}")
            if new:
                print(f"      + {new}")
            else:
                print(f"      (duplicate removed)")
        print()

# path building / display
# ---------------------------------------------------------------------------

PRESETS = {
    "1": ("Flat",                 "{sub}",         "{sub}"),
    "2": ("Public/Private split", "Public/{sub}",  "Private/{sub}"),
    "3": ("All Private",          "Private/{sub}", "Private/{sub}"),
}


def build_paths(source, name, subfolder, preset):
    _, h_tpl, cpp_tpl = PRESETS[preset]
    def resolve(tpl):
        filled = tpl.replace("{sub}", subfolder).strip("/")
        return os.path.join(source, filled) if filled else source
    return [
        (name + ".h",   resolve(h_tpl),   "Header        "),
        (name + ".cpp", resolve(cpp_tpl), "Implementation"),
    ]


def pretty(source, proj_name, label, dest_dir, filename):
    full    = os.path.join(dest_dir, filename)
    display = full.replace(os.path.normpath(source), os.path.join("Source", proj_name))
    print(f"  {label}  {display}")


# main move logic
# ---------------------------------------------------------------------------

def move_class(source, proj_name, name):
    name = name.strip()

    if not name:
        print("  Skipping empty class name.")
        return

    print(f"\n--- {name} ---")

    subfolder = input("Subfolder? (leave blank for none): ").strip()

    sub = subfolder or ""
    print()
    for key, (label, h_tpl, cpp_tpl) in PRESETS.items():
        h_ex   = h_tpl.replace("{sub}", sub).strip("/")
        cpp_ex = cpp_tpl.replace("{sub}", sub).strip("/")
        if h_ex == cpp_ex:
            print(f"  [{key}] {label:<28}  .h + .cpp → {h_ex or 'module root'}")
        else:
            print(f"  [{key}] {label:<28}  .h → {h_ex}   .cpp → {cpp_ex}")
    print()

    preset = input("  Which preset (1-3): ").strip()
    if preset not in PRESETS:
        preset = "1"

    entries = build_paths(source, name, subfolder, preset)

    inc_paths = {}
    for (filename, dest_dir, _) in entries:
        try:
            inc_paths[filename] = compute_include_path(source, dest_dir, filename)
        except ValueError as e:
            print(f"  ERROR: {e}")
            return

    print()
    for (filename, dest_dir, label) in entries:
        pretty(source, proj_name, label, dest_dir, filename)
        if filename.endswith(".h"):
            print(f"    include → \"{inc_paths[filename]}\"")
    print()

    index = build_index(source)
    preview_includes(source, proj_name, name, inc_paths[name + ".h"], entries, index)

    confirm = input("Confirm? (y/n): ").strip().lower()
    if confirm != "y":
        print("  Skipped.")
        return

    for (filename, dest_dir, _) in entries:
        src = find_file(index, filename)
        if not src:
            print(f"  NOT FOUND: {filename}")
            continue

        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError as e:
            print(f"  ERROR creating directory for {filename}: {e}")
            continue

        dest = os.path.join(dest_dir, filename)

        if os.path.abspath(src) == os.path.abspath(dest):
            print(f"  Already in place: {filename}")
        else:
            try:
                shutil.move(src, dest)
                print(f"  Moved: {filename}")
            except shutil.Error as e:
                print(f"  ERROR moving {filename}: {e}")
            except OSError as e:
                # Can happen on Windows when moving across drives (e.g. C: → D:)
                print(f"  ERROR moving {filename} (cross-drive move?): {e}")

    index = build_index(source)

    for (filename, dest_dir, _) in entries:
        ext  = os.path.splitext(filename)[1]
        dest = os.path.join(dest_dir, filename)
        if not os.path.exists(dest):
            continue

        if ext == ".h":
            update_includes(source, name, inc_paths[filename])

        update_self_includes(source, dest, index)


# entry point
# ---------------------------------------------------------------------------

def run():
    print("UE C++ File Mover")
    print()
    source_input = input("Source path (leave blank to use current directory): ").strip().strip('"')

    if not source_input:
        source_input = os.getcwd()
    source_input = source_input.rstrip("\\/")

    parts = source_input.replace("\\", "/").split("/")

    if parts[-1].lower() == "source":
        proj_name = parts[-2] if len(parts) >= 2 else parts[-1]
        source = os.path.join(source_input, proj_name)
    else:
        proj_name = parts[-1]
        source = os.path.join(source_input, "Source", proj_name)

    if not os.path.exists(source):
        print(f"Path not found: {source}")
        print(f"  (looked for module folder at: {source})")
        return

    print(f"  Project: {proj_name}")
    print()

    patch_build_cs(source, proj_name)

    raw = input("\nClasses to move (comma separated): ").strip()
    if not raw:
        print("No classes entered. Exiting.")
        return

    classes = [c.strip() for c in raw.split(",") if c.strip()]
    for name in classes:
        move_class(source, proj_name, name)

    print("\nDone! Right-click your .uproject -> Generate Visual Studio Project Files, then rebuild.")

if __name__ == "__main__":
    run()
