"""Physical FPGA demonstration; fixed teammate LLR, no synthetic timing.
Generated/edited with OpenAI Codex. Original codec/dataset credits retained.
"""
from pathlib import Path
from datetime import datetime
import argparse, csv, hashlib, json, os, statistics, threading
import fpga_bridge as bridge
from fixed_llr import make_fixed_job
from terminal_common import save_result, save_manifest, parse_limits

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / 'dataset'

def cases():
    return json.loads((DATASET/'manifest.json').read_text(encoding='utf-8-sig'))['cases']

ATTACH_RUNNING = False

def configure(version):
    if version not in ('v1','v2','v3'):
        raise ValueError('Select v1, v2 or v3')
    cfg = json.loads((ROOT/version/'config.json').read_text(encoding='utf-8-sig'))
    meta = json.loads((ROOT/version/'hardware_manifest.json').read_text(encoding='utf-8'))
    for key in ('firmware','bitstream','fsbl'):
        path = (ROOT/version/cfg[key]).resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest() != meta['artifacts'][key]['sha256']:
            raise ValueError(f'{version} hardware integrity failed: {key}')
        cfg[key] = str(path)
    cfg["attach_running"] = ATTACH_RUNNING
    bridge.load_config = lambda: dict(cfg)
    return meta

class BoardLock:
    """Prevent this package's UI and batch from controlling JTAG concurrently."""
    def __enter__(self):
        import msvcrt
        self.f = (ROOT/'board.lock').open('a+b')
        self.f.seek(0); self.f.write(b'0'); self.f.flush(); self.f.seek(0)
        try: msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.f.close()
            raise RuntimeError('Another demo is using the board. Close it first.')
        return self
    def __exit__(self,*_):
        import msvcrt
        self.f.seek(0); msvcrt.locking(self.f.fileno(),msvcrt.LK_UNLCK,1); self.f.close()

def summarize(rows):
    values = [r['fpga_dma_ms'] for r in rows if r['phase']=='measured']
    if len(values)!=5: raise ValueError('Exactly five measured runs are required')
    # Reject nondeterministic output rather than silently averaging failures.
    if len({r['output_sha256'] for r in rows})!=1:
        raise ValueError('Output differs across repeated identical inputs')
    return dict(mean_ms=statistics.mean(values),median_ms=statistics.median(values),
                min_ms=min(values),max_ms=max(values),stdev_ms=statistics.stdev(values),
                measured_runs=5,warmup_runs=sum(r['phase']=='warmup' for r in rows))

def write_csv(path, rows):
    if not rows: return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def run_case(version,case,limits,directory,batch,initialize,event,cancel):
    job,codec,data,manifest = make_fixed_job(DATASET/case['llr'],limits,directory)
    manifest.update(version=version,hardware=configure(version),
                    startup_mode="vitis_attach_user_selected_version" if ATTACH_RUNNING else "automatic",
                    measurement_policy='one excluded warmup, five measured runs; arithmetic mean' if batch else 'one run per iteration limit; no averaging')
    save_manifest(job,manifest)
    records=[]
    def relay(kind,message):
        if kind!='result':
            event(kind,message);return
        limit,path,report=message
        ordinal=len(records)
        phase=('warmup' if ordinal==0 else 'measured') if batch else 'single'
        sub=job/(f'warmup' if phase=='warmup' else f'run_{ordinal:02d}' if batch else f'iteration_{limit}')
        sub.mkdir()
        import shutil
        output=sub/'decoded.u8';shutil.copyfile(path,output)
        submanifest=dict(manifest,results=[])
        result=save_result(sub,codec,data,submanifest,limit,output,report)
        mismatch=result.get('dataset_reference_bit_mismatches')
        if mismatch is not None and mismatch!=0:
            raise RuntimeError(f'Dataset reference mismatch: {mismatch}; run excluded, batch aborted')
        record=dict(result,version=version,case=case['id'],iteration_limit=limit,phase=phase,
                    run=ordinal if batch else 1,llr_sha256=manifest['llr_sha256'],
                    output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                    dataset_reference_bit_mismatches=mismatch)
        records.append(record)
        write_csv(job/'runs.csv',records)
        manifest['results']=records;save_manifest(job,manifest)
        event('sample',dict(record=record,image=str(sub/f'iteration_{limit}.png'),
                            comparison=str(sub/f'comparison_{limit}.png')))
    try:
        bridge.run_hardware(data.llr,limits,job/'transport',initialize,relay,cancel)
        manifest['completed']=True
        if batch: manifest['statistics']=summarize(records)
        save_manifest(job,manifest)
    except Exception as exc:
        manifest.update(completed=False,error=str(exc));save_manifest(job,manifest);raise
    return manifest

def batch_run(versions,selected,limit=20,event=lambda k,m:print(f'{k}: {m}',flush=True),cancel=None):
    cancel=cancel or threading.Event()
    session=ROOT/'results'/('batch_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    session.mkdir(parents=True)
    summaries=[]
    with BoardLock():
        for version in versions:
            for index,case in enumerate(selected):
                if cancel.is_set(): raise bridge.Cancelled('Cancelled')
                event('stage',f'{version} / {case["id"]}: 1 warmup + 5 measured runs')
                manifest=run_case(version,case,[limit]*6,session/version/case['id'],True,index==0,event,cancel)
                row=dict(version=version,case=case['id'],iteration_limit=limit,
                         llr_sha256=manifest['llr_sha256'],**manifest['statistics'],
                         payload_bit_errors=manifest['results'][-1]['payload_bit_errors'],
                         payload_ber=manifest['results'][-1]['payload_ber'],
                         mean_actual_iterations=manifest['results'][-1]['mean_actual_iterations'])
                summaries.append(row);write_csv(session/'summary.csv',summaries)
                event('stage',f'{version} / {case["id"]}: MEAN = {row["mean_ms"]:.3f} ms')
        # Fair per-image ratios, never confuse individual and whole-dataset means.
        ratios=[]
        for case in selected:
            by={r['version']:r['mean_ms'] for r in summaries if r['case']==case['id']}
            row=dict(case=case['id'],**{v+'_mean_ms':t for v,t in by.items()})
            for old,new in [('v1','v2'),('v1','v3'),('v2','v3')]:
                if old in by and new in by:row[new+'_speedup_vs_'+old]=by[old]/by[new]
            ratios.append(row)
        write_csv(session/'comparison.csv',ratios)
    return session

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--version',choices=['v1','v2','v3','all'],default='all')
    p.add_argument('--case',default='all',help='all or exact dataset case ID')
    p.add_argument('--iterations',type=int,default=20)
    p.add_argument("--attach-running",action="store_true",help="Use controller already started by Vitis; no reset, bitstream programming or firmware download")
    p.add_argument('--validate-only',action='store_true')
    a=p.parse_args()
    global ATTACH_RUNNING
    ATTACH_RUNNING = a.attach_running
    if ATTACH_RUNNING and a.version == "all":
        p.error("Attach mode requires one explicit --version, matching Vitis hardware")
    versions=['v1','v2','v3'] if a.version=='all' else [a.version]
    selected=[c for c in cases() if a.case=='all' or c['id']==a.case]
    if not selected:raise ValueError('Case not found')
    if not 0<=a.iterations<=20:raise ValueError('Iterations must be 0..20')
    if a.validate_only:
        for v in versions:configure(v)
        for c in selected:
            import tempfile
            (ROOT/'results').mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='verify_',dir=ROOT/'results') as temp:
                make_fixed_job(DATASET/c['llr'],[20],Path(temp)/'case')
            print('VERIFIED',c['id'],flush=True)
        return
    if ATTACH_RUNNING:
        print('ATTACH MODE: Vitis must have started the matching controller. Do not reset or run another debugger.\nHardware version is user-selected, not automatically identified. JTAG input upload briefly halts A53 outside timing.',flush=True)
    else:
        print('Close Vitis debug sessions, RealTerm bridges and other FPGA UIs.\n'
          'Board will be reset and initialized automatically.\n'
          'JTAG transfer can take minutes; the measured FPGA timer excludes it.',flush=True)
    print('SAVED:',batch_run(versions,selected,a.iterations),flush=True)

if __name__=='__main__':main()
