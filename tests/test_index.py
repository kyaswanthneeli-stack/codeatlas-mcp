import tempfile
import unittest
from pathlib import Path
from codeatlas.index import Index

class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'maths.py').write_text('def add(a,b):\n    return a+b\n\ndef twice(x):\n    return add(x,x)\n')
        (self.root/'test_maths.py').write_text('from maths import twice as double\ndef test_twice():\n    assert double(2)==4\n')
        self.db = Index(self.root)
        self.db.build()
    def tearDown(self):
        self.db.close(); self.tmp.cleanup()
    def test_symbols(self):
        self.assertEqual(len(self.db.find_symbols('maths.py:')),3)
    def test_direct_call(self):
        edge=self.db.get_call_graph('maths.py:twice')['edges'][0]
        self.assertEqual(edge['callee'],'maths.py:add')
    def test_import_alias(self):
        self.assertEqual(self.db.get_call_graph('test_maths.py:test_twice')['edges'][0]['callee'],'maths.py:twice')
    def test_transitive_test_impact(self):
        self.assertIn('test_maths.py:test_twice',self.db.find_impacted_tests('maths.py:add')['tests'])
    def test_path_escape(self):
        with self.assertRaises(ValueError):self.db.summarize_module('../secret.py')
    def test_deleted_files_removed(self):
        (self.root/'test_maths.py').unlink();self.db.build()
        self.assertEqual(self.db.find_impacted_tests('maths.py:add')['tests'],[])
    def test_syntax_error_reported(self):
        (self.root/'broken.py').write_text('def broken(')
        self.assertEqual(len(self.db.build()['errors']),1)
    def test_unresolved_retained(self):
        (self.root/'dynamic.py').write_text('def run(obj):\n    return obj.method()\n')
        self.db.build();self.assertEqual(self.db.get_call_graph('dynamic.py:run')['edges'][0]['resolution'],'unresolved')
    def test_cycle_bounded(self):
        (self.root/'cycle.py').write_text('def a():\n    b()\ndef b():\n    a()\n')
        self.db.build();self.assertEqual(len(self.db.get_call_graph('cycle.py:a',5)['edges']),2)
    def test_package_relative_import(self):
        (self.root/'pkg').mkdir();(self.root/'pkg/__init__.py').write_text('')
        (self.root/'pkg/a.py').write_text('def f():\n    pass\n')
        (self.root/'pkg/b.py').write_text('from .a import f\ndef g():\n    f()\n')
        self.db.build();self.assertEqual(self.db.get_call_graph('pkg/b.py:g')['edges'][0]['callee'],'pkg/a.py:f')
    def test_nested_functions(self):
        (self.root/'nested.py').write_text('def outer():\n    def inner():\n        pass\n    inner()\n')
        self.db.build();self.assertEqual(self.db.get_call_graph('nested.py:outer')['edges'][0]['callee'],'nested.py:outer.inner')
    def test_graph_limit(self):
        g=self.db.get_call_graph('test_maths.py:test_twice',5,max_edges=1)
        self.assertEqual(len(g['edges']),1);self.assertTrue(g['truncated'])
    def test_database_root_bound(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(ValueError):Index(other,self.db.database)
    def test_symlink_file_ignored(self):
        (self.root/'linked.py').symlink_to(self.root/'maths.py')
        self.assertEqual(self.db.build()['files'],2)
    def test_duplicate_definition_omitted(self):
        (self.root/'duplicate.py').write_text('def same(): pass\ndef same(): pass\n')
        self.assertEqual(self.db.build()['duplicate_symbols_omitted'],1)

if __name__=='__main__':unittest.main()
