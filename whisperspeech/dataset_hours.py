# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/D. Dataset hours calculation.ipynb.

# %% auto 0
__all__ = []

# %% ../nbs/D. Dataset hours calculation.ipynb 1
import webdataset as wds
from whisperspeech import utils
from fastcore.script import call_parse

# %% ../nbs/D. Dataset hours calculation.ipynb 4
def calc_hours(x):
    if x['vad.npy'].size == 0: return 0
    x = x['vad.npy']
    return (x[-1,1] - x[0,0]) / 3600

# %% ../nbs/D. Dataset hours calculation.ipynb 6
@call_parse
def process_ds(
    input_glob:str
):
    ds = wds.WebDataset(utils.shard_glob(input_glob)).compose(
        wds.decode(),
        wds.map(calc_hours),
    )
    dl = wds.WebLoader(ds, num_workers=16, batch_size=None)
    hours = sum(x for x in dl)
    print(f"Total hours: {hours:.1f}")
    return hours
