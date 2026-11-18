import os
import sys
import tempfile
import unittest
from pathlib import Path
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class ProtocolTests(unittest.TestCase):
    def test_stdio_discovery_and_query(self):
        async def check():
            with tempfile.TemporaryDirectory() as root:
                Path(root,'a.py').write_text('def hello():\n    return 1\n')
                params=StdioServerParameters(command=sys.executable,args=['-m','codeatlas.server'],env={**os.environ,'CODEATLAS_ROOT':root})
                with anyio.fail_after(15):
                    async with stdio_client(params) as (read,write):
                        async with ClientSession(read,write) as session:
                            await session.initialize()
                            names={t.name for t in (await session.list_tools()).tools}
                            self.assertEqual(names,{'index_repository','find_symbols','summarize_module','get_call_graph','find_impacted_tests'})
                            indexed=await session.call_tool('index_repository',{})
                            self.assertFalse(indexed.isError)
                            found=await session.call_tool('find_symbols',{'query':'hello'})
                            self.assertFalse(found.isError)
                            self.assertIn('a.py:hello',str(found.content))
        anyio.run(check)
