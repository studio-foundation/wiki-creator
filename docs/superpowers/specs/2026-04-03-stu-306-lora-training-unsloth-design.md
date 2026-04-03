# STU-306 — LoRA Training : Setup Unsloth + Premier Run wiki-page-item

## Objectif

Script monolithique `scripts/lora_train.py` qui charge le dataset JSONL de STU-305, fine-tune Llama-3.2-3B-Instruct en QLoRA 4-bit via Unsloth, et exporte un GGUF Q4_K_M prêt pour Ollama. Cible : RTX 3060 Laptop 6 GB VRAM.

## CLI

```bash
python scripts/lora_train.py \
  --dataset-dir processing_output/lora/throneofglass/ \
  --output-dir models/wiki-page-item-lora/
```

### Flags optionnels

| Flag | Défaut | Description |
|------|--------|-------------|
| `--skip-train` | false | Reprend depuis un adapter sauvegardé, ne fait que merge + export GGUF |
| `--epochs` | 3 | Nombre d'époques d'entraînement |

## Phases

### Phase 1 — Load dataset

- Charge `train.jsonl` et `eval.jsonl` depuis `--dataset-dir`
- Formate en chatml : `<|im_start|>user\n{instruction}<|im_end|>\n<|im_start|>assistant\n{output}<|im_end|>`

### Phase 2 — Train

| Param | Valeur | Justification |
|-------|--------|---------------|
| Modèle | `unsloth/Llama-3.2-3B-Instruct` | Tient dans 6 GB VRAM |
| Quantization | 4-bit (QLoRA) | ~4-5 GB VRAM |
| LoRA rank | 16 | Bon ratio qualité/VRAM pour 220 exemples |
| LoRA alpha | 32 | 2x rank, standard |
| Target modules | `q_proj, v_proj` | Suffisant pour du fine-tune instruction |
| Batch size | 1 | Contrainte VRAM |
| Gradient accumulation | 4 | Effective batch = 4 |
| Epochs | 3 | Petit dataset, plusieurs passes nécessaires |
| Learning rate | 2e-4 | Standard Unsloth |
| Max seq length | 4096 | Les wiki pages peuvent être longues |

- Évaluation sur `eval.jsonl` à chaque époque
- Log de la loss train/eval au terminal
- Sauvegarde de la loss curve en PNG dans `--output-dir`

### Phase 3 — Merge

- Merge l'adapter LoRA dans le modèle de base (float16)
- Sauvegarde dans `{output-dir}/merged/`

### Phase 4 — Export GGUF

- Export en `Q4_K_M` via `model.save_pretrained_gguf()`
- Sauvegarde dans `{output-dir}/gguf/`
- Affiche la commande `ollama create` à copier-coller

## Sorties

```
models/wiki-page-item-lora/
├── adapter/          # LoRA adapter weights
├── merged/           # Full merged model (float16)
├── gguf/             # Q4_K_M GGUF file
├── loss_curve.png    # Train/eval loss plot
└── train_log.json    # Hyperparams + loss finale
```

## Dépendances

```
unsloth
matplotlib
```

## Critères d'acceptation

- Run d'entraînement complété sans erreur
- Loss finale documentée (courbe PNG + valeur dans train_log.json)
- Adaptateur LoRA sauvegardé et GGUF exporté
- Commande `ollama create` affichée en sortie

## Dépend de

- STU-305 : dataset `train.jsonl` + `eval.jsonl` prêt dans `processing_output/lora/throneofglass/`
