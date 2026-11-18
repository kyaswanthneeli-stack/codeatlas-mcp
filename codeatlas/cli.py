import argparse
import json
from .index import Index

def main():
    p = argparse.ArgumentParser(description='Index Python code without executing it')
    p.add_argument('root')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('index')
    find = sub.add_parser('find'); find.add_argument('query')
    summary = sub.add_parser('summary'); summary.add_argument('path')
    graph = sub.add_parser('graph'); graph.add_argument('symbol')
    impacted = sub.add_parser('tests'); impacted.add_argument('symbol')
    a = p.parse_args()
    db = Index(a.root)
    try:
        if a.command == 'index': result = db.build()
        elif a.command == 'find': result = db.find_symbols(a.query)
        elif a.command == 'summary': result = db.summarize_module(a.path)
        elif a.command == 'graph': result = db.get_call_graph(a.symbol)
        else: result = db.find_impacted_tests(a.symbol)
        print(json.dumps(result, indent=2))
    finally:
        db.close()

if __name__ == '__main__': main()
