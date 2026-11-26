"""Model count, budget and causal input/output contract smoke tests."""
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from market_us.models import (CONTEXT, FEATURES, HISTORY, KINDS, USMarketModel,
                              match_budget, parameters)

def test_20_distinct_models_and_budget():
    assert len(KINDS) == len(set(KINDS)) == 20
    for kind in KINDS:
        model, record = match_budget(kind)
        assert abs(record.deviation_pct) <= 6
        assert parameters(model) == record.parameters

@pytest.mark.parametrize("kind", KINDS)
def test_forward_backward(kind):
    torch.set_num_threads(2)
    model, record = match_budget(kind)
    x = torch.randn(2, HISTORY, FEATURES)
    x[..., -1] = 1
    context = torch.randn(2, CONTEXT)
    out = model(x, context)
    assert set(out) == {"binary_logits", "next_features"}
    assert out["binary_logits"].shape == (2, 2)
    assert out["next_features"].shape == (2, FEATURES)
    loss = out["binary_logits"].square().mean() + out["next_features"].square().mean()
    loss.backward()
    assert torch.isfinite(loss)
    assert all(p.grad is None or torch.isfinite(p.grad).all()
               for p in model.parameters())


def test_reject_invalid_batch():
    model = USMarketModel("gru", 32)
    with pytest.raises(ValueError):
        model(torch.zeros(2, HISTORY, FEATURES), torch.zeros(3, CONTEXT))
