"""Analyze actual A53 timer reports. Never supplies estimated results."""
from pathlib import Path
import hashlib,json,statistics
ROOT=Path(__file__).resolve().parent
JOB=Path(r'C:\Users\jay\Desktop\CEG_5203\Final_Project\ldpc_fpga_terminal\runs\realterm_20261024_235333_529436\request_1')
meta=json.loads((JOB/'results.json').read_text())
fpga=meta['results'][0]
assert meta['exact_dataset_input'] and meta['input_mode']=='fixed_dataset_llr'
raw=Path(meta['source_llr']).read_bytes()
assert hashlib.sha256(raw).hexdigest()==meta['llr_sha256']==meta['dataset_llr_sha256']
assert raw==(JOB/'input_llr.f32').read_bytes()
assert fpga['dataset_reference_bit_mismatches']==0
lines=(ROOT/'a53_fixed_reports.txt').read_text().splitlines()
reports=[[int(x,0) for x in line.split()] for line in lines if line.strip() and not line.startswith('#')]
assert len(reports)==6,'Need 1 warmup + 5 measurements'
times=[]
for seq,r in enumerate(reports,1):
 assert len(r)==42 and r[0]==0x43505542 and r[2]==3 and r[4]==seq
 assert r[5]==6081 and r[6]==20 and r[7]==6081 and r[8]==0
 assert r[15]==fpga['max_actual_iterations']
 assert r[16]==sum(int(k)*v for k,v in fpga['actual_iteration_histogram'].items())
 for i in range(21):assert r[20+i]==fpga['actual_iteration_histogram'].get(str(i),0)
 ticks=r[11]+(r[12]<<32);hz=r[9]+(r[10]<<32)
 times.append(ticks*1000/hz)
a=(ROOT/'a53_fixed_decoded.u8').read_bytes();b=(JOB/'decoded.u8').read_bytes()
assert len(a)==len(b)==6081*384,'Output size mismatch'
mismatch=sum(x!=y for x,y in zip(a,b))
assert mismatch==0,f'A53/FPGA bit mismatch: {mismatch}'
reference=Path(meta['dataset_reference_path']).read_bytes()
assert a==reference,'A53 output differs from teammate reference'
median=statistics.median(times[1:])
result=dict(source='Physical A53 XTime measurements, single core, plain C O3, per-word early stop',
 frames=6081,iteration_limit=20,input_sha256=hashlib.sha256((JOB/'input_llr.f32').read_bytes()).hexdigest(),
 warmup_ms=times[0],measured_ms=times[1:],a53_median_ms=median,
 fpga_dma_ms=fpga['fpga_dma_ms'],fpga_measurement_note='Fixed-dataset physical FPGA single run, not a five-run median',
 a53_over_fpga_speedup=median/fpga['fpga_dma_ms'],a53_cpu_hz=reports[0][41],timer_hz=hz,
 output_bit_mismatches=mismatch,teammate_reference_bit_mismatches=0,exact_dataset_input=True,
 timing_includes='A53 input/message initialization, NMS, stopping checks, per-word control; warm caches',
 timing_excludes='JTAG, staging copies, validation, output files, UART',
 cache_policy='I/D caches enabled, computation buffers in cacheable DDR',
 fpga_reference_results=str(JOB/'results.json'))
(ROOT/'comparison_fixed_llr.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
print(f"\nA53 median: {median:.3f} ms; FPGA+DMA: {fpga['fpga_dma_ms']:.3f} ms; speedup: {result['a53_over_fpga_speedup']:.3f}x")
