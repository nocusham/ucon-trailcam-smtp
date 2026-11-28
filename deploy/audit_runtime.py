"""Offline structural comparison of the reference and refactored Python source.

Read only committed Git objects. Do not import either runtime or execute its
code. This is a review inventory, not a proof of behavioral equivalence.
"""
import argparse
import ast
from collections import Counter
from pathlib import Path
import re
import subprocess


BASELINE = '163f46ba2e355654a477a62073441dd61bbecb5a'
PREFIX = 'ucon_trailcam_smtp.'
PROBES = {'probe', 'cloud_probe', 'smtp_probe'}
MOVED = {
    'smtp_probe': {
        'load_image': 'mail_message',
        'build_message': 'mail_message',
        'send_message': 'mail_message',
        'read_smtp_settings': 'smtp_settings',
    },
    'cloud_probe': dict.fromkeys((
        'ApiError', 'post_json', 'discover_devices', 'list_devices',
        'authenticate', 'get_device_by_uid', 'list_cloud_events',
    ), 'cloud_api'),
    'probe': dict.fromkeys(('DiagnosticRelay', 'relay_compat'), 'sdk_relay'),
}
SDK_MODULES = {
    'p4p_camera_sdk.credentials': 'sdk_credentials',
    'p4p_camera_sdk.sdcard': 'sdk_sdcard',
    'p4p_camera_sdk.sdcard_client': 'sdk_sdcard',
}
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def commit_id(value):
    if not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('Require a full lowercase commit ID')
    return value


def target_module(module, name):
    module = module.removeprefix(PREFIX).removeprefix('tools.')
    return MOVED.get(module, {}).get(name, SDK_MODULES.get(module, module))


class Normalize(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        # Keep imported names and aliases, preserving evaluation order. Only
        # normalize the explicitly documented relocation/re-export boundaries.
        if node.level or node.module is None:
            return node
        return [ast.ImportFrom(module=target_module(node.module, name.name),
                               names=[name], level=0) for name in node.names]


def shape(node):
    return ast.dump(Normalize().visit(node), include_attributes=False)


def definitions(tree):
    result = {}
    for node in tree.body:
        if isinstance(node, DEFS):
            if node.name in result:
                raise ValueError('Duplicate top-level definition: ' + node.name)
            result[node.name] = node
    return result


def statements(tree):
    return [shape(node) for i, node in enumerate(tree.body)
            if not isinstance(node, (*DEFS, ast.Import, ast.ImportFrom))
            and not (i == 0 and isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Constant)
                     and isinstance(node.value.value, str))]


def imports(tree):
    # Inventory top-level imports separately: splitting modules necessarily
    # changes their global import sets and import initialization timing.
    result = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            result.extend((target_module(node.module or '', a.name), a.name, a.asname, node.level)
                          for a in node.names)
        elif isinstance(node, ast.Import):
            result.extend(('', a.name, a.asname, 0) for a in node.names)
    return Counter(result)


def load(root, commit, path):
    return ast.parse(git(root, 'show', commit + ':' + path), filename=path)


def compare(root, baseline, candidate):
    baseline, candidate = commit_id(baseline), commit_id(candidate)
    old_paths = git(root, 'ls-tree', '-r', '--name-only', baseline).decode().splitlines()
    new_paths = git(root, 'ls-tree', '-r', '--name-only', candidate).decode().splitlines()
    old = {Path(p).stem: load(root, baseline, p) for p in old_paths
           if '/' not in p and p.endswith('.py') and not p.startswith('test_')}
    new = {Path(p).stem: load(root, candidate, p) for p in new_paths
           if re.fullmatch(r'(src/ucon_trailcam_smtp|tools)/[^/]+\.py', p)
           and Path(p).stem != '__init__'}
    if not old or not new:
        raise ValueError('Missing baseline or candidate modules')
    old_defs = {module: definitions(tree) for module, tree in old.items()}
    new_defs = {module: definitions(tree) for module, tree in new.items()}
    matched = set()
    unchanged = 0
    differences = []
    for module, defs in sorted(old_defs.items()):
        for name, node in sorted(defs.items()):
            target = MOVED.get(module, {}).get(name, module)
            other = new_defs.get(target, {}).get(name)
            if other is None:
                differences.append('MISSING definition: ' + module + '.' + name)
                continue
            matched.add((target, name))
            if shape(node) == shape(other):
                unchanged += 1
            else:
                differences.append('CHANGED definition: ' + module + '.' + name
                                   + ' -> ' + target + '.' + name)
    for module, defs in sorted(new_defs.items()):
        for name in sorted(defs):
            if (module, name) not in matched:
                differences.append('ADDED definition: ' + module + '.' + name)
    import_changes = []
    for module, tree in sorted(old.items()):
        if module not in new:
            differences.append('MISSING module: ' + module)
            continue
        if statements(tree) != statements(new[module]):
            differences.append('CHANGED module statements: ' + module)
        if imports(tree) != imports(new[module]):
            import_changes.append(module)
    for module in sorted(set(new) - set(old)):
        if statements(new[module]):
            differences.append('ADDED module statements: ' + module)
        import_changes.append(module + ' (new module)')
    return old, new, unchanged, differences, import_changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    old, new, unchanged, differences, import_changes = compare(root, args.baseline, args.candidate)
    print('Baseline:', args.baseline)
    print('Candidate:', args.candidate)
    print(f'Modules inspected: {len(old)} baseline, {len(new)} candidate')
    print(f'Unchanged normalized definitions: {unchanged}')
    print(f'Definition/module statement findings: {len(differences)}')
    for item in differences:
        print(item)
    print('Top-level import inventory differences:')
    for item in import_changes:
        print('  ' + item)
    print('Structural review complete; findings require review, not an automatic pass.')


if __name__ == '__main__':
    main()
