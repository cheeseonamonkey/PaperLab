"""Polymarket US 20-model CPU screening on all authentic, usable US records.

Uses real settled outcomes + timestamped official BTC candle/contract *display*
history. Historic display prices are NOT executable quotes; no P&L claims.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import logging
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from market_us.collector import DB
from market_us.models import KINDS, HISTORY, FEATURES, CONTEXT, match_budget

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments/results/us-20-150k-first"
LOG = logging.getLogger("yeno.us.sweep")
UTC = dt.timezone.utc


def query(db: Path):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        con.execute("BEGIN")
        m = pd.read_sql_query(
            "SELECT slug,horizon_min,window_start,window_end,settlement "
            "FROM markets WHERE settlement IN ('0','1') ORDER BY window_start", con)
        h = pd.read_sql_query(
            "SELECT slug,sample_at,up_display,down_display FROM historical_prices "
            "ORDER BY slug,sample_at", con)
        b = pd.read_sql_query(
            "SELECT sample_at,open,high,low,close,tick_count,bucket_sec "
            "FROM btc_reference ORDER BY sample_at", con)
        con.commit()
        return m,h,b
    finally:
        con.close()


REFERENCE_COLUMNS = ("open", "high", "low", "close", "tick_count")


def normalize_reference(frame):
    """Return one 60-second bar per minute from mixed 60s/15s reference rows.

    The live reference collector moved from 60s to 15s buckets on 2026-11-05.
    Training requires minute bars, so aggregate sub-minute rows up to the
    minute floor and keep native minute rows where they already exist. A bar
    stamped t still only becomes usable at t+60 (see build()).
    """
    if frame.empty:
        return frame
    if "bucket_sec" not in frame:
        return frame.drop_duplicates("sample_at")
    native = frame[frame.bucket_sec >= 60].copy()
    native = native.sort_values("sample_at").drop_duplicates("sample_at")
    sub = frame[frame.bucket_sec < 60].copy()
    pieces = [native]
    if not sub.empty:
        sub["sample_at"] = (sub.sample_at // 60) * 60
        agg = (sub.groupby("sample_at", as_index=False)
                  .agg(open=("open", "first"), high=("high", "max"),
                       low=("low", "min"), close=("close", "last"),
                       tick_count=("tick_count", "sum")))
        agg = agg[~agg.sample_at.isin(set(native.sample_at))]
        pieces.append(agg)
    out = pd.concat(pieces, ignore_index=True)
    out["bucket_sec"] = 60
    return out.sort_values("sample_at").reset_index(drop=True)


def build(m, h, b):
    if b.empty or h.empty or m.empty:
        raise ValueError("No authentic settled US history + BTC reference data")
    # A minute bar stamped t is first usable at t+60.
    b = normalize_reference(b).set_index("sample_at")
    grid = np.arange(int(b.index.min()), int(b.index.max()) + 60, 60)
    b = b.reindex(grid)
    close = pd.to_numeric(b.close, errors="coerce")
    log = np.log(close.where(close > 0))
    ret = (log - log.shift(1)) * 1000
    candle_range = np.log(pd.to_numeric(b.high, errors="coerce") /
                          pd.to_numeric(b.low, errors="coerce")) * 1000
    features = np.stack([
        ret.fillna(0).to_numpy(),
        ((log - log.shift(5))*1000).fillna(0).to_numpy(),
        ((log - log.shift(15))*1000).fillna(0).to_numpy(),
        ((log - log.shift(60))*1000).fillna(0).to_numpy(),
        ret.rolling(15, min_periods=15).std().fillna(0).to_numpy(),
        ret.rolling(60, min_periods=60).std().fillna(0).to_numpy(),
        candle_range.replace([np.inf,-np.inf],np.nan).fillna(0).to_numpy(),
        (pd.to_numeric(b.tick_count, errors="coerce")/60).fillna(0).to_numpy(),
        log.fillna(0).to_numpy(),
    ],axis=1).astype("float32")
    base_idx = {int(t)+60:i for i,t in enumerate(grid) if np.isfinite(close.iloc[i])}
    by_slug = {}
    for slug,g in h.groupby("slug",sort=False):
        by_slug[slug] = {int(r.sample_at)+60:(float(r.up_display),float(r.down_display))
                         for r in g.itertuples(index=False)
                         if pd.notna(r.up_display) and pd.notna(r.down_display)}
    def build_market(market):
        start,end,horizon = int(market.window_start),int(market.window_end),int(market.horizon_min)
        if horizon not in (15,60) or end-start != horizon*60:
            return None
        ref_idx=base_idx.get(start)
        quotes=by_slug.get(market.slug,{})
        if ref_idx is None or not quotes:
            return None
        reference=float(features[ref_idx,8])
        # Build a causal 120-minute sequence through the last valid decision.
        times=np.arange(start-(HISTORY-1)*60,end+60,60)
        seq=np.zeros((len(times),FEATURES),dtype="float32")
        previous=None
        for j,t in enumerate(times):
            i=base_idx.get(int(t))
            if i is not None:
                seq[j,:8]=features[i,:8]
                seq[j,9]=(features[i,8]-reference)*1000
                seq[j,17]=1.0
            active=start <= t < end
            if active:
                seq[j,10]=max(0,(end-t)/(horizon*60))
                seq[j,11]=(t-start)/(horizon*60)
                seq[j,18]=1.0
                seq[j,19]=float(horizon==60)
                q=quotes.get(int(t))
                if q is not None:
                    up,down=q
                    seq[j,12:14]=up,down
                    seq[j,14]=up-previous if previous is not None else 0
                    seq[j,15]=up+down-1
                    seq[j,16]=1.0
                    previous=up
            phase=2*np.pi*((t%86400)/86400)
            seq[j,20]=np.sin(phase)
            seq[j,21]=np.cos(phase)
            # Historical volume data absent: channel 22=0; gap=1 minute.
            seq[j,23]=1.0
        date=dt.datetime.fromtimestamp(start, UTC).date().isoformat()
        rows=[]
        for t in range(start+60,end,60):
            j=(t-times[0])//60
            if not seq[j,16] or not seq[j,17] or seq[j-HISTORY+1:j+1,17].sum()<60:
                continue
            rows.append((j,t))
        if not rows:
            return None
        return date,seq,rows,horizon,market,quotes

    # Two-pass build: keeping one window per market (~70 MB for 6k markets)
    # instead of one Python tuple per decision sample (~1.6 GB) avoids the
    # OOM that killed the 52-day run on this 11 GB host.
    plans=[]
    counts=defaultdict(int)
    for market in m.itertuples(index=False):
        plan=build_market(market)
        if plan is not None:
            plans.append(plan)
            counts[plan[0]]+=len(plan[2])
    if not plans:
        raise ValueError("No dated US decision samples")
    total=sum(len(p[2]) for p in plans)
    data={
        "x":np.empty((total,HISTORY,FEATURES),dtype="float32"),
        "c":np.empty((total,12),dtype="float32"),
        "y":np.empty(total,dtype="float32"),
        "h":np.empty(total,dtype="int64"),
        "next":np.empty((total,FEATURES),dtype="float32"),
        "display":np.empty(total,dtype="float32"),
        "slugs":np.empty(total,dtype=object),
        "times":np.empty(total,dtype="int64"),
        "dates":np.empty(total,dtype=object),
    }
    cursor=0
    for date,seq,rows,horizon,market,quotes in plans:
        for j,t in rows:
            curr=seq[j]
            data["x"][cursor]=seq[j-HISTORY+1:j+1]
            data["c"][cursor]=[int(horizon==15),int(horizon==60),
                curr[10],curr[11],curr[9],curr[12],curr[13],
                curr[4],curr[5],curr[20],curr[21],curr[16]]
            data["y"][cursor]=float(market.settlement)
            data["h"][cursor]=int(horizon==60)
            data["next"][cursor]=seq[j+1]
            data["display"][cursor]=float(quotes[int(t)][0])
            data["slugs"][cursor]=market.slug
            data["times"][cursor]=t
            data["dates"][cursor]=date
            cursor+=1
    dates=sorted(counts)
    if len(dates)<3:
        raise ValueError(f"Only {len(dates)} dated US samples, need 3+")
    return data, {"samples":cursor,"date_rows":dict(counts),
                  "market_rows":len(m),"display_rows":len(h),"btc_candles":len(b),
                  "sample_cadence_seconds":60,
                  "warning":"History display values, NOT executable past bid/ask."}


def split(data):
    counts=Counter(data["dates"])
    good=sorted(d for d,n in counts.items() if n>=100)
    if len(good)<3:
        raise ValueError(f"Need >=3 independent dates >=100 observations: {dict(counts)}")
    dev,final=good[-2:]
    dev_start=int(dt.datetime.fromisoformat(dev).replace(tzinfo=UTC).timestamp())
    final_start=int(dt.datetime.fromisoformat(final).replace(tzinfo=UTC).timestamp())
    horizon=np.where(data["h"]==0,900,3600)
    # Whole-day split with 2h embargo before validation day boundaries.
    tr=np.where((data["dates"]<dev)&(data["times"]+horizon<dev_start-7200))[0]
    va=np.where((data["dates"]==dev)&(data["times"]+horizon<final_start-7200))[0]
    te=np.where(data["dates"]==final)[0]
    if min(len(tr),len(va),len(te))<100:
        raise ValueError("Split too small")
    return (tr,va,te),{"train_dates":sorted(set(data["dates"][tr])),
                       "dev_date":dev,"sealed_date":final,
                       "rows":{"train":len(tr),"dev":len(va),"sealed":len(te)},
                       "embargo_seconds":7200}


def standardize(data,tr):
    # Fit every scaler ONLY on preceding training dates.
    xm=data["x"][tr].mean((0,1),dtype="float64")
    xs=data["x"][tr].std((0,1),dtype="float64")
    cm=data["c"][tr].mean(0,dtype="float64")
    cs=data["c"][tr].std(0,dtype="float64")
    xs=np.maximum(xs,1e-3);cs=np.maximum(cs,1e-3)
    data["x"]=np.clip((data["x"]-xm)/xs,-8,8).astype("float32")
    data["next"]=np.clip((data["next"]-xm)/xs,-8,8).astype("float32")
    data["c"]=np.clip((data["c"]-cm)/cs,-8,8).astype("float32")
    # Preserve actual nonnegative minute-gap values for continuous-time cells.
    data["x"][:,:,-1]=1.0
    data["next"][:,-1]=1.0
    return {"x_mean":xm.tolist(),"x_std":xs.tolist(),
            "c_mean":cm.tolist(),"c_std":cs.tolist()}


def batches(data,idx,batch_size,shuffle=False,seed=42):
    vals=tuple(torch.from_numpy(np.ascontiguousarray(data[k][idx]))
               for k in ("x","c","y","h","next"))
    return DataLoader(TensorDataset(*vals),batch_size=batch_size,
                      shuffle=shuffle,generator=torch.Generator().manual_seed(seed))


def metrics(p,y,h):
    p=np.clip(p,1e-5,1-1e-5)
    def calc(z):
        return {"n":int(z.sum()),
                "logloss":float(np.mean(-y[z]*np.log(p[z])-(1-y[z])*np.log(1-p[z]))),
                "brier":float(np.mean((p[z]-y[z])**2)),
                "accuracy":float(np.mean((p[z]>=0.5)==y[z]))}
    return {"overall":calc(np.ones(len(y),dtype=bool)),
            "15m":calc(h==0) if (h==0).any() else None,
            "1h":calc(h==1) if (h==1).any() else None}


def evaluate(model,loader):
    model.eval()
    p=[];y=[];h=[]
    with torch.inference_mode():
        for x,c,target,head,_ in loader:
            o=model(x,c)["binary_logits"].gather(1,head[:,None]).squeeze(1)
            p.append(torch.sigmoid(o).numpy());y.append(target.numpy());h.append(head.numpy())
    return metrics(np.concatenate(p),np.concatenate(y),np.concatenate(h))


def train_model(kind,data,train,dev,args,output):
    torch.manual_seed(args.seed)
    model,rec=match_budget(kind,150_000)
    opt=torch.optim.AdamW(model.parameters(),lr=args.lr,weight_decay=0.001)
    tr=batches(data,train,args.batch_size,True,args.seed)
    dv=batches(data,dev,256)
    best=float("inf");best_epoch=0;history=[];weights=None
    for epoch in range(args.epochs):
        model.train();losses=[];t=time.monotonic()
        for x,c,y,head,nxt in tr:
            opt.zero_grad(set_to_none=True)
            o=model(x,c)
            pred=o["binary_logits"].gather(1,head[:,None]).squeeze(1)
            bce=nn.functional.binary_cross_entropy_with_logits(pred,y)
            # Lightweight next-state auxiliary objective; no fake execution data.
            ssl=nn.functional.smooth_l1_loss(
                o["next_features"][:,[0,1,4,6,9,12,14]],
                nxt[:,[0,1,4,6,9,12,14]])
            loss=bce+0.03*ssl
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(),1.0)
            opt.step();losses.append(loss.item())
        dev_score=evaluate(model,dv)
        ll=dev_score["overall"]["logloss"]
        history.append({"epoch":epoch+1,"train_loss":float(np.mean(losses)),
                        "dev_logloss":ll,"seconds":round(time.monotonic()-t,1)})
        if ll<best-0.0003:
            best=ll;best_epoch=epoch+1
            weights={k:v.detach().clone().cpu() for k,v in model.state_dict().items()}
        if epoch+1>=3 and epoch+1-best_epoch>=2:
            break
    assert weights is not None
    model.load_state_dict(weights)
    result={"kind":kind,"params":rec.parameters,"width":rec.width,
            "best_epoch":best_epoch,"epochs_ran":len(history),
            "dev":evaluate(model,dv),"history":history,"checkpoint":kind+".pt"}
    torch.save({"kind":kind,"state_dict":weights,"seed":args.seed,
                "venue":"Polymarket US","price_data":"historical DISPLAY, not execution"},
               output/result["checkpoint"])
    return result


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument("--db",type=Path,default=DB)
    parser.add_argument("--output",type=Path,default=OUT)
    parser.add_argument("--epochs",type=int,default=5)
    parser.add_argument("--batch-size",type=int,default=64)
    parser.add_argument("--lr",type=float,default=0.001)
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--threads",type=int,default=2)
    parser.add_argument("--max-hours",type=float,default=3)
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    args.output.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(args.threads)
    np.random.seed(args.seed)
    started=time.monotonic()
    markets,history,spot=query(args.db)
    data,info=build(markets,history,spot)
    (train,dev,test),dates=split(data)
    info.update({"splits":dates,"source":"OFFICIAL Polymarket US",
                 "started":dt.datetime.now(UTC).isoformat(),
                 "goal":"out-of-sample probability screening, NOT claimed USD profit",
                 "configuration":vars(args)|{"output":str(args.output),"db":str(args.db)}})
    (args.output/"manifest.json").write_text(json.dumps(info,indent=2,default=str)+"\n")
    scalers=standardize(data,train)
    (args.output/"scalers.json").write_text(json.dumps(scalers)+"\n")
    baseline={"dev":metrics(data["display"][dev],data["y"][dev],data["h"][dev]),
              "sealed":None,
              "constant_dev":metrics(np.full(len(dev),data["y"][train].mean()),
                                     data["y"][dev],data["h"][dev])}
    (args.output/"baselines.json").write_text(json.dumps(baseline,indent=2)+"\n")
    LOG.info("ready: samples=%d splits=%s baseline_dev=%.4f",len(data["y"]),
             dates["rows"],baseline["dev"]["overall"]["logloss"])
    if args.dry_run:
        return
    rows=[]
    for j,kind in enumerate(KINDS,1):
        if time.monotonic()-started>args.max_hours*3600:
            LOG.warning("HARD TIME BUDGET stopping at %d / 20",len(rows))
            break
        LOG.info("START %d/20 %s",j,kind)
        t=time.monotonic()
        r=train_model(kind,data,train,dev,args,args.output)
        r["wall_seconds"]=round(time.monotonic()-t,1)
        rows.append(r)
        (args.output/"progress.json").write_text(
            json.dumps({"complete_models":len(rows),"target_models":20,
                        "rows":rows},indent=2)+"\n")
        LOG.info("DONE %d/20 %s dev_logloss=%.5f secs=%.1f",
                 j,kind,r["dev"]["overall"]["logloss"],r["wall_seconds"])
    if len(rows)==20:
        # Test remains sealed until every dev-selected checkpoint frozen.
        test_loader=batches(data,test,256)
        for row in rows:
            model,_=match_budget(row["kind"],150_000)
            bundle=torch.load(args.output/row["checkpoint"],map_location="cpu",weights_only=True)
            model.load_state_dict(bundle["state_dict"])
            row["sealed"]=evaluate(model,test_loader)
        baseline["sealed"]=metrics(data["display"][test],data["y"][test],data["h"][test])
        rows.sort(key=lambda x:x["dev"]["overall"]["logloss"])
        (args.output/"results.json").write_text(
            json.dumps({"completed":True,"ranking":"dev_logloss",
                        "elapsed_seconds":round(time.monotonic()-started,1),
                        "baselines":baseline,"models":rows},indent=2)+"\n")
        LOG.info("COMPLETE 20/20 best=%s dev=%.5f sealed=%.5f",
                 rows[0]["kind"],rows[0]["dev"]["overall"]["logloss"],
                 rows[0]["sealed"]["overall"]["logloss"])
    else:
        LOG.error("INCOMPLETE %d/20",len(rows))


if __name__=="__main__":
    run()
