"""Run with CODEATLAS_ROOT=/path/to/repo python -m codeatlas.server."""
import os
from mcp.server.fastmcp import FastMCP
from .index import Index

server = FastMCP('CodeAtlas')

def index():
    root = os.environ.get('CODEATLAS_ROOT')
    if not root:
        raise ValueError('Set CODEATLAS_ROOT to the repository directory')
    return Index(root, os.environ.get('CODEATLAS_DB'))

def invoke(method, *args):
    db = index()
    try:
        return getattr(db, method)(*args)
    finally:
        db.close()

@server.tool()
def index_repository() -> dict:
    """Rebuild a Python AST index in local SQLite. Does not import or execute target code."""
    return invoke('build')

@server.tool()
def find_symbols(query: str, limit: int = 20) -> list:
    """Find indexed file:qualified-name IDs and signatures. At most 100 results."""
    return invoke('find_symbols', query, limit)

@server.tool()
def summarize_module(path: str, limit: int = 50) -> dict:
    """Return indexed definitions, signatures and short docstrings for a repository-relative Python file."""
    return invoke('summarize_module', path, limit)

@server.tool()
def get_call_graph(symbol_id: str, depth: int = 2, direction: str = 'outgoing', max_edges: int = 100) -> dict:
    """Retrieve bounded static call candidates and unresolved calls; not runtime tracing."""
    return invoke('get_call_graph', symbol_id, depth, direction, max_edges)

@server.tool()
def find_impacted_tests(symbol_id: str, depth: int = 5) -> dict:
    """Find potentially impacted test symbols via reverse static call candidates; incomplete for dynamic Python."""
    return invoke('find_impacted_tests', symbol_id, depth)

if __name__ == '__main__':
    server.run(transport='stdio')
