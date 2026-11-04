"""Load a manifest-verified teammate LLR verbatim; never generate new noise.
Generated/edited with OpenAI Codex. Original dataset/algorithm credit retained.
"""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import math
import numpy as np
from PIL import Image
from codec import Codec,ImageInput,reconstruct
from terminal_common import ROOT,save_manifest


def make_fixed_job(value,limits,directory=None):
    if not limits or any(type(v) is not int or not 0<=v<=20 for v in limits):
        raise ValueError('Iterations must be integers from 0 to 20')
    llr_path=Path(str(value).strip().strip('"').strip("'")).expanduser().resolve()
    if not llr_path.is_file():
        raise FileNotFoundError(f'LLR file was not found: {llr_path}')
    manifest_path=next((p/'manifest.json' for p in llr_path.parents if (p/'manifest.json').is_file()),None)
    if manifest_path is None:
        raise ValueError('Expected dataset/cases/<case>/llr.f32 with dataset/manifest.json')
    dataset_root=manifest_path.parent
    metadata=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if (metadata.get('n'),metadata.get('k'),metadata.get('m'))!=(384,194,192):
        raise ValueError('Dataset must use the same LDPC (384,194), M=192')
    if metadata.get('schedule')!='flooding' or metadata.get('alpha')!=0.75 or metadata.get('clip')!=30.0:
        raise ValueError('Dataset decoding parameters do not match this FPGA')
    case=next((c for c in metadata['cases'] if (dataset_root/c['llr']).resolve()==llr_path),None)
    if case is None:
        raise ValueError('LLR is not a case listed in the dataset manifest')
    def verified(relative):
        path=(dataset_root/relative).resolve()
        if not path.is_relative_to(dataset_root):
            raise ValueError('Dataset path leaves its root')
        expected=metadata['files'][relative]
        content=path.read_bytes()
        if len(content)!=expected['bytes'] or hashlib.sha256(content).hexdigest()!=expected['sha256']:
            raise ValueError(f'Dataset integrity check failed: {relative}')
        return path,content
    # Exact code tables, not just the same nominal codeword length.
    for name in ['checks.i32','variable_edges.i32','info.i32','pivots.i32','parity_map.u8']:
        _,raw=verified('code/'+name)
        if raw!=(ROOT/'assets'/'code'/name).read_bytes():
            raise ValueError(f'Dataset LDPC code table differs from FPGA: {name}')
    _,raw=verified(case['llr'])
    digest=hashlib.sha256(raw).hexdigest()
    frames=int(case['frames'])
    if not 1<=frames<=8192 or len(raw)!=frames*384*4:
        raise ValueError('LLR byte count/frame count invalid')
    llr=np.frombuffer(raw,dtype='<f4').reshape(frames,384)
    if not np.all(np.isfinite(llr)) or np.any(np.abs(llr)>30):
        raise ValueError('Fixed LLR must be finite float32 in [-30,30]; no automatic clipping')
    image_path,_=verified(case['image'])
    tx_path,tx_raw=verified(case['tx'])
    reference_path,reference_raw=verified(case['reference'])
    if len(tx_raw)!=frames*384 or len(reference_raw)!=frames*384:
        raise ValueError('Dataset output/reference sizes invalid')
    with Image.open(image_path) as image_file:
        image=image_file.convert('RGB')
    if image.size!=(metadata['width'],metadata['height']):
        raise ValueError('Image dimensions differ from manifest')
    codec=Codec()
    bits=np.unpackbits(np.asarray(image,dtype='u1').reshape(-1),bitorder='big')
    encoded=np.frombuffer(tx_raw,dtype='u1').reshape(frames,384)
    if bits.size!=case['payload_bits'] or np.any(encoded>1) or codec.unsatisfied(encoded):
        raise ValueError('Dataset tx/bit count invalid')
    if not np.array_equal(codec.payload(encoded,bits.size),bits):
        raise ValueError('Dataset tx payload does not match source image')
    channel=case['channel']
    db=float(channel['ebn0_db']); sigma=float(channel['noise_sigma'])
    if not math.isfinite(db) or not math.isfinite(sigma) or sigma<0:
        raise ValueError('Invalid dataset channel metadata')
    data=ImageInput(image,bits,encoded,llr,reconstruct(codec,(llr<0).astype('u1'),image.size),sigma,db,int(case['noise_seed']))
    job=Path(directory) if directory else ROOT/'runs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    job.mkdir(parents=True,exist_ok=False)
    # WRITE ORIGINAL BYTES: no image resize, encoding, AWGN, clipping or float recomputation.
    (job/'input_llr.f32').write_bytes(raw)
    (job/'encoded_tx.u8').write_bytes(tx_raw)
    image.save(job/'original.png');data.received.save(job/'received.png')
    result=dict(source_image=str(image_path),source_llr=str(llr_path),input_mode='fixed_dataset_llr',
        dataset_manifest=str(manifest_path),dataset_case=case['id'],
        dataset_reference_path=str(reference_path),dataset_reference_iterations=metadata['iterations'],
        ebn0_db=db,noise_seed=data.seed,no_noise=False,iteration_limits=limits,
        width=image.width,height=image.height,codewords=frames,payload_bits=int(bits.size),
        llr_sha256=digest,dataset_llr_sha256=metadata['files'][case['llr']]['sha256'],
        exact_dataset_input=True,channel='Fixed dataset float32 LLR; copied byte-for-byte; no new noise',
        decoder='physical FPGA via AXI DMA; float32 flooding NMS alpha=.75, per-codeword early termination',
        timing_includes='ARM control, sequential TX/RX DMA, FPGA decode, polling',
        timing_excludes='dataset file loading/integrity verification, JTAG transport, output packing, validation, UART',
        completed=False,results=[])
    save_manifest(job,result)
    return job,codec,data,result
