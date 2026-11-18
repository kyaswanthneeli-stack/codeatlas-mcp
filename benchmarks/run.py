"""Reproducible synthetic structural-context benchmark; not an agent/token benchmark."""
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path
from codeatlas.index import Index

def main():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        # 100 files × 500 lines = 50,000 lines, deliberately comment-heavy.
        for i in range(100):
            body='def helper(x):\n    return x+1\n\ndef operation(x):\n    return helper(x)\n'
            lines=body.splitlines()+['# Synthetic background context, not representative production code.']*495
            (root/f'module_{i:03}.py').write_text('\n'.join(lines)+'\n')
        db=Index(root)
        start=time.perf_counter();summary=db.build();index_ms=(time.perf_counter()-start)*1000
        times=[]
        for _ in range(100):
            start=time.perf_counter();answer=db.get_call_graph('module_050.py:operation');times.append((time.perf_counter()-start)*1000)
        raw=(root/'module_050.py').read_bytes()
        encoded=json.dumps(answer,separators=(',',':')).encode()
        result={'python':platform.python_version(),'corpus':'100 generated Python files, 500 lines each; comment-heavy','lines':50000,'index_ms':round(index_ms,3),'warm_query_p50_ms':round(statistics.median(times),3),'warm_query_p95_ms':round(sorted(times)[94],3),'repetitions':100,'baseline':'one full 500-line module as UTF-8 bytes','baseline_bytes':len(raw),'call_graph_json_bytes':len(encoded),'byte_reduction_percent':round((1-len(encoded)/len(raw))*100,2),'index':summary,'limits':'Byte reduction only. No tokenizer, LLM, answer-quality or end-to-end agent measurement. A call graph is less informative than source. Synthetic comments exaggerate compression.'}
        db.close();print(json.dumps(result,indent=2))
if __name__=='__main__':main()
