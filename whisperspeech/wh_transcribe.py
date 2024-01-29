# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/2A. Whisper quantization dataset preparation.ipynb.

# %% auto 0
__all__ = []

# %% ../nbs/2A. Whisper quantization dataset preparation.ipynb 3
import os
import io
import time
import torch
import torchaudio

# %% ../nbs/2A. Whisper quantization dataset preparation.ipynb 4
from pathlib import Path
import json
from fastprogress import progress_bar, master_bar
import numpy as np
import random

import whisper

from torch import nn
import torch.nn.functional as F
from torch.utils.data.dataloader import DataLoader

from fastcore.script import *

from . import vad, utils
import webdataset as wds

# %% ../nbs/2A. Whisper quantization dataset preparation.ipynb 9
# let's make it a bit more conservative
# with full 30 second chunks it sometimes misses a small part of the transcript
def random_cutter(dur):
    if random.random() < 0.5:
        return dur > 28 * (random.random()*0.95+0.05)
    else:
        return dur > 28

def chunk_merger(segments, should_cut=lambda x: x > 28):
    if len(segments) == 0: return segments
    curr_start = segments[0][0]
    curr_end = 0
    merged = []

    for ts,te in segments:
        if should_cut(te - curr_start) and curr_end - curr_start > 0:
            merged.append((curr_start, curr_end))
            curr_start = ts
        curr_end = te
    merged.append((curr_start, curr_end))
    return merged

# %% ../nbs/2A. Whisper quantization dataset preparation.ipynb 18
def merge_in(*datasets):
    """Merge multiple datasets into the current one returning samples with the union of keys.
    
    It requires (and validates) all datasets to have the same ordering of keys so you have
    to use it before any sample shuffling. Shard shuffling is ok.
    """
    def merge_loop(main_samples):
        for samples in zip(*[main_samples]+[iter(x) for x in datasets]):
            key = samples[0]['__key__']
            news = {}
            for s in samples:
                assert s['__key__'] == key
                news.update(s)
            yield news
    return merge_loop

# %% ../nbs/2A. Whisper quantization dataset preparation.ipynb 19
import copy

# %% ../nbs/2A. Whisper quantization dataset preparation.ipynb 20
# a workaround for https://github.com/webdataset/webdataset/issues/297
# should be possible to use ds.compose here
def wds_compose(ds, *args):
    ds = copy.copy(ds)
    ds.pipeline = copy.copy(ds.pipeline)
    for f in args:
        ds.append(f)
    return ds

# %% ../nbs/2A. Whisper quantization dataset preparation.ipynb 24
def split_to_chunks(stream, ikey='vad.npy', pad_to_seconds=30, random_shift=False):
    for s in stream:
        audio, sr = s['audio']
        imax = len(s[ikey]) - 1
        for i,(ts,te) in enumerate(s[ikey]):
            samples = audio[0,int(ts*sr):int(te*sr)]
            if pad_to_seconds is not None:
                padding = pad_to_seconds*sr-samples.shape[-1]
                lpad = random.randint(0, padding) if random_shift else 0
                samples = F.pad(samples, (lpad, padding-lpad))
            yield {"__key__": s['__key__'] + f"_{i:03d}",
                   "__url__": s['__url__'],
                   "i": i, "imax": imax,
                   "tstart": ts, "tend": te, "total_seconds": audio.shape[-1]/sr,
                   "lpad": lpad, "rpad": padding-lpad,
                   "lpad_s": lpad/sr, "rpad_s": (padding-lpad)/sr,
                   "samples": samples, "sample_rate": sr}

# %% ../nbs/2A. Whisper quantization dataset preparation.ipynb 39
def flac_to_txt_name(input, model_size):
    return input.rsplit("/", 1)[1].replace('flac', f'{model_size}-txt') + ".gz"

@call_parse
def process_shard(
    input:str,          # input shard URL/path
    output:str=None,    # output shard URL/path
    bs:int=None,        # batch size (16 uses around 11GB of VRAM)
    n_samples:int=None, # limit the number of samples (useful for quick benchmarking)
    whisper_model:str="base.en", # Whisper model size
    language:str="en",  # transcription language
):
    if output is None: output = flac_to_txt_name(input, whisper_model)
    if bs is None: bs = 16
    if n_samples is None: n_samples = 'noinfer'
    else: n_samples = n_samples // bs

    ds = wds_compose(vad.load_dataset(input),
        merge_in(wds.WebDataset(vad.flac_to_vad_name(input)).decode()),
        wds.map_dict(**{"vad.npy":chunk_merger}),
        split_to_chunks,
        utils.resampler(16000, 'samples_16k'),
        wds.to_tuple('__key__', 'samples_16k'),
        wds.batched(bs),
    )
    dl = DataLoader(ds, num_workers=2, batch_size=None)
    
    whmodel = whisper.load_model(whisper_model)
    decoding_options = whisper.DecodingOptions(language=language)
    
    tmp = output+".tmp"
    with wds.TarWriter(tmp) as sink:
        for keys, samples in progress_bar(dl, total=n_samples):
            with torch.no_grad():
                embs = whmodel.encoder(whisper.log_mel_spectrogram(samples).cuda())
                decs = whmodel.decode(embs, decoding_options)
            for key, dec in zip(keys, decs):
                sink.write({
                    "__key__": key,
                    "txt": dec.text,
                })
    os.rename(tmp, output)
