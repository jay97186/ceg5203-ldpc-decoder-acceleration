"""Shared image preparation and hardware-result persistence; no software fallback."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import math
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from codec import Codec,prepare_image,evaluate
ROOT=Path(__file__).resolve().parent
BOUNDS={64:(64,48),128:(128,96),256:(256,192)}

def parse_limits(value):
    try:
        tokens=str(value).replace(';',',').replace('，',',').replace(' ',',').split(',')
        values=[int(v) for v in tokens if v]
    except ValueError:
        raise ValueError('Iterations must be integers from 0 to 20, separated by commas.') from None
    if not values or any(v<0 or v>20 for v in values):
        raise ValueError('Choose one or more iteration limits from 0 to 20.')
    return sorted(set(values))

def validate_settings(db,seed,size,limits):
    if not math.isfinite(db) or not -10<=db<=20:
        raise ValueError('Eb/N0 must be between -10 and 20 dB.')
    if not 0<=seed<=2147483647: raise ValueError('Seed must be from 0 to 2147483647.')
    if size not in BOUNDS: raise ValueError('Size must be 64, 128 or 256.')
    if not limits or any(type(v) is not int or not 0<=v<=20 for v in limits):
        raise ValueError('Iteration limits must be integers from 0 to 20.')

def resolve_image(value):
    text=str(value).strip().strip('"').strip("'")
    path=ROOT/'assets'/'demo.png' if text.lower()=='sample' else Path(text).expanduser()
    path=path.resolve()
    if not path.is_file(): raise FileNotFoundError(f'Image was not found: {path}')
    return path

def make_job(value,db,seed,size,limits,no_noise=False,directory=None):
    validate_settings(db,seed,size,limits)
    source=resolve_image(value)
    job=Path(directory) if directory else ROOT/'runs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    job.mkdir(parents=True,exist_ok=False)
    codec=Codec()
    data=prepare_image(source,codec,BOUNDS[size],db,seed,no_noise)
    if len(data.llr)>8192: raise ValueError('The FPGA controller supports at most 8192 codewords.')
    data.image.save(job/'original.png')
    data.received.save(job/'received.png')
    data.encoded.tofile(job/'encoded_tx.u8')
    data.llr.astype('<f4').tofile(job/'input_llr.f32')
    manifest=dict(source_image=str(source),ebn0_db=db,noise_seed=seed,no_noise=bool(no_noise),
        iteration_limits=limits,width=data.image.width,height=data.image.height,codewords=len(data.llr),
        payload_bits=int(data.payload_bits.size),llr_sha256=hashlib.sha256(data.llr.tobytes()).hexdigest(),
        channel='PC BPSK/AWGN; R=194/384; float32 LLR clipped +/-30',
        decoder='physical FPGA via AXI DMA; float32 flooding NMS alpha=.75, per-codeword early termination',
        timing_includes='ARM control, sequential TX/RX DMA, FPGA decode, polling',
        timing_excludes='PC noise/image preparation, JTAG transport, output packing, validation, UART',
        completed=False,results=[])
    save_manifest(job,manifest)
    return job,codec,data,manifest

def save_manifest(job,manifest):
    target=Path(job)/'results.json'
    tmp=target.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    tmp.replace(target)

def save_result(job,codec,data,manifest,limit,path,report,verify=False):
    words=np.fromfile(path,dtype='u1')
    if words.size!=len(data.llr)*384 or np.any(words>1):
        raise ValueError('The FPGA returned invalid output bits.')
    words=words.reshape(-1,384)
    image,metrics=evaluate(codec,data,words)
    result=dict(report,**metrics)
    if verify:
        expected=codec.reference(data.llr,limit)
        mismatch=int(np.count_nonzero(words!=expected))
        result['cpu_reference_mismatches']=mismatch
        if mismatch:
            manifest['error']=f'FPGA/CPU mismatch: {mismatch} bits at limit {limit}'
            manifest['results'].append(result);save_manifest(job,manifest)
            raise RuntimeError(manifest['error'])
    if manifest.get('input_mode')=='fixed_dataset_llr' and limit==manifest.get('dataset_reference_iterations'):
        reference=np.fromfile(manifest['dataset_reference_path'],dtype='u1')
        if reference.size!=words.size:
            raise ValueError('Dataset reference output size mismatch')
        result['dataset_reference_bit_mismatches']=int(np.count_nonzero(words.reshape(-1)!=reference))
        print(f"DATASET REFERENCE: output bit mismatches={result['dataset_reference_bit_mismatches']}",flush=True)
    image.save(Path(job)/f'iteration_{limit}.png')
    manifest['results'].append(result)
    make_comparison(data.image,data.received,image,limit,Path(job)/f'comparison_{limit}.png')
    save_manifest(job,manifest)
    print(f"RESULT iter={limit}: FPGA+DMA={report['fpga_dma_ms']:.3f} ms, "
          f"payload_errors={metrics['payload_bit_errors']}/{data.payload_bits.size}, "
          f"BER={metrics['payload_ber']:.8g}, mean_iterations={report['mean_actual_iterations']:.3f}",flush=True)
    return result

def make_comparison(original,received,decoded,limit,path):
    width,height=320,240
    out=Image.new('RGB',(3*width, height+52),'white')
    draw=ImageDraw.Draw(out)
    try: font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',18)
    except OSError: font=ImageFont.load_default()
    for index,(label,im) in enumerate([('Original',original),('Noisy received',received),(f'FPGA: limit {limit}',decoded)]):
        small=im.copy();small.thumbnail((width-16,height))
        out.paste(small,(index*width+(width-small.width)//2,44+(height-small.height)//2))
        draw.text((index*width+12,10),label,fill='black',font=font)
    out.save(path)
