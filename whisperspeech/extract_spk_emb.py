# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/2A. Speaker Embeddings.ipynb.

# %% auto 0
__all__ = []

# %% ../nbs/2A. Speaker Embeddings.ipynb 3
import os
from os.path import expanduser
import sys

from fastprogress import progress_bar
from fastcore.script import *
import webdataset as wds
import torch
import torch.nn.functional as F
from torch.utils.data.dataloader import DataLoader

from . import vad, utils

try:
    # 0.5.16
    from speechbrain.pretrained import EncoderClassifier
except: # 1.0.0
    from speechbrain.inference.classifiers import EncoderClassifier
from .inference import get_compute_device

# %% ../nbs/2A. Speaker Embeddings.ipynb 5
def calc_len(x):
    x['seconds'] = torch.tensor(x['tend'] - x['tstart'])
    return x

def chunked_dataset(input, bs=16):
    ds = utils.vad_dataset([input]).compose(
        utils.resampler(16000, 'samples_16k'),
        wds.map(calc_len),
        wds.to_tuple('__key__', 'samples_16k', 'seconds'),
        wds.batched(bs),
    )
    dl = DataLoader(ds, num_workers=1, batch_size=None)
    return dl

# %% ../nbs/2A. Speaker Embeddings.ipynb 13
@call_parse
def process_shard(
    input:str,          # input shard URL/path
    output:str,         # output shard URL/path
    batch_size:int=16,        # batch size
    n_samples:int=None, # limit the number of samples (useful for quick benchmarking)
):
    device = get_compute_device()
    if n_samples is None: total = 'noinfer'
    else: total = n_samples // batch_size

    dl = chunked_dataset(input, bs=batch_size)
    
    classifier = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb",
                                                savedir=expanduser("~/.cache/speechbrain/"),
                                                run_opts = {"device": device})
    
    with utils.AtomicTarWriter(output) as sink:
        for keys, samples, seconds in progress_bar(dl, total=total):
            with torch.no_grad():
                embs = classifier.encode_batch(samples, wav_lens=seconds/30).squeeze(1)
            for key, emb in zip(keys, embs):
                sink.write({
                    "__key__": key,
                    "spk_emb.npy": emb.cpu().numpy(),
                })
        if n_samples is not None:
            sink.abort = True
        sys.stdout.write("\n")
