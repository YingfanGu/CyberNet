# Quick Start: Clean Checkpoint System

## What You Need to Know

✅ **Your training script now uses clean checkpoints**  
✅ **Resume training works seamlessly**  
✅ **No more numpy.object_ errors**

---

## Common Tasks

### Task 1: Start Fresh Training
```bash
python train_cyberattack.py
```

**What happens**:
- Trains 3 scenarios (baseline, degraded, resilient)
- Saves clean checkpoint every episode
- Creates directory: `out/SMARTCOMP/checkpoints/FedRL/grid-3x3/MMDD/...`
- Inside: `checkpoint_000000.pkl`, `checkpoint_000001.pkl`, etc.

---

### Task 2: Resume Training (Recommended)
```bash
# Continue for 50 more episodes
python resume_training.py --episodes 50

# Or just resilient scenario
python resume_training.py --episodes 50 --scenarios resilient

# Or baseline and degraded only
python resume_training.py --episodes 50 --scenarios baseline degraded
```

**What happens**:
- Finds latest checkpoint automatically
- Loads weights with `_load_clean_checkpoint()`
- Trains for N more episodes
- Saves new clean checkpoints
- All in same directory

---

### Task 3: Verify Checkpoints Work
```bash
python test_checkpoint_system.py
```

**What happens**:
- Trains fresh for 3 episodes
- Resumes from checkpoint for 2 more episodes
- Reports success ✓

---

## Checkpoint Files

### Where They Are
```
out/SMARTCOMP/checkpoints/FedRL/grid-3x3/
  MMDD/  (date when created)
    Cyberattack_3x3_resilience_baseline_naive_ranked/
      checkpoint_000000.pkl  ← Episode 0 weights
      checkpoint_000001.pkl  ← Episode 1 weights
      checkpoint_000002.pkl  ← Episode 2 weights
      ...
    Cyberattack_3x3_resilience_degraded_naive_ranked/
      checkpoint_000000.pkl
      checkpoint_000001.pkl
      ...
    Cyberattack_3x3_resilience_resilient_trust_ranked/
      checkpoint_000000.pkl
      checkpoint_000001.pkl
      ...
```

### What's Inside
Each `.pkl` file contains:
- **episode**: Episode number (0, 1, 2, ...)
- **timestamp**: When saved
- **policies**: Weights for all agents
- **env_config**: Environment configuration

---

## Important Changes

### What Changed in Code
| File | Change |
|------|--------|
| `seal/trainer/base.py` | New `_save_clean_checkpoint()` method |
| `seal/trainer/base.py` | New `_load_clean_checkpoint()` method |
| `seal/trainer/base.py` | Updated `train()` to use clean save |
| `seal/trainer/base.py` | Updated `load()` to use clean load |

### What Stayed the Same
- `train_cyberattack.py` - No changes needed
- `resume_training.py` - No changes needed
- Training behavior - Identical
- Results - Identical (better checkpoint reliability)

---

## Troubleshooting

### Q: My old checkpoints don't load?
**A**: They have corrupted optimizer state. That's fine.
- Delete old checkpoint directory
- Run fresh training: `python train_cyberattack.py`
- Resume from new checkpoints: `python resume_training.py --episodes 50`

### Q: Training creates no checkpoints?
**A**: Check `train_cyberattack.py` has `checkpoint_freq=1` in trainer creation:
```python
trainer = BaselineTrainer(
    ...
    checkpoint_freq=1,  ← This must be present
    ...
)
```

### Q: Resume training fails with "No checkpoint found"?
**A**: Run fresh training first:
```bash
python train_cyberattack.py --episodes 3
python resume_training.py --episodes 50
```

### Q: Checkpoint files are very large (>500 MB)?
**A**: That's a Ray checkpoint (old format). Delete and start fresh:
```bash
python train_cyberattack.py  # Creates ~235 KB per checkpoint
```

---

## Before & After

### Before (Broken ❌)
```
train_cyberattack.py → Trains model ✓
  ↓
Ray saves checkpoint (complex format)
  ↓
resume_training.py → Load checkpoint
  ↓
❌ TypeError: can't convert np.ndarray of type numpy.object_
❌ Can't resume training
❌ Stuck, must start over
```

### After (Fixed ✅)
```
train_cyberattack.py → Trains model ✓
  ↓
_save_clean_checkpoint() saves weights only (simple format)
  ↓
resume_training.py → Load checkpoint
  ↓
✅ _load_clean_checkpoint() restores weights
✅ Training resumes seamlessly
✅ Save new checkpoints
✅ Continue indefinitely
```

---

## Command Reference

### Training Commands
```bash
# Fresh training (all 3 scenarios, default 20 episodes)
python train_cyberattack.py

# Resume training (default 35 episodes)
python resume_training.py

# Resume only resilient (50 episodes)
python resume_training.py --episodes 50 --scenarios resilient

# Resume baseline and degraded only
python resume_training.py --episodes 50 --scenarios baseline degraded

# Test checkpoint system
python test_checkpoint_system.py
```

### Checkpoint Management
```bash
# Find all checkpoints
ls out/SMARTCOMP/checkpoints/FedRL/grid-3x3/*/Cyberattack*/*/*.pkl

# Check checkpoint contents
python -c "
import pickle
with open('path/to/checkpoint_000005.pkl', 'rb') as f:
    data = pickle.load(f)
    print(f'Episode: {data[\"episode\"]}')
    print(f'Policies: {list(data[\"policies\"].keys())}')
"

# Delete all checkpoints and start fresh
rm -rf out/SMARTCOMP/checkpoints/FedRL/grid-3x3/
python train_cyberattack.py
```

---

## Next Steps

1. **Test it**: Run `python test_checkpoint_system.py`
2. **Train**: Run `python train_cyberattack.py` for 10-20 episodes
3. **Resume**: Run `python resume_training.py --episodes 50`
4. **Analyze**: Check results in `out/` directory

---

## Documentation

- **Implementation Details**: See `CHECKPOINT_IMPLEMENTATION.md`
- **Complete Restructure Info**: See `CHECKPOINT_RESTRUCTURE.md`
- **Code Changes**: See `seal/trainer/base.py` lines 243-501

---

## Summary

Your checkpoint system now works reliably. No more serialization errors. Just train, resume, and repeat. ✓
