"""YeNo Polymarket US: bounded, resumable 20x250k research fit.

Use the complete *usable* historical US corpus in the final refit. Screen on
earlier-day train/later-day validation first, with market-equal weighting.
Frozen raw database and auxiliary data ensure restart reproducibility.
Historical prices are display prices, NOT executable fills or trading P&L.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import logging
import multiprocessing as mp
import os
import shutil
import sqlite3
import time
import traceback
from pathlib import Path
from queue import Empty

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F

from market_us.collector import DB
from market_us.exogenous import STORE, build_features
from market_us.models import FEATURES, CONTEXT
from market_us.models_experimental import match_budget_40
from market_us.train_sweep import build, metrics, query, standardize
from market_us.sweep40 import write_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "experiments/results/us-20-250k-all-days"
KINDS = (
    "kan_mixer", "simple_rnn", "stacked_rnn", "lag_gated_mlp", "lstm",
    "skip_gru_2", "diagonal_ssm", "lowrank_mlp", "tcn_gru", "random_fourier",
    "wavelet_mlp", "crossnet", "multidecay_ssm", "regime_moe",
    "multiscale_gru", "projected_gru", "conv_gru", "depthwise_tcn",
    "spectral_gate", "tsmixer",
)
LOG = logging.getLogger("yeno.us.250k")
SHARED: dict = {}
EMBARGO = 7200


def snapshot_db(src: Path, out: Path) -> None:
    if out.exists():
        return
    tmp = out.with_suffix(".partial")
    if tmp.exists():
        tmp.unlink()
    with sqlite3.connect(f"file:{src.resolve()}?mode=ro", uri=True) as original:
        with sqlite3.connect(tmp) as frozen:
            original.backup(frozen)
    tmp.replace(out)


def snapshot_auxiliary(src: Path, out: Path) -> None:
    out.mkdir(exist_ok=True, parents=True)
    if (out/"snapshot.json").exists():
        return
    manifest={}
    for path in src.glob("*.parquet"):
        dest=out/path.name
        shutil.copy2(path,dest)
        manifest[path.name]=hashlib.sha256(dest.read_bytes()).hexdigest()
    write_json(out/"snapshot.json",manifest)


def day_folds(data, shift=0):
    days=sorted(d for d,n in zip(*np.unique(data["dates"],return_counts=True)) if n>=100)
    if len(days)<20:
        raise ValueError(f"Need >=20 usable days, found {len(days)}")
    # Both retrospective tests use only earlier dates for training. The
    # exposed Nov 3/4 dates are exploratory, not fresh unseen holdouts.
    folds=[]
    for stop in (len(days)-12-shift,len(days)-6-shift):
        tr_days=days[:stop]
        val_days=days[stop:stop+5]
        vstart=int(pd.Timestamp(str(val_days[0]),tz="UTC").timestamp())
        end=data["times"] + np.where(data["h"]==0,900,3600)
        tr=np.flatnonzero(np.isin(data["dates"],tr_days)&(end<vstart-EMBARGO))
        va=np.flatnonzero(np.isin(data["dates"],val_days))
        if min(len(tr),len(va)) < 500:
            raise ValueError(f"Insufficient fold rows {len(tr)}/{len(va)}")
        folds.append((tr,va,{"train_days":list(tr_days),"validation_days":list(val_days),
                             "train_rows":len(tr),"validation_rows":len(va)}))
    # All observed settled days become eligible for final model fitting, but
    # the final fitted models must not claim a clean evaluation on those days.
    return folds, np.arange(len(data["y"])), list(days)


def attach_asof_features(data, training_indices: np.ndarray, store: Path):
    times=data["times"]
    order=np.argsort(times,kind="stable")
    inv=np.empty(len(times),dtype=np.int64)
    inv[order]=np.arange(len(times))
    frame=build_features(store,pd.Series(pd.to_datetime(times[order],unit="s",utc=True)),
                         include_revised=False)
    timestamps=frame["decision_at"].astype("int64").to_numpy()//1_000_000_000
    if not np.array_equal(timestamps,times[order]):
        raise ValueError("As-of feature rows became misaligned")
    accepted, report=[],{}
    for name in frame.columns:
        if name=="decision_at":
            continue
        # Avoid nonstationary ETF level prices; use returns/changes instead.
        if name.endswith("__value") and name.startswith(
            ("sp500_spy","nasdaq_qqq","gold_gld","oil_uso","usd_uup")):
            continue
        vals=pd.to_numeric(frame[name],errors="coerce").to_numpy(dtype="float64")[inv]
        good=np.isfinite(vals)
        covered=float(good[training_indices].mean())
        observed=vals[training_indices][good[training_indices]]
        unique=np.std(observed) if len(observed) else 0
        usable=covered>=0.95 and unique>1e-8
        report[name]={"accepted":bool(usable),"train_coverage":round(covered,5)}
        if not usable:
            continue
        lo,hi=np.quantile(observed,[0.001,0.999])
        median=np.median(observed)
        vals[~good]=median
        vals=np.clip(vals,lo,hi)
        accepted.append((name,vals.astype("float32")))
    if not accepted:
        raise ValueError("No sufficiently covered auxiliary features")
    data["c"]=np.column_stack([data["c"]]+[v for _,v in accepted]).astype("float32")
    return {"accepted":[name for name,_ in accepted],
            "base_context":CONTEXT, "context_dim":data["c"].shape[1],
            "coverage":report,"no_revision_sensitive_macro":True,
            "coinbase_recent_only_excluded_when_insufficient_coverage":True}


def market_weights(data, idx):
    _, inverse, counts=np.unique(data["slugs"][idx],return_inverse=True,
                                 return_counts=True)
    val=1.0/counts[inverse]
    val/=val.mean()
    out=np.zeros(len(data["y"]),dtype="float32")
    out[idx]=val
    return torch.from_numpy(out)


def score(prob, idx):
    data=SHARED["data"]
    y,h,slugs=data["y"][idx],data["h"][idx],data["slugs"][idx]
    ans=metrics(prob,y,h)
    p=np.clip(prob.astype("float64"),1e-5,1-1e-5)
    loss=-(y*np.log(p)+(1-y)*np.log(1-p))
    _,inverse,count=np.unique(slugs,return_inverse=True,return_counts=True)
    ans["market_equal_logloss"]=float(np.mean(np.bincount(inverse,weights=loss)/count))
    phase=data["phase"][idx]
    ans["phases"]={}
    for key,mask in (("early",phase<1/3),
                     ("middle",(phase>=1/3)&(phase<2/3)),
                     ("late",phase>=2/3)):
        if mask.sum():
            ans["phases"][key]={"n":int(mask.sum()),
                                  "logloss":float(loss[mask].mean()),
                                  "accuracy":float(np.mean((p[mask]>=0.5)==y[mask]))}
    return ans


class MarketResidual(nn.Module):
    def __init__(self, name, params, context, dropout):
        super().__init__()
        self.core,self.audit=match_budget_40(name,params,context_dim=context)
        self.dropout=dropout
        self.core.head.add_module("dropout",nn.Dropout(dropout))
        nn.init.zeros_(self.core.binary.weight)
        nn.init.zeros_(self.core.binary.bias)

    def forward(self,x,c,p,head):
        if self.training and self.dropout:
            numeric=F.dropout1d(x[:,:,:16].transpose(1,2),
                                p=self.dropout,training=True).transpose(1,2)
            x=torch.cat((numeric,x[:,:,16:]),dim=-1)
            c=torch.cat((c[:,:2],F.dropout(c[:,2:],p=self.dropout,
                                            training=True)),dim=-1)
        out=self.core(x,c)
        delta=out["binary_logits"].gather(1,head[:,None]).squeeze(-1)
        return torch.logit(p.clamp(1e-4,1-1e-4))+0.45*delta, delta


def predict(model,idx,batch=640):
    tensor=SHARED["tensor"];pred=[]
    model.eval()
    with torch.inference_mode():
        for start in range(0,len(idx),batch):
            ids=torch.as_tensor(idx[start:start+batch],dtype=torch.long)
            logits,_=model(tensor["x"][ids],tensor["c"][ids],
                            tensor["display"][ids],tensor["h"][ids])
            pred.append(torch.sigmoid(logits).numpy())
    return np.concatenate(pred)


def one_job(name,fold_id,train,dev,args,out,deadline,epochs=None):
    torch.set_num_threads(args.threads_per_worker)
    tensors=SHARED["tensor"]
    random_seed=args.seed+KINDS.index(name)
    torch.manual_seed(random_seed)
    model=MarketResidual(name,args.params,tensors["c"].shape[-1],args.dropout)
    optimizer=torch.optim.AdamW(model.parameters(),lr=args.lr,
                                 weight_decay=args.weight_decay)
    weights=market_weights(SHARED["data"],train)
    baseline=score(SHARED["data"]["display"][dev],dev) if dev is not None else None
    best=baseline["market_equal_logloss"] if dev is not None else float("inf")
    chosen=0
    best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    history=[]
    count=epochs if epochs is not None else args.max_epochs
    for epoch in range(1,count+1):
        if time.monotonic()>deadline-120:
            raise TimeoutError("Approaching training window end")
        model.train()
        shuffled=torch.as_tensor(train,dtype=torch.long)
        generator=torch.Generator().manual_seed(random_seed+fold_id*100+epoch)
        shuffled=shuffled[torch.randperm(len(shuffled),generator=generator)]
        total=0.
        for ids in shuffled.split(args.batch_size):
            optimizer.zero_grad(set_to_none=True)
            logits,delta=model(tensors["x"][ids],tensors["c"][ids],
                                tensors["display"][ids],tensors["h"][ids])
            loss=F.binary_cross_entropy_with_logits(logits,tensors["y"][ids],
                                                     reduction="none")
            loss=((loss+args.residual_penalty*delta.square())*weights[ids]).mean()
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite model loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(),1.)
            optimizer.step()
            total+=loss.item()*len(ids)
        if dev is not None:
            dscore=score(predict(model,dev),dev)
            objective=dscore["market_equal_logloss"]
            if objective < best-0.00005:
                best,chosen=objective,epoch
                best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
        else:
            chosen=epoch
            best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
            dscore=None
        history.append({"epoch":epoch,
                        "train_loss":total/len(train),
                        "dev_market_equal_loss":objective if dev is not None else None})
        if dev is not None and epoch-chosen >= 2:
            break
        if time.monotonic()>deadline-120:
            break
    model.load_state_dict(best_state)
    row={"kind":name,"fold":fold_id,"train_rows":len(train),"dev_rows":len(dev) if dev is not None else 0,
         "parameters":model.audit["params"],"epochs":len(history),"chosen_epoch":chosen,
         "history":history,"baseline":baseline,
         "dev":score(predict(model,dev),dev) if dev is not None else None}
    half={k:v.half() if torch.is_floating_point(v) else v
          for k,v in best_state.items()}
    torch.save({"kind":name,"target":args.params,
                "context_dim":tensors["c"].shape[-1],
                "dropout":args.dropout,"state_dict":half,
                "float32_training":True,"fp16_checkpoint":True,
                "stage":fold_id,"selected_epoch":chosen},
               out/(name+".pt"))
    write_json(out/(name+".json"),row)
    return row


def worker(jobs,fold_id,train,dev,args,folder,deadline,production_epochs):
    torch.set_num_threads(args.threads_per_worker)
    while time.monotonic()<deadline-120:
        try:
            name=jobs.get_nowait()
        except Empty:
            return
        result=folder/(name+".json")
        if result.exists():
            continue
        try:
            # Every selected architecture receives a final all-days fit.
            # Record whether it beat the baseline separately: fitting is
            # research, not authorization to deploy a losing model.
            ep=max(1,production_epochs[name]) if production_epochs is not None else None
            one_job(name,fold_id,train,dev,args,folder,deadline,ep)
            LOG.info("FINISHED %s %s",fold_id,name)
        except TimeoutError:
            LOG.warning("TIME BUDGET stopping %s/%s; retry later",fold_id,name)
            return
        except Exception as exc:
            LOG.error("FAILED %s %s: %s",fold_id,name,exc)
            write_json(folder/(name+".error.json"),
                       {"error":repr(exc),"traceback":traceback.format_exc()})


def stage(name,stage_id,train,dev,args,deadline,production_epochs=None):
    folder=args.output/name
    folder.mkdir(parents=True,exist_ok=True)
    remaining=[kind for kind in KINDS if not (folder/(kind+".json")).exists()]
    if remaining:
        ctx=mp.get_context("fork")
        jobs=ctx.Queue()
        for kind in remaining: jobs.put(kind)
        workers=[ctx.Process(target=worker,args=(jobs,stage_id,train,dev,args,
                    folder,deadline,production_epochs)) for _ in range(args.workers)]
        for w in workers:w.start()
        for w in workers:w.join()
    rows=[json.loads((folder/(kind+".json")).read_text())
          for kind in KINDS if (folder/(kind+".json")).exists()]
    write_json(args.output/(name+"_progress.json"),
               {"stage":name,"finished":len(rows),"target":len(KINDS),
                "rows":[{"kind":r["kind"],"selected_epoch":r["chosen_epoch"],
                         "dev_market_equal_loss":r["dev"]["market_equal_logloss"] if r.get("dev") else None}
                        for r in rows]})
    return len(rows)==len(KINDS)


def run(args):
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/"run.lock").open("w") as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.warning("Already running; refusing duplicate training")
            return
        db=args.output/"frozen_us.sqlite3"
        snapshot_db(args.db,db)
        aux=args.output/"frozen_exogenous"
        snapshot_auxiliary(STORE,aux)
        raw,history,reference=query(db)
        data,info=build(raw,history,reference)
        folds,all_idx,days=day_folds(data,args.fold_shift)
        data["phase"]=data["c"][:,3].copy()
        feature_audit=attach_asof_features(data,folds[0][0],aux)
        write_json(args.output/"feature_audit.json",feature_audit)
        scalers=standardize(data,folds[0][0])
        write_json(args.output/"scalers.json",scalers)
        SHARED["data"]=data
        SHARED["tensor"]={k:torch.from_numpy(np.ascontiguousarray(data[k]))
                           for k in ("x","c","y","h","display")}
        write_json(args.output/"manifest.json",{
            "models":list(KINDS),"target_params":args.params,
            "samples":len(data["y"]),"all_usable_days":days,
            "date_count":len(days),"folds":[m for _,_,m in folds],
            "features":feature_audit["accepted"],"context_dim":data["c"].shape[1],
            "data_warning":"Historical display prices are NOT executable fills",
            "evaluation_warning":"All dates are retrospectively exposed through prior experiments",
            "final_stage":"Train every usable day only after validation. No holdout claim for final refit.",
            "run_started":dt.datetime.now(dt.timezone.utc).isoformat(),
            "settings":{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}})
        deadline=time.monotonic()+args.max_minutes*60
        for number,(tr,dev,meta) in enumerate(folds):
            if not stage(f"fold{number+1}",number+1,tr,dev,args,deadline):
                LOG.info("PAUSED after fold %d",number+1)
                return
        frozen_epochs={}
        comparisons={}
        for kind in KINDS:
            records=[json.loads((args.output/f"fold{i}"/(kind+".json")).read_text())
                     for i in (1,2)]
            losses=[r["dev"]["market_equal_logloss"] for r in records]
            bases=[r["baseline"]["market_equal_logloss"] for r in records]
            wins=sum(a<b for a,b in zip(losses,bases))
            # No cherry-pick: only promote if beats the market on BOTH folds.
            frozen_epochs[kind]=min(r["chosen_epoch"] for r in records) if wins==2 else 0
            comparisons[kind]={"model":losses,"market":bases,"wins":wins,
                               "final_epochs":frozen_epochs[kind]}
        write_json(args.output/"fold_comparisons.json",comparisons)
        if not stage("all_days_fit",3,all_idx,None,args,deadline,frozen_epochs):
            LOG.info("PAUSED production fit")
            return
        write_json(args.output/"finished.json",{
            "complete":True,"days_used_in_final_fit":len(days),
            "models_compared":len(KINDS),
            "models_eligible_for_further_validation":sum(x>0 for x in frozen_epochs.values()),
            "models_fitted_on_all_days":len(KINDS),
            "note":"All architectures are exploratory; final fits have no unbiased holdout. No P&L claims."})
        LOG.info("COMPLETE 20/20 two-fold comparisons; final all-dates fit complete")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--db",type=Path,default=DB)
    parser.add_argument("--output",type=Path,default=OUTPUT)
    parser.add_argument("--params",type=int,default=250000)
    parser.add_argument("--batch-size",type=int,default=192)
    parser.add_argument("--workers",type=int,default=3)
    parser.add_argument("--threads-per-worker",type=int,default=2)
    parser.add_argument("--max-epochs",type=int,default=3)
    parser.add_argument("--dropout",type=float,default=0.18)
    parser.add_argument("--lr",type=float,default=0.00025)
    parser.add_argument("--weight-decay",type=float,default=0.02)
    parser.add_argument("--residual-penalty",type=float,default=0.03)
    parser.add_argument("--fold-shift",type=int,default=0)
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--max-minutes",type=int,default=89)
    args=parser.parse_args()
    assert args.workers*args.threads_per_worker<=6
    assert args.max_minutes<=90
    assert 0<=args.fold_shift<=12
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    torch.set_num_threads(2)
    run(args)


if __name__=="__main__":
    main()
