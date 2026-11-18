"""AST extraction and conservative static name resolution. Never imports target code."""
import ast
import hashlib
import json
import os
import sqlite3
from pathlib import Path

IGNORE = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'build', 'dist', '.tox'}
MAX_FILE_BYTES = 1_000_000

class Index:
    def __init__(self, root, database=None):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('Repository root must be a directory')
        self.database = Path(database) if database else self.root / '.codeatlas.sqlite3'
        self.db = sqlite3.connect(self.database)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, module TEXT, digest TEXT, lines INTEGER);
        CREATE TABLE IF NOT EXISTS symbols(id TEXT PRIMARY KEY, path TEXT, module TEXT, name TEXT, qualname TEXT, kind TEXT, line INTEGER, end_line INTEGER, signature TEXT, doc TEXT);
        CREATE TABLE IF NOT EXISTS calls(caller TEXT, target TEXT, line INTEGER, callee TEXT, resolution TEXT);
        ''')
        saved = self.db.execute("SELECT value FROM meta WHERE key='root'").fetchone()
        if saved and saved['value'] != str(self.root):
            self.db.close()
            raise ValueError('Database belongs to another repository')
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('root', ?)", (str(self.root),))
        self.db.commit()

    def close(self):
        self.db.close()

    def _path(self, path):
        candidate = (self.root / path).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError('Path escapes repository root')
        return candidate

    def build(self):
        files, symbols, raw_calls, aliases, errors = [], [], [], {}, []
        for folder, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in IGNORE and not Path(folder, d).is_symlink())
            for name in sorted(names):
                path = Path(folder, name)
                if path.suffix != '.py' or path.is_symlink():
                    continue
                rel = path.relative_to(self.root).as_posix()
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        raise ValueError('File exceeds 1 MB limit')
                    source = path.read_text(encoding='utf-8')
                    tree = ast.parse(source, filename=rel)
                except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
                    errors.append({'path': rel, 'error': str(exc)[:240]})
                    continue
                module = rel[:-3].replace('/', '.')
                if module.endswith('.__init__'):
                    module = module[:-9]
                files.append((rel, module, hashlib.sha256(source.encode()).hexdigest(), len(source.splitlines())))
                mapping = {}
                # Only module-level imports are treated as reliable bindings.
                for node in tree.body:
                    if isinstance(node, ast.Import):
                        for item in node.names:
                            mapping[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
                    elif isinstance(node, ast.ImportFrom):
                        base = node.module or ''
                        if node.level:
                            package = module.split('.') if name == '__init__.py' else module.split('.')[:-1]
                            keep = max(0, len(package) - node.level + 1)
                            base = '.'.join(package[:keep] + ([base] if base else []))
                        for item in node.names:
                            if item.name != '*':
                                mapping[item.asname or item.name] = (base + '.' + item.name).strip('.')
                aliases[rel] = mapping
                outer = self
                class Visitor(ast.NodeVisitor):
                    def __init__(self):
                        self.stack = []
                        self.function = []
                    def visit_ClassDef(self, node):
                        qual = '.'.join(self.stack + [node.name])
                        symbols.append((rel + ':' + qual, rel, module, node.name, qual, 'class', node.lineno, node.end_lineno, 'class ' + node.name, (ast.get_docstring(node) or '')[:400]))
                        self.stack.append(node.name)
                        for child in node.body:
                            self.visit(child)
                        self.stack.pop()
                    def visit_FunctionDef(self, node):
                        qual = '.'.join(self.stack + [node.name])
                        sid = rel + ':' + qual
                        prefix = 'async def ' if isinstance(node, ast.AsyncFunctionDef) else 'def '
                        signature = prefix + node.name + '(' + ast.unparse(node.args)[:400] + ')'
                        symbols.append((sid, rel, module, node.name, qual, 'function', node.lineno, node.end_lineno, signature, (ast.get_docstring(node) or '')[:400]))
                        self.stack.append(node.name)
                        self.function.append(sid)
                        # Body only: decorators/default arguments run in the surrounding scope.
                        for child in node.body:
                            self.visit(child)
                        self.function.pop()
                        self.stack.pop()
                    visit_AsyncFunctionDef = visit_FunctionDef
                    def visit_Call(self, node):
                        if self.function:
                            target = ast.unparse(node.func)[:300]
                            raw_calls.append((self.function[-1], rel, target, node.lineno))
                        self.generic_visit(node)
                Visitor().visit(tree)
        # IDs are stable file:qualified-name strings. Duplicate definitions remain ambiguous.
        counts = {}
        for symbol in symbols:
            counts[symbol[0]] = counts.get(symbol[0], 0) + 1
        unique = {s[0]: s for s in symbols if counts[s[0]] == 1}
        by_full = {}
        for s in unique.values():
            by_full.setdefault(s[2] + '.' + s[4], []).append(s[0])
        resolved = []
        for caller, rel, target, line in raw_calls:
            candidates = []
            if target.isidentifier():
                scope = caller.split(':', 1)[1].split('.')
                # Search lexical scopes, then module scope; this is not runtime binding analysis.
                for depth in range(len(scope), -1, -1):
                    sid = rel + ':' + '.'.join(scope[:depth] + [target])
                    if sid in unique:
                        candidates = [sid]
                        break
            if not candidates:
                first, *rest = target.split('.')
                if first in aliases.get(rel, {}):
                    full = '.'.join([aliases[rel][first]] + rest)
                    candidates = by_full.get(full, [])
            callee = candidates[0] if len(candidates) == 1 else None
            resolved.append((caller, target, line, callee, 'static_candidate' if callee else 'unresolved'))
        with self.db:
            for table in ['files', 'symbols', 'calls']:
                self.db.execute('DELETE FROM ' + table)
            self.db.executemany('INSERT INTO files VALUES (?,?,?,?)', files)
            self.db.executemany('INSERT INTO symbols VALUES (?,?,?,?,?,?,?,?,?,?)', unique.values())
            self.db.executemany('INSERT INTO calls VALUES (?,?,?,?,?)', resolved)
        return {'files': len(files), 'symbols': len(unique), 'calls': len(resolved), 'resolved_candidates': sum(bool(c[3]) for c in resolved), 'errors': errors, 'duplicate_symbols_omitted': sum(v > 1 for v in counts.values()), 'analysis': 'Static candidates, not proof of runtime calls. Reindex after source changes.'}

    def find_symbols(self, query, limit=20):
        limit = min(100, max(1, limit))
        return [dict(r) for r in self.db.execute('SELECT id,kind,signature,line,end_line FROM symbols WHERE instr(lower(id),lower(?))>0 ORDER BY id LIMIT ?', (query, limit))]

    def summarize_module(self, path, limit=50):
        rel = self._path(path).relative_to(self.root).as_posix()
        file = self.db.execute('SELECT * FROM files WHERE path=?', (rel,)).fetchone()
        if not file:
            raise ValueError('Module is not indexed')
        rows = self.db.execute('SELECT id,kind,signature,line,end_line,doc FROM symbols WHERE path=? ORDER BY line LIMIT ?', (rel, min(100, max(1, limit)))).fetchall()
        count = self.db.execute('SELECT count(*) FROM symbols WHERE path=?', (rel,)).fetchone()[0]
        return {'file': dict(file), 'symbols': [dict(r) for r in rows], 'truncated': count > len(rows)}

    def get_call_graph(self, symbol_id, depth=2, direction='outgoing', max_edges=100):
        if direction not in ('outgoing', 'incoming'):
            raise ValueError('direction must be outgoing or incoming')
        if not self.db.execute('SELECT 1 FROM symbols WHERE id=?', (symbol_id,)).fetchone():
            raise ValueError('Unknown symbol ID')
        depth = min(5, max(0, depth))
        max_edges = min(500, max(1, max_edges))
        frontier, visited, edges, seen = [symbol_id], {symbol_id}, [], set()
        truncated = False
        for level in range(depth):
            next_frontier = []
            for sid in frontier:
                field = 'caller' if direction == 'outgoing' else 'callee'
                for row in self.db.execute('SELECT * FROM calls WHERE ' + field + '=? ORDER BY line,target', (sid,)):
                    key = tuple(row)
                    if key in seen:
                        continue
                    if len(edges) >= max_edges:
                        truncated = True
                        break
                    seen.add(key)
                    edges.append(dict(row))
                    nxt = row['callee'] if direction == 'outgoing' else row['caller']
                    if nxt and nxt not in visited:
                        visited.add(nxt)
                        next_frontier.append(nxt)
            frontier = next_frontier
        return {'root': symbol_id, 'direction': direction, 'edges': edges, 'truncated': truncated, 'depth_limit': depth, 'warning': 'Static candidates may be wrong when names are rebound or shadowed; unresolved dynamic calls are retained.'}

    def find_impacted_tests(self, symbol_id, depth=5):
        graph = self.get_call_graph(symbol_id, depth, 'incoming', 500)
        ids = {symbol_id} | {e['caller'] for e in graph['edges']}
        tests = []
        for sid in sorted(ids):
            path, qualname = sid.split(':', 1)
            if Path(path).name.startswith('test_') or Path(path).name.endswith('_test.py'):
                tests.append(sid)
        return {'tests': tests, 'truncated': graph['truncated'], 'warning': 'Potentially impacted tests inferred from static call candidates. Not a complete test selection system; dynamic fixtures and indirect calls may be missed.'}
